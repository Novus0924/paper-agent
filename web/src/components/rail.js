/**
 * components/rail.js —— 左侧 60px 图标导航栏
 */

import { h, icon, ICONS } from '../lib/dom.js';

/**
 * @param {string} active  当前页 key: 'workbench' | 'evidence' | 'new'
 * @param {(k:string)=>void} onGo
 */
export function Rail(active, onGo) {
  const items = [
    { k: 'workbench', title: '工作台', d: ICONS.home },
    { k: 'evidence', title: '证据', d: ICONS.shield },
  ];

  const rail = h('aside.rail', null,
    h('div.mark', { text: 'PA', title: 'paper-agent' }),
    h('nav', null,
      ...items.map((it) => h('button.rbtn', {
        class: active === it.k ? 'on' : '',
        title: it.title,
        'aria-label': it.title,
        'aria-current': active === it.k ? 'page' : null,
        onclick: () => onGo(it.k),
      }, icon(it.d, 17))),
      h('span.raildiv'),
      h('button.rbtn', {
        class: active === 'new' ? 'on' : '',
        title: '新任务',
        'aria-label': '新任务',
        'aria-current': active === 'new' ? 'page' : null,
        onclick: () => onGo('new'),
      }, icon(ICONS.plus, 17)),
    ),
  );
  return rail;
}