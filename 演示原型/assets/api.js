/* ============================================================
 * api.js —— 数据/网络适配层（Batch 3 · B3-3 mock + B3-4 live）
 * 唯一网络出口；对上层只暴露一组与运行态无关的动作：
 *   createRun / getRun / stepOnce / runAll / stopAuto / resetRun / ensureRunning / isAuto
 *   + ensureLoaded / loadRuns（live 模式按需拉取，views 零改动）
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
   * live 实现（B3-4）——真后端 HTTP + SSE，事件归一化写 store
   * ============================================================ */

  /** fetch JSON；非 2xx 时抛出后端人话错误（j.error） */
  function lf(path, opts) {
    return fetch(CONFIG.base + path, opts).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          throw new Error(j.error || ('HTTP ' + r.status));
        });
      }
      return r.json();
    });
  }

  /** state.json → 视图期望的 run 形状（与 mock 的 run 对象同构） */
  function normalizeState(state) {
    state = state || {};
    return {
      run_id: state.run_id,
      workflow: state.workflow || 'research',
      run_status: state.run_status || 'PLANNED',
      degraded: !!state.degraded,
      goal: state.goal || '',
      lit_source: state.lit_source || '',
      created_at: state.created_at || '',
      updated_at: state.updated_at || '',
      steps_order: (state.steps_order || []).slice(),
      steps: Object.assign({}, state.steps),
      attempts: Object.assign({}, state.attempts),
      toolcalls: [], conclusions: [], n_evidence: 0,
      _live: true, _rank: -1,
    };
  }

  /** provenance.jsonl 行 → EV 卡期望形状（meta 字段兜底：title/doi/year/venue/cites） */
  function normalizeProv(rows) {
    return (rows || []).map(function (p) {
      var meta = Object.assign({ title: '', doi: '', year: '', venue: '', cites: 0, sources: [] }, p.meta || {});
      if (!meta.doi && typeof p.ref === 'string' && p.ref.indexOf('doi.org/') >= 0) {
        meta.doi = p.ref.split('doi.org/')[1];
      }
      return Object.assign({}, p, { meta: meta, sha256: p.sha256 || '', chain_hash: p.chain_hash || '' });
    });
  }

  /** research 才有 review.json；materials 等工作流缺省时给"诚实占位"（视图渲染不崩、语义不撒谎） */
  function normalizeReview(rv) { return (rv && rv.final) ? rv : emptyReview(); }
  function emptyReview() {
    return {
      converged: false, iterations: 0,
      final: {
        overall: null, n_blocking: 0, verdict: '本工作流不产生自审数据',
        scores: {}, blocking_issues: [], strengths: [], weaknesses: [],
        actions: [], summary: 'materials 等工作流不含 R6 自审步骤，无 review.json（research 工作流会有）。',
      },
    };
  }
  function normalizeFactcheck(fc) {
    return (fc && fc.citations) ? fc
      : { citations: { consistency_rate: null, n: 0, tally: {}, results: [] }, contradictions: { n_contradictions: 0, n_claims_considered: 0 }, data_consistency: [] };
  }

  /** SSE 订阅：后端事件归一化 → 更新 store（step/tool/degraded/conclusion/done） */
  function subscribeSSE(id) {
    var st = STORE.live[id]; if (!st) return;
    if (st.es) { try { st.es.close(); } catch (e) { /* 重建 */ } }
    var es;
    try { es = new EventSource(CONFIG.base + '/api/runs/' + encodeURIComponent(id) + '/events'); }
    catch (e) { toast('无法建立实时连接：' + e.message); return; }
    st.es = es;
    function on(ev, fn) {
      es.addEventListener(ev, function (e) {
        var d; try { d = JSON.parse(e.data); } catch (err) { return; }
        var cur = STORE.live[id] && STORE.live[id].run;
        if (!cur) return;
        fn(cur, d);
        STORE.emit();
      });
    }
    on('step', function (run, d) {
      if (run.steps[d.step] !== undefined) run.steps[d.step] = d.status;
      if (d.status === 'DONE') {
        run.attempts[d.step] = (run.attempts[d.step] || 0) + 1;
        refreshDetail(id); // 拉详情补全 toolcall 的 output/invoked_at 与 n_evidence
      }
      if (d.status === 'FAILED') { run.run_status = 'FAILED'; refreshDetail(id); }
    });
    on('tool', function (run, d) {
      var found = null;
      for (var i = run.toolcalls.length - 1; i >= 0; i--) {
        if (run.toolcalls[i].step === d.step) { found = run.toolcalls[i]; break; }
      }
      if (found) Object.assign(found, d);
      else run.toolcalls.push(Object.assign({ invoked_at: new Date().toISOString().slice(0, 19) + 'Z', output: null }, d));
    });
    on('degraded', function (run, d) { run.degraded = true; });
    on('conclusion', function (run, d) {
      if (!d.cid) return;
      for (var i = 0; i < run.conclusions.length; i++) {
        if (run.conclusions[i].cid === d.cid) { Object.assign(run.conclusions[i], d); return; }
      }
      run.conclusions.push({ cid: d.cid, text: d.text, evidence_ids: (d.evidence_ids || []).slice() });
    });
    on('done', function (run, d) {
      run.run_status = d.run_status || run.run_status;
      if (d.run_status === 'DONE' || d.run_status === 'FAILED') refreshDetail(id);
    });
  }

  /** 详情拉取（防抖）：run 详情 + 全局证据数据（PROVENANCE/REVIEW/FACTCHECK）+ 报告正文 */
  function refreshDetail(id) {
    var st = STORE.live[id]; if (!st) return;
    if (st._rt) clearTimeout(st._rt);
    st._rt = setTimeout(function () { st._rt = null; loadRun(id); }, 700);
  }

  function loadRun(id) {
    return lf('/api/runs/' + encodeURIComponent(id)).then(function (ev) {
      var run = normalizeState(ev.state);
      run.toolcalls = ev.toolcalls || [];
      run.conclusions = ev.conclusions || [];
      run.n_evidence = (ev.provenance || []).length;
      STORE.registerRun(run);
      STORE.ensure(id).run = run;
      STORE.live[id].loaded = true;
      D.PROVENANCE = normalizeProv(ev.provenance);
      D.REVIEW = normalizeReview(ev.review);
      D.FACTCHECK = normalizeFactcheck(ev.factcheck);
      STORE.emit();
      // 报告正文：仅在 run 完成后拉取（未完成时后端必 404，不发起无谓请求）
      if (run.run_status !== 'DONE') {
        D.REPORT_MD = '# 报告尚未生成\n\nreport.md 会在报告步骤（R5_write / P5_report）完成后生成——先回到「运行监控」把流程跑完，再回到本页导出。';
        STORE.emit();
        return null;
      }
      return fetch(CONFIG.base + '/api/runs/' + encodeURIComponent(id) + '/report')
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (md) {
          if (md != null) D.REPORT_MD = md;
          else D.REPORT_MD = '# 报告获取失败\n\n流程已完成但 report.md 不可得，请检查后端日志。';
          STORE.emit();
        }).catch(function () { /* 网络抖动不影响主数据 */ });
    }).catch(function (e) { toast('加载 run 详情失败：' + e.message); });
  }

  /** 启动时拉取任务列表（live）：真实 runs 替换 PA_DATA.RUNS（总览页数据源） */
  function loadRuns() {
    return lf('/api/runs').then(function (r) {
      var runs = (r.runs || []).map(normalizeState);
      D.RUNS = runs;
      D.runsById = {};
      runs.forEach(function (run) {
        D.runsById[run.run_id] = run;
        STORE.ensure(run.run_id); // 预建 live 槽位
      });
      STORE.emit();
    }).catch(function (e) { toast('加载任务列表失败：' + e.message); });
  }

  function liveCreateRun(goal, workflow, source) {
    return lf('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: goal, workflow: workflow, lit_source: source }),
    }).then(function (r) {
      var run = normalizeState(r.state || { run_id: r.run_id, workflow: workflow });
      run.goal = goal; run.lit_source = source;
      STORE.registerRun(run);
      STORE.ensure(r.run_id).run = run;
      subscribeSSE(r.run_id);
      return r.run_id;
    });
  }

  function liveNextPending(run) {
    for (var i = 0; i < run.steps_order.length; i++) {
      if (run.steps[run.steps_order[i]] === 'PENDING') return run.steps_order[i];
    }
    return null;
  }

  function liveStep(id) {
    var run = getRun(id); if (!run) return Promise.resolve();
    var sid = liveNextPending(run);
    if (!sid) { toast('没有待执行步骤'); return Promise.resolve(); }
    var st = STORE.live[id]; if (st) st.busy = true;
    subscribeSSE(id); // 先订阅再推进，避免丢首帧事件
    STORE.emit();
    return lf('/api/runs/' + encodeURIComponent(id) + '/step', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: sid }),
    }).then(function () {
      if (st) st.busy = false; STORE.emit();
    }).catch(function (e) {
      if (st) st.busy = false; STORE.emit();
      toast('推进失败：' + e.message);
    });
  }

  function liveRunAll(id) {
    subscribeSSE(id);
    STORE.emit();
    return lf('/api/runs/' + encodeURIComponent(id) + '/run-all', { method: 'POST' })
      .then(function () { STORE.emit(); })
      .catch(function (e) { toast('启动失败：' + e.message); });
  }

  function liveStop(id) {
    var st = STORE.live[id];
    if (st && st.es) { try { st.es.close(); } catch (e) { /* ignore */ } st.es = null; }
    toast('已停止跟随实时事件（后端任务不受影响，刷新页面可重新跟随）');
  }

  function liveReset(id) { toast('live 模式不支持重放——真实 run 无法重置（重放请用 mock 模式）'); }

  /** live 下进入监控页：拉详情 + 订阅事件；不自动开跑（真实执行需用户显式点击） */
  function liveEnsureRunning(id) {
    loadRun(id);
    subscribeSSE(id);
  }

  function liveEnsureLoaded(id) {
    var st = STORE.live[id];
    if (st && st.loaded) return;
    loadRun(id);
  }

  /* ============================================================
   * 公共接口（按 mode 分派：mock / live 同签名）
   * ============================================================ */
  var api = {
    CONFIG: CONFIG,
    isLive: isLive,
    mode: function () { return CONFIG.mode; },
    getRun: getRun,
    isAuto: isAuto,
    ensureLoaded: function (id) { if (isLive()) liveEnsureLoaded(id); },
    loadRuns: function () { if (isLive()) return loadRuns(); return Promise.resolve(); },
    createRun: function (g, w, s) { return isLive() ? liveCreateRun(g, w, s) : mockCreateRun(g, w, s); },
    stepOnce: function (id) { return isLive() ? liveStep(id) : stepOnce(id); },
    runAll: function (id) { return isLive() ? liveRunAll(id) : startAuto(id); },
    stopAuto: function (id) { return isLive() ? liveStop(id) : stopAuto(id); },
    resetRun: function (id) { return isLive() ? liveReset(id) : resetRun(id); },
    ensureRunning: function (id) { return isLive() ? liveEnsureRunning(id) : ensureRunning(id); },
  };

  window.PA_API = api;
})();
