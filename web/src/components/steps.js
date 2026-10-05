/**
 * components/steps.js —— 步骤条
 * ------------------------------------------------------------
 * 数据源：state.steps_order[] + state.steps{}
 * 状态映射（state.py: StepStatus）：
 *   DONE → done（绿）  RUNNING → act（琥珀高亮）  FAILED → 失败  PENDING/SKIPPED → 灰
 */

import { h } from '../lib/dom.js';
import { STEP_LABELS } from '../api/constants.js';

const CLS = { DONE: 'done', RUNNING: 'act', FAILED: 'fail', PENDING: '', SKIPPED: 'skip' };

export function StepBar({ state }) {
  const order = state.steps_order || Object.keys(state.steps || {});
  const bar = h('div.steps', { role: 'list', 'aria-label': '流水线步骤' });

  for (const sid of order) {
    const st = state.steps?.[sid] || 'PENDING';
    const cls = CLS[st] ?? '';
    const short = sid.split('_')[0];                 // R1 / P1
    const label = STEP_LABELS[sid] || sid;
    bar.appendChild(h(`div.st${cls ? '.' + cls : ''}`, {
      role: 'listitem',
      title: `${sid} · ${st}`,
      'data-step': sid,
    },
      h('div.stk', { text: short }),
      h('div.stn', { text: label }),
    ));
  }
  return bar;
}