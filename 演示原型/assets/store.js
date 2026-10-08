/* ============================================================
 * store.js —— 极简 pub/sub + 实时 run 注册表（Batch 3 · B3-2 抽出）
 * 从 app.js 抽出：listeners / on / emit 与 live 注册表（runId → 运行态）。
 * 单一数据流：api.js → store → views。SSE / 模拟推进器都只更新 store；
 * 视图只订阅 store（views.js 零改动）。
 * 无模块、无构建、无网络；挂在 window.PA_STORE。
 * ============================================================ */
(function () {
  'use strict';

  /* ---------- 订阅 / 广播 ---------- */
  var listeners = [];
  function on(fn) {
    listeners.push(fn);
    return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
  }
  function emit() {
    listeners.slice().forEach(function (f) { try { f(); } catch (e) { console.error(e); } });
  }

  /* ---------- 实时 run 注册表 ---------- */
  // runId → { run, timer, auto, busy, started }
  var live = {};

  function ensure(id) {
    if (!live[id]) live[id] = { run: null, timer: null, auto: false, busy: false, started: false };
    return live[id];
  }
  function get(id) { return live[id] || null; }
  function drop(id) {
    var st = live[id];
    if (st && st.timer) clearTimeout(st.timer);
    delete live[id];
  }

  /* ---------- run 数据注册（统一维护 PA_DATA.RUNS / runsById） ----------
   * 视图「总览」直接读 PA_DATA.RUNS（非经 app），故 run 的增删必须同步这里。
   */
  function registerRun(run) {
    var D = window.PA_DATA;
    if (!D.runsById[run.run_id]) D.RUNS.unshift(run);
    D.runsById[run.run_id] = run;
    return run;
  }
  function removeRun(id) {
    var D = window.PA_DATA;
    delete D.runsById[id];
    for (var i = 0; i < D.RUNS.length; i++) {
      if (D.RUNS[i].run_id === id) { D.RUNS.splice(i, 1); break; }
    }
  }

  window.PA_STORE = {
    on: on, emit: emit,
    live: live, ensure: ensure, get: get, drop: drop,
    registerRun: registerRun, removeRun: removeRun,
  };
})();
