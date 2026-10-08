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
 *  【sources_status 有两个持久来源，内存只是实时缓存】
 *     ① run-step 命令的 stdout JSON（实时，含 elapsed 计时）；
 *     ② toolcalls/*.json 的 **output 子对象**（R1_search 落盘含 sources_status，
 *        实证：runs/<id>/toolcalls/<ts>_R1_search.json → output.sources_status）。
 *     → run-step 后把 stdout 存内存（stepOutputs）供 SSE 实时用；
 *       装配 evidence 时内存 miss 则回读 toolcalls 文件，**重启不丢**。
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
// MAINT-4：WORKFLOWS / STEP_LABELS 单一真源在 web/shared/prompt.mjs
// （server.js 与 prompt.js 同为 ESM，见 web/package.json type:"module"），
// 删除本地重复声明，防与 core/paper_agent/state.py 漂移。
import { WORKFLOWS } from '../shared/prompt.mjs';

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
 * Python 解释器。优先读环境变量 PAPER_AGENT_PYTHON，再回退系统 PATH 的 python。
 * 不保留任何机器特定绝对路径——历史版本硬编码过旧开发机的 python.exe，
 * 对新部署毫无意义且易误导（existsSync 虽会跳过，但属于死配置）。
 *    部署时只需设 PAPER_AGENT_PYTHON（可选），否则走 PATH。
 */
function resolvePython() {
  if (process.env.PAPER_AGENT_PYTHON) return process.env.PAPER_AGENT_PYTHON;
  return 'python';
}
const PYTHON = resolvePython();
const RUNS_DIR = path.join(AGENT_ROOT, 'runs');

/* ══════════════════════════════════════════════════════════
   SEC-3：spawn 环境变量白名单
   （对齐 plugins/paper-agent-tools/index.mjs 的 ENV_ALLOWLIST / curatedEnv 原则）
   ══════════════════════════════════════════════════════════ */
/**
 * 原 `{ ...process.env }` 把整份宿主环境透传给 Python 子进程——与插件侧
 * curatedEnv 的最小环境原则冲突（防"提示注入诱导出站请求外泄密钥"：
 * CLI 子进程一旦被诱导出站，整包 env 里的 AGNES_* 与各类 secret 全部可读）。
 *
 * 白名单来源 = 对 core/paper_agent/ 全部 os.environ 读取点的依赖调查
 * （逐个 grep 取证，行号基于 HEAD）：
 *   - __init__.py:33 / cli.py:232   PAPER_AGENT_ROOT、paper-agent_ROOT（双根，
 *                                   由 buildChildEnv 钉死 AGENT_ROOT，不透传宿主值）
 *   - state.py:130                  paper-agent_LIT_SOURCE   （P1 检索来源默认值）
 *   - research.py:51                paper-agent_READ_LIMIT   （R2 精读篇数上限）
 *   - chaos.py:37                   paper-agent_CHAOS        （故障注入模式；
 *                                   CLI --chaos 经 set_chaos_mode 在子进程内自写，
 *                                   此处保留透传仅为兼容环境注入方式）
 *   - litsearch.py:830              PAPER_AGENT_MAILTO       （arXiv API 礼貌联络邮箱）
 *   - llm.py:132/133/138            PAPER_AGENT_LLM_BASE_URL / _MODEL / _API_KEY
 *                                   （LLM 网关；密钥只透传给 CLI 子进程，
 *                                   不再随整包 env 暴露给任意代码路径）
 *   - report.py:254                 PAPER_AGENT_ENFORCE_JUDGMENT（judgment 硬前置旁路）
 *   - materials_snapshot.py:156     PAPER_AGENT_SNAPSHOT / paper-agent_SNAPSHOT（快照选择，双名）
 *   - cli.py:842/843                paper-agent_PYTHON（doctor 自检回显）
 *   - cli.py:748                    AGH_ENTRY（doctor 的 AGH 入口线索，可选探测）
 *   - steps.py:389 / materials_snapshot.py:572 内部再 spawn 子进程时
 *     dict(os.environ) 继承本 CLI 进程环境 → Windows spawn 必需项必须在此
 */
const ENV_ALLOWLIST = [
  // ---- Windows 进程 / spawn 运行必需 ----
  'PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'COMSPEC', 'PATHEXT', 'WINDIR',
  'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL',
  // ---- Python core 显式读取的功能变量（用途见上方调查注释）----
  'PAPER_AGENT_PYTHON', 'paper-agent_PYTHON',
  'paper-agent_LIT_SOURCE', 'paper-agent_READ_LIMIT', 'paper-agent_CHAOS',
  'PAPER_AGENT_MAILTO', 'PAPER_AGENT_ENFORCE_JUDGMENT',
  'PAPER_AGENT_LLM_BASE_URL', 'PAPER_AGENT_LLM_MODEL', 'PAPER_AGENT_LLM_API_KEY',
  'PAPER_AGENT_SNAPSHOT', 'paper-agent_SNAPSHOT',
  'AGH_ENTRY',
  // ---- 出站代理：urllib 按 getproxies() 读取，在线检索 / LLM 走代理的环境必需 ----
  'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
  'http_proxy', 'https_proxy', 'no_proxy',
];

/** 构建子进程环境：白名单挑选 + 双根变量/PYTHONPATH 钉死（保留原钉死语义）。 */
function buildChildEnv() {
  const env = {};
  for (const k of ENV_ALLOWLIST) {
    if (process.env[k] !== undefined) env[k] = process.env[k];
  }
  // 双根变量钉死 AGENT_ROOT（保留 merge 融合逻辑，消除任何根探测歧义）
  env['paper-agent_ROOT'] = AGENT_ROOT;
  env['PAPER_AGENT_ROOT'] = AGENT_ROOT;
  env.PYTHONPATH = path.join(AGENT_ROOT, 'core');
  return env;
}

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
      // ★ 关键：子进程环境走白名单（SEC-3，见 buildChildEnv 注释）。
      //   双根变量钉死 AGENT_ROOT（merge 融合：双名都注入），保证「服务读的
      //   目录」与「Python 写的目录」永远一致——Python core 认
      //   paper-agent_ROOT / PAPER_AGENT_ROOT 双名，双名都钉死以消除任何探测歧义。
      //   - 不再整包透传 process.env：宿主环境残留的失效根变量会让 CLI 把产物
      //     写到别的仓库（实测：runs 静默分裂），且 secret 全量暴露给子进程。
      env: buildChildEnv(),
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
  // PERF-1：文件名含时间戳、已升序排序（字典序=时间序），从尾部反向扫，
  // 命中该 step 即返回——避免此前的 O(n) 全量读盘解析。
  for (let i = files.length - 1; i >= 0; i--) {
    const d = await readJson(path.join(dir, files[i]), null);
    if (d && d.step === step && d.tool) return d.tool;
  }
  return 'sciret_run_step';
}

/**
 * 装配 toolcalls 数组（对应前端的 tool 卡）。
 * 数据来源：
 *   - toolcalls/*.json → step / tool / invoked_at / input / output
 *     （output.sources_status = R1_search 落盘的四源状态，重启后仍可回读）
 *   - 内存中的 stepOutputs → 该步骤 run-step 的 stdout JSON（实时优先）
 *
 * PERF-1：per-run 读盘缓存（文件名列表 + 各文件 mtime）。目录内容未变
 * （文件集合与 mtime 逐一对得上）则复用上一次解析结果，避免 evidence /
 * SSE 快照等热路径每次全量读盘解析全部 toolcalls 文件。
 */
async function readToolcalls(runId, stepOutputs) {
  const dir = path.join(runDir(runId), 'toolcalls');
  let names = [];
  try {
    names = (await fsp.readdir(dir)).filter((f) => f.endsWith('.json')).sort();
  } catch { return []; }

  // 取当前各文件的 mtime 作为"内容未变"指纹（mtime 变了才重新解析）
  const mtimes = await Promise.all(names.map(async (f) => {
    try { return (await fsp.stat(path.join(dir, f))).mtimeMs; }
    catch { return -1; }
  }));
  const cached = toolcallCache.get(runId);
  let parsed;
  if (cached && cached.names.length === names.length
      && cached.names.every((n, i) => n === names[i] && cached.mtimes[i] === mtimes[i])) {
    parsed = cached.parsed;
  } else {
    parsed = [];
    for (const f of names) {
      const d = await readJson(path.join(dir, f), null);
      if (d && d.step) parsed.push(d);
    }
    toolcallCache.set(runId, { names, mtimes, parsed });
  }

  const order = (await readState(runId))?.steps_order || [];
  const out = [];
  for (const d of parsed) {
    const so = stepOutputs.get(d.step) || {};
    const idx = order.indexOf(d.step);
    out.push({
      step: d.step,
      step_index: idx >= 0 ? idx + 1 : out.length + 1,
      tool: d.tool || 'sciret_run_step',
      status: 'completed',
      elapsed_ms: so.elapsed_ms ?? null,
      input: d.input || {},
      // sources_status：内存（实时 stdout）优先；重启后从 toolcalls 文件的
      // output 子对象回读（R1_search 落盘含四源状态，P1 为单源无此字段 → null）
      sources_status: so.sources_status || d.output?.sources_status
        || d.sources_status || null,
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
/**
 * runId → true：per-run 互斥标记（LOGIC-4）。
 * /step 与 /run-all 执行期间置位，防止并发双 POST 同时 spawn 两个进程操作
 * 同一 run（state.json last-writer-wins、双份账本追加）。
 * 释放路径：/step 校验失败的同步释放、执行结束的 .finally、
 * 以及 PERF-5 的终态清理兜底。
 */
const running = new Map();
/** runId → { names, mtimes, parsed }：toolcalls 目录读盘缓存（PERF-1） */
const toolcallCache = new Map();

function getOutMap(runId) {
  if (!stepOutputs.has(runId)) stepOutputs.set(runId, new Map());
  return stepOutputs.get(runId);
}

function subscribe(runId, res) {
  if (!subscribers.has(runId)) subscribers.set(runId, new Set());
  subscribers.get(runId).add(res);
  // PERF-5：30s 心跳，输出 SSE 注释帧（不会触发前端事件回调），
  // 防代理/浏览器把空闲连接掐断。连接关闭时必须清掉定时器。
  const hb = setInterval(() => {
    try { res.write(': ping\n\n'); } catch { /* 客户端已断开 */ }
  }, 30000);
  res.on('close', () => {
    clearInterval(hb);
    subscribers.get(runId)?.delete(res);
  });
}

function emit(runId, event, data) {
  const set = subscribers.get(runId);
  if (!set?.size) return;
  const frame = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of set) {
    try { res.write(frame); } catch { /* 客户端已断开 */ }
  }
}

/**
 * PERF-5：广播终态 done 并做内存清理。
 * 顺序红线：subscribers 的清理必须放在 done 帧写完之后——emit() 内部是
 * 同步 res.write，本函数返回时终态帧已落socket；若先清订阅者，客户端将
 * 永远收不到终态帧。
 * 清理内容：stepOutputs（含 __cids）、per-run 互斥标记、toolcalls 读盘缓存、
 * subscribers 集合（终态后不再有事件；用户重试时客户端会重建 SSE 连接）。
 */
function emitDoneAndCleanup(runId, runStatus, extra = {}) {
  emit(runId, 'done', { run_status: runStatus, ...extra });
  stepOutputs.delete(runId);
  toolcallCache.delete(runId);
  running.delete(runId);
  subscribers.delete(runId);
}

/* ══════════════════════════════════════════════════════════
   核心动作：推进一个步骤
   ══════════════════════════════════════════════════════════ */

/**
 * 返回下一个可执行的步骤 id；无可执行返回 null。
 * LOGIC-6：对齐 CLI 的 pending_or_failed 语义——除 PENDING 外也挑 FAILED
 * （FAILED→RUNNING 是 state.py 步骤级合法转移），web 端失败后可重试，
 * 不再"一次失败即死局"。
 */
function nextPending(state) {
  const order = state?.steps_order || [];
  return order.find((s) => {
    const v = state.steps?.[s];
    return v === 'PENDING' || v === 'FAILED';
  }) || null;
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
    // LOGIC-3：失败路径修正。此前两处错误：
    //   ① "读 state 只改内存对象"从未写盘——Python 侧 _fail_running_step 已把
    //      步骤落盘为 FAILED，那段是死代码，已删除（注释与实际不符）；
    //   ② 无条件 emit done:{run_status:'FAILED'}——单步失败后 run 多数仍是
    //      RUNNING（Python 单步路径不收敛），前端会收到虚假终态。
    // 现与成功路径对齐：回读 state.json 取真实 run_status，仅当真实状态为
    // 终态（DONE/FAILED）才发 done，否则只发 step FAILED。
    emit(runId, 'step', { step, status: 'FAILED', error: msg });
    const stFail = await readState(runId);
    if (stFail && (stFail.run_status === 'DONE' || stFail.run_status === 'FAILED')) {
      emitDoneAndCleanup(runId, stFail.run_status);
    }
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

  // PERF-1：本步只读一次 state.json，供 tool 的 step_index 与末尾的终态判断
  // 共享（此前 execStep 内 readState 被重复调用两次）。
  const stAfter = await readState(runId);

  emit(runId, 'tool', {
    step,
    step_index: stAfter?.steps_order?.indexOf(step) + 1,
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
  // PERF-5：终态帧发完即清理内存（emitDoneAndCleanup 保证 done 帧先写完）。
  if (stAfter) {
    const allDone = Object.values(stAfter.steps || {})
      .every((s) => s === 'DONE' || s === 'SKIPPED');
    if (allDone && stAfter.run_status !== 'RUNNING') {
      emitDoneAndCleanup(runId, stAfter.run_status);
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
  // 这里只读取真实状态并广播。PERF-5：终态帧发完即清理内存。
  // 注：若 execStep 已在最后一步做过终态清理，此处 emit 无订阅者、静默空转。
  const st = await readState(runId);
  emitDoneAndCleanup(runId, st?.run_status || 'DONE');
}

/* ══════════════════════════════════════════════════════════
   HTTP 层
   ══════════════════════════════════════════════════════════ */

/* ══════════════════════════════════════════════════════════
   SEC-1：CORS 白名单
   ══════════════════════════════════════════════════════════ */
/**
 * 默认白名单：
 *   - http://127.0.0.1:5173 / http://localhost:5173 —— 前端 dev server；
 *   - 'null' —— 演示原型（演示原型/index.html）是 file:// 双击打开的，无构建、
 *     无 dev server，其 live 模式直接 fetch 本服务；file:// 页面的 Origin 头
 *     是字符串 "null"，必须放行，否则 live 全旅程演示不可用。
 *     ★ 决策与残余风险：'null' 意味着本机任意本地 HTML（也是 null origin）
 *     同样能读到响应——但本服务的威胁模型定位是"第三方网页 drive-by-
 *     localhost"（公网网站里的 JS 探测用户本机服务），本地文件属用户信任域，
 *     且服务只绑 127.0.0.1，公网侧无法直接触达。
 * 可用环境变量 PAPER_AGENT_CORS_ORIGIN（逗号分隔）整体覆盖默认白名单。
 */
const CORS_ALLOW_ORIGINS = (process.env.PAPER_AGENT_CORS_ORIGIN || '')
  .split(',').map((s) => s.trim()).filter(Boolean);
if (!CORS_ALLOW_ORIGINS.length) {
  CORS_ALLOW_ORIGINS.push('http://127.0.0.1:5173', 'http://localhost:5173', 'null');
}

/**
 * 按请求 Origin 计算 CORS 响应头：
 *   - 请求带 Origin 且在白名单 → 返回 ACAO=<该 Origin>（回显而非 *，
 *     未来如需 credentials 可安全开启）+ Vary: Origin（多 origin 缓存正确性）；
 *   - Origin 不在白名单 → 不发 ACAO 头（由浏览器同源策略自行拦截；
 *     服务端不做 403——CORS 只是响应头层面的控制）；
 *   - 无 Origin（curl / CLI / 健康检查等非浏览器客户端）→ 不发任何 CORS 头，
 *     正常处理请求（这些客户端没有 CORS 概念，绝不能因无 Origin 而拒绝）。
 */
function corsHeaders(req) {
  const origin = req.headers.origin;
  if (origin === undefined) return {};
  if (CORS_ALLOW_ORIGINS.includes(origin)) {
    return { 'Access-Control-Allow-Origin': origin, Vary: 'Origin' };
  }
  return { Vary: 'Origin' };
}

const json = (res, code, body) => {
  const s = JSON.stringify(body);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(s),
    // res.req 是当前请求对象（Node http.ServerResponse 内置属性）
    ...corsHeaders(res.req),
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
      ...corsHeaders(req),
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
      // SEC-1：SSE 同样是数据返回端点（规格三处清单之外发现的第四处硬编码
      // ACAO:*，不收紧则整条 CORS 白名单形同虚设），统一走 corsHeaders。
      ...corsHeaders(req),
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
    // SEC-5：goal 直传 argv，Windows 命令行长度限制约 32K——超大 goal 会让
    // spawn 直接失败且报错难懂。8192 字符上限既远离系统限制，也远超任何
    // 合法研究目标的长度。
    if (goal.length > 8192) {
      return err(res, 400,
        `goal 过长（${goal.length} 字符），上限 8192 字符`, 'GOAL_TOO_LONG');
    }

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
    // PERF-2：并行读取全部 state.json（此前串行 await，runs 一多延迟线性放大）
    const states = await Promise.all(names.map((n) => readState(n)));
    const runs = states.filter(Boolean)
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
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

    // LOGIC-4：per-run 互斥。检查+占位必须同处一个同步块（中间不能有 await），
    // 否则两个并发请求会在对方置位前双双通过检查（Node 单线程下 await 是
    // 切换点）。占位后任何提前 return 都必须释放。
    if (running.get(runId)) {
      return err(res, 409, '该 run 已有步骤在执行，请等待完成后再试', 'BUSY');
    }
    running.set(runId, true);

    let body;
    try { body = await readBody(req); }
    catch { running.delete(runId); return err(res, 400, '请求体解析失败', 'BAD_BODY'); }
    const step = body.step;
    if (!step || !(st.steps_order || []).includes(step)) {
      running.delete(runId);
      return err(res, 400, `未知步骤：${step}`, 'BAD_STEP');
    }
    // LOGIC-6：对齐 CLI pending_or_failed 语义——放行 PENDING 与 FAILED
    //（FAILED→RUNNING 是状态机合法转移，失败可重试）；其余状态仍 409。
    const cur = st.steps[step];
    if (cur !== 'PENDING' && cur !== 'FAILED') {
      running.delete(runId);
      return err(res, 409,
        `步骤 ${step} 当前为 ${cur}，无法推进（仅 PENDING/FAILED 可执行）`, 'BAD_STATE');
    }

    // 异步执行，HTTP 立刻返回；进度走 SSE。
    // 互斥释放：无论执行成败（含 catch 路径）都走 .finally；
    // PERF-5 的终态清理也会兜底删除。
    // 注意：done 事件由 execStep / execAll 自己发（它们才知道 finish 后的真实 run_status），
    // 这里不要再补发，否则会与 execStep 里的重复且状态可能写错。
    execStep(runId, step)
      .catch((e) => emit(runId, 'step', { step, status: 'FAILED', error: e.message }))
      .finally(() => { running.delete(runId); });

    return json(res, 200, { ok: true, state: st });
  }

  /* ══════ §4.2 全流程 ══════ */
  const allM = p.match(/^\/api\/runs\/([^/]+)\/run-all$/);
  if (allM && m === 'POST') {
    const runId = decodeURIComponent(allM[1]);
    if (!validRunId(runId)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    const st = await readState(runId);
    if (!st) return err(res, 404, 'run 不存在', 'NOT_FOUND');

    // LOGIC-4：per-run 互斥（检查+占位同处一个同步块，防 await 切换点竞态）
    if (running.get(runId)) {
      return err(res, 409, '该 run 已有步骤在执行，请等待完成后再试', 'BUSY');
    }
    running.set(runId, true);

    execAll(runId)
      .catch(async (e) => {
        // LOGIC-3：异常兜底也回读真实状态再广播，不臆断 FAILED
        //（run 内各步骤的失败已由 execStep 各自广播 step FAILED）。
        const stCur = await readState(runId).catch(() => null);
        const rs = stCur?.run_status;
        if (rs === 'DONE' || rs === 'FAILED') {
          emitDoneAndCleanup(runId, rs, { error: e.message });
        } else {
          emit(runId, 'step', { status: 'FAILED', error: e.message });
        }
      })
      .finally(() => { running.delete(runId); });

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
        ...corsHeaders(res.req),
        // SEC-4：report.md 含 LLM/文献衍生产物，加低成本防御头——
        // nosniff 阻止浏览器把正文嗅探成可执行类型；
        // Content-Disposition 明确 inline + 固定文件名，防借附件名做钓鱼伪装。
        // 正文渲染消毒（HTML 化时的 XSS 处理）归前端评审范围。
        'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': 'inline; filename="report.md"',
      });
      return res.end(md);
    } catch {
      return err(res, 404, 'report.md尚未生成（需先跑完 R5_write）', 'NO_REPORT');
    }
  }

  /* ══════ Batch 4 · 证据查询层（B4-3，只读）══════
   * 实现真源 = core/paper_agent/query.py（经 CLI 复用，前端不做第二份实现）。
   * 安全约定：
   *   - runs_dir 一律钉死为本服务的 RUNS_DIR（**不来自请求参数**，防目录穿越）；
   *   - run_id 走 validRunId 白名单；
   *   - kw/doi/tier/kind/source 以独立 argv 传入（无 shell 拼接，无注入面）。
   */
  if (p === '/api/evidence/query' && m === 'GET') {
    const q = url.searchParams;
    const limitRaw = Number(q.get('limit'));
    const limit = Number.isFinite(limitRaw) && limitRaw > 0 ? Math.min(Math.floor(limitRaw), 500) : 200;
    const args = ['query', '--runs', RUNS_DIR, '--limit', String(limit)];
    for (const [flag, key] of [['--kw', 'kw'], ['--doi', 'doi'], ['--tier', 'tier'], ['--kind', 'kind'], ['--source', 'source']]) {
      const v = String(q.get(key) || '').trim();
      if (v) args.push(flag, v);
    }
    for (const rid of String(q.get('run') || '').split(',').map((s) => s.trim()).filter(Boolean)) {
      if (!validRunId(rid)) return err(res, 400, `run_id 格式非法：${rid}`, 'BAD_ID');
      args.push('--run', rid);
    }
    const r = await runCli(args, { timeoutMs: 30000 });
    if (r.code !== 0 || !r.json?.ok) {
      const msg = r.json?.error
        || (r.stderr || '').trim().split(/\r?\n/).slice(-1)[0]
        || `query 失败（退出码 ${r.code}）`;
      return err(res, 500, msg, 'QUERY_ERROR');
    }
    return json(res, 200, r.json);
  }

  if (p === '/api/evidence/graph' && m === 'GET') {
    const rid = String(url.searchParams.get('run') || '');
    if (!validRunId(rid)) return err(res, 400, 'run_id 格式非法', 'BAD_ID');
    const r = await runCli(['query', '--runs', RUNS_DIR, '--graph', rid], { timeoutMs: 30000 });
    if (r.code !== 0 || !r.json?.ok) {
      const msg = r.json?.error
        || (r.stderr || '').trim().split(/\r?\n/).slice(-1)[0]
        || `graph 失败（退出码 ${r.code}）`;
      return err(res, 500, msg, 'GRAPH_ERROR');
    }
    return json(res, 200, r.json);
  }

  if (p === '/api/evidence/aggregate' && m === 'GET') {
    const r = await runCli(['query', '--runs', RUNS_DIR, '--aggregate'], { timeoutMs: 30000 });
    if (r.code !== 0 || !r.json?.ok) {
      const msg = r.json?.error
        || (r.stderr || '').trim().split(/\r?\n/).slice(-1)[0]
        || `aggregate 失败（退出码 ${r.code}）`;
      return err(res, 500, msg, 'AGGREGATE_ERROR');
    }
    return json(res, 200, r.json);
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