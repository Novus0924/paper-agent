/**
 * _verify_scratch/p0_sse_verify.mjs
 * ============================================================
 * P0 专项验证（Task #10）——针对 batch 1 修复包的两个 P0 项：
 *
 *   P0-3（SSE 竞态）：新建立 / 刷新后的 SSE 连接，必须**立即**收到初始
 *        补发快照（step / tool / conclusion），而不是空白等待。
 *
 *   P0-1（工具名真源）：实时 tool 事件里的 tool 名，必须与
 *        toolcalls/*.json 的 tool 字段**完全一致**，且都是插件真实注册的
 *        sciret_* 真名（sciret_run_step / sciret_verify / sciret_report …），
 *        绝不是此前硬编码的幻觉名（sciret_search_papers 等）。
 *
 * 做法：真起 web 后端（端口 8787）→ 创建 research 任务（lit_source=local，
 *      不触网、快）→ SSE 客户端 A 挂上 → 推进 R1_search → 抓实时 tool 事件
 *      → 比对 toolcalls 文件；再新开 SSE 客户端 B，验证补发快照。
 *
 * 零第三方依赖（沿用项目红线）：只用 node:http / node:child_process / node:fs。
 *
 * 退出码：全部通过 → 0；任一断言失败 → 1。
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..');
const PORT = Number(process.env.P0_PORT || 8787);
const HOST = '127.0.0.1';
const BASE = `http://${HOST}:${PORT}`;

/** 插件真实注册的工具名（真源：plugins/paper-agent-tools/index.mjs） */
const REAL_TOOLS = new Set([
  'sciret_plan', 'sciret_run_step', 'sciret_status',
  'sciret_verify', 'sciret_report', 'sciret_cite', 'sciret_resume',
]);

const checks = [];
function check(name, ok, detail = '') {
  checks.push({ name, ok, detail });
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? '  → ' + detail : ''}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------- HTTP 小工具 ---------------- */
function req(method, p, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const r = http.request({ host: HOST, port: PORT, path: p, method, headers: data ? {
      'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data),
    } : {} }, (res) => {
      let out = '';
      res.on('data', (c) => { out += c; });
      res.on('end', () => {
        let json = null;
        try { json = JSON.parse(out); } catch { /* 非 JSON */ }
        resolve({ status: res.statusCode, raw: out, json });
      });
    });
    r.on('error', reject);
    if (data) r.write(data);
    r.end();
  });
}

/**
 * 打开一条 SSE 连接，逐事件回调；返回 { events, close }。
 * 用原生 http 手撸 SSE 解析（零依赖）。
 */
function openSSE(runId) {
  return new Promise((resolve, reject) => {
    const events = [];
    const r = http.request({ host: HOST, port: PORT, path: `/api/runs/${runId}/events`, method: 'GET',
      headers: { Accept: 'text/event-stream' } }, (res) => {
      let buf = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        buf += chunk;
        let idx;
        // 逐个 SSE frame 切分（双换行分隔）
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let ev = null; const dataLines = [];
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) ev = line.slice(6).trim();
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
          }
          if (!ev || !dataLines.length) continue;
          let payload = null;
          try { payload = JSON.parse(dataLines.join('\n')); } catch { /* 忽略坏帧 */ }
          events.push({ event: ev, data: payload });
        }
      });
      resolve({ events, res, close: () => { try { res.destroy(); } catch { /* already */ } } });
    });
    r.on('error', reject);
    r.end();
  });
}

/* ---------------- 主流程 ---------------- */
async function waitHealth(timeoutMs = 15000) {
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await req('GET', '/api/health');
      if (r.status === 200 && r.json?.ok) return r.json;
    } catch { /* 还没起 */ }
    if (Date.now() - t0 > timeoutMs) throw new Error('后端健康检查超时');
    await sleep(300);
  }
}

async function main() {
  console.log('== P0 专项验证：SSE 竞态(P0-3) + 工具名真源(P0-1) ==');
  console.log(`   后端: ${BASE}   仓库根: ${REPO}`);

  let srv = null;
  let createdRun = null;
  const conns = [];

  try {
    // 端口占用检查：若已在跑则复用，否则自己起
    let health = null;
    try { health = await (await req('GET', '/api/health')).json; } catch { /* not up */ }
    if (!health?.ok) {
      srv = spawn(process.execPath, ['server/paper-agent-server.js'], {
        cwd: path.join(REPO, 'web'),
        env: { ...process.env, PORT: String(PORT), PAPER_AGENT_ROOT: REPO },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
      srv.stdout.on('data', () => { /* 吞掉服务日志 */ });
      srv.stderr.on('data', (c) => process.stderr.write(`[server] ${c}`));
      health = await waitHealth();
    }
    check('后端就绪 /api/health ok', health?.ok === true, `runs_dir=${health?.runs_dir}`);

    // ── 创建 research 任务（lit_source=local：不触网、快） ──
    const created = await req('POST', '/api/runs', {
      goal: 'P0 专项验证：多源检索与证据链一致性',
      workflow: 'research',
      lit_source: 'local',
    });
    if (created.status !== 201 || !created.json?.run_id) {
      check('创建任务 (POST /api/runs)', false, `status=${created.status} ${created.raw.slice(0, 200)}`);
      throw new Error('创建任务失败，终止');
    }
    createdRun = created.json.run_id;
    const runId = createdRun;
    const stepsOrder = created.json.state?.steps_order || [];
    check('创建任务 → 得到 run_id', true, `${runId}  steps=${stepsOrder.join(',')}`);

    // ── SSE 客户端 A：先挂上，再推进（验证实时 tool 事件） ──
    const A = await openSSE(runId);
    conns.push(A);
    await sleep(200);

    const firstStep = stepsOrder[0];
    const stResp = await req('POST', `/api/runs/${runId}/step`, { step: firstStep });
    check(`推进首步 ${firstStep}`, stResp.status === 200, `status=${stResp.status}`);

    // 等待首步 DONE（local 源通常很快，给足 60s）
    const t0 = Date.now();
    let gotTool = null;
    while (Date.now() - t0 < 60000) {
      gotTool = A.events.find((e) => e.event === 'tool' && e.data?.step === firstStep);
      const done = A.events.find((e) => e.event === 'step' && e.data?.step === firstStep && e.data?.status === 'DONE');
      if (gotTool && done) break;
      await sleep(200);
    }
    check('客户端 A 收到实时 tool 事件', !!gotTool, gotTool ? `tool=${gotTool.data.tool}` : '未收到');

    // ── P0-1：实时 tool 名 == toolcalls/*.json 的 tool 名 ──
    const tcDir = path.join(REPO, 'runs', runId, 'toolcalls');
    let fileTools = [];
    try {
      const files = fs.readdirSync(tcDir).filter((f) => f.endsWith('.json')).sort();
      fileTools = files.map((f) => {
        try { return JSON.parse(fs.readFileSync(path.join(tcDir, f), 'utf8')).tool; } catch { return null; }
      });
    } catch { /* 目录不存在 */ }
    const fileToolFirst = fileTools.find(Boolean) || null;
    check('P0-1 toolcalls/*.json 里工具名为真名', !!fileToolFirst && REAL_TOOLS.has(fileToolFirst),
      `file tools=${JSON.stringify(fileTools)}`);
    check('P0-1 实时 tool 名 == 文件 tool 名', !!gotTool && gotTool.data.tool === fileToolFirst,
      `live=${gotTool?.data.tool}  file=${fileToolFirst}`);
    check('P0-1 实时 tool 名为插件真实注册名', !!gotTool && REAL_TOOLS.has(gotTool.data.tool),
      `live=${gotTool?.data.tool}`);
    check('P0-1 实时 tool 名不是幻觉名', !!gotTool && !/search_papers|parse_paper|analyze_paper|verify_facts|self_review/.test(String(gotTool.data.tool)),
      `live=${gotTool?.data.tool}`);

    // ── P0-3：新开的 SSE 连接 B 必须立即收到补发快照 ──
    // 关键：A 在推进前就挂上（连接早于 toolcalls 文件写入）；B 此刻才连，
    // 它唯一能拿到首步 tool 事件的途径就是「补发快照」——正是 P0-3 的修复点。
    const B = await openSSE(runId);
    conns.push(B);
    // 给补发一点时间（补发是异步读文件，通常 <500ms）
    const tB = Date.now();
    let bkStep = null, bkTool = null;
    while (Date.now() - tB < 5000) {
      bkStep = B.events.find((e) => e.event === 'step' && e.data?.step === firstStep);
      bkTool = B.events.find((e) => e.event === 'tool' && e.data?.step === firstStep);
      if (bkStep && bkTool) break;
      await sleep(100);
    }
    check('P0-3 新连接立即收到补发 step 快照', !!bkStep,
      bkStep ? `step=${firstStep} status=${bkStep.data.status}` : '未收到');
    check('P0-3 新连接立即收到补发 tool 快照', !!bkTool,
      bkTool ? `tool=${bkTool.data.tool}` : '未收到');
    check('P0-3 补发 tool 名与真源一致', !!bkTool && bkTool.data.tool === fileToolFirst,
      `backfill=${bkTool?.data.tool}  file=${fileToolFirst}`);

    // ── 收尾：至少再验一步，确认多步 tool 事件都是真名 ──
    // 全部 tool 事件（A + B）都必须是真名
    const allToolEvs = [...A.events, ...B.events].filter((e) => e.event === 'tool');
    const allReal = allToolEvs.length > 0 && allToolEvs.every((e) => REAL_TOOLS.has(e.data?.tool));
    check('所有 tool 事件均为真名（A+B 合并）', allReal,
      `names=${JSON.stringify([...new Set(allToolEvs.map((e) => e.data?.tool))])}`);

  } catch (e) {
    check('验证流程未抛异常', false, e.message);
  } finally {
    for (const c of conns) c.close();
    if (srv) { try { srv.kill(); } catch { /* 已退出 */ } }
    // 清理本次创建的 run（仓库相对路径；避免污染 runs/）
    if (createdRun) {
      const d = path.join(REPO, 'runs', createdRun);
      try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* 忽略 */ }
    }
  }

  const failed = checks.filter((c) => !c.ok);
  console.log(`\n== 汇总：${checks.length - failed.length}/${checks.length} 通过 ==`);
  if (failed.length) {
    console.log('失败项：');
    for (const f of failed) console.log(`  - ${f.name}  (${f.detail})`);
    process.exit(1);
  }
  console.log('P0_SSE_VERIFY_OK');
  process.exit(0);
}

main();
