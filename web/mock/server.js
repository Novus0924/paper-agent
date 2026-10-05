/**
 * mock/server.js —— Mock 后端（零依赖，node:http）
 * ------------------------------------------------------------
 * 完整实现《对接方案.md》§4 的四个接口，让前端无需真后端即可联调：
 *   POST /api/runs                    → 201 { run_id, state }
 *   GET  /api/runs                    → { runs: [...] }
 *   GET  /api/runs/:id                → { ...run }
 *   POST /api/runs/:id/step           → 200 { ok, state }
 *   POST /api/runs/:id/run-all        → 200 { ok, state }
 *   GET  /api/runs/:id/events         → SSE（step/tool/degraded/conclusion/done）
 *   GET  /api/runs/:id/evidence       → { provenance, conclusions, factcheck, review, state }
 *
 * 启动：node mock/server.js  （默认端口 8788，可用 PORT 环境变量覆盖）
 * 真实后端联调：把前端 window.__PAPER_API__.mock 设为 false 即可切走。
 */

import http from 'node:http';
import { WORKFLOWS } from '../src/api/constants.js';
import { makeRun, seedRuns } from '../src/api/mock-data.js';

const PORT = Number(process.env.PORT || 8788);
const HOST = '127.0.0.1';   // 与方案一致：只绑本机

/* ---- 内存状态 ---- */
const db = new Map();       // run_id -> run
seedRuns().forEach((r) => db.set(r.state.run_id, r));

/** SSE 订阅者：run_id -> Set<res> */
const subs = new Map();
function subscribe(runId, res) {
  if (!subs.has(runId)) subs.set(runId, new Set());
  subs.get(runId).add(res);
  res.on('close', () => subs.get(runId)?.delete(res));
}
function emit(runId, event, data) {
  const set = subs.get(runId);
  if (!set?.size) return;
  const frame = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of set) { try { res.write(frame); } catch { /* 客户端已断 */ } }
}

/* ---- 工具函数 ---- */
const json = (res, code, body) => {
  const s = JSON.stringify(body);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(s),
    'Access-Control-Allow-Origin': '*',
  });
  res.end(s);
};
const readBody = (req) => new Promise((resolve) => {
  let b = '';
  req.on('data', (c) => { b += c; if (b.length > 1e6) req.destroy(); });
  req.on('end', () => { try { resolve(b ? JSON.parse(b) : {}); } catch { resolve({}); } });
});

/** 每次 run 一个定时器句柄，用于暂停 */
const timers = new Map();
function clearTimers(runId) {
  const t = timers.get(runId);
  if (t) { clearTimeout(t); timers.delete(runId); }
}

/**
 * 推进一个步骤：先发 step(RUNNING) → 发 tool → 发 degraded（若有）→ step(DONE)
 * step 用 setTimeout 链模拟真实耗时，便于前端看到 loading 态。
 */
function advance(runId, stepId) {
  const run = db.get(runId);
  if (!run) return;
  const { state, toolcalls } = run;
  const tc = toolcalls.find((t) => t.step === stepId);
  const delay = Math.min(tc?.elapsed_ms ?? 1200, 2400);

  state.run_status = 'RUNNING';
  state.steps[stepId] = 'RUNNING';
  emit(runId, 'step', { step: stepId, status: 'RUNNING' });

  timers.set(runId, setTimeout(() => {
    if (!db.has(runId)) return;
    state.steps[stepId] = 'DONE';
    state.updated_at = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    state.attempts[stepId] = (state.attempts[stepId] || 0) + 1;

    emit(runId, 'step', { step: stepId, status: 'DONE', elapsed_ms: tc?.elapsed_ms ?? delay });
    if (tc) emit(runId, 'tool', { step: stepId, ...tc });

    // 降级源单独发事件（方案 §4.3：degraded 是特色不是错误）
    if (tc?.sources_status) {
      for (const [src, st] of Object.entries(tc.sources_status)) {
        if (!String(st).startsWith('ok')) {
          state.degraded = true;
          emit(runId, 'degraded', { source: src, reason: st, step: stepId });
        }
      }
    }

    // 核验步骤产出结论
    if (stepId === 'R4_verify' || stepId === 'P4_verify') {
      run.conclusions.forEach((c) => emit(runId, 'conclusion', c));
    }

    // 若为 run-all，检查是否还有下一步
    const order = state.steps_order;
    const i = order.indexOf(stepId);
    const next = order.slice(i + 1).find((s) => state.steps[s] === 'PENDING');
    if (next) {
      advance(runId, next);
    } else {
      const anyRunning = order.some((s) => state.steps[s] === 'RUNNING');
      if (!anyRunning) {
        state.run_status = 'DONE';
        emit(runId, 'done', { run_status: 'DONE' });
      }
    }
  }, delay));
}

/* ---- 路由 ---- */
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const p = url.pathname;
  const m = req.method;

  // CORS 预检
  if (m === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    return res.end();
  }

  /* §4.3 SSE —— 必须先于 JSON 路由处理 */
  const evMatch = p.match(/^\/api\/runs\/([^/]+)\/events$/);
  if (evMatch && m === 'GET') {
    const runId = decodeURIComponent(evMatch[1]);
    if (!db.has(runId)) return json(res, 404, { error: 'run 不存在' });
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'Access-Control-Allow-Origin': '*',
      'X-Accel-Buffering': 'no',
    });
    res.write('retry: 2000\n\n');
    res.write(`event: ping\ndata: ${JSON.stringify({ ts: Date.now() })}\n\n`);
    subscribe(runId, res);
    return;
  }

  /* §4.1 创建任务 */
  if (p === '/api/runs' && m === 'POST') {
    const body = await readBody(req);
    if (!body.goal || !String(body.goal).trim()) {
      return json(res, 400, { error: 'goal 不能为空', code: 'BAD_REQUEST' });
    }
    const workflow = WORKFLOWS[body.workflow] ? body.workflow : 'research';
    const run = makeRun({
      goal: String(body.goal).trim(),
      workflow,
      lit_source: body.lit_source || 'auto',
      degraded: false,
      run_status: 'PLANNED',
      steps_done: 0,
    });
    // 新 run 一开始就 RUNNING 首个步骤（模拟 plan 后立即开跑）
    run.state.run_status = 'RUNNING';
    db.set(run.state.run_id, run);
    emit(run.state.run_id, 'step', { step: run.state.steps_order[0], status: 'RUNNING' });
    advance(run.state.run_id, run.state.steps_order[0]);
    return json(res, 201, { run_id: run.state.run_id, state: run.state });
  }

  /* 附加：任务列表 */
  if (p === '/api/runs' && m === 'GET') {
    const runs = [...db.values()]
      .sort((a, b) => (b.__t || 0) - (a.__t || 0))
      .map((r) => r.state);
    return json(res, 200, { runs });
  }

  /* 附加：单个 run */
  const oneMatch = p.match(/^\/api\/runs\/([^/]+)$/);
  if (oneMatch && m === 'GET') {
    const run = db.get(decodeURIComponent(oneMatch[1]));
    if (!run) return json(res, 404, { error: 'run 不存在', code: 'NOT_FOUND' });
    return json(res, 200, run);
  }

  /* §4.2 推进单步 */
  const stepMatch = p.match(/^\/api\/runs\/([^/]+)\/step$/);
  if (stepMatch && m === 'POST') {
    const runId = decodeURIComponent(stepMatch[1]);
    const run = db.get(runId);
    if (!run) return json(res, 404, { error: 'run 不存在', code: 'NOT_FOUND' });
    const body = await readBody(req);
    const step = body.step;
    if (!step || !run.state.steps_order.includes(step)) {
      return json(res, 400, { error: `未知步骤：${step}`, code: 'BAD_STEP' });
    }
    if (run.state.steps[step] !== 'PENDING') {
      return json(res, 409, { error: `步骤 ${step} 当前为 ${run.state.steps[step]}，无法推进`, code: 'BAD_STATE' });
    }
    advance(runId, step);
    return json(res, 200, { ok: true, state: run.state });
  }

  /* §4.2 全流程 */
  const allMatch = p.match(/^\/api\/runs\/([^/]+)\/run-all$/);
  if (allMatch && m === 'POST') {
    const runId = decodeURIComponent(allMatch[1]);
    const run = db.get(runId);
    if (!run) return json(res, 404, { error: 'run 不存在', code: 'NOT_FOUND' });
    const next = run.state.steps_order.find((s) => run.state.steps[s] === 'PENDING');
    if (!next) return json(res, 200, { ok: true, state: run.state });
    advance(runId, next);
    return json(res, 200, { ok: true, state: run.state });
  }

  /* §4.4 证据溯源 */
  const evdMatch = p.match(/^\/api\/runs\/([^/]+)\/evidence$/);
  if (evdMatch && m === 'GET') {
    const run = db.get(decodeURIComponent(evdMatch[1]));
    if (!run) return json(res, 404, { error: 'run 不存在', code: 'NOT_FOUND' });
    return json(res, 200, {
      provenance: run.provenance,
      conclusions: run.conclusions,
      factcheck: run.factcheck,
      review: run.review,
      state: run.state,
      toolcalls: run.toolcalls,
    });
  }

  json(res, 404, { error: `无此路由：${m} ${p}`, code: 'NO_ROUTE' });
});

server.listen(PORT, HOST, () => {
  console.log(`[mock] paper-agent mock 后端已启动`);
  console.log(`[mock]   http://${HOST}:${PORT}`);
  console.log(`[mock]   内存中 ${db.size} 个 run`);
});