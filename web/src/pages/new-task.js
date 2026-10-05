/**
 * pages/new-task.js —— 界面三·新建任务
 * ------------------------------------------------------------
 * 对应后端接口：POST /api/runs（§4.1）
 *   { goal, workflow, lit_source } → 201 { run_id, state }
 *
 * 提交后跳转工作台并订阅 SSE（POST 返回即建好 run，事件由 §4.3 推送）。
 */

import { h, icon, ICONS, toast } from '../lib/dom.js';
import { Rail } from '../components/rail.js';
import { WORKFLOW_META, LIT_SOURCES, WORKFLOWS, STEP_LABELS, buildSystemPrompt } from '../api/constants.js';
import * as api from '../api/client.js';

export function NewTaskPage(ctx) {
  const { onGo, onCreated } = ctx;

  let workflow = 'research';
  let litSource = 'auto';
  let sources = new Set(['auto']);

  /* ---- 目标输入 ---- */
  const ta = h('textarea', {
    placeholder: '用一句话描述你想研究的问题，例如：检索并综述固态电解质界面阻抗的表征方法',
    rows: 5, 'aria-label': '研究目标',
  });

  /* ---- 工作流卡 ---- */
  const optEls = [];
  const opts = h('div.opts');
  for (const [key, meta] of Object.entries(WORKFLOW_META)) {
    const card = h('div.opt', {
      class: key === workflow ? 'on' : '',
      role: 'radio', tabindex: '0',
      'aria-checked': key === workflow ? 'true' : 'false',
      onclick: () => pickWorkflow(key),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickWorkflow(key); } },
    },
      h('div.oname', { text: meta.label }),
      h('div.odesc', { text: meta.desc }),
      h('div.osteps', null, ...meta.steps.map((s) =>
        h('span.ostep', { text: s.split('_')[0], title: `${s} · ${STEP_LABELS[s] || ''}` }))),
    );
    optEls.push({ key, el: card });
    opts.appendChild(card);
  }

  function pickWorkflow(k) {
    workflow = k;
    for (const o of optEls) {
      const on = o.key === k;
      o.el.classList.toggle('on', on);
      o.el.setAttribute('aria-checked', on ? 'true' : 'false');
    }
    renderPreview();
    renderPromptPreview();   // 工作流变了，提示词里的【工作流】行也要跟着变
  }

  /* ---- 检索来源 ---- */
  const chipEls = [];
  const srcline = h('div.srcline', { role: 'group', 'aria-label': '检索来源' });
  for (const s of LIT_SOURCES) {
    const b = h('button.chip', {
      class: [s.id === 'auto' ? 'on' : '', s.effective === false ? 'off' : ''].filter(Boolean).join(' '),
      text: s.id === 'auto' ? 'auto · 自动降级' : s.label,
      title: s.desc || s.label,
      dataset: { id: s.id },
      onclick: () => { if (s.effective === false) { toast(`${s.label}：${s.desc}`, ''); return; } toggleSource(s.id); },
    });
    chipEls.push(b);
    srcline.appendChild(b);
  }

  function toggleSource(id) {
    if (id === 'auto') {
      // auto 是互斥的「自动降级」：选中它则清空其它
      sources = new Set(['auto']);
    } else {
      sources.delete('auto');
      if (sources.has(id)) sources.delete(id); else sources.add(id);
      if (!sources.size) sources = new Set(['auto']);
    }
    // 回传后端的是单个 lit_source：多选时取 auto（后端 auto 即并行四源+降级）
    litSource = sources.size === 1 ? [...sources][0] : 'auto';
    for (const b of chipEls) {
      b.classList.toggle('on', sources.has(b.dataset.id));
    }
    renderPreview();
    renderPromptPreview();
  }

  /* ---- 会发生什么 ---- */
  const whats = h('div.whats');
  function renderPreview() {
    const steps = WORKFLOWS[workflow];
    const picked = [...sources];
    const srcText = picked.includes('auto')
      ? 'auto（先试 arXiv，失败自动降级）'
      : picked.length === 1
        ? (LIT_SOURCES.find((s) => s.id === picked[0])?.label || picked[0])
        : `${picked.map((id) => LIT_SOURCES.find((s) => s.id === id)?.label || id).join(' / ')}（多选，按 auto 执行）`;
    whats.replaceChildren(
      h('div.wstep', null, h('div.wn', { text: '1' }), h('div.wt', null,
        h('b', { text: '多源检索' }), '　', `${srcText}，检索记录全程落盘`)),
      h('div.wstep', null, h('div.wn', { text: '2' }), h('div.wt', null,
        h('b', { text: '逐步执行' }), '　', `本次共 ${steps.length} 步：${steps.map((s) => STEP_LABELS[s] || s).join(' → ')}`)),
      h('div.wstep', null, h('div.wn', { text: '3' }), h('div.wt', null,
        h('b', { text: '证据绑定' }), '　', '每条结论强制关联 DOI 与哈希链，无证据不给结论')),
      h('div.wstep', null, h('div.wn', { text: '4' }), h('div.wt', null,
        h('b', { text: '自审收敛' }), '　', '核验引用一致性，未通过则标记待修并扣分')),
    );
  }
  renderPreview();

  /* ---- 系统约束预览（M3 / 方案 §5.2）
     §5.2 明确要求：「前端必须把这段提示词显示给用户 —— 用户有权知道
     『我输入的话被加了什么』」。所以这里在提交前就实时预览，随目标/工作流/来源变化。
     ⚠️ 这份预览用前端模板按当前选择即时渲染；真正下发的那份由后端生成并存档，
     提交后工作台显示的是**后端返回的存档内容**，两者模板逐字一致。 */
  const pvSlot = h('div.pv.newpv');
  function renderPromptPreview() {
    const g = ta.value.trim();
    pvSlot.replaceChildren(
      h('summary.pvh', null,
        h('span', { text: '将要施加的系统约束' }),
        h('span.pvhint', { text: g ? '（点击展开/收起）' : '（填写目标后显示）' }),
      ),
      h('pre.pvb', {
        text: g
          ? buildSystemPrompt(g, workflow, litSource)
          : '（在上面的「研究目标」里输入后，这里会显示完整提示词）',
      }),
      h('div.pvnote.neutral', {
        text: '提示词用于向流水线施加检索与证据约束，并在运行中明示给你；它不会被塞进检索查询串里污染检索结果。',
      }),
    );
  }
  ta.addEventListener('input', renderPromptPreview);
  renderPromptPreview();
  const errSlot = h('div');
  const submit = h('button.solid', { onclick: onSubmit },
    document.createTextNode('开始研究'), icon(ICONS.arrowRight, 14));

  async function onSubmit() {
    const goal = ta.value.trim();
    errSlot.replaceChildren();
    if (!goal) {
      errSlot.appendChild(h('div.errbar', { style: { margin: 'var(--s4) 0 0' } },
        h('span.dot.fail'),
        h('span', null, h('b', { text: '请先填写研究目标。' }), '目标会作为参数直接传给流水线。'),
      ));
      ta.focus();
      return;
    }
    submit.disabled = true;
    submit.replaceChildren(document.createTextNode('创建中…'));
    try {
      const r = await api.createRun({ goal, workflow, lit_source: litSource });
      toast(`已创建 ${r.run_id}`, 'ok');
      // 不手动传 system_prompt：工作台会重新 GET，后端存档的那份才是准的
      onCreated(r.run_id, r.state);
    } catch (e) {
      submit.disabled = false;
      submit.replaceChildren(document.createTextNode('开始研究'), icon(ICONS.arrowRight, 14));
      errSlot.appendChild(h('div.errbar', { style: { margin: 'var(--s4) 0 0' } },
        h('span.dot.fail'),
        h('span', null, h('b', { text: '创建失败：' }), e.message),
      ));
    }
  }

  // Ctrl/Cmd + Enter 提交
  ta.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); onSubmit(); }
  });

  const page = h('section.view.on', null,
    Rail('new', (k) => onGo(k, ctx.runId)),
    h('div.body', null,
      h('main.main', null,
        h('div.mhead', null,
          h('div', null,
            h('div.mtitle', { text: '新建任务' }),
            h('div.mtags', null,
              h('span.tag', { text: '提交后按流水线逐步执行，每步状态与证据均可回溯' }),
            ),
          ),
        ),
        h('div.nt', null,
          h('div.ntinner', null,
            h('div.ntlabel', null, '研究目标'),
            ta,
            h('div.ntlabel', { style: { marginTop: 'var(--s5)' } }, '工作流'),
            opts,
            h('div.ntlabel', { style: { marginTop: 'var(--s5)' } },
              '检索来源',
              h('span.nthint', { text: '多选时按 auto 处理' }),
            ),
            srcline,
            h('div.ntlabel', { style: { marginTop: 'var(--s5)' } },
              '系统约束',
              h('span.nthint', { text: '提交前可见，不影响检索词' }),
            ),
            pvSlot,
            errSlot,
            h('div.ntact', null, submit),
            whats,
          ),
        ),
      ),
    ),
  );

  setTimeout(() => ta.focus(), 60);
  return page;
}