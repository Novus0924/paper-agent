/**
 * components/task-list.js —— 左侧任务列表
 * ------------------------------------------------------------
 * 数据源：GET /api/runs（附加接口，方案 §4 未列但任务栏必需）
 * 状态点语义（对齐 state.py 的 RunStatus + degraded）：
 *   RUNNING → run   DONE → ok   FAILED → fail   degraded → warn   PLANNED → wait
 */

import { h, icon, ICONS, relTime } from '../lib/dom.js';
import { STEP_LABELS } from '../api/constants.js';

/** 计算一个 run 的展示状态 */
export function runStatusOf(state) {
  const steps = state.steps_order || Object.keys(state.steps || {});
  const doneCount = steps.filter((s) => state.steps?.[s] === 'DONE').length;
  const failed = steps.some((s) => state.steps?.[s] === 'FAILED');

  if (state.run_status === 'FAILED' || failed) {
    return { dot: 'fail', text: `失败 · ${steps.find((s) => state.steps?.[s] === 'FAILED') || ''}`.replace(/ · $/, '') };
  }
  if (state.run_status === 'RUNNING') {
    const cur = steps.find((s) => state.steps?.[s] === 'RUNNING');
    return { dot: 'run', text: cur ? `运行中 · ${STEP_LABELS[cur] || cur}` : '运行中' };
  }
  if (state.run_status === 'PLANNED') return { dot: 'wait', text: '已规划' };
  if (state.degraded) return { dot: 'warn', text: `已降级 · ${doneCount} 步完成` };
  return { dot: 'ok', text: `已完成 · ${relTime(state.updated_at)}` };
}

/**
 * @param {object[]} runs    run state 数组
 * @param {string}   current 当前 run_id
 * @param {(id:string)=>void} onPick
 * @param {()=>void} onNew
 */
export function TaskList({ runs, current, onPick, onNew }) {
  const list = h('div.tlist');

  if (!runs.length) {
    list.appendChild(h('div.empty', { style: { padding: 'var(--s7) var(--s3)' } },
      h('div.et', { text: '还没有研究任务' }),
      h('div.ed', { text: '点右上 + 新建一个，系统会按 research 或 materials 流水线跑。' }),
    ));
  }

  for (const st of runs) {
    const s = runStatusOf(st);
    const item = h('div.ti', {
      class: st.run_id === current ? 'on' : '',
      role: 'button',
      tabindex: '0',
      'data-run': st.run_id,
      onclick: () => onPick(st.run_id),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(st.run_id); } },
    },
      h('div.tgoal', { text: st.goal || '(无目标)' }),
      h('div.tmeta', null,
        h(`span.dot.${s.dot}`),
        h('span', { text: s.text }),
      ),
    );
    list.appendChild(item);
  }

  return h('aside.tasks', null,
    h('div.th', null,
      h('span.tname', { text: '研究任务' }),
      h('button.tnew', { title: '新建任务', 'aria-label': '新建任务', onclick: onNew },
        icon(ICONS.plus, 13)),
    ),
    list,
  );
}