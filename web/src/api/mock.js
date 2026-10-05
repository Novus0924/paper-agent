/**
 * api/mock.js —— 前端侧 Mock 拦截层
 * ------------------------------------------------------------
 * 两种 mock 模式（本文件负责前端内联模式，mock/server.js 负责独立进程模式）：
 *
 *  A. 内联模式（默认，mock:true）
 *     直接替换 fetch + EventSource，数据在浏览器内存里，操作零延迟。
 *     适合：纯 UI 走查、组件调试、写前端时不用起后端。
 *
 *  B. 进程模式（mock:'http' 或 window.__PAPER_API__.base 指向 mock server）
 *     node mock/server.js 起在 8788，前端设 base='http://127.0.0.1:8788'。
 *     适合：验证真实 HTTP + SSE 链路（联调前必做一次）。
 *
 * 切换真实后端：window.__PAPER_API__ = { mock: false, base: 'http://127.0.0.1:8787' }
 */

import { WORKFLOWS } from './constants.js';
import { makeRun, seedRuns } from './mock-data.js';

export function installMock() {
  const db = new Map();
  seedRuns().forEach((r) => db.set(r.state.run_id, r));

  /* ---------- SSE 订阅表 ---------- */
  const subs = new Map();   // run_id -> Set<handler>
  const timers = new Map(); // run_id -> timeoutId

  function emit(runId, type, data) {
    for (const fn of subs.get(runId) || []) {
      try { fn({ type, data }); } catch (e) { console.error('[mock] handler error', e); }
    }
  }

  function advance(runId, stepId) {
    const run = db.get(runId);
    if (!run) return;
    const tc = run.toolcalls.find((t) => t.step === stepId);
    const delay = Math.min(tc?.elapsed_ms ?? 1200, 2400);

    run.state.run_status = 'RUNNING';
    run.state.steps[stepId] = 'RUNNING';
    emit(runId, 'step', { step: stepId, status: 'RUNNING' });

    timers.set(runId, setTimeout(() => {
      if (!db.has(runId)) return;
      run.state.steps[stepId] = 'DONE';
      run.state.updated_at = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
      emit(runId, 'step', { step: stepId, status: 'DONE', elapsed_ms: tc?.elapsed_ms ?? delay });
      if (tc) emit(runId, 'tool', { step: stepId, ...tc });

      for (const [src, st] of Object.entries(tc?.sources_status || {})) {
        if (!String(st).startsWith('ok')) {
          run.state.degraded = true;
          emit(runId, 'degraded', { source: src, reason: String(st), step: stepId });
        }
      }
      if (stepId === 'R4_verify' || stepId === 'P4_verify') {
        run.conclusions.forEach((c) => emit(runId, 'conclusion', c));
      }

      const order = run.state.steps_order;
      const i = order.indexOf(stepId);
      const next = order.slice(i + 1).find((s) => run.state.steps[s] === 'PENDING');
      if (next) { advance(runId, next); }
      else {
        run.state.run_status = 'DONE';
        emit(runId, 'done', { run_status: 'DONE' });
      }
    }, delay));
  }

  /* ---------- 拦截 fetch ---------- */
  const ok = (data, status = 200) =>
    new Response(JSON.stringify(data), {
      status, headers: { 'Content-Type': 'application/json' },
    });
  const bad = (msg, status = 400, code = 'BAD_REQUEST') =>
    new Response(JSON.stringify({ error: msg, code }), {
      status, headers: { 'Content-Type': 'application/json' },
    });

  window.fetch = async (input, init = {}) => {
    const url = new URL(String(input), location.origin);
    const p = url.pathname;
    const m = (init.method || 'GET').toUpperCase();
    const body = init.body ? JSON.parse(init.body) : {};

    // §4.3 SSE：EventSource 走不到 fetch，这里不处理
    if (p.endsWith('/events')) return ok({});

    // §4.1 创建
    if (p === '/api/runs' && m === 'POST') {
      if (!body.goal || !String(body.goal).trim()) return bad('goal 不能为空');
      const wf = WORKFLOWS[body.workflow] ? body.workflow : 'research';
      const run = makeRun({
        goal: String(body.goal).trim(), workflow: wf,
        lit_source: body.lit_source || 'auto', degraded: false,
        run_status: 'RUNNING', steps_done: 0,
      });
      db.set(run.state.run_id, run);
      advance(run.state.run_id, run.state.steps_order[0]);
      return ok({ run_id: run.state.run_id, state: run.state }, 201);
    }

    // 列表
    if (p === '/api/runs' && m === 'GET') {
      const runs = [...db.values()]
        .sort((a, b) => (b.__t || 0) - (a.__t || 0))
        .map((r) => r.state);
      return ok({ runs });
    }

    let mm;

    // §4.2 单步
    mm = p.match(/^\/api\/runs\/([^/]+)\/step$/);
    if (mm && m === 'POST') {
      const run = db.get(mm[1]);
      if (!run) return bad('run 不存在', 404, 'NOT_FOUND');
      if (!body.step || !run.state.steps_order.includes(body.step)) return bad(`未知步骤：${body.step}`);
      if (run.state.steps[body.step] !== 'PENDING') {
        return bad(`步骤 ${body.step} 当前为 ${run.state.steps[body.step]}，无法推进`, 409, 'BAD_STATE');
      }
      advance(mm[1], body.step);
      return ok({ ok: true, state: run.state });
    }

    // §4.2 全流程
    mm = p.match(/^\/api\/runs\/([^/]+)\/run-all$/);
    if (mm && m === 'POST') {
      const run = db.get(mm[1]);
      if (!run) return bad('run 不存在', 404, 'NOT_FOUND');
      const next = run.state.steps_order.find((s) => run.state.steps[s] === 'PENDING');
      if (next) advance(mm[1], next);
      return ok({ ok: true, state: run.state });
    }

    // §4.4 证据
    mm = p.match(/^\/api\/runs\/([^/]+)\/evidence$/);
    if (mm && m === 'GET') {
      const run = db.get(mm[1]);
      if (!run) return bad('run 不存在', 404, 'NOT_FOUND');
      return ok({
        provenance: run.provenance, conclusions: run.conclusions,
        factcheck: run.factcheck, review: run.review,
        state: run.state, toolcalls: run.toolcalls,
      });
    }

    // 单个 run
    mm = p.match(/^\/api\/runs\/([^/]+)$/);
    if (mm && m === 'GET') {
      const run = db.get(mm[1]);
      if (!run) return bad('run 不存在', 404, 'NOT_FOUND');
      return ok(run);
    }

    return bad(`无此路由：${m} ${p}`, 404, 'NO_ROUTE');
  };

  /* ---------- 拦截 EventSource ---------- */
  const OPEN = 1, CLOSED = 2;

  class MockEventSource {
    constructor(url) {
      this.url = String(url);
      this.readyState = 0;                 // CONNECTING
      this._listeners = new Map();
      this._handler = null;
      const mm = this.url.match(/\/api\/runs\/([^/]+)\/events/);
      this.runId = mm ? decodeURIComponent(mm[1]) : null;

      this._timer = setTimeout(() => {
        if (this.readyState === CLOSED) return;
        this.readyState = OPEN;
        this._fire('ping', { ts: Date.now() });
      }, 60);

      if (this.runId) {
        if (!subs.has(this.runId)) subs.set(this.runId, new Set());
        // 保留同一引用，close 时可精确解绑，避免内存泄漏
        this._handler = (ev) => this._fire(ev.type, ev.data);
        subs.get(this.runId).add(this._handler);
      }
      console.info('[mock] SSE 已连接', this.runId);
    }

    _fire(type, data) {
      const fns = this._listeners.get(type);
      if (!fns?.size) return;
      const ev = { type, data: JSON.stringify(data), lastEventId: '' };
      for (const fn of fns) {
        try { fn(ev); } catch (e) { console.error('[mock] listener error', e); }
      }
    }

    addEventListener(type, fn) {
      if (!this._listeners.has(type)) this._listeners.set(type, new Set());
      this._listeners.get(type).add(fn);
    }

    removeEventListener(type, fn) {
      this._listeners.get(type)?.delete(fn);
    }

    close() {
      if (this.readyState === CLOSED) return;
      this.readyState = CLOSED;
      clearTimeout(this._timer);
      if (this.runId && this._handler) {
        subs.get(this.runId)?.delete(this._handler);
        this._handler = null;
      }
      this._listeners.clear();
    }
  }

  window.EventSource = MockEventSource;
  window.EventSource.CONNECTING = 0;
  window.EventSource.OPEN = OPEN;
  window.EventSource.CLOSED = CLOSED;

  console.info(
    `%c[mock] 内联 mock 已启用 · ${db.size} 个 run`,
    'color:#D9A441',
  );
}