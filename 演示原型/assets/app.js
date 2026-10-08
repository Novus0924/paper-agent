/* ============================================================
 * app.js —— 路由 / 外壳（Batch 3 · B3-2/B3-3 改为消费 store + api）
 * 运行态与数据动作下沉到 api.js，pub/sub 与 run 注册表下沉到 store.js；
 * 本文件只负责：选择器渲染（侧栏/顶栏）、路由分派、视图挂载。
 * 经典 <script> 全局协作：window.PA_APP
 * 无模块、无构建、无网络；file:// 双击即可运行。
 * ============================================================ */
(function () {
  'use strict';

  var C = window.PA_CONST, D = window.PA_DATA, UI = window.PA_UI, V = window.PA_VIEWS,
      STORE = window.PA_STORE, API = window.PA_API;
  var h = UI.h, icon = UI.icon;

  /* ---------- 导航模型（元数据来自 constants.js） ---------- */
  var NAV = C.NAV;

  /* ---------- 路由表（键来自 constants.js，视图来自 views.js） ---------- */
  var VIEW_MAP = {
    overview: V.overview, new: V.newTask, monitor: V.monitor, evidence: V.evidence,
    report: V.report, library: V.library, health: V.health, agh: V.agh,
    settings: V.settings, recovery: V.recovery,
  };
  var TITLES = {
    overview: '总览', new: '新建任务', monitor: '运行监控', evidence: '证据溯源',
    report: '报告与审计导出', library: '文献资源', health: '环境体检', agh: 'AGH 集成',
    settings: '设置', recovery: '故障恢复演练',
  };
  var RUN_SCOPED = { monitor: true, evidence: true, report: true };
  var ROUTES = {};
  C.ROUTE_KEYS.forEach(function (k) {
    ROUTES[k] = { view: VIEW_MAP[k], title: TITLES[k], runScoped: !!RUN_SCOPED[k] };
  });

  /* ---------- app 接口（委托 api / store） ---------- */
  var app = {
    on: STORE.on, emit: STORE.emit,
    getRun: API.getRun, createRun: API.createRun,
    stepOnce: API.stepOnce, runAll: API.runAll, stopAuto: API.stopAuto, isAuto: API.isAuto,
    resetRun: API.resetRun, ensureRunning: API.ensureRunning,
    toast: UI.toast,
    go: function (hash) { if (location.hash === hash) render(); else location.hash = hash; },
    refresh: render,
  };

  /* ---------- 外壳 DOM ---------- */
  var navList, brandBtn, appShell, topbar, viewHost, crumbSlot, tbTitle, tbActions;
  var cleanups = [];

  function buildShell() {
    var root = document.getElementById('app');
    root.className = 'app';

    // 侧栏
    var mark = h('div', { class: 'brand-mark' }, 'PA');
    var brand = h('button', { class: 'nav-brand', style: { background: 'none', border: 'none', cursor: 'pointer', width: '100%' },
      title: '折叠/展开导航', onclick: function () { root.classList.toggle('collapsed'); } }, [
      mark,
      h('div', { class: 'brand-text' }, [h('b', {}, 'paper-agent'), h('span', {}, '科研工作台 2.0')]),
    ]);
    brandBtn = brand;
    navList = h('nav', { class: 'nav-list', 'aria-label': '主导航' });
    var nav = h('div', { class: 'nav' }, [brand, navList,
      h('div', { class: 'nav-foot' }, h('div', { class: 'muted', style: { fontSize: '11px' } }, 'Demo · 全假数据 · 不联网'))]);

    // 主区
    tbTitle = h('div', { class: 'tb-title' }, '总览');
    crumbSlot = h('div', { class: 'tb-sub' });
    tbActions = h('div', { class: 'row gap2' });
    topbar = h('header', { class: 'topbar' }, [tbTitle, crumbSlot, h('span', { class: 'grow' }), tbActions]);
    viewHost = h('main', { class: 'view', id: 'view' });
    var main = h('div', { class: 'main' }, [topbar, viewHost]);
    root.appendChild(nav); root.appendChild(main);
  }

  function renderNav(activeKey) {
    UI.clear(navList);
    NAV.forEach(function (n) {
      if (n.sep) { navList.appendChild(h('div', { class: 'nav-sep' })); return; }
      var item = h('button', { class: 'nav-item', type: 'button', 'aria-current': n.key === activeKey ? 'page' : null,
        title: n.label, onclick: function () { app.go('#/' + n.key); } }, [icon(n.icon), h('span', {}, n.label)]);
      navList.appendChild(item);
    });
  }

  function renderTopbar(key, runId) {
    var r = ROUTES[key] || ROUTES.overview;
    tbTitle.textContent = r.title;
    UI.clear(crumbSlot);
    UI.clear(tbActions);
    if (r.runScoped && runId) {
      if (API.isLive()) API.ensureLoaded(runId); // live：按需拉详情（到达后 emit 重渲染）
      var run = API.getRun(runId)
        || (API.isLive() ? (D.RUNS[0] || null) : null)
        || D.runsById[D.SHOWCASE_ID];
      crumbSlot.appendChild(h('span', { class: 'crumb-run', title: '点击复制 run_id', onclick: function () { UI.copyText(run.run_id, UI.toast); } },
        [icon('hash', 12), h('span', { class: 'mono' }, run.run_id)]));
      crumbSlot.appendChild(UI.runStatusBadge(run));
    } else {
      crumbSlot.appendChild(h('span', { class: 'mono' }, 'paper-agent 2.0 · 展示原型'));
    }
    tbActions.appendChild(h('button', { class: 'btn', onclick: function () { app.go('#/new'); } }, [icon('plus'), '新建']));
    var exportTarget = (API.isLive() && D.RUNS[0] && D.RUNS[0].run_id) || D.SHOWCASE_ID;
    tbActions.appendChild(h('button', { class: 'btn solid', onclick: function () { app.go('#/report/' + exportTarget); } }, [icon('download'), '导出']));
  }

  function render() {
    var hash = location.hash || '#/overview';
    var seg = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
    var key = seg[0] || 'overview';
    if (!ROUTES[key]) key = 'overview';
    var runId = seg[1], ev = seg[2];

    // 结束上一个 view
    cleanups.forEach(function (f) { try { f(); } catch (e) { console.error(e); } });
    cleanups = [];

    var r = ROUTES[key];
    // 监控页：进入即自动开跑（对齐主线旅程）
    if (key === 'monitor' && runId) API.ensureRunning(runId);

    renderNav(key);
    renderTopbar(key, runId);

    var node = r.view({ app: app, runId: runId, params: seg.slice(2), onCleanup: function (f) { cleanups.push(f); } });
    UI.mount(viewHost, node);
    viewHost.scrollTop = 0;
    if (typeof window.scrollTo === 'function') window.scrollTo(0, 0);
  }

  /* ---------- 启动 ---------- */
  function boot() {
    buildShell();
    if (!location.hash) location.replace('#/overview');
    if (API.isLive()) API.loadRuns(); // live：启动即拉真实任务列表
    window.addEventListener('hashchange', render);
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.PA_APP = app;
})();
