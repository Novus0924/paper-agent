/**
 * api/client.js —— 后端接口客户端
 * ------------------------------------------------------------
 * 严格对齐《对接方案.md》§4 API 契约：
 *   §4.1  POST /api/runs                      创建任务
 *   §4.2  POST /api/runs/{id}/step            推进单步
 *         POST /api/runs/{id}/run-all         全流程推进
 *   §4.3  GET  /api/runs/{id}/events          SSE 事件流
 *   §4.4  GET  /api/runs/{id}/evidence        证据溯源
 *
 * 附加（方案 §4 未列，但左侧任务栏必需）：
 *   GET  /api/runs                           任务列表
 *
 * 切换真实后端：把 window.__PAPER_API_BASE__ 设为 ''（同源）
 * 或 'http://127.0.0.1:8787'。默认为同源 + mock 开关。
 */

const CFG = window.__PAPER_API__ || {};
export const API_BASE = CFG.base ?? '';
export const USE_MOCK = CFG.mock !== false;

/** 统一的请求封装：解析 JSON、规范化错误 */
async function req(path, { method = 'GET', body, signal } = {}) {
  const url = API_BASE + path;
  let res;
  try {
    res = await fetch(url, {
      method,
      signal,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(`网络请求失败：${url}`, 0, 'NETWORK');
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); }
    catch { throw new ApiError(`响应不是合法 JSON（HTTP ${res.status}）`, res.status, 'BAD_JSON'); }
  }
  if (!res.ok) {
    const msg = data?.error || data?.message || `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, data?.code || 'HTTP');
  }
  return data;
}

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/* ══════════════════════════════════════════════════════════
   §4.1 创建任务
   POST /api/runs  { goal, workflow, lit_source }
   → 201 { run_id, state }
   ══════════════════════════════════════════════════════════ */
export function createRun({ goal, workflow, lit_source }) {
  return req('/api/runs', { method: 'POST', body: { goal, workflow, lit_source } });
}

/** 附加：任务列表（左侧栏） */
export function listRuns() {
  return req('/api/runs');
}

/** 附加：单个 run 快照（刷新后恢复工作台） */
export function getRun(runId) {
  return req(`/api/runs/${encodeURIComponent(runId)}`);
}

/* ══════════════════════════════════════════════════════════
   §4.2 推进
   POST /api/runs/{id}/step  { step }  → { ok, state }
   POST /api/runs/{id}/run-all         → { ok, state }
   ══════════════════════════════════════════════════════════ */
export function runStep(runId, step) {
  return req(`/api/runs/${encodeURIComponent(runId)}/step`, {
    method: 'POST', body: { step },
  });
}

export function runAll(runId) {
  return req(`/api/runs/${encodeURIComponent(runId)}/run-all`, { method: 'POST' });
}

/* ══════════════════════════════════════════════════════════
   §4.4 证据溯源
   GET /api/runs/{id}/evidence → { provenance, conclusions, factcheck, review, state }
   ══════════════════════════════════════════════════════════ */
export function getEvidence(runId) {
  return req(`/api/runs/${encodeURIComponent(runId)}/evidence`);
}

/* ══════════════════════════════════════════════════════════
   §4.3 SSE 事件流
   GET /api/runs/{id}/events
   事件类型（方案 §4.3）：step / tool / degraded / conclusion / done
   另外接受 message（AGH 通道的逐块文本，见 §1.2）
   ══════════════════════════════════════════════════════════ */
export function subscribeEvents(runId, handlers = {}) {
  const { onEvent, onError, onOpen, onClose } = handlers;
  const es = new EventSource(API_BASE + `/api/runs/${encodeURIComponent(runId)}/events`);

  es.onopen = () => onOpen?.();
  es.onerror = () => {
    // EventSource 会自动重连；连接彻底断开（readyState=CLOSED）才交给上层处理
    if (es.readyState === EventSource.CLOSED) {
      onError?.(new ApiError('事件流已断开', 0, 'SSE_CLOSED'));
      onClose?.();
    }
  };

  const TYPES = ['step', 'tool', 'degraded', 'conclusion', 'done', 'message', 'ping'];
  const handlers_ = {};
  for (const t of TYPES) {
    handlers_[t] = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); }
      catch { data = { raw: ev.data }; }
      onEvent?.({ type: t, data });
    };
    es.addEventListener(t, handlers_[t]);
  }

  return {
    close() { es.close(); },
    get readyState() { return es.readyState; },
  };
}