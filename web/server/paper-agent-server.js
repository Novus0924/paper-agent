/**
 * server/paper-agent-server.js —— M1 真实后端
 * ============================================================
 * 职责（对接方案 §6 / §8 的 M1）：
 *   1. HTTP + SSE，绑定 127.0.0.1
 *   2. spawn paper_agent.cli（确定性 Python 流水线，方案 §3.1 的主干）
 *   3. 读runs/<id>/ 产物 → 装配成 §4 的响应
 *   4. 把推进过程转成 SSE 事件（方案 §4.3 的 5 类事件）
 *
 * ★ 与 mock/server.js 的区别：那个返回造假数据，这个真跑 Python。
 *
 * 零第三方依赖（沿用项目红线）：只用 node:http / node:child_process / node:fs。
 *
 * 实测校准的事实（本文件所有解析逻辑都基于此，不是推测）：
 *
 *  【契约冲突】CLI 的 --lit-source 只接受 "" | local | arxiv | auto，
 *     而方案 §4.1 写的是 auto|arxiv|crossref|openalex|semantic_scholar。
 *     实测传 crossref 会被 argparse 直接拒绝退出（code 2）。
 *     → 见 resolveLitSource()：按能力映射，未知值降级为 auto。
 *
 *  【plan 不回显 goal】plan 的 stdout JSON 里没有 goal 字段，
 *     必须读 runs/<id>/state.json 才有。
 *
 *  【sources_status 不在 toolcalls 文件里】
 *     toolcalls/*.json 的实际 keys 只有 input / invoked_at / output / step / tool。
 *     四源状态在 **run-step 命令的 stdout JSON** 里（swe 实测已见）。
 *     → 所以每次 run-step 后把 stdout 存进内存，作为该步骤的 tool 事件数据源。
 *
 *  【conclusions.jsonl 可能不存在】
 *     R1..R3 跑完时该文件还没生成，R4/R5 之后才有。
 *     → evidence 接口必须容错，不能假定存在。
 *
 *  【步骤是阻塞的】单步 R1 实测耗时约 8s（含真实网络检索），
 *     所以 SSE 必须在 spawn 之前就建立，并把 step(RUNNING) 先推出去。
 */

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildSystemPrompt, savePrompt, loadPrompt, countPrompts } from './prompt.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(__dirname, '..');

/* ══════════════════════════════════════════════════════════
   配置
   ══════════════════════════════════════════════════════════ */
const PORT = Number(process.env.PORT || 8787);      // 方案 §6 建议端口
const HOST = '127.0.0.1';                            // 方案 §6：只绑本机

/**
 * paper-agent 仓库根（产物的 runs/ 在这里）。
 * 本工程已随仓库入库为 <repo>/web/，所以父目录就是仓库根。
 * ⚠️ 若你把web/ 移出仓库单独跑，必须显式设 PAPER_AGENT_ROOT，
 *    否则会指向错误的目录、报「runs 不存在」。
 */
const AGENT_ROOT = process.env.PAPER_AGENT_ROOT
  || path.resolve(WEB_ROOT, '..');

/**
 * Python 解释器。优先读环境变量，再试常见位置。
 * ⚠️ 下面第一项是本机开发环境的绝对路径，**换机器必然不存在**——
 *existsSync 判定会跳过它，最终回退到 `python`（走系统 PATH）。
 *    别人部署时只需设PAPER_AGENT_PYTHON，不必改代码。
 */
function resolvePython() {
  if (process.env.PAPER_AGENT_PYTHON) return process.env.PAPER_AGENT_PYTHON;
  const cands = [
    // 本机开发路径（不存在时自动跳过）
    'C:/Users/lenovo/AppData/Local/Programs/Python/Python312/python.exe',
    'python', 'python3',
  ];
  for (const c of cands) {
    if (c === 'python' || c === 'python3') return c;
    if (fs.existsSync(c)) return c;
  }
  return 'python';
}
const PYTHON = resolvePython();
const RUNS_DIR = path.join(AGENT_ROOT, 'runs');

/* ══════════════════════════════════════════════════════════
   CLI 调用
   ══════════════════════════════════════════════════════════ */

/** CLI 支持的 lit_source 白名单（实测 argparse choices） */
const CLI_LIT_SOURCES = new Set(['', 'local', 'arxiv', 'auto']);

/**
 * 把前端的 lit_source 映射到 CLI 能吃的值。
 * 前端可选 auto/arxiv/crossref/openalex/semantic_scholar，
 * 但 CLI 只认 ""/local/arxiv/auto。
 * crossref/openalex/semantic_scholar 三个值 CLI 不支持 → 归为 auto
 *（auto = 先试 arxiv 再降级，正是多源场景想要的语义）。
 */
export function resolveLitSource(input) {
  if (!input) return 'auto';
  if (CLI_LIT_SOURCES.has(input)) return input;
  return 'auto';
}

/**
 * spawn CLI 并收集输出。
 * CLI 约定：stdout 只输出单个 JSON 对象（cli.py 的 _emit）。
 */
function runCli(args, { timeoutMs = 180000 } = {}) {
  return new Promise((resolve) => {
    const child = spawn(PYTHON, ['-m', 'paper_agent.cli', ...args], {
      cwd: AGENT_ROOT,
      // ★ 关键：显式把子进程的 paper-agent_ROOT（带连字符，Python 真源）钉死为
      //   本服务读取 runs/ 所用的 AGENT_ROOT，保证「服务读的目录」与「Python 写的
      //   目录」永远一致。
      //   - 不再盲传 process.env：本机若残留一个失效的 paper-agent_ROOT 用户变量，
      //     会被 Python 侧 P0-2 的根校验拒绝（或更糟：写到另一个 runs/ 造成错位）。
      //   - 覆盖掉（而非删除）该变量是安全的：当它本来为空/正确时，值与 Python 的
      //     __file__ 自动探测结果完全相同。
      env: {
        ...process.env,
        PYTHONPATH: path.join(AGENT_ROOT, 'core'),
        'paper-agent_ROOT': AGENT_ROOT,
      },
      windowsHide: true,
    });

    let out = '', err = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill(); } catch { /* 已退出 */ }
      resolve({ code: -1, stdout: out, stderr: `超时 ${timeoutMs}ms`, json: null });
    }, timeoutMs);

    child.stdout.on('data', (c) => { out += c; });
    child.stderr.on('data', (c) => { err += c; });

    child.on('error', (e) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      resolve({ code: -1, stdout: out, stderr: `无法启动 Python（${PYTHON}）：${e.message}`, json: null });
    });

    child.on('close', (code) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      // stdout 末行才是 JSON（前面可能有警告）
      const lines = out.trim().split(/\r?\n/).filter(Boolean);
      let json = null;
      for (let i = lines.length - 1; i >= 0; i--) {
        try { json = JSON.parse(lines[i]); break; } catch { /* 继续往前找 */ }
      }
      resolve({ code, stdout: out, stderr: err, json });
    });
  });
}

/* ══════════════════════════════════════════════════════════
   产物读取（全部容错：文件可能不存在/被写坏）
   ══════════════════════════════════════════════════════════ */

async function readJson(file, fallback = null) {
  try {
    const txt = await fsp.readFile(file, 'utf8');
    return JSON.parse(txt);
  } catch { return fallback; }
}

async function readJsonl(file) {
  try {
    const txt = await fsp.readFile(file, 'utf8');
    return txt.split(/\r?\n/).filter((l) => l.trim()).map((l) => {
      try { return JSON.parse(l); } catch { return null; }
    }).filter(Boolean);
  } catch { return []; }
}

/** run 目录 */
function runDir(runId) { return path.join(RUNS_DIR, runId); }

/** 安全校验 run_id，防目录穿越 */
function validRunId(runId) {
  return typeof runId === 'string'
    && /^run-\d{8}-\d{6}-[0-9a-f]{6,}$/i.test(runId);
}

/** 读 state.json */
async function readState(runId) {
  return await readJson(path.join(runDir(runId), 'state.json'), null);
}

/** 步骤中文名（对齐 core/paper_agent/state.py 的 WORKFLOWS） */
const STEP_LABELS = {
  R1_search: '检索', R2_read: '精读', R3_analyze: '分析',
  R4_verify: '核验', R5_write: '撰写', R6_review: '自审',
  P1_lit_search: '检索', P2_clean_data: '清洗', P3_run_experiment: '实验',
  P4_verify: '验证', P5_report: '报告',
};
const WORKFLOWS = {
  research: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write', 'R6_review'],
  materials: ['P1_lit_search', 'P2_clean_data', 'P3_run_experiment', 'P4_verify', 'P5_report'],
};

/**
 * 读取某步骤最近一次工具调用的真实工具名（真源 = toolcalls/*.json 的 tool 字段）。
 *
 * P0-1 修复：此前存在 `toolNameOf(step)` 硬编码映射，返回的是插件里**根本不存在的
 * 幻觉工具名**（sciret_search_papers / sciret_parse_paper / sciret_analyze_paper /
 * sciret_verify_facts / sciret_self_review …），而 plugins/paper-agent-tools/index.mjs
 * 真实注册的只有 7 个：sciret_plan / sciret_run_step / sciret_status / sciret_verify /
 * sciret_report / sciret_cite / sciret_resume。
 * 后果：同一 run「实时 SSE 看到的工具名」≠「刷新后读文件得到的工具名」，且实时那个是错的。
 * 现统一以 toolcalls/*.json 的 tool 字段为唯一真源（权威值 sciret_run_step；
 * materials 的 P4/P5 为 sciret_verify / sciret_report），实时与刷新读同一真源。
 */
async function latestToolName(runId, step) {
  const dir = path.join(runDir(runId), 'toolcalls');
  let files = [];
  try { files = (await fsp.readdir(dir)).filter((f) => f.endsWith('.json')).sort(); }
  catch { return 'sciret_run_step'; }
  let found = null;
  for (const f of files) {
    const d = await readJson(path.join(dir, f), null);
    if (d && d.step === step && d.tool) found = d.tool;
  }
  return found || 'sciret_run_step';
}

/**
 * 装配 toolcalls 数组（对应前端的 tool 卡）。
 * 数据来源：
 *   - toolcalls/*.json → step / tool / invoked_at / input / output
 *   - 内存中的 stepOutputs → 该步骤 run-step 的 stdout JSON（含 sources_status ★）
 */
async function readToolcalls(runId, stepOutputs) {
  const dir = path.join(runDir(runId), 'toolcalls');
  let files = [];
  try {
    files = (await fsp.readdir(dir)).filter((f) => f.endsWith('.json')).sort();
  } catch { return []; }

  const order = (await readState(runId))?.steps_order || [];
  const out = [];
  for (const f of files) {
    const d = await readJson(path.join(dir, f), null);
    if (!d || !d.step) continue;
    const so = stepOutputs.get(d.step) || {};
    const idx = order.indexOf(d.step);
    out.push({
      step: d.step,
      step_index: idx >= 0 ? idx + 1 : out.length + 1,
      tool: d.tool || 'sciret_run_step',
      status: 'completed',
      elapsed_ms: so.elapsed_ms ?? null,
      input: d.input || {},
      // ★ sources_status 只存在于 run-step 的 stdout，文件里没有
      sources_status: so.sources_status || d.sources_status || null,
      output: d.output ?? null,
      invoked_at: d.invoked_at ?? null,
    });
  }
  return out;
}

/** 装配 evidence 响应（对应 §4.4） */
async function readEvidence(runId) {
  const dir = runDir(runId);
  const state = await readState(runId);

  const provenance = await readJsonl(path.join(dir, 'provenance.jsonl'));
  // ★ conclusions.jsonl 在 R1..R3 阶段还不存在，必须容错
  const conclusions = await readJsonl(path.join(dir, 'conclusions.jsonl'));
  const factcheck = await readJson(path.join(dir, 'factcheck', 'factcheck.json'), null);
  const review = await readJson(path.join(dir, 'review', 'review.json'), null);
  const toolcalls = await readToolcalls(runId, stepOutputs.get(runId) || new Map());

  return { provenance, conclusions, factcheck, review, state, toolcalls };
}

/* ══════════════════════════════════════════════════════════
   运行态（内存）
   ══════════════════════════════════════════════════════════ */
/** runId → Map<step, {sources_status, elapsed_ms, raw}> */
const stepOutputs = new Map();
/** runId → Set<SSE res> */
const subscribers = new Map();
/** runId → Set<child> 正在跑的进程，用于终止 */
const running = new Map();

function getOutMap(runId) {
  if (!stepOutputs.has(runId)) stepOutputs.set(runId, new Map());
  return stepOutputs.get(runId);
}

function subscribe(runId, res) {
  if (!subscribers.has(runId)) subscribers.set(runId, new Set());
  subscribers.get(runId).add(res);
  res.on('close', () => subscribers.get(runId)?.delete(res));
}

function emit(runId, event, data) {
  const set = subscribers.get(runId);
  if (!set?.size) return;
  const frame = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of set) {
    try { res.write(frame); } catch { /* 客户端已断开 */ }
  }
}

/* ══════════════════════════════════════════════════════════
   核心动作：推进一个步骤
   ══════════════════════════════════════════════════════════ */

/** 返回下一个可执行的步骤 id；无可执行返回 null */
function nextPending(state) {
  const order = state?.steps_order || [];
  return order.find((s) => state.steps?.[s] === 'PENDING') || null;
}

/**
 * 执行单个步骤（SSE 已在别处建立）。
 * 注意：CLI 是阻塞的（单步实测约 8s），所以先推 RUNNING 再 spawn。
 */
async function execStep(runId, step) {
  const t0 = Date.now();
  emit(runId, 'step', { step, status: 'RUNNING' });

  const { code, json, stderr } = await runCli(['run-step', '--run', runId, '--step', step]);

  if (code !== 0 || !json?.ok) {
    const msg = json?.error || json?.reason
      || (stderr || '').trim().split(/\r?\n/).slice(-1)[0]
      || `退出码 ${code}`;
    // 失败时也要把状态写回去，否则前端会一直转
    const st = await readState(runId);
    if (st) st.steps[step] = 'FAILED';
    emit(runId, 'step', { step, status: 'FAILED', error: msg });
    emit(runId, 'done', { run_status: 'FAILED' });
    return false;
  }

  const elapsed = Date.now() - t0;
  const om = getOutMap(runId);
  om.set(step, {
    elapsed_ms: elapsed,
    sources_status: json.sources_status || null,
    raw: json,
  });

  emit(runId, 'step', { step, status: 'DONE', elapsed_ms: elapsed });
  emit(runId, 'tool', {
    step,
    step_index: (await readState(runId))?.steps_order?.indexOf(step) + 1,
    tool: await latestToolName(runId, step),
    status: 'completed',
    elapsed_ms: elapsed,
    input: json.input || { step },
    sources_status: json.sources_status || null,
  });

  // 降级源单独发事件（§4.3：degraded 是特色不是错误）
  for (const [src, st] of Object.entries(json.sources_status || {})) {
    if (!String(st).startsWith('ok')) {
      emit(runId, 'degraded', { source: src, reason: String(st), step });
    }
  }

  // 结论事件：每步跑完都补发一次（按cid 去重，前端也会去重）
  // 实测：conclusions.jsonl 在 R1..R3 阶段还不存在，R4/R5 之后才陆续写入，
  // 所以不能只在 R4 发一次——那样会漏掉 R5/R6 阶段新增的结论。
  const sentCids = stepOutputs.get(runId).get('__cids') || new Set();
  const concl = await readJsonl(path.join(runDir(runId), 'conclusions.jsonl'));
  for (const c of concl) {
    if (!c.cid || sentCids.has(c.cid)) continue;
    sentCids.add(c.cid);
    emit(runId, 'conclusion', c);
  }
  getOutMap(runId).set('__cids', sentCids);

  // 若这恰好是最后一步，run_status 已由 Python 侧自动收敛为 DONE（P2-3），
  // 这里只读取真实状态并广播，不再做后端补丁式 finish。
  const stAfter = await readState(runId);
  if (stAfter) {
    const allDone = Object.values(stAfter.steps || {})
      .every((s) => s === 'DONE' || s === 'SKIPPED');
    if (allDone && stAfter.run_status !== 'RUNNING') {
      emit(runId, 'done', { run_status: stAfter.run_status });
    }
  }

  return true;
}

/** 连续推进直到没有 PENDING 或出错 */
async function execAll(runId) {
  for (;;) {
    const st = await readState(runId);
    if (!st) return;
    const step = nextPending(st);
    if (!step) break;
    const ok = await execStep(runId, step);
    if (!ok) return;
  }

  // P2-3：run_status 已由 Python 侧在最后一步完成时自动收敛
  // （模型驱动逐步 run-step 路径现会自动 finish，无需后端补丁）。
  // 这里只读取真实状态并广播。
  const st = await readState(runId);
  emit(runId, 'done', { run_status: st?.run_status || 'DONE' });
}

/* ══════════════════════════════════════════════════════════
   HTTP 层
   ══════════════════════════════════════════════════════════ */

const json = (res, code, body) => {
  const s = JSON.stringify(body);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(s),
    'Access-Control-Allow-Origin': '*',
  });
  res.end(s);
};
const err = (res, code, msg, c = 'ERROR') => json(res, code, { error: msg, code: c });

async function readBody(req) {
  const chunks = [];
  for await (const c of req) {
    chunks.push(c);
    if (chunks.reduce((a, b) => a + b.length, 0) > 1e6) req.destroy();
  }
  if (!chunks.length) return {};
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { return {}; }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const p = url.pathname;
  const m = req.method.toUpperCase();

  if (m === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    return res.end();
  }

  /* ---------- 健康检查 ---------- */
  if (p === '/api/health') {
    return json(res, 200, {
      ok: true,
      agent_root: AGENT_ROOT,
      runs_dir: fs.existsSync(RUNS_DIR) ? RUNS_DIR : '(不存在)',
      python: PYTHON,
      runs_count: fs.existsSync(RUNS_DIR) ? fs.readdirSync(RUNS_DIR).length : 0,
      prompts_archived: countPrompts(),
    });
  }

  /* ══════ §4.3 SSE ══════ */
  const evM = p.match(/^\/api\/runs\/([^/]+)\/events$/);
  if (evM && m === 'GET') {
    const runId = decodeURIComponent(evM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    if (!await readState(runId)) return err(res, 404, 'run 不存在', 'NOT_FOUND');

    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'Access-Control-Allow-Origin': '*',
      'X-Accel-Buffering': 'no',
    });
    res.write('retry: 2000\n\n');
    res.write(`event: ping\ndata: ${JSON.stringify({ ts: Date.now() })}\n\n`);

    // P0-3 修复：先把本连接加入订阅集合，再做补发。
    // 此前顺序是「先 emit() 补发、后 subscribe()」——而 emit() 只在 subscribers
    // 集合里广播，此刻本连接尚未入集合 → 补发事件全部丢失（新连接/刷新后看到空白）。
    subscribe(runId, res);

    // 补发当前状态，避免前端刷新后看到空白。
    // 补发**直写本连接**（res.write），而不是走全局 emit()——否则会把快照
    // 重复广播给其它已订阅的客户端。
    const sse = (event, data) => {
      try { res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); }
      catch { /* 客户端已断开 */ }
    };
    const st = await readState(runId);
    if (st) {
      for (const s of st.steps_order || []) {
        sse('step', { step: s, status: st.steps[s] });
      }
      const tcs = await readToolcalls(runId, stepOutputs.get(runId) || new Map());
      for (const tc of tcs) sse('tool', tc);
      const concl = await readJsonl(path.join(runDir(runId), 'conclusions.jsonl'));
      for (const c of concl) {
        sse('conclusion', c);
        const cids = getOutMap(runId).get('__cids') || new Set();
        cids.add(c.cid);
        getOutMap(runId).set('__cids', cids);
      }
    }

    return;
  }

  /* ══════ §4.1 创建 ══════ */
  if (p === '/api/runs' && m === 'POST') {
    const body = await readBody(req);
    const goal = String(body.goal || '').trim();
    if (!goal) return err(res, 400, 'goal 不能为空', 'BAD_GOAL');

    const workflow = WORKFLOWS[body.workflow] ? body.workflow : 'research';
    const litSource = resolveLitSource(body.lit_source);

    const args = ['plan', '--goal', goal, '--workflow', workflow];
    if (litSource) args.push('--lit-source', litSource);

    const r = await runCli(args);
    if (r.code !== 0 || !r.json?.ok) {
      const msg = (r.stderr || '').trim().split(/\r?\n/).slice(-2).join(' ')
        || r.json?.error || `plan 失败（退出码 ${r.code}）`;
      return err(res, 500, msg, 'CLI_ERROR');
    }

    const runId = r.json.run_id;
    // plan 的 stdout 不含 goal，必须读 state.json
    const state = await readState(runId);

    // M3（方案 §5.2）：生成首轮系统提示词并存档。
    // 刻意存到 <web>/.data/prompts/ 而不是 runs/<id>/——后者的
    // events.jsonl / provenance.jsonl 是 Python 侧 append-only 哈希链账本。
    const promptText = buildSystemPrompt(goal, workflow, litSource);
    const saved = await savePrompt(runId, {
      goal, workflow, lit_source: litSource,
      injected: true,
      // Python 主干是「goal 作为 --goal 参数直传 CLI」（§5.2 注），
      // 提示词用于：① 向用户明示将被施加的约束；② AGH 增强通道（M4）复用。
      delivery: 'cli-arg:goal',
      text: promptText,
    });

    return json(res, 201, {
      run_id: runId,
      state,
      system_prompt: saved ? promptText : null,
      prompt_archived: saved,
    });
  }

  /* ══════ 附加：任务列表 ══════ */
  if (p === '/api/runs' && m === 'GET') {
    let names = [];
    try { names = (await fsp.readdir(RUNS_DIR)).filter((n) => /^run-/.test(n)); } catch { /* 无 runs 目录 */ }
    const runs = [];
    for (const n of names) {
      const st = await readState(n);
      if (st) runs.push(st);
    }
    runs.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    return json(res, 200, { runs });
  }

  /* ══════ §4.4 证据 ══════ */
  const evdM = p.match(/^\/api\/runs\/([^/]+)\/evidence$/);
  if (evdM && m === 'GET') {
    const runId = decodeURIComponent(evdM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    if (!await readState(runId)) return err(res, 404, 'run 不存在', 'NOT_FOUND');
    return json(res, 200, await readEvidence(runId));
  }

  /* ══════ §4.2 推进单步 ══════ */
  const stepM = p.match(/^\/api\/runs\/([^/]+)\/step$/);
  if (stepM && m === 'POST') {
    const runId = decodeURIComponent(stepM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    const st = await readState(runId);
    if (!st) return err(res, 404, 'run 不存在', 'NOT_FOUND');

    const body = await readBody(req);
    const step = body.step;
    if (!step || !(st.steps_order || []).includes(step)) {
      return err(res, 400, `未知步骤：${step}`, 'BAD_STEP');
    }
    if (st.steps[step] !== 'PENDING') {
      return err(res, 409, `步骤 ${step} 当前为 ${st.steps[step]}，无法推进`, 'BAD_STATE');
    }

    // 异步执行，HTTP 立刻返回；进度走 SSE
    // 注意：done 事件由 execStep / execAll 自己发（它们才知道 finish 后的真实 run_status），
    // 这里不要再补发，否则会与 execStep 里的重复且状态可能写错。
    execStep(runId, step)
      .catch((e) => emit(runId, 'step', { step, status: 'FAILED', error: e.message }));

    return json(res, 200, { ok: true, state: st });
  }

  /* ══════ §4.2 全流程 ══════ */
  const allM = p.match(/^\/api\/runs\/([^/]+)\/run-all$/);
  if (allM && m === 'POST') {
    const runId = decodeURIComponent(allM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    const st = await readState(runId);
    if (!st) return err(res, 404, 'run 不存在', 'NOT_FOUND');

    execAll(runId).catch((e) => emit(runId, 'done', { run_status: 'FAILED', error: e.message }));
    return json(res, 200, { ok: true, state: st });
  }

  /* ══════ 附加：单run 快照 ══════ */
  const oneM = p.match(/^\/api\/runs\/([^/]+)$/);
  if (oneM && m === 'GET') {
    const runId = decodeURIComponent(oneM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    const st = await readState(runId);
    if (!st) return err(res, 404, 'run 不存在', 'NOT_FOUND');
    const ev = await readEvidence(runId);
    // M3：把后端存档的真实提示词带回去。
    // 没有存档的（例如本功能之前创建的 run）返回 null，
    // 前端据此回退到本地模板并**显式标注**是本地重算，不假装是后端下发的。
    const pr = await loadPrompt(runId);
    return json(res, 200, {
      ...ev,
      state: st,
      system_prompt: pr?.text || null,
      prompt_meta: pr
        ? { injected: true, archived_at: pr.created_at, delivery: pr.delivery, lit_source: pr.lit_source }
        : { injected: false, reason: '本 run 创建于提示词存档功能之前' },
    });
  }

  /* ══════ 附加：报告正文 ══════ */
  const rptM = p.match(/^\/api\/runs\/([^/]+)\/report$/);
  if (rptM && m === 'GET') {
    const runId = decodeURIComponent(rptM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    try {
      const md = await fsp.readFile(path.join(runDir(runId), 'report.md'), 'utf8');
      res.writeHead(200, {
        'Content-Type': 'text/markdown; charset=utf-8',
        'Access-Control-Allow-Origin': '*',
      });
      return res.end(md);
    } catch {
      return err(res, 404, 'report.md尚未生成（需先跑完 R5_write）', 'NO_REPORT');
    }
  }

  err(res, 404, `无此路由：${m} ${p}`, 'NO_ROUTE');
});

server.listen(PORT, HOST, () => {
  console.log('[server] paper-agent 真实后端已启动');
  console.log(`[server]   http://${HOST}:${PORT}`);
  console.log(`[server]   AGENT_ROOT = ${AGENT_ROOT}`);
  console.log(`[server]   RUNS_DIR   = ${RUNS_DIR}${fs.existsSync(RUNS_DIR) ? '' : '  (不存在!)'}`);
  console.log(`[server]   PYTHON     = ${PYTHON}`);
  console.log('[server]   前端联调：node mock/serve.js  然后打开');
  console.log('[server]     http://127.0.0.1:5173/?mock=0&base=' + `http://${HOST}:${PORT}`);
});