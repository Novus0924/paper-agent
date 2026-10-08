/* ============================================================
 * views.js —— 8 个界面（+ 可选第 9：故障恢复演练）
 * 每个 view 为 (ctx) => Node；ctx = { app, runId, params, onCleanup }
 * 挂在 window.PA_VIEWS。
 * ============================================================ */
(function () {
  'use strict';

  var UI = window.PA_UI;
  var D = window.PA_DATA;
  var h = UI.h, icon = UI.icon;

  function goEv(ctx, ev) { ctx.app.go('#/evidence/' + D.SHOWCASE_ID + '/' + ev); }
  function relTime(iso) {
    var t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    var now = new Date('2026-10-08T08:00:00Z').getTime();
    var d = Math.max(0, Math.round((now - t) / 1000));
    if (d < 60) return d + ' 秒前';
    if (d < 3600) return Math.round(d / 60) + ' 分钟前';
    return Math.round(d / 3600) + ' 小时前';
  }

  /* ============================================================
   * 界面 1 · 总览
   * ============================================================ */
  function overview(ctx) {
    var P = window.PA_DATA;
    var kpis = h('div', { class: 'grid g4' }, P.KPI.map(function (k) {
      return UI.kpiCard({
        icon: ({ runs: 'target', pass: 'check', ev: 'link', src: 'db' })[k.id],
        label: k.label, value: k.value, unit: k.unit, sub: k.sub,
        onclick: function () {
          if (k.id === 'ev' || k.id === 'src' || k.id === 'pass') { ctx.app.go('#/evidence/' + P.SHOWCASE_ID); }
          else { UI.toast('已按「' + k.label + '」筛选运行列表', k.sub); }
        },
      });
    }));

    // 运行列表
    var runs = P.RUNS.slice().sort(function (a, b) { return a._rank - b._rank; });
    var runlist = h('div', { class: 'runlist' }, runs.map(function (r) {
      return h('div', { class: 'runrow', role: 'button', tabindex: '0', title: r.goal,
        onclick: function () { openRun(ctx, r); } }, [
        h('div', { class: 'rr-main' }, [
          UI.statusDot(r.run_status),
          h('div', { class: 'rr-text col' }, [
            h('div', { class: 'rr-goal' }, r.goal),
            h('div', { class: 'rr-meta' }, [r.workflow + ' · ' + r.steps_order.length + ' 步 · ' + relTime(r.updated_at)]),
          ]),
        ]),
        h('div', { class: 'rr-side' }, [
          h('span', { class: 'rr-id' }, r.run_id.replace('run-', '')),
          UI.runStatusBadge(r),
        ]),
      ]);
    }));

    // 迷你步骤条 + 结论流
    var showcase = P.runsById[P.SHOWCASE_ID];
    var feed = h('div', {}, showcase.conclusions.slice(0, 3).map(function (c) {
      return h('div', { class: 'conclusion', style: { marginBottom: '8px' } }, [
        h('span', { class: 'c-id' }, c.cid + '：'),
        h('span', { class: 'c-text', style: { fontSize: '12px' } }, c.text.length > 90 ? c.text.slice(0, 90) + '…' : c.text),
      ]);
    }));

    var trust = UI.card([
      h('div', { class: 'trustbar' }, Object.keys(P.TRUST).map(function (k) {
        var t = P.TRUST[k];
        return UI.tooltip(h('div', { class: 'trust-cell' }, [
          h('div', { class: 'tv', style: { color: t.ok ? 'var(--ok)' : 'var(--warn)' } }, [icon(t.ok ? 'check' : 'warn', 15), ' ' + t.value]),
          h('div', { class: 'tl' }, t.label),
        ]), { text: t.detail });
      })),
    ], { title: '可复现性 / 信任指标', sub: '悬停查看明细' });

    return h('div', { class: 'grid gap5' }, [
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [
        h('div', { class: 'col' }, [
          h('div', { style: { fontSize: '20px', fontWeight: 700 } }, '科研工作台'),
          h('div', { class: 'muted' }, 'paper-agent 2.0 · 可审计 · 可复现 · 证据可溯源'),
        ]),
        h('button', { class: 'btn solid lg', onclick: function () { ctx.app.go('#/new'); } }, [icon('plus'), '新建任务']),
      ]),
      kpis,
      h('div', { class: 'grid g-2-1' }, [
        UI.card([runlist], { title: '运行列表', sub: runs.length + ' 个 run · 点选进入监控或证据' }),
        h('div', { class: 'col gap4' }, [
          UI.card([
            h('div', { class: 'row', style: { justifyContent: 'space-between', marginBottom: '10px' } }, [
              h('span', { class: 'muted', style: { fontSize: '12px' } }, '最近 run · ' + showcase.run_id),
              UI.runStatusBadge(showcase),
            ]),
            UI.miniStepBar(showcase.steps_order, showcase.steps),
            h('div', { class: 'help' }, '步骤顺序：' + showcase.steps_order.map(function (s) { return D.STEP_LABELS[s]; }).join(' → ')),
          ], { title: '最近 run 状态', sub: showcase.goal }),
          UI.card([feed,
            h('button', { class: 'btn ghost sm', onclick: function () { ctx.app.go('#/evidence/' + showcase.run_id); } }, ['查看全部结论与证据 ', icon('chevR')]),
          ], { title: '实时结论流', sub: '结论 C1–C5 · 均可溯源' }),
          trust,
        ]),
      ]),
    ]);
  }
  function openRun(ctx, r) {
    if (r.run_status === 'RUNNING' || r._live) ctx.app.go('#/monitor/' + r.run_id);
    else ctx.app.go('#/evidence/' + r.run_id);
  }

  /* ============================================================
   * 界面 2 · 新建任务向导
   * ============================================================ */
  function newTask(ctx) {
    var state = { goal: '', workflow: 'research', source: 'auto', err: '' };

    var errNode = h('div', { class: 'field-err hidden' });
    var ta = UI.textarea({ rows: '3', placeholder: '例：检索并综述固态电解质界面阻抗的表征方法', 'aria-label': '研究目标' });
    ta.addEventListener('input', function () { state.goal = ta.value; sync(); });

    var wfWrap = h('div', { class: 'pick' });
    function renderWf() {
      UI.clear(wfWrap);
      ['research', 'materials'].forEach(function (id) {
        var meta = D.WORKFLOW_META[id];
        wfWrap.appendChild(UI.pickCard({
          name: meta.label, desc: meta.desc, on: state.workflow === id,
          extra: h('div', { class: 'chain-view' }, meta.steps.map(function (s) { return s + '(' + D.STEP_LABELS[s] + ')'; }).join(' → ')),
          onclick: function () { state.workflow = id; renderWf(); sync(); },
        }));
      });
    }

    var srcWrap = h('div', { class: 'row wrap gap2' });
    function renderSrc() {
      UI.clear(srcWrap);
      D.LIT_SOURCES.forEach(function (s) {
        srcWrap.appendChild(UI.chip(s.label, {
          on: state.source === s.id, off: !s.effective, title: s.desc,
          onclick: function () { if (!s.effective) return; state.source = s.id; renderSrc(); sync(); },
        }));
      });
    }

    var previewPre = h('pre', { class: 'preview-pre' });
    var willhappen = h('ol', { class: 'willhappen' });
    function renderPreview() {
      previewPre.textContent = D.buildSystemPrompt(state.goal || '（在此输入你的研究目标）', state.workflow, state.source);
      UI.clear(willhappen);
      var steps = D.WORKFLOW_META[state.workflow].steps;
      var items = [
        '创建隔离 run 实例（sciret_plan），生成步骤状态机与 append-only 台账。',
        '按 ' + state.workflow + ' 工作流逐步执行：' + steps.map(function (s) { return D.STEP_LABELS[s]; }).join(' → ') + '。',
        '检索来源 ' + state.source + '，不可用源自动降级切源（任务不中断）。',
        '提交后跳转「运行监控」，可逐步执行或跑完整个流程。',
      ];
      items.forEach(function (t) { willhappen.appendChild(h('li', {}, t)); });
    }
    function sync() { renderPreview(); }
    renderWf(); renderSrc(); renderPreview();

    var submit = h('button', { class: 'btn solid lg', onclick: function () {
      if (!state.goal.trim()) {
        state.err = '请先填写研究目标（不能为空）';
        errNode.textContent = state.err; errNode.classList.remove('hidden');
        ta.focus(); return;
      }
      errNode.classList.add('hidden');
      var rid = ctx.app.createRun(state.goal.trim(), state.workflow, state.source);
      UI.toast('已创建任务，正在进入运行监控…', rid, 'ok');
      ctx.app.go('#/monitor/' + rid);
    } }, [icon('play'), '开始研究']);

    return h('div', { class: 'grid gap5', style: { maxWidth: '1080px', margin: '0 auto' } }, [
      h('div', { class: 'col' }, [
        h('div', { style: { fontSize: '20px', fontWeight: 700 } }, '新建任务'),
        h('div', { class: 'muted' }, '研究目标 → 工作流 → 检索来源 → 系统约束预览（提交前可见）'),
      ]),
      h('div', { class: 'grid g-2-1' }, [
        h('div', { class: 'col gap4' }, [
          UI.card([ta, errNode,
            h('div', { class: 'help' }, '越具体越好：领域 + 对象 + 方法/目标。'), ], { title: '① 研究目标' }),
          UI.card([wfWrap], { title: '② 工作流（二选一）', sub: '决定步骤链与约束模板' }),
          UI.card([srcWrap, h('div', { class: 'help' }, '灰显项：当前 CLI 暂不支持，将按 auto 执行（不隐藏、如实标注）。')],
            { title: '③ 检索来源' }),
        ]),
        h('div', { class: 'col gap4' }, [
          UI.card([previewPre], { title: '系统约束实时预览', sub: '随工作流/来源变化同步更新' }),
          UI.card([h('div', { class: 'willhappen', style: { marginBottom: '14px' } }, willhappen),
            h('div', { class: 'row gap3' }, [submit])], { title: '会发生什么' }),
        ]),
      ]),
    ]);
  }

  /* ============================================================
   * 界面 3 · 运行监控
   * ============================================================ */
  function monitor(ctx) {
    var runId = ctx.runId;
    var app = ctx.app;
    var run = app.getRun(runId);
    if (!run) return UI.emptyState('未找到该 run：' + runId, 'alert');

    var stepsWrap = h('div');
    var degradedWrap = h('div');
    var toolsWrap = h('div');
    var concWrap = h('div');
    var tagRow = h('div', { class: 'row wrap gap2' });
    var actionsWrap = h('div', { class: 'row wrap gap2' });

    function paint() {
      var r = app.getRun(runId);
      // 标签行
      UI.clear(tagRow);
      var doneN = r.steps_order.filter(function (s) { return r.steps[s] === 'DONE'; }).length;
      var app_ = D.SOURCES_STATUS;
      var availN = Object.keys(app_).filter(function (k) { return String(app_[k]).indexOf('ok') === 0; }).length;
      [['activity', 'workflow=' + r.workflow],
       ['hash', 'run_id=' + r.run_id],
       ['target', doneN + '/' + r.steps_order.length + ' 步'],
       ['db', '来源可用 ' + availN + '/4'],
       ['link', '结论 ' + (r.conclusions ? r.conclusions.length : 0) + ' 条']].forEach(function (t) {
        tagRow.appendChild(h('span', { class: 'chip static' }, [icon(t[0], 13), t[1]]));
      });

      // 动作
      UI.clear(actionsWrap);
      var running = r.run_status === 'RUNNING' || r.run_status === 'PLANNED';
      if (running) {
        actionsWrap.appendChild(h('button', { class: 'btn', onclick: function () { app.stepOnce(runId); } }, [icon('chevR'), '执行下一步']));
        actionsWrap.appendChild(h('button', { class: 'btn solid', onclick: function () { app.runAll(runId); } }, [icon('bolt'), '跑完整个流程']));
      } else {
        actionsWrap.appendChild(h('button', { class: 'btn', onclick: function () { app.go('#/evidence/' + runId); } }, [icon('link'), '查看证据']));
        actionsWrap.appendChild(h('button', { class: 'btn', onclick: function () { app.go('#/report/' + runId); } }, [icon('file'), '查看报告']));
        actionsWrap.appendChild(h('button', { class: 'btn ghost', onclick: function () { app.resetRun(runId); } }, [icon('refresh'), '重放推进']));
      }

      // 降级条
      UI.clear(degradedWrap);
      if (r.degraded) degradedWrap.appendChild(UI.degradedBar(r));

      // 步骤条
      UI.clear(stepsWrap);
      stepsWrap.appendChild(UI.stepBar(r.steps_order, r.steps, D.STEP_LABELS));

      // 工具卡流
      UI.clear(toolsWrap);
      var tcs = r.toolcalls || [];
      tcs.forEach(function (tc, i) {
        toolsWrap.appendChild(UI.toolCard(tc, { open: i === tcs.length - 1 && r.run_status === 'RUNNING' }));
      });
      var curStep = r.steps_order.filter(function (s) { return r.steps[s] === 'RUNNING'; })[0];
      if (curStep) toolsWrap.appendChild(UI.skeletonToolCard(curStep));
      if (!tcs.length && !curStep) toolsWrap.appendChild(UI.emptyState('尚未产生工具调用', 'box'));

      // 结论流
      UI.clear(concWrap);
      var cs = r.conclusions || [];
      if (!cs.length) concWrap.appendChild(UI.emptyState('尚未产生结论，点「执行下一步」推进', 'link'));
      cs.forEach(function (c) { concWrap.appendChild(UI.conclusionCard(c, function (ev) { goEv(ctx, ev); })); });
    }

    paint();
    var unsub = app.on(function () { paint(); });
    ctx.onCleanup(unsub);
    if (run._live && run.run_status !== 'DONE' && !app.isAuto(runId)) { /* 等待手动推进 */ }

    return h('div', { class: 'grid gap4' }, [
      UI.card([
        h('div', { class: 'row wrap gap2', style: { marginBottom: '10px' } }, [
          h('span', { class: 'ink2', style: { fontSize: '14px', fontWeight: 600 } }, run.goal),
          h('span', { class: 'grow' }),
          UI.runStatusBadge(app.getRun(runId)),
        ]),
        tagRow,
        h('div', { class: 'divider', style: { margin: '14px 0' } }),
        actionsWrap,
      ]),
      degradedWrap,
      UI.card([stepsWrap], { title: '步骤条', sub: '待执行 → 运行中(琥珀) → 完成(绿)' }),
      h('div', { class: 'grid g-2-1' }, [
        UI.card([toolsWrap], { title: '工具调用', sub: '每次调用均为真实的 sciret_run_step（点击展开 input/output/四源状态）' }),
        UI.card([concWrap], { title: '结论流', sub: '点结论中的 EV 编号可跳转证据溯源' }),
      ]),
    ]);
  }

  /* ============================================================
   * 界面 4 · 证据溯源
   * ============================================================ */
  function evidence(ctx) {
    var runId = ctx.runId && ctx.runId !== 'undefined' ? ctx.runId : D.SHOWCASE_ID;
    var run = ctx.app.getRun(runId) || D.runsById[D.SHOWCASE_ID];
    var evs = D.PROVENANCE;
    var filter = 'all', q = '';

    var verdicts = h('div', { class: 'grid g4' }, [
      verdict('100%', '引用一致性', '3 处引用全部一致', 'ok'),
      verdict('7.67', '自审评分', '1 项待修（阻断）', 'warn'),
      verdict('21', '证据条目', 'fact 21 · artifact 0', ''),
      verdict('3.75', '来源可用', '/4 源 · 1 源降级', 'warn'),
    ]);
    function verdict(v, l, s, cls) {
      return h('div', { class: 'card verdict' }, [
        h('div', { class: 'v-val', style: { color: cls === 'ok' ? 'var(--ok)' : cls === 'warn' ? 'var(--warn)' : 'var(--ink)' } }, v),
        h('div', { class: 'v-lab' }, l),
        h('div', { class: 'v-sub' }, s),
      ]);
    }

    // 结论 ↔ 证据绑定
    var bindings = h('div', {}, (run.conclusions || D.CONCLUSIONS).map(function (c) {
      return h('div', { class: 'conclusion', style: { borderLeftColor: 'var(--line-2)' } }, [
        h('div', { class: 'row', style: { marginBottom: '6px', justifyContent: 'space-between' } }, [
          h('span', { class: 'c-id' }, c.cid),
          h('span', { class: 'muted', style: { fontSize: '11.5px' } }, c.evidence_ids.length + ' 条证据'),
        ]),
        h('div', { class: 'c-text' }, c.text),
        h('div', { class: 'c-evs' }, c.evidence_ids.map(function (ev) {
          return h('button', { class: 'ev-chip', type: 'button', onclick: function () { flash(ev); } }, ev);
        })),
      ]);
    }));

    // 自审明细
    var rv = D.REVIEW.final;
    var scores = h('div', {}, Object.keys(rv.scores).map(function (k) {
      var v = rv.scores[k];
      return h('div', { class: 'row gap2', style: { marginBottom: '7px', fontSize: '12.5px' } }, [
        h('span', { style: { width: '110px', color: 'var(--ink-2)' } }, k),
        h('span', { style: { flex: '1', height: '7px', borderRadius: '4px', background: 'var(--raised)', overflow: 'hidden' } },
          h('span', { style: { display: 'block', height: '100%', width: (v * 10) + '%', background: v >= 7 ? 'var(--ok)' : v >= 4 ? 'var(--amber)' : 'var(--fail)' } })),
        h('span', { class: 'mono', style: { width: '42px', textAlign: 'right', color: v >= 7 ? 'var(--ok)' : 'var(--fail)' } }, v.toFixed(2)),
      ]);
    }));
    var reviewPanel = UI.card([
      scores,
      h('div', { class: 'divider' }),
      rv.blocking_issues.map(function (b) {
        return h('div', { class: 'degraded-bar', style: { marginBottom: '8px' } }, [icon('alert'), h('span', {}, [h('b', {}, '阻断项 ' + b.tag + '：'), b.detail])]);
      }),
      h('div', { class: 'section-title', style: { margin: '12px 0 6px' } }, '建议动作'),
      h('ul', { style: { margin: 0, paddingLeft: '18px', color: 'var(--ink-2)', fontSize: '12.5px' } }, rv.actions.map(function (a) { return h('li', {}, a); })),
    ], { title: '自审明细（review.json）', sub: rv.verdict });

    // 证据流 + 筛选
    var filterWrap = h('div', { class: 'row wrap gap2' });
    var searchInput = h('input', { type: 'text', placeholder: '按标题 / DOI / ev_id 搜索…', style: { maxWidth: '280px' } });
    searchInput.addEventListener('input', function () { q = searchInput.value.trim(); renderEvs(); });
    var evList = h('div', {}, null);
    function renderFilters() {
      UI.clear(filterWrap);
      [['all', '全部'], ['fact', 'fact'], ['artifact', 'artifact']].forEach(function (f) {
        var n = f[0] === 'all' ? evs.length : evs.filter(function (e) { return e.tier === f[0]; }).length;
        filterWrap.appendChild(UI.chip(f[1] + ' (' + n + ')', { on: filter === f[0], onclick: function () { filter = f[0]; renderFilters(); renderEvs(); } }));
      });
    }
    function renderEvs() {
      var list = evs.filter(function (e) {
        if (filter !== 'all' && e.tier !== filter) return false;
        if (q) {
          var m = e.meta || {};
          var hay = (e.ev_id + ' ' + (m.title || '') + ' ' + (m.doi || '') + ' ' + e.ref + ' ' + e.kind).toLowerCase();
          if (hay.indexOf(q.toLowerCase()) < 0) return false;
        }
        return true;
      });
      UI.clear(evList);
      if (!list.length) { evList.appendChild(UI.emptyState('无匹配证据', 'filter')); return; }
      list.forEach(function (e) { evList.appendChild(UI.evidenceCard(e)); });
    }
    function flash(ev) {
      var node = document.getElementById('ev-' + ev);
      if (!node) { filter = 'all'; q = ''; searchInput.value = ''; renderFilters(); renderEvs(); node = document.getElementById('ev-' + ev); }
      if (node) {
        node.scrollIntoView({ behavior: 'smooth', block: 'center' });
        node.classList.add('flash');
        setTimeout(function () { node.classList.remove('flash'); }, 1800);
      }
    }
    renderFilters(); renderEvs();

    var activeEv = ctx.params && ctx.params[0];
    if (activeEv) setTimeout(function () { flash(activeEv); }, 60);

    return h('div', { class: 'grid gap4' }, [
      verdicts,
      UI.card([UI.degradedBar(run)], {}),
      h('div', { class: 'grid g-2-1' }, [
        UI.card([bindings], { title: '结论 ↔ 证据绑定', sub: '每条结论可点 EV 芯片定位证据' }),
        reviewPanel,
      ]),
      UI.card([
        h('div', { class: 'row wrap gap3', style: { marginBottom: '12px' } }, [filterWrap, h('span', { class: 'grow' }), searchInput]),
        evList,
      ], { title: '证据条目流（provenance）', sub: 'tier=fact/artifact · 每条含 sha256 / chain_hash / 生产者步骤' }),
    ]);
  }

  /* ============================================================
   * 界面 5 · 报告与审计导出
   * ============================================================ */
  function inlineMd(text, ctx, runId) {
    var f = document.createDocumentFragment();
    var re = /(\*\*[^*]+\*\*|\[EV-\d+\])/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) f.appendChild(document.createTextNode(text.slice(last, m.index)));
      var tok = m[0];
      if (tok.indexOf('**') === 0) f.appendChild(h('strong', {}, tok.slice(2, -2)));
      else {
        var ev = tok.slice(1, -1);
        f.appendChild(h('span', { class: 'ev-ref', role: 'button', tabindex: '0', title: '查看证据 ' + ev,
          onclick: function () { ctx.app.go('#/evidence/' + runId + '/' + ev); } }, tok));
      }
      last = m.index + tok.length;
    }
    if (last < text.length) f.appendChild(document.createTextNode(text.slice(last)));
    return f;
  }
  function renderMarkdown(md, ctx, runId) {
    var root = h('div', { class: 'report' });
    md.split('\n').forEach(function (line) {
      if (!line.trim()) return;
      if (line.indexOf('# ') === 0) root.appendChild(h('h1', {}, inlineMd(line.slice(2), ctx, runId)));
      else if (line.indexOf('## ') === 0) root.appendChild(h('h2', {}, inlineMd(line.slice(3), ctx, runId)));
      else if (line.indexOf('> ') === 0) root.appendChild(h('blockquote', {}, inlineMd(line.slice(2), ctx, runId)));
      else if (line.indexOf('- ') === 0) {
        var ul = root.lastChild;
        if (!ul || ul.tagName !== 'UL') { ul = h('ul', {}); root.appendChild(ul); }
        ul.appendChild(h('li', {}, inlineMd(line.slice(2), ctx, runId)));
      } else root.appendChild(h('p', {}, inlineMd(line, ctx, runId)));
    });
    return root;
  }
  function report(ctx) {
    var runId = ctx.runId && ctx.runId !== 'undefined' ? ctx.runId : D.SHOWCASE_ID;
    var exportWrap = h('div', { class: 'col gap3' }, [
      h('button', { class: 'btn solid', onclick: function () {
        var b = this; b.disabled = true; b.textContent = '生成审计包中…';
        setTimeout(function () {
          b.disabled = false; b.innerHTML = '';
          b.appendChild(icon('download')); b.appendChild(document.createTextNode('导出审计包 ZIP'));
          UI.toast('审计包已生成（Demo）', 'paper-agent-audit-' + runId + '.zip', 'ok');
        }, 900);
      } }, [icon('download'), '导出审计包 ZIP']),
      h('button', { class: 'btn', onclick: function () { UI.toast('已复制引用（Demo）', '10 条文献引用 + 5 条结论', 'ok'); } }, [icon('copy'), '复制引用']),
      h('button', { class: 'btn ghost', onclick: function () { UI.toast('已下载 report.md（Demo）', '', 'ok'); } }, [icon('file'), '导出 Markdown']),
    ]);

    var manifest = UI.card([
      h('div', { class: 'manifest' }, D.AUDIT_PACK.map(function (f) {
        return h('div', { class: 'mf-row' }, [
          h('span', { class: 'mf-ico' }, icon(f.name.endsWith('.py') ? 'bolt' : 'file')),
          h('div', { class: 'grow col' }, [
            h('div', { class: 'mf-name' }, f.name),
            h('div', { class: 'mf-desc' }, f.desc),
          ]),
          h('span', { class: 'mf-hash', title: f.hash }, f.hash.slice(0, 10) + '…'),
          h('span', { class: 'badge ok', style: { marginLeft: '8px' } }, [icon('check'), '哈希已登记']),
          h('span', { class: 'badge ok' }, [icon('check'), '链校验通过']),
        ]);
      })),
    ], { title: '审计包内容清单', sub: '独立复核脚本可离线校验哈希链' });

    return h('div', { class: 'grid gap4' }, [
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [
        h('div', { class: 'col' }, [
          h('div', { style: { fontSize: '18px', fontWeight: 700 } }, '报告与审计导出'),
          h('div', { class: 'muted' }, '把 run 变成可交付报告 + 可复核审计包'),
        ]),
        UI.badge('哈希链完整', 'ok', 'shield'),
      ]),
      h('div', { class: 'grid g-2-1' }, [
        UI.card([renderMarkdown(D.REPORT_MD, ctx, runId)], { title: 'report.md', sub: '结论带 [EV-XXXX] 角标，可点击溯源' }),
        h('div', { class: 'col gap4' }, [UI.card([exportWrap], { title: '导出面板' }), manifest]),
      ]),
    ]);
  }

  /* ============================================================
   * 界面 6 · 文献资源
   * ============================================================ */
  function library(ctx) {
    var tab = 'lit';
    var body = h('div');
    var tabsWrap = h('div', { class: 'tabs' });
    function renderTabs() {
      UI.clear(tabsWrap);
      [['lit', '文献库'], ['data', '数据集'], ['graph', '证据图']].forEach(function (t) {
        tabsWrap.appendChild(h('button', { class: 'tab' + (tab === t[0] ? ' on' : ''), onclick: function () { tab = t[0]; renderTabs(); renderBody(); } }, t[1]));
      });
    }
    function renderBody() {
      UI.clear(body);
      if (tab === 'lit') {
        body.appendChild(UI.card([UI.dataTable([
          { label: '标题', render: function (r) { return h('span', { class: 't-title' }, r.title); } },
          { label: '作者', key: 'authors' },
          { label: '年份', render: function (r) { return h('span', { class: 'mono' }, r.year); } },
          { label: '期刊', key: 'venue' },
          { label: 'DOI', render: function (r) { return h('a', { class: 'mono', href: '#', onclick: function (e) { e.preventDefault(); UI.toast('核对 DOI（Demo）', 'https://doi.org/' + r.doi, 'ok'); } }, r.doi); } },
          { label: '来源', render: function (r) { return UI.badge(r.source, 'tier'); } },
          { label: '引用', render: function (r) { return h('span', { class: 'mono' }, r.cites); } },
        ], D.LITERATURE)], { title: '文献库', sub: D.LITERATURE.length + ' 篇 · DOI 可核对（均为真实 DOI）' }));
      } else if (tab === 'data') {
        body.appendChild(h('div', { class: 'grid g2' }, D.DATASETS.map(function (d) {
          return UI.card([
            h('div', { class: 'row gap2' }, [UI.badge(d.license, 'ok'), UI.badge(d.files, 'tier')]),
            h('div', { class: 'muted', style: { margin: '10px 0', fontSize: '12.5px' } }, d.desc),
            h('div', { class: 'row gap4', style: { fontSize: '12.5px' } }, [
              h('div', {}, [h('div', { class: 'muted' }, '原始行数'), h('div', { class: 'mono', style: { fontSize: '16px' } }, d.rows_raw)]),
              h('span', { class: 'muted' }, '→'),
              h('div', {}, [h('div', { class: 'muted' }, '清洗后'), h('div', { class: 'mono', style: { fontSize: '16px', color: 'var(--ok)' } }, d.rows_cleaned)]),
            ]),
            h('a', { href: '#', class: 'mono', style: { display: 'inline-block', marginTop: '12px' }, onclick: function (e) { e.preventDefault(); UI.toast('数据集来源（Demo）', d.source, 'ok'); } }, [d.source]),
          ], { title: d.name });
        })));
      } else {
        body.appendChild(UI.card([buildGraph()], { title: '结论 — 证据 — 文献 关系图', sub: '力导向简化版（示意）' }));
      }
    }
    function buildGraph() {
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 680 360'); svg.style.width = '100%'; svg.style.height = '360px';
      var concl = [{ id: 'C1', x: 120, y: 70 }, { id: 'C2', x: 120, y: 160 }, { id: 'C3', x: 120, y: 250 }];
      var evs = [{ id: 'EV-0001', x: 340, y: 50 }, { id: 'EV-0002', x: 340, y: 110 }, { id: 'EV-0012', x: 340, y: 160 }, { id: 'EV-0016', x: 340, y: 250 }];
      var lit = [{ id: 'Kamaya2011', x: 560, y: 50 }, { id: 'Kato2016', x: 560, y: 110 }, { id: 'Murugan2007', x: 560, y: 200 }];
      function line(a, b) { var l = document.createElementNS('http://www.w3.org/2000/svg', 'line'); l.setAttribute('x1', a.x); l.setAttribute('y1', a.y); l.setAttribute('x2', b.x); l.setAttribute('y2', b.y); l.setAttribute('stroke', '#303036'); l.setAttribute('stroke-width', '1.2'); svg.appendChild(l); }
      line(concl[0], evs[0]); line(concl[0], evs[1]); line(concl[1], evs[2]); line(concl[2], evs[3]);
      line(evs[0], lit[0]); line(evs[1], lit[1]); line(evs[2], lit[1]); line(evs[3], lit[2]);
      function node(p, text, color) {
        var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', '7'); c.setAttribute('fill', color); svg.appendChild(c);
        var t = document.createElementNS('http://www.w3.org/2000/svg', 'text'); t.setAttribute('x', p.x); t.setAttribute('y', p.y + 22); t.setAttribute('text-anchor', 'middle'); t.setAttribute('fill', '#8A8A85'); t.setAttribute('font-size', '11'); t.setAttribute('font-family', 'monospace'); t.textContent = text; svg.appendChild(t);
      }
      concl.forEach(function (p) { node(p, p.id, '#D9A441'); });
      evs.forEach(function (p) { node(p, p.id, '#7FA8D9'); });
      lit.forEach(function (p) { node(p, p.id, '#6BBF8A'); });
      return svg;
    }
    renderTabs(); renderBody();
    return h('div', { class: 'grid gap4' }, [
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [
        h('div', { class: 'col' }, [
          h('div', { style: { fontSize: '18px', fontWeight: 700 } }, '文献资源'),
          h('div', { class: 'muted' }, '证明「数据是真的」——真实 DOI、真实数据集、来源可核对'),
        ]),
      ]),
      tabsWrap, body,
    ]);
  }

  /* ============================================================
   * 界面 7 · 环境体检 / 设置
   * ============================================================ */
  function health(ctx) {
    var items = D.HEALTH.map(function (x) { return Object.assign({}, x, { _state: 'idle' }); });
    var banner = h('div', { class: 'health-banner' });
    var list = h('div');
    function renderBanner() {
      UI.clear(banner);
      var hasWarn = items.some(function (i) { return i._state === 'warn'; });
      var hasFail = items.some(function (i) { return i._state === 'fail'; });
      var state = !items.some(function (i) { return i._state !== 'idle'; }) ? 'idle' : hasFail ? 'fail' : hasWarn ? 'warn' : 'ok';
      var cfg = { idle: ['menu', 'idle', '尚未体检', '点击右侧「开始体检」逐项自检'], ok: ['check', 'ok', '环境健康', '全部 ' + items.length + ' 项通过'], warn: ['warn', 'warn', '有 2 项需处理', '不阻断主流程，按指引修复即可'], fail: ['alert', 'fail', '存在阻断项', '请先修复阻断项'] }[state];
      banner.appendChild(h('div', { class: 'hb-ico', style: { background: 'var(--raised)', color: 'var(--' + cfg[1] + ')' } }, icon(cfg[0], 24)));
      banner.appendChild(h('div', { class: 'grow col' }, [h('div', { style: { fontSize: '16px', fontWeight: 650 } }, cfg[2]), h('div', { class: 'muted' }, cfg[3])]));
      banner.appendChild(h('button', { class: 'btn solid', onclick: runCheck }, [icon('heart'), '开始体检']));
    }
    function renderList() {
      UI.clear(list);
      items.forEach(function (it) {
        var s = it._state;
        var ic = { idle: ['clock', 'ci-pending'], run: ['refresh', 'ci-pending'], ok: ['check', 'ci-ok'], warn: ['warn', 'ci-warn'], fail: ['alert', 'ci-fail'] }[s];
        var lbl = { idle: '待检测', run: '检测中…', ok: '通过', warn: '需处理', fail: '阻断' }[s];
        var row = h('div', { class: 'check-item' }, [
          h('div', { class: 'ci-ico ' + ic[1] }, icon(ic[0], 14)),
          h('div', { class: 'grow col' }, [
            h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [
              h('span', { class: 'ci-name' }, it.name),
              UI.badge(lbl, s === 'ok' ? 'ok' : s === 'warn' ? 'warn' : s === 'fail' ? 'fail' : 'idle'),
            ]),
            s !== 'idle' && s !== 'run' ? h('div', { class: 'ci-detail' }, it.detail) : null,
            (s === 'warn' || s === 'fail') && it.fix ? h('div', { class: 'row' }, [
              h('div', { class: 'ci-fix grow' }, [h('b', {}, '修复指引：'), it.fix]),
              h('button', { class: 'btn sm', style: { marginLeft: '10px' }, onclick: function () { it._state = 'ok'; it.detail = it.detail + ' · 已按指引修复'; renderList(); renderBanner(); UI.toast('已应用修复（Demo）', it.name, 'ok'); } }, '一键修复'),
            ]) : null,
          ]),
        ]);
        list.appendChild(row);
      });
    }
    function runCheck() {
      items.forEach(function (i) { i._state = 'idle'; });
      renderList(); renderBanner();
      var k = 0;
      var t = setInterval(function () {
        if (k < items.length) {
          items[k]._state = 'run'; renderList();
          (function (idx) {
            setTimeout(function () {
              items[idx]._state = D.HEALTH[idx].status; // 还原真实结论
              k = idx + 1; renderList(); renderBanner();
              if (k >= items.length) { clearInterval(t); UI.toast('体检完成：4 项通过 · 2 项需处理', '请看修复指引', 'warn'); }
            }, 420);
          })(k);
        } else clearInterval(t);
      }, 520);
      setTimeout(function () { items[0] && items.forEach(function (i) { if (i._state === 'idle') i._state = 'run'; }); renderList(); }, 10);
    }
    // 初始：显示真实状态（无需点击也可见）
    items.forEach(function (i) { i._state = i.status; });
    renderBanner(); renderList();

    var settings = UI.card([
      settingRow('主题', ['dark', 'light'], D.SETTINGS.theme, function (v) { D.SETTINGS.theme = v; UI.toast('主题已切换（Demo 仅示意）', v); }),
      settingRow('默认工作流', ['research', 'materials'], D.SETTINGS.defaultWorkflow, function (v) { D.SETTINGS.defaultWorkflow = v; UI.toast('默认工作流已保存', v); }),
      settingRow('默认检索来源', ['auto', 'arxiv', 'local'], D.SETTINGS.defaultSource, function (v) { D.SETTINGS.defaultSource = v; UI.toast('默认来源已保存', v); }),
    ], { title: '设置（快速入口）', sub: '完整设置见左侧「设置」' });
    function settingRow(label, opts, cur, onChange) {
      var wrap = h('div', { class: 'row wrap gap2', style: { marginBottom: '10px' } }, [h('span', { style: { width: '120px', color: 'var(--ink-2)', fontSize: '12.5px' } }, label)]);
      opts.forEach(function (o) {
        wrap.appendChild(UI.chip(o, { on: cur === o, onclick: function () { onChange(o); } }));
      });
      return wrap;
    }

    return h('div', { class: 'grid gap4' }, [
      h('div', { class: 'col' }, [
        h('div', { style: { fontSize: '18px', fontWeight: 700 } }, '环境体检 / 设置'),
        h('div', { class: 'muted' }, '把「上手门槛高」变成加分项：一键自检 + 人类可读修复指引'),
      ]),
      banner,
      h('div', { class: 'grid g-2-1' }, [
        UI.card([list], { title: '体检项', sub: '每项均给出具体修复指引（绝不出现 ModuleNotFoundError 误导）' }),
        UI.card([
          h('div', { class: 'col gap2', style: { fontSize: '12.5px', color: 'var(--ink-2)' } }, [
            h('div', {}, [h('b', {}, '环境变量契约'), '（P0-2 修复方向）']),
            h('div', { class: 'mono', style: { background: 'var(--raised)', padding: '8px 10px', borderRadius: '6px' } }, 'paper-agent_ROOT = "" （未生效）'),
            h('div', { class: 'mono', style: { background: 'var(--raised)', padding: '8px 10px', borderRadius: '6px' } }, 'paper-agent_PYTHON = /usr/bin/python3'),
            h('div', { class: 'help' }, '在启动 daemon 的终端里设置后重启 daemon；避免重复 export 导致覆盖。'),
          ]),
        ], { title: '环境变量实际生效值' }),
      ]),
      settings,
    ]);
  }

  /* ============================================================
   * 界面 8 · AGH 集成
   * ============================================================ */
  function agh(ctx) {
    var layers = [
      ['L1', '交互层', 'Web / CLI / 科研工作台（本原型）'],
      ['L2', '编排层', '模型驱动：sciret_plan → run_step → status'],
      ['L3', '插件层', 'paper-agent-tools（7 工具，trusted）'],
      ['L4', 'Python CLI 内核', 'paper-agent.cli（零依赖，状态机 + 台账）'],
      ['L5', '产物层', 'runs/<id>/：state / provenance / conclusions / toolcalls'],
      ['L6', '执行底座', 'AGH 守护进程 · 会话账本 · 审批'],
    ];
    var layerDiag = h('div', { class: 'layer-diagram' }, layers.map(function (l, i) {
      return h('div', { class: 'layer' + (i === 2 ? ' hi' : '') }, [
        h('span', { class: 'ly-tag' }, l[0]),
        h('span', { class: 'ly-name' }, l[1]),
        h('span', { class: 'ly-desc' }, l[2]),
      ]);
    }));

    var toolWrap = h('div', { class: 'grid g2' });
    D.TOOLS.forEach(function (t) {
      var card = h('div', { class: 'card tool-cat', role: 'button', tabindex: '0', onclick: function () { card.querySelector('.tc-detail').classList.toggle('hidden'); } }, [
        h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [h('span', { class: 'tname' }, t.name), t.meta.isReadOnly ? UI.badge('只读', 'ok', 'shield') : UI.badge('写操作', 'warn', 'bolt')]),
        h('div', { class: 'muted', style: { fontSize: '12px', marginTop: '6px' } }, t.desc),
        h('div', { class: 'meta-tags' }, [
          h('span', { class: 'meta-tag ' + (t.meta.isReadOnly ? 'ro' : '') }, 'isReadOnly=' + t.meta.isReadOnly),
          h('span', { class: 'meta-tag' }, 'requiresApproval=' + t.meta.requiresApproval),
          h('span', { class: 'meta-tag' }, 'replay=' + t.meta.replay),
          h('span', { class: 'meta-tag' }, 'wallMs=' + t.meta.wallMs),
        ]),
        h('div', { class: 'tc-detail hidden', style: { marginTop: '10px' } }, [
          h('div', { class: 'tc-sec-label' }, 'parameters'),
          UI.pre(t.params.map(function (p) { return p[0] + ': ' + p[1] + (p[2] ? ' (required)' : ''); }).join('\n')),
        ]),
      ]);
      toolWrap.appendChild(card);
    });

    // 会话回放
    var replay = h('div', { class: 'replay' });
    var replayIdx = -1;
    D.AGH_SESSION.events.forEach(function (e, i) {
      var isCall = e.kind === 'tool/call';
      replay.appendChild(h('div', { class: 'replay-ev', dataset: { i: i } }, [
        h('span', { class: 're-clock mono', style: { width: '70px', color: 'var(--ink-3)', flex: '0 0 auto' } }, e.at),
        h('span', { class: 're-kind ' + (isCall ? 'call' : 'result') }, isCall ? 'call' : 'result'),
        h('div', { class: 're-body' }, [
          h('div', { class: 're-tool' }, e.tool),
          h('div', { class: 'mono', style: { fontSize: '11px', color: 'var(--ink-3)', whiteSpace: 'pre-wrap' } },
            JSON.stringify(isCall ? e.input : e.output)),
        ]),
      ]));
    });
    var replayTimer = null;
    function play() {
      var n = D.AGH_SESSION.events.length;
      UI.clear(replay);
      D.AGH_SESSION.events.forEach(function (e, i) {
        var isCall = e.kind === 'tool/call';
        replay.appendChild(h('div', { class: 'replay-ev', dataset: { i: i } }, [
          h('span', { class: 're-clock mono', style: { width: '70px', color: 'var(--ink-3)', flex: '0 0 auto' } }, e.at),
          h('span', { class: 're-kind ' + (isCall ? 'call' : 'result') }, isCall ? 'call' : 'result'),
          h('div', { class: 're-body' }, [
            h('div', { class: 're-tool' }, e.tool),
            h('div', { class: 'mono', style: { fontSize: '11px', color: 'var(--ink-3)', whiteSpace: 'pre-wrap' } }, JSON.stringify(isCall ? e.input : e.output)),
          ]),
        ]));
      });
      var k = -1;
      clearInterval(replayTimer);
      replayTimer = setInterval(function () {
        k++;
        if (k >= n) { clearInterval(replayTimer); return; }
        var rows = replay.querySelectorAll('.replay-ev');
        rows.forEach(function (r, j) { r.classList.toggle('on', j <= k); });
        rows[k].scrollIntoView({ block: 'nearest' });
      }, 700);
    }
    ctx.onCleanup(function () { clearInterval(replayTimer); });

    var boundary = h('div', { class: 'boundary' }, [
      h('div', { style: { fontWeight: 650, color: 'var(--ink)' } }, '集成边界（诚实呈现）'),
      h('ul', {}, [
        h('li', {}, 'AGH 是执行底座，不是强依赖：科研能力全部在 Python CLI 内。'),
        h('li', {}, 'ACP 模式不装载第三方插件（已关闭该模式），避免边界混淆。'),
        h('li', {}, '已知限制：写类工具默认 requiresApproval="destructive"，若宿主将 approvals.mode 设为 off 会被旁路（宿主配置责任）。'),
        h('li', {}, '本 Demo 的会话回放为固定脚本，不连 AGH、不联网，保证 100% 可重复。'),
      ]),
    ]);

    return h('div', { class: 'grid gap4' }, [
      h('div', { class: 'col' }, [
        h('div', { style: { fontSize: '18px', fontWeight: 700 } }, 'AGH 集成'),
        h('div', { class: 'muted' }, 'AGH 是执行底座 · 7 个 sciret_* 工具 · 诚实讲清边界'),
      ]),
      h('div', { class: 'grid g-2-1' }, [
        UI.card([layerDiag], { title: '架构六层（L1–L6）', sub: '科研能力下沉到 L4，L3 仅做工具暴露' }),
        UI.card([boundary], { title: '集成边界说明' }),
      ]),
      UI.card([toolWrap], { title: 'sciret_* 工具目录（7 个）', sub: '点卡片展开参数 schema' }),
      UI.card([
        h('div', { class: 'row', style: { marginBottom: '10px' } }, [
          h('div', { class: 'col' }, [h('div', { class: 'mono', style: { fontSize: '12px' } }, 'session ' + D.AGH_SESSION.session_id), h('div', { class: 'muted', style: { fontSize: '11.5px' } }, 'run ' + D.AGH_SESSION.run_id + ' · 起于 ' + D.AGH_SESSION.started_at)]),
          h('span', { class: 'grow' }),
          h('button', { class: 'btn solid', onclick: play }, [icon('play'), '播放会话回放']),
        ]),
        replay,
      ], { title: '会话回放', sub: '固定脚本 · 模型调用 sciret_plan → run_step → status → cite' }),
    ]);
  }

  /* ============================================================
   * 界面 7b · 设置
   * ============================================================ */
  function settings(ctx) {
    function settingRow(label, opts, cur, onChange) {
      var wrap = h('div', { class: 'row wrap gap2', style: { marginBottom: '12px' } }, [h('span', { style: { width: '130px', color: 'var(--ink-2)', fontSize: '12.5px' } }, label)]);
      opts.forEach(function (o) {
        wrap.appendChild(UI.chip(o, {
          on: cur === o,
          onclick: function () { onChange(o); UI.toast('设置已保存（Demo）', label + ' = ' + o, 'ok'); },
        }));
      });
      return wrap;
    }
    return h('div', { class: 'grid gap4', style: { maxWidth: '720px' } }, [
      h('div', { class: 'col' }, [
        h('div', { style: { fontSize: '18px', fontWeight: 700 } }, '设置'),
        h('div', { class: 'muted' }, '主题 / 默认工作流 / 默认检索来源'),
      ]),
      UI.card([
        settingRow('主题', ['dark', 'light'], D.SETTINGS.theme, function (v) { D.SETTINGS.theme = v; }),
        settingRow('默认工作流', ['research', 'materials'], D.SETTINGS.defaultWorkflow, function (v) { D.SETTINGS.defaultWorkflow = v; }),
        settingRow('默认检索来源', ['auto', 'arxiv', 'local'], D.SETTINGS.defaultSource, function (v) { D.SETTINGS.defaultSource = v; }),
      ], { title: '偏好设置' }),
      UI.card([
        h('div', { class: 'col gap2', style: { fontSize: '12.5px', color: 'var(--ink-2)' } }, [
          h('div', {}, [h('b', {}, '环境变量契约'), '（显示实际生效值）']),
          h('div', { class: 'mono', style: { background: 'var(--raised)', padding: '8px 10px', borderRadius: '6px' } }, 'paper-agent_ROOT = "" （未生效）'),
          h('div', { class: 'mono', style: { background: 'var(--raised)', padding: '8px 10px', borderRadius: '6px' } }, 'paper-agent_PYTHON = /usr/bin/python3'),
          h('div', { class: 'help' }, '在启动 daemon 的终端里设置后重启 daemon；避免重复 export 覆盖（见环境体检页 P0-2 指引）。'),
        ]),
      ], { title: '环境变量' }),
    ]);
  }

  /* ============================================================
   * 界面 9（可选）· 故障恢复演练
   * ============================================================ */
  function recovery(ctx) {
    var scenes = [
      { name: 'A · 工具失败自动重试', desc: '单步失败时按 attempts 重试，成功即继续；不丢步骤。', flow: [['fail', 'R4_verify 失败'], ['warn', 'attempts=2 重试'], ['ok', 'R4_verify 完成']] },
      { name: 'B · 数据源降级切源', desc: '数据源不可用 → 自动切源，橙色提示「任务未中断」。', flow: [['fail', 'semantic_scholar HTTPError'], ['warn', '自动降级'], ['ok', 'crossref 补位']] },
      { name: 'C · 崩溃后断点续跑', desc: '进程中断后 sciret_resume：仅执行 PENDING/FAILED，DONE 复用。', flow: [['warn', 'daemon 崩溃'], ['run', 'sciret_resume'], ['ok', '复用已完成步骤']] },
      { name: 'D · 复现校验失败回滚', desc: 'P4 容差校验不通过 → run_status=FAILED，保留现场供诊断。', flow: [['ok', 'P3 实验完成'], ['fail', 'P4 容差校验失败'], ['warn', '标记 FAILED，不产出报告']] },
    ];
    return h('div', { class: 'grid gap4' }, [
      h('div', { class: 'col' }, [
        h('div', { style: { fontSize: '18px', fontWeight: 700 } }, '故障恢复演练'),
        h('div', { class: 'muted' }, '四种故障场景的确定性恢复路径 · 强化「可故障恢复」卖点'),
      ]),
      h('div', { class: 'grid g2' }, scenes.map(function (s) {
        return h('div', { class: 'scenario' }, [
          h('div', { class: 'sc-name' }, s.name),
          h('div', { class: 'sc-desc' }, s.desc),
          h('div', { class: 'sc-flow' }, s.flow.map(function (n, i) {
            return UI.frag(i > 0 ? h('span', { class: 'sc-arrow' }, '→') : null, h('span', { class: 'sc-node ' + n[0] }, n[1]));
          })),
        ]);
      })),
      UI.card([
        h('div', { class: 'muted', style: { fontSize: '12.5px' } }, '以上场景均由 paper-agent 状态机 + append-only 台账保证：任何中断都可从 run 目录恢复，且哈希链保持完整。'),
      ], { title: '为什么可恢复' }),
    ]);
  }

  window.PA_VIEWS = { overview: overview, newTask: newTask, monitor: monitor, evidence: evidence, report: report, library: library, health: health, settings: settings, agh: agh, recovery: recovery };
})();
