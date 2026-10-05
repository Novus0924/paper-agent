/**
 * components/tool-card.js —— 工具调用卡（可折叠）
 * ------------------------------------------------------------
 * 数据源：§4.3 SSE event: tool
 *   { step, tool, step_index, elapsed_ms, status, input, sources_status }
 * sources_status 形如 {"arxiv":"ok:10","semantic_scholar":"unavailable:HTTPError"}
 * → ok 前缀渲染为绿色「ok 10」，否则红色「不可用」。
 *
 * 注意：degraded 是特色不是错误，单独用橙色 degraded 事件在页面上汇总（见 degraded-bar.js）。
 */

import { h, dur, esc } from '../lib/dom.js';

function renderSources(status) {
  const row = h('div.srcrow');
  for (const [name, st] of Object.entries(status || {})) {
    const s = String(st);
    const ok = s.startsWith('ok');
    const n = ok ? s.split(':')[1] : null;
    row.appendChild(h(`span.src.${ok ? 'ok' : 'no'}`, {
      text: `${name} · ${ok ? `ok ${n}` : '不可用'}`,
      title: s,
    }));
  }
  return row;
}

function renderKV(input) {
  const kv = h('div.kv');
  for (const [k, v] of Object.entries(input || {})) {
    if (v === '' || v === null || v === undefined) continue;
    kv.appendChild(h('span.k', { text: k }));
    kv.appendChild(h('span.v', { text: typeof v === 'object' ? JSON.stringify(v) : String(v) }));
  }
  return kv;
}

/**
 * @param {object} tc   tool call
 * @param {boolean} open 默认展开
 */
export function ToolCard(tc, open = false) {
  const idx = String(tc.step_index ?? tc.index ?? 1).padStart(2, '0');
  const failed = tc.status === 'failed';
  const warn = tc.warn === true;

  const card = h(`div.tool${open ? '.open' : ''}`, { 'data-tool': tc.tool || '' },
    h('div.thead', {
      role: 'button',
      tabindex: '0',
      'aria-expanded': open ? 'true' : 'false',
      onclick: (e) => {
        const c = e.currentTarget.parentNode;
        c.classList.toggle('open');
        e.currentTarget.setAttribute('aria-expanded', c.classList.contains('open') ? 'true' : 'false');
      },
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const c = e.currentTarget.parentNode;
          c.classList.toggle('open');
          e.currentTarget.setAttribute('aria-expanded', c.classList.contains('open') ? 'true' : 'false');
        }
      },
    },
      h('div.ticon', { text: idx }),
      h('div.tname2', { text: tc.tool || '(未知工具)' }),
      h('div.tstat', failed ? { style: { color: 'var(--fail)' } } : warn ? { style: { color: 'var(--warn)' } } : null,
        h(`span.dot.${failed ? 'fail' : warn ? 'warn' : 'ok'}`),
        h('span', { text: failed ? '失败' : warn ? (tc.note || '1 项待修') : `完成 · ${dur(tc.elapsed_ms)}` }),
      ),
      h('div.chev', null, (() => {
        const NS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('width', '12'); svg.setAttribute('height', '12');
        svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '1.6');
        svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', 'M9 18l6-6-6-6');
        svg.appendChild(p);
        return svg;
      })()),
    ),
    h('div.tbody', null,
      renderKV(tc.input),
      tc.sources_status ? renderSources(tc.sources_status) : null,
      tc.note && !tc.sources_status ? h('div.srcrow', null, h('span.src.no', { text: tc.note })) : null,
    ),
  );
  return card;
}

/** 步骤正在执行时的骨架卡 */
export function ToolCardPending(toolName) {
  return h('div.tool', null,
    h('div.thead', { style: { cursor: 'default' } },
      h('div.ticon', { text: '··' }),
      h('div.tname2', { text: toolName || '执行中' }),
      h('div.tstat', null, h('span.dot.run'), h('span', { text: '运行中' })),
    ),
  );
}