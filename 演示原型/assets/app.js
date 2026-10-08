/* ============================================================
 * app.js —— 路由 / 状态 / 模拟推进器 / 外壳
 * 经典 <script> 全局协作：window.PA_APP
 * 无模块、无构建、无网络；file:// 双击即可运行。
 * ============================================================ */
(function () {
  'use strict';

  var D = window.PA_DATA, UI = window.PA_UI, V = window.PA_VIEWS;
  var h = UI.h, icon = UI.icon;

  var STEP_MS = 8000; // 模拟推进器：每 8s 推进一步（对齐规格）

  /* ---------- 轻量 store ---------- */
  var listeners = [];
  function on(fn) {
    listeners.push(fn);
    return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
  }
  function emit() { listeners.slice().forEach(function (f) { try { f(); } catch (e) { console.error(e); } }); }

  /* ---------- 实时 run 注册表 ---------- */
  var live = {}; // runId -> { run, timer, auto, busy, started }

  /* ---------- 步骤 → 工具调用 / 结论 模板 ---------- */
  function tcBase(run_id, step, output) {
    return { step: step, tool: 'sciret_run_step', invoked_at: new Date().toISOString().slice(0, 19) + 'Z',
      input: { run_id: run_id, step: step }, output: output };
  }
  function toolsFor(run) {
    if (run.workflow === 'materials') {
      return [
        tcBase(run.run_id, 'P1_lit_search', { n_hits: 8, sources_status: D.SOURCES_STATUS, unavailable: D.UNAVAILABLE }),
        tcBase(run.run_id, 'P2_clean_data', { rows_in: 1284, rows_out: 599, anomalies: 0 }),
        tcBase(run.run_id, 'P3_run_experiment', { n_train: 479, n_test: 120, r2: 0.91 }),
        tcBase(run.run_id, 'P4_verify', { n_checks: 5, n_pass: 5, status: 'PASS' }),
        tcBase(run.run_id, 'P5_report', { report: 'report.md', n_conclusions: 3 }),
      ];
    }
    return [
      tcBase(run.run_id, 'R1_search', { n_hits: 10, sources_status: D.SOURCES_STATUS, unavailable: D.UNAVAILABLE }),
      tcBase(run.run_id, 'R2_read', { n_read: 3, n_failed: 0, n_low_confidence: 0 }),
      tcBase(run.run_id, 'R3_analyze', { n_innovations: 0, n_gaps: 3 }),
      tcBase(run.run_id, 'R4_verify', { consistency_rate: 1.0, n_contradictions: 0 }),
      tcBase(run.run_id, 'R5_write', { n_statements: 19, cite_rate: 1.0 }),
      tcBase(run.run_id, 'R6_review', { overall: 7.67, n_blocking: 1, verdict: '需大修（Major Revision）' }),
    ];
  }
  function conclusionsFor(run) {
    if (run.workflow === 'materials') {
      return [
        { cid: 'M1', _after: 'P1_lit_search', text: '多源检索命中 8 篇；OBELiX 数据集 599 条已加载（CC-BY-4.0）。', evidence_ids: ['EV-0001', 'EV-0006'] },
        { cid: 'M2', _after: 'P3_run_experiment', text: '交叉验证 R²=0.91；5 项容差检查全部通过。', evidence_ids: ['EV-0016'] },
        { cid: 'M3', _after: 'P5_report', text: '报告生成完成，3 条结论均绑定数据溯源。', evidence_ids: ['EV-0019'] },
      ];
    }
    return D.CONCLUSIONS.map(function (c, i) {
      return { cid: c.cid, text: c.text, evidence_ids: c.evidence_ids.slice(), _after: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write'][i] };
    });
  }

  /* ---------- 模拟推进器 ---------- */
  function nextStep(run) {
    for (var i = 0; i < run.steps_order.length; i++) { if (run.steps[run.steps_order[i]] === 'PENDING') return run.steps_order[i]; }
    return null;
  }
  function beginStep(run, sid) {
    run.steps[sid] = 'RUNNING';
    if (run.run_status === 'PLANNED') run.run_status = 'RUNNING';
    emit();
  }
  function finishStep(run, sid) {
    run.steps[sid] = 'DONE';
    run.attempts[sid] = (run.attempts[sid] || 0) + 1;
    var tc = (run._tools || []).filter(function (t) { return t.step === sid; })[0];
    if (tc) run.toolcalls.push(tc);
    var c = (run._conclusions || []).filter(function (x) { return x._after === sid; })[0];
    if (c) run.conclusions.push({ cid: c.cid, text: c.text, evidence_ids: c.evidence_ids });
    if (sid === 'R1_search' || sid === 'P1_lit_search') run.degraded = true; // 首步触发降级（演示）
    if (run.steps_order.every(function (s) { return run.steps[s] === 'DONE'; })) run.run_status = 'DONE';
    emit();
  }
  function tick(run) {
    var st = live[run.run_id];
    if (!st || !st.auto) { emit(); return; }
    var sid = nextStep(run);
    if (!sid) { st.auto = false; emit(); return; }
    if (run.steps[sid] !== 'RUNNING') beginStep(run, sid);
    st.timer = setTimeout(function () {
      finishStep(run, sid);
      var s2 = live[run.run_id];
      if (s2 && s2.auto) tick(run); else emit();
    }, STEP_MS);
  }
  function startAuto(id) {
    var run = getRun(id), st = live[id];
    if (!run || !st || run.run_status === 'DONE') return;
    st.auto = true; st.busy = false; emit(); tick(run);
  }
  function stopAuto(id) {
    var st = live[id]; if (!st) return;
    st.auto = false; clearTimeout(st.timer); emit();
  }
  function stepOnce(id) {
    var run = getRun(id), st = live[id]; if (!run || !st) return;
    if (st.auto) { st.auto = false; clearTimeout(st.timer); }
    if (st.busy) return;
    var sid = nextStep(run); if (!sid) return;
    if (run.steps[sid] !== 'RUNNING') beginStep(run, sid);
    st.busy = true;
    st.timer = setTimeout(function () { finishStep(run, sid); st.busy = false; emit(); }, STEP_MS);
  }
  function resetRun(id) {
    var run = getRun(id), st = live[id]; if (!run || !st) return;
    clearTimeout(st.timer);
    run.steps_order.forEach(function (s) { run.steps[s] = 'PENDING'; });
    run.attempts = {};
    run.toolcalls = [];
    run.conclusions = [];
    run.degraded = false;
    run.run_status = 'PLANNED';
    st.auto = false; st.busy = false; st.started = false;
    UI.toast('已重置并重放推进', run.run_id);
    startAuto(id);
  }
  function ensureRunning(id) {
    var run = getRun(id), st = live[id];
    if (!run || !st || st.started || run.run_status === 'DONE') return;
    st.started = true;
    startAuto(id);
  }

  /* ---------- 创建 run ---------- */
  var seq = 0;
  function createRun(goal, workflow, source) {
    seq++;
    var ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
    var id = 'run-' + ts + '-demo' + seq;
    var steps = {}, attempts = {};
    D.WORKFLOWS[workflow].forEach(function (s) { steps[s] = 'PENDING'; });
    var run = {
      run_id: id, workflow: workflow, run_status: 'PLANNED', degraded: false,
      goal: goal, lit_source: source, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      steps_order: D.WORKFLOWS[workflow].slice(), steps: steps, attempts: attempts,
      toolcalls: [], conclusions: [], n_evidence: 0, _live: true, _rank: -1,
    };
    run._tools = toolsFor(run);
    run._conclusions = conclusionsFor(run);
    D.RUNS.unshift(run);
    D.runsById[id] = run;
    live[id] = { run: run, timer: null, auto: false, busy: false, started: false };
    return id;
  }
  function getRun(id) { return D.runsById[id] || null; }
  function isAuto(id) { return !!(live[id] && live[id].auto); }

  /* ---------- 导航模型 ---------- */
  var NAV = [
    { key: 'overview', label: '总览', icon: 'grid' },
    { key: 'new', label: '新建任务', icon: 'plus' },
    { key: 'monitor', label: '运行监控', icon: 'activity' },
    { key: 'evidence', label: '证据溯源', icon: 'link' },
    { key: 'report', label: '报告与导出', icon: 'file' },
    { key: 'library', label: '文献资源', icon: 'book' },
    { key: 'health', label: '环境体检', icon: 'heart' },
    { key: 'agh', label: 'AGH 集成', icon: 'box' },
    { sep: true },
    { key: 'settings', label: '设置', icon: 'gear' },
    { key: 'recovery', label: '故障演练', icon: 'shield' },
  ];
  var ROUTES = {
    overview: { view: V.overview, title: '总览' },
    new: { view: V.newTask, title: '新建任务' },
    monitor: { view: V.monitor, title: '运行监控', runScoped: true },
    evidence: { view: V.evidence, title: '证据溯源', runScoped: true },
    report: { view: V.report, title: '报告与审计导出', runScoped: true },
    library: { view: V.library, title: '文献资源' },
    health: { view: V.health, title: '环境体检' },
    agh: { view: V.agh, title: 'AGH 集成' },
    settings: { view: V.settings, title: '设置' },
    recovery: { view: V.recovery, title: '故障恢复演练' },
  };

  /* ---------- app 接口 ---------- */
  var cleanups = [];
  var app = {
    on: on, emit: emit, getRun: getRun, createRun: createRun,
    stepOnce: stepOnce, runAll: startAuto, stopAuto: stopAuto, isAuto: isAuto,
    resetRun: resetRun, ensureRunning: ensureRunning,
    toast: UI.toast,
    go: function (hash) { if (location.hash === hash) render(); else location.hash = hash; },
    refresh: render,
  };

  /* ---------- 外壳 DOM ---------- */
  var navList, brandBtn, appShell, topbar, viewHost, crumbSlot, tbTitle, tbActions;

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
      var run = getRun(runId) || D.runsById[D.SHOWCASE_ID];
      crumbSlot.appendChild(h('span', { class: 'crumb-run', title: '点击复制 run_id', onclick: function () { UI.copyText(run.run_id, UI.toast); } },
        [icon('hash', 12), h('span', { class: 'mono' }, run.run_id)]));
      crumbSlot.appendChild(UI.runStatusBadge(run));
    } else {
      crumbSlot.appendChild(h('span', { class: 'mono' }, 'paper-agent 2.0 · 展示原型'));
    }
    tbActions.appendChild(h('button', { class: 'btn', onclick: function () { app.go('#/new'); } }, [icon('plus'), '新建']));
    tbActions.appendChild(h('button', { class: 'btn solid', onclick: function () { app.go('#/report/' + D.SHOWCASE_ID); } }, [icon('download'), '导出']));
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
    if (key === 'monitor' && runId) ensureRunning(runId);

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
    window.addEventListener('hashchange', render);
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.PA_APP = app;
})();
