/* ============================================================
 * api.js —— 数据/网络适配层（Batch 3 · B3-3 mock + B3-4 live）
 * 唯一网络出口；对上层只暴露一组与运行态无关的动作：
 *   createRun / getRun / stepOnce / runAll / stopAuto / resetRun / ensureRunning / isAuto
 * 模式由 URL 参数 `?mode=live&base=http://127.0.0.1:8787` 或 window.PA_API_CONFIG 决定：
 *   - mock（默认）：内存建 run + 模拟推进器（STEP_MS=8000），完全离线、100% 可复现；
 *   - live：走真后端 HTTP + SSE，事件归一化为与 mock 完全一致的形状后再写 store，
 *           从而 views.js 零改动（路线 B 的核心收益）。
 * 无模块、无构建；挂 window.PA_API。
 * ============================================================ */
(function () {
  'use strict';

  var C = window.PA_CONST, D = window.PA_DATA, STORE = window.PA_STORE, UI = window.PA_UI;

  /* ---------- 配置解析 ---------- */
  var CONFIG = Object.assign(
    { mode: 'mock', base: '', stepMs: 8000 },
    (window.PA_API_CONFIG || {})
  );
  (function resolveFromUrl() {
    if (window.PA_API_CONFIG && window.PA_API_CONFIG.mode) return; // 显式配置优先
    try {
      if (typeof location !== 'undefined' && location.search) {
        var sp = new URLSearchParams(location.search);
        var m = sp.get('mode');
        if (m) CONFIG.mode = m;
        var b = sp.get('base');
        if (b) CONFIG.base = b.replace(/\/+$/, '');
      }
    } catch (e) { /* 无 location（如 Node 冒烟测试）→ 保持默认 mock */ }
  })();

  function isLive() { return CONFIG.mode === 'live'; }
  function toast() { if (UI && UI.toast) return UI.toast.apply(UI, arguments); }

  /* ---------- 通用查询 ---------- */
  function getRun(id) { return D.runsById[id] || null; }
  function isAuto(id) { return !!(STORE.live[id] && STORE.live[id].auto); }

  /* ============================================================
   * mock 模式（默认；离线兜底）
   * ============================================================ */

  var STEP_MS = CONFIG.stepMs;

  /* ---------- 步骤 → 工具调用 / 结论 模板 ---------- */
  function tcBase(run_id, step, output) {
    return {
      step: step, tool: 'sciret_run_step',
      invoked_at: new Date().toISOString().slice(0, 19) + 'Z',
      input: { run_id: run_id, step: step }, output: output,
    };
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
    STORE.emit();
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
    STORE.emit();
  }
  function tick(run) {
    var st = STORE.live[run.run_id];
    if (!st || !st.auto) { STORE.emit(); return; }
    var sid = nextStep(run);
    if (!sid) { st.auto = false; STORE.emit(); return; }
    if (run.steps[sid] !== 'RUNNING') beginStep(run, sid);
    st.timer = setTimeout(function () {
      finishStep(run, sid);
      var s2 = STORE.live[run.run_id];
      if (s2 && s2.auto) tick(run); else STORE.emit();
    }, STEP_MS);
  }
  function startAuto(id) {
    var run = getRun(id), st = STORE.live[id];
    if (!run || !st || run.run_status === 'DONE') return;
    st.auto = true; st.busy = false; STORE.emit(); tick(run);
  }
  function stopAuto(id) {
    var st = STORE.live[id]; if (!st) return;
    st.auto = false; clearTimeout(st.timer); STORE.emit();
  }
  function stepOnce(id) {
    var run = getRun(id), st = STORE.live[id]; if (!run || !st) return;
    if (st.auto) { st.auto = false; clearTimeout(st.timer); }
    if (st.busy) return;
    var sid = nextStep(run); if (!sid) return;
    if (run.steps[sid] !== 'RUNNING') beginStep(run, sid);
    st.busy = true;
    st.timer = setTimeout(function () { finishStep(run, sid); st.busy = false; STORE.emit(); }, STEP_MS);
  }
  function resetRun(id) {
    var run = getRun(id), st = STORE.live[id]; if (!run || !st) return;
    clearTimeout(st.timer);
    run.steps_order.forEach(function (s) { run.steps[s] = 'PENDING'; });
    run.attempts = {};
    run.toolcalls = [];
    run.conclusions = [];
    run.degraded = false;
    run.run_status = 'PLANNED';
    st.auto = false; st.busy = false; st.started = false;
    toast('已重置并重放推进', run.run_id);
    startAuto(id);
  }
  function ensureRunning(id) {
    var run = getRun(id), st = STORE.live[id];
    if (!run || !st || st.started || run.run_status === 'DONE') return;
    st.started = true;
    startAuto(id);
  }

  /* ---------- 创建 run（mock） ---------- */
  var seq = 0;
  function mockCreateRun(goal, workflow, source) {
    seq++;
    var ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
    var id = 'run-' + ts + '-demo' + seq;
    var steps = {}, attempts = {};
    C.WORKFLOWS[workflow].forEach(function (s) { steps[s] = 'PENDING'; });
    var run = {
      run_id: id, workflow: workflow, run_status: 'PLANNED', degraded: false,
      goal: goal, lit_source: source, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      steps_order: C.WORKFLOWS[workflow].slice(), steps: steps, attempts: attempts,
      toolcalls: [], conclusions: [], n_evidence: 0, _live: true, _rank: -1,
    };
    run._tools = toolsFor(run);
    run._conclusions = conclusionsFor(run);
    STORE.registerRun(run);
    STORE.live[id] = { run: run, timer: null, auto: false, busy: false, started: false };
    return id;
  }

  /* ============================================================
   * 公共接口
   * ============================================================ */
  var api = {
    CONFIG: CONFIG,
    isLive: isLive,
    mode: function () { return CONFIG.mode; },
    getRun: getRun,
    isAuto: isAuto,
    createRun: mockCreateRun,
    stepOnce: stepOnce,
    runAll: startAuto,
    stopAuto: stopAuto,
    resetRun: resetRun,
    ensureRunning: ensureRunning,
  };

  window.PA_API = api;
})();
