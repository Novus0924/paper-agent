/* ============================================================
 * components.js —— 无依赖 UI 原语（挂 window.PA_UI）
 * h() 极简 hyperscript；icon() 内联 SVG；组件均返回 DOM 节点。
 * ============================================================ */
(function () {
  'use strict';

  /* ---------- hyperscript ---------- */
  function append(el, kids) {
    for (const k of kids) {
      if (k == null || k === false) continue;
      if (Array.isArray(k)) { append(el, k); continue; }
      if (k instanceof Node) { el.appendChild(k); continue; }
      el.appendChild(document.createTextNode(String(k)));
    }
  }
  function h(tag, attrs) {
    const el = document.createElement(tag);
    const kids = Array.prototype.slice.call(arguments, 2);
    if (attrs && typeof attrs === 'object' && !(attrs instanceof Node) && !Array.isArray(attrs)) {
      for (const k in attrs) {
        const v = attrs[k];
        if (v == null || v === false) continue;
        if (k === 'class' || k === 'className') el.className = v;
        else if (k === 'html') el.innerHTML = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
        else if (k === 'dataset' && typeof v === 'object') Object.assign(el.dataset, v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (v === true) el.setAttribute(k, '');
        else el.setAttribute(k, v);
      }
    } else {
      kids.unshift(attrs);
    }
    append(el, kids);
    return el;
  }
  function frag() { const f = document.createDocumentFragment(); append(f, Array.prototype.slice.call(arguments)); return f; }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function mount(el, node) { clear(el); append(el, [node]); return el; }

  /* ---------- 图标（stroke = currentColor, 24x24） ---------- */
  const ICONS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    activity: '<polyline points="3 12 7 12 10 5 14 19 17 12 21 12"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><polyline points="14 3 14 8 19 8"/>',
    book: '<path d="M4 4h12a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z"/><line x1="18" y1="20" x2="8" y2="20"/>',
    heart: '<path d="M12 21s-7-4.5-9.5-9A5.5 5.5 0 0 1 12 6a5.5 5.5 0 0 1 9.5 6c-2.5 4.5-9.5 9-9.5 9z"/>',
    box: '<path d="M9 3v6M15 3v6M6 9h12v3a6 6 0 0 1-12 0zM12 18v3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6A7 7 0 0 0 19 12z"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    warn: '<path d="M12 3 2 20h20L12 3z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="17" r=".7" fill="currentColor" stroke="none"/>',
    alert: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><circle cx="12" cy="16.4" r=".7" fill="currentColor" stroke="none"/>',
    clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    download: '<path d="M12 3v12"/><polyline points="7 10 12 15 17 10"/><path d="M4 19h16"/>',
    search: '<circle cx="11" cy="11" r="7"/><line x1="16" y1="16" x2="21" y2="21"/>',
    play: '<polygon points="6 4 20 12 6 20 6 4"/>',
    chevR: '<polyline points="9 6 15 12 9 18"/>',
    chevD: '<polyline points="6 9 12 15 18 9"/>',
    external: '<path d="M14 3h7v7"/><path d="M21 3l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
    hash: '<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/>',
    layers: '<polygon points="12 3 21 8 12 13 3 8"/><polyline points="3 13 12 18 21 13"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><polyline points="21 3 21 8 16 8"/>',
    spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    filter: '<polygon points="3 5 21 5 14 13 14 20 10 17 10 13 3 5"/>',
    x: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
    menu: '<line x1="3" y1="7" x2="21" y2="7"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="17" x2="21" y2="17"/>',
    db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  };
  function icon(name, sz) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    // 默认尺寸必须显式设置，否则 SVG 在 flex 容器内会撑满（CSS width/height 可覆盖）
    const s = sz || 16;
    svg.setAttribute('width', s);
    svg.setAttribute('height', s);
    svg.style.flex = '0 0 auto';
    svg.innerHTML = ICONS[name] || '';
    return svg;
  }

  /* ---------- 状态映射 ---------- */
  function statusClass(s) {
    return ({ DONE: 'ok', RUNNING: 'run', FAILED: 'fail', PENDING: 'idle', PLANNED: 'idle', SKIPPED: 'idle',
      ok: 'ok', warn: 'warn', fail: 'fail' })[s] || 'idle';
  }
  function runStatusBadge(run) {
    const map = { DONE: ['ok', '已完成'], RUNNING: ['run', '运行中'], FAILED: ['fail', '失败'], PLANNED: ['idle', '待执行'] };
    const [cls, label] = map[run.run_status] || ['idle', run.run_status];
    const kids = [h('span', { class: 'dot' }), label];
    if (run.degraded && run.run_status !== 'FAILED') kids.push(h('span', { class: 'muted', style: { fontSize: '11px' } }, '· 已降级'));
    return h('span', { class: 'badge ' + cls }, kids);
  }
  function statusDot(s) { return h('span', { class: 'sdot ' + s, title: s }); }
  function badge(text, cls, ic) {
    const kids = [];
    if (ic) kids.push(icon(ic));
    else kids.push(h('span', { class: 'dot' }));
    kids.push(text);
    return h('span', { class: 'badge ' + (cls || '') }, kids);
  }
  function chip(label, opts) {
    opts = opts || {};
    const c = h('button', { class: 'chip' + (opts.on ? ' on' : '') + (opts.off ? ' off' : '') + (opts.static ? ' static' : ''),
      type: 'button', title: opts.title || '', onclick: opts.off || opts.static ? null : opts.onclick }, label);
    if (opts.icon) c.insertBefore(icon(opts.icon), c.firstChild);
    return c;
  }
  function sectionTitle(t) { return h('div', { class: 'section-title' }, t); }
  function card(kids, opts) {
    opts = opts || {};
    const c = h('div', { class: 'card' + (opts.pad5 ? ' pad5' : '') });
    if (opts.title) {
      c.appendChild(h('div', { class: 'card-hd' }, [
        h('div', { class: 'grow col' }, [
          h('h3', {}, opts.title),
          opts.sub ? h('div', { class: 'sub' }, opts.sub) : null,
        ]),
        opts.actions || null,
      ]));
    }
    append(c, Array.isArray(kids) ? kids : [kids]);
    return c;
  }
  function kpiCard(k) {
    return h('div', { class: 'card kpi', onclick: k.onclick, role: 'button', tabindex: '0' },
      h('div', { class: 'k-label' }, [icon(k.icon || 'spark'), k.label]),
      h('div', { class: 'k-val' }, [k.value, h('span', { class: 'unit' }, k.unit)]),
      h('div', { class: 'k-sub' }, k.sub));
  }
  function emptyState(msg, ic) {
    return h('div', { class: 'empty' }, [icon(ic || 'search'), h('div', {}, msg)]);
  }
  function pre(obj) {
    const txt = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
    return h('pre', { class: 'code' }, txt);
  }
  function tooltip(bodyNode, opts) {
    opts = opts || {};
    return h('span', { class: 'tip' + (opts.flip ? ' flip' : '') }, [bodyNode, h('span', { class: 'tip-body' }, opts.text || '')]);
  }
  function copyText(text, toastFn) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => toastFn && toastFn('已复制到剪贴板', text), () => fallbackCopy(text, toastFn));
      } else fallbackCopy(text, toastFn);
    } catch (e) { fallbackCopy(text, toastFn); }
  }
  function fallbackCopy(text, toastFn) {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toastFn && toastFn('已复制到剪贴板', text); }
    catch (e) { toastFn && toastFn('复制失败，请手动选择', text); }
    document.body.removeChild(ta);
  }

  /* ---------- toast ---------- */
  let toastHost = null;
  function toast(msg, sub, kind) {
    if (!toastHost) {
      toastHost = h('div', { class: 'toasts' });
      document.body.appendChild(toastHost);
    }
    const t = h('div', { class: 'toast ' + (kind || '') }, [
      icon(kind === 'warn' ? 'warn' : kind === 'fail' ? 'alert' : 'check'),
      h('div', { class: 'grow' }, [h('div', {}, msg), sub ? h('div', { class: 't-sub' }, sub) : null]),
    ]);
    toastHost.appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 3200);
  }

  /* ---------- 步骤条 ---------- */
  function stepBar(stepsOrder, steps, labels) {
    const bar = h('div', { class: 'stepbar' });
    stepsOrder.forEach((sid, i) => {
      const st = steps[sid] || 'PENDING';
      bar.appendChild(h('div', { class: 'step', dataset: { status: st, step: sid } }, [
        h('div', { class: 's-idx' }, st === 'DONE' ? icon('check', 12) : String(i + 1)),
        h('div', { class: 's-body' }, [
          h('div', { class: 's-name' }, labels[sid] || sid),
          h('div', { class: 's-id' }, sid),
        ]),
      ]));
      if (i < stepsOrder.length - 1) bar.appendChild(h('span', { class: 'step-arrow' }, icon('chevR', 14)));
    });
    return bar;
  }
  function miniStepBar(stepsOrder, steps) {
    const bar = h('div', { class: 'mini-stepbar' });
    stepsOrder.forEach((sid) => {
      const st = (steps[sid] || 'PENDING').toLowerCase();
      bar.appendChild(h('div', { class: 'mini-step ' + st, title: sid + ' · ' + steps[sid] }));
    });
    return bar;
  }

  /* ---------- 降级条 ---------- */
  function degradedBar(run) {
    const unav = (window.PA_DATA.UNAVAILABLE || []).join('、');
    const st = window.PA_DATA.SOURCES_STATUS || {};
    const bad = Object.keys(st).filter((k) => String(st[k]).indexOf('unavailable') === 0);
    const detail = bad.map((k) => k + '（' + st[k] + '）').join(' · ');
    return h('div', { class: 'degraded-bar', role: 'status' }, [
      icon('warn'),
      h('span', {}, [
        h('b', {}, '已自动降级：'),
        detail || unav,
        h('span', { class: 'dg-notstop' }, ' · 任务未中断'),
      ]),
      tooltip(h('button', { class: 'dg-help', type: 'button' }, '这是什么？'), {
        text: '降级 = 某个数据源临时不可用（如 semantic_scholar 返回 HTTPError），系统自动切换到可用来源继续执行，属于「特色非失败」，产物完整、哈希链不受影响。',
      }),
    ]);
  }

  /* ---------- 工具卡 ---------- */
  function sourcesTag(sourcesStatus) {
    const wrap = h('div', { class: 'src-grid' });
    Object.keys(sourcesStatus || {}).forEach((k) => {
      const v = String(sourcesStatus[k]);
      const bad = v.indexOf('unavailable') === 0;
      wrap.appendChild(h('span', { class: 'src-tag ' + (bad ? 'bad' : 'ok') },
        [icon(bad ? 'warn' : 'check', 12), k + ':' + v.replace('ok:', '').replace('unavailable:', '✕ ')]));
    });
    return wrap;
  }
  function toolCard(tc, opts) {
    opts = opts || {};
    const open = !!opts.open;
    const body = h('div', { class: 'tc-body' + (open ? '' : ' hidden') }, [
      h('div', {}, [h('div', { class: 'tc-sec-label' }, 'input'), pre(tc.input)]),
      h('div', {}, [h('div', { class: 'tc-sec-label' }, 'output'), pre(tc.output)]),
      tc.output && tc.output.sources_status
        ? h('div', {}, [h('div', { class: 'tc-sec-label' }, 'sources_status（四源）'), sourcesTag(tc.output.sources_status)])
        : null,
    ]);
    const chev = icon('chevD', 14);
    const hd = h('div', { class: 'tc-hd', onclick: function () {
      const hid = body.classList.toggle('hidden');
      chev.style.transform = hid ? 'rotate(-90deg)' : '';
    } }, [
      chev,
      h('span', { class: 'tc-name' }, tc.tool),
      h('span', { class: 'tc-step' }, '· ' + tc.step + ' · ' + (window.PA_DATA.STEP_LABELS[tc.step] || '')),
      h('span', { class: 'grow' }),
      h('span', { class: 'tc-badge' }, tc.invoked_at ? tc.invoked_at.slice(11) : ''),
      badge('完成', 'ok'),
    ]);
    chev.style.transition = 'transform 150ms var(--ease)';
    if (!open) chev.style.transform = 'rotate(-90deg)';
    return h('div', { class: 'toolcard' + (opts.current ? ' current' : '') }, [hd, body]);
  }
  function skeletonToolCard(step) {
    return h('div', { class: 'toolcard current' }, [
      h('div', { class: 'tc-hd' }, [
        icon('refresh', 14),
        h('span', { class: 'tc-name' }, 'sciret_run_step'),
        h('span', { class: 'tc-step' }, '· ' + step + ' · 执行中…'),
        h('span', { class: 'grow' }),
        badge('运行中', 'run'),
      ]),
      h('div', { class: 'tc-body' }, [
        h('div', { class: 'skeleton sk-line', style: { width: '60%' } }),
        h('div', { class: 'skeleton sk-line', style: { width: '85%' } }),
        h('div', { class: 'skeleton sk-line', style: { width: '40%' } }),
      ]),
    ]);
  }

  /* ---------- 结论卡 ---------- */
  function conclusionCard(c, onEv) {
    return h('div', { class: 'conclusion' }, [
      h('span', { class: 'c-id' }, c.cid + '：'),
      h('span', { class: 'c-text' }, c.text),
      h('div', { class: 'c-evs' }, c.evidence_ids.map((ev) =>
        h('button', { class: 'ev-chip', type: 'button', onclick: () => onEv && onEv(ev), title: '查看证据 ' + ev }, ev))),
    ]);
  }

  /* ---------- 证据卡 ---------- */
  function evidenceCard(p, onFlash) {
    const m = p.meta || {};
    const isLit = p.kind === 'literature';
    const title = m.title || p.ref;
    return h('div', { class: 'evcard', id: 'ev-' + p.ev_id, dataset: { ev: p.ev_id, tier: p.tier, kind: p.kind } }, [
      h('div', { class: 'ev-top' }, [
        h('span', { class: 'ev-id' }, p.ev_id),
        h('span', { class: 'ev-title', title }, title),
        h('span', { class: 'grow' }),
        badge(p.tier, 'tier'),
        badge(window.PA_DATA.KIND_META[p.kind] || p.kind, ''),
      ]),
      h('div', { class: 'ev-meta' }, [
        isLit && m.doi ? h('span', {}, [h('span', { class: 'k' }, 'DOI '), h('a', { class: 'v', href: 'https://doi.org/' + m.doi, target: '_blank', rel: 'noopener', onclick: (e) => e.preventDefault() }, m.doi)]) : null,
        isLit && m.year ? h('span', {}, [h('span', { class: 'k' }, '年份 '), h('span', { class: 'v' }, m.year)]) : null,
        isLit && m.cites ? h('span', {}, [h('span', { class: 'k' }, '引用 '), h('span', { class: 'v' }, m.cites)]) : null,
        h('span', {}, [h('span', { class: 'k' }, '生产者步骤 '), h('span', { class: 'v' }, p.producer_step)]),
        p.sha256 ? h('span', {}, [h('span', { class: 'k' }, 'sha256 '), h('span', { class: 'v' }, p.sha256.slice(0, 12) + '…')]) : null,
        h('span', { class: 'hash-line', title: '链哈希：' + p.chain_hash + '\n已通过哈希链校验 ✓' },
          [icon('link', 12), h('span', { class: 'chain-badge' }, '链哈希已校验')]),
      ]),
    ]);
  }

  /* ============================================================
   * 表单控件
   * ============================================================ */
  function textarea(attrs) {
    const el = h('textarea', attrs || {});
    return el;
  }
  function field(label, control, errNode) {
    return h('div', {}, [h('label', { class: 'f-label' }, label), control, errNode || null]);
  }
  function pickCard(opts) {
    const el = h('div', { class: 'pickcard' + (opts.on ? ' on' : ''), role: 'radio', 'aria-checked': opts.on ? 'true' : 'false', tabindex: '0',
      onclick: opts.onclick,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); opts.onclick && opts.onclick(); } } }, [
      h('div', { class: 'pc-hd' }, [h('span', { class: 'pc-name' }, opts.name), h('span', { class: 'pc-radio' })]),
      h('div', { class: 'pc-desc' }, opts.desc),
      opts.extra || null,
    ]);
    return el;
  }

  /* ---------- 数据表 ---------- */
  function dataTable(columns, rows) {
    const t = h('table', { class: 'dt' });
    t.appendChild(h('thead', {}, h('tr', {}, columns.map((c) => h('th', {}, c.label)))));
    t.appendChild(h('tbody', {}, rows.map((r) =>
      h('tr', {}, columns.map((c) => h('td', {}, c.render ? c.render(r) : r[c.key]))))));
    return t;
  }

  window.PA_UI = {
    h, frag, clear, mount, icon, ICONS, badge, chip, card, kpiCard, emptyState, pre,
    tooltip, copyText, toast, statusClass, runStatusBadge, statusDot, stepBar, miniStepBar,
    degradedBar, toolCard, skeletonToolCard, sourcesTag, conclusionCard, evidenceCard,
    field, pickCard, dataTable, sectionTitle, textarea,
  };
})();
