/**
 * main.js —— 应用入口：hash 路由 + 页面装配 + mock 拦截
 * ------------------------------------------------------------
 * 路由：
 *   #/workbench            工作台（默认，最近一个 run）
 *   #/run/<run_id>          指定 run 的工作台
 *   #/run/<run_id>/evidence 证据溯源
 *   #/run/<run_id>/evidence/<ev_id>  证据溯源并高亮某条证据
 *   #/new                   新建任务
 *
 * Mock 模式：window.__PAPER_API__.mock !== false 时，api/client.js 走本地
 * mock 数据与本地 SSE 模拟器，不发真实 HTTP 请求（见 api/mock.js）。
 */

import { WorkbenchPage } from './pages/workbench.js';
import { EvidencePage } from './pages/evidence.js';
import { NewTaskPage } from './pages/new-task.js';
import { installMock } from './api/mock.js';
import * as api from './api/client.js';

window.__PAPER_API__ = window.__PAPER_API__ || { mock: true, base: '' };
if (window.__PAPER_API__.mock) installMock();

const app = document.getElementById('app');

const ctx = {
  runs: [],
  runId: null,
  highlightEv: null,
  onGo,
  onPickRun,
  onReloadRuns,
  onReload,
};

/**
 * 路由表（run_id 恒以 "run-" 开头，故 parts[1]==='evidence' 不会与 run_id 混淆）：
 *   #/workbench                      工作台（默认，最近一个 run）
 *   #/run/<run_id>                   指定 run 的工作台
 *   #/run/<run_id>/evidence          证据溯源
 *   #/run/<run_id>/evidence/<ev_id>  证据溯源并高亮某条证据
 *   #/new                            新建任务
 */
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const parts = raw.split('/').filter(Boolean);
  if (!parts.length) return { view: 'workbench', runId: null, ev: null };

  if (parts[0] === 'new') return { view: 'new', runId: null, ev: null };

  if (parts[0] === 'run' && parts[1] && parts[1] !== 'evidence') {
    const runId = parts[1];
    if (parts[2] === 'evidence') {
      return { view: 'evidence', runId, ev: parts[3] || null };
    }
    return { view: 'workbench', runId, ev: null };
  }

  return { view: 'workbench', runId: null, ev: null };
}

/** 导航：更新 hash（触发 route） */
export function onGo(view, runId, ev) {
  if (view === 'new') { location.hash = '#/new'; return; }
  const id = runId || ctx.runId || '';
  if (view === 'evidence') {
    location.hash = ev ? `#/run/${id}/evidence/${ev}` : `#/run/${id}/evidence`;
  } else {
    location.hash = `#/run/${id}`;
  }
}

function onPickRun(id) { onGo('workbench', id); }

async function onReloadRuns() {
  try { ctx.runs = (await api.listRuns()).runs || []; } catch { /* 保持旧值 */ }
  document.querySelector('.view.on')?._updateRuns?.(ctx.runs);
}

/** 强制重渲染当前页 */
function onReload() { route(true); }

let currentPage = null;

async function route(force = false) {
  const { view, runId, ev } = parseHash();
  ctx.highlightEv = ev || null;

  // 首次进入：拉任务列表
  if (!ctx.runs.length) {
    try { ctx.runs = (await api.listRuns()).runs || []; } catch { ctx.runs = []; }
  }

  // 决定 runId
  let id = runId;
  if (!id && view !== 'new') {
    id = ctx.runs[0]?.run_id || null;
    ctx.runId = id;
  }
  if (id) ctx.runId = id;

  // 无 run 且不是新建页 → 引导到新建页
  if (!id && view !== 'new') {
    if (!location.hash.startsWith('#/new')) { location.hash = '#/new'; return; }
  }

  let page;
  if (view === 'new') {
    page = NewTaskPage({
      ...ctx,
      runId: ctx.runId,
      // 创建成功后整页重渲染，工作台会GET /api/runs/{id} 取到后端存档的提示词，
      // 所以不需要把 system_prompt 手动传过去（那样反而会绕过「后端为准」的约定）。
      onCreated: (newId) => { ctx.runs = []; onReloadRuns().then(() => onGo('workbench', newId)); },
    });
  } else if (view === 'evidence') {
    page = EvidencePage({ ...ctx, runId: id, onPickRun });
  } else {
    page = WorkbenchPage({
      ...ctx, runId: id, onPickRun,
      onReload,
      onReloadRuns: () => onReloadRuns(),
    });
    // 让页面能刷新任务栏
    setTimeout(() => page._updateRuns?.(ctx.runs), 0);
  }

  app.replaceChildren(page);
  currentPage = page;
}

window.addEventListener('hashchange', () => route());
route();

// 便于联调时在控制台手动刷新
window.__paperAgent = { ctx, route, api };