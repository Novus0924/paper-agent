/**
 * lib/dom.js —— 极简 DOM 工具（无框架）
 * ------------------------------------------------------------
 * 为什么不引框架：与项目「零第三方依赖」红线一致；
 * 前端体量不大，模板函数 + 事件委托足够，且联调时少一层构建。
 */

/** h('div.cls#id', {attrs}, ...children) */
export function h(spec, props = null, ...children) {
  const [tagPart, ...rest] = String(spec).split(/(?=[.#])/);
  const el = document.createElement(tagPart || 'div');
  for (const r of rest) {
    if (r[0] === '.') el.classList.add(r.slice(1));
    else if (r[0] === '#') el.id = r.slice(1);
  }
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className += (el.className ? ' ' : '') + v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') {
        el.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(4)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/**
 * appendAll —— 安全追加，自动展开数组/假值。
 * ⚠️ 原生 el.append(数组) 会把数组 toString 成 "[object HTMLButtonElement]"，
 *    本项目踩过一次这个坑（证据页筛选 chip 全变字符串），
 *    所以凡是可能传数组的地方一律用这个函数，不要用原生 append。
 */
export function appendAll(el, ...items) {
  append(el, items);
  return el;
}

/** SVG 图标（stroke 风格，与设计稿一致） */
export function icon(paths, size = 16) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.5');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  for (const d of [].concat(paths)) {
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  }
  return svg;
}

export const ICONS = {
  home: 'M3 9l9-6 9 6v10a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  shield: ['M9 12l2 2 4-4', 'M12 3l8 4v5c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V7z'],
  plus: 'M12 5v14M5 12h14',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  chevron: 'M9 18l6-6-6-6',
  play: 'M7 4l12 8-12 8z',
  stop: 'M6 6h12v12H6z',
  refresh: ['M20 11a8 8 0 10-2.3 6', 'M20 4v7h-7'],
  back: 'M19 12H5M11 18l-6-6 6-6',
  doc: ['M14 3v5h5', 'M19 8v11a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5z'],
  copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
  external: ['M14 4h6v6', 'M20 4l-9 9', 'M18 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h5'],
  alert: ['M12 8v5', 'M12 16h.01', 'M12 3l9 16H3z'],
};

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** 转义为 HTML 文本节点内容（防注入） */
export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** 相对时间 */
export function relTime(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return new Date(t).toLocaleDateString('zh-CN');
}

/** 时长格式化 */
export function dur(ms) {
  if (ms === null || ms === undefined) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** 字节数 */
export function bytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/** 截断哈希：2adcef8c…b8561d25c */
export function shortHash(s, head = 8, tail = 8) {
  if (!s) return '—';
  if (s.length <= head + tail + 1) return s;
  return `${s.slice(0, head)}…${s.slice(-tail)}`;
}

/** 复制到剪贴板 */
export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }
}

/** Toast */
export function toast(msg, kind = '') {
  let host = document.getElementById('toast-host');
  if (!host) {
    host = h('div#toast-host');
    document.body.appendChild(host);
  }
  const t = h(`div.toast${kind ? '.' + kind : ''}`, { text: msg });
  host.appendChild(t);
  setTimeout(() => {
    t.style.transition = 'opacity .2s, transform .2s';
    t.style.opacity = '0';
    t.style.transform = 'translateY(6px)';
    setTimeout(() => t.remove(), 220);
  }, 2200);
}

/** 事件委托 */
export function delegate(root, sel, type, fn) {
  root.addEventListener(type, (e) => {
    const el = e.target.closest(sel);
    if (el && root.contains(el)) fn(e, el);
  });
}