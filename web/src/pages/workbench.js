/**
 * pages/workbench.js —— 界面一·主工作台
 * ------------------------------------------------------------
 * 对应后端接口：
 *   GET  /api/runs/{id}          初始快照（附加）
 *   GET  /api/runs/{id}/events   SSE 实时事件（§4.3）
 *   POST /api/runs/{id}/step     推进单步（§4.2）
 *   POST /api/runs/{id}/run-all  全流程（§4.2）
 *
 * SSE 事件 → UI 映射：
 *   step        → 步骤条状态 + 当前步骤高亮
 *   tool        → 追加工具调用卡（折叠）
 *   degraded    → 顶部橙色降级提示条（特色，非错误）
 *   conclusion  → 追加结论卡
 *   done        → 步骤条收尾、按钮状态复位、任务列表刷新
 */

import { h, icon, ICONS, toast } from '../lib/dom.js';
import { StepBar } from '../components/steps.js';
import { ToolCard, ToolCardPending } from '../components/tool-card.js';
import { ConclusionCard } from '../components/conclusion-card.js';
import { Rail } from '../components/rail.js';
import { TaskList } from '../components/task-list.js';
import { buildSystemPrompt, WORKFLOWS, STEP_LABELS } from '../api/constants.js';
import * as api from '../api/client.js';

export function WorkbenchPage(ctx) {
  const { runId, runs, onGo, onPickRun, onReloadRuns } = ctx;

  /* ---------- 状态 ---------- */
  let state = null;
  let toolcalls = [];
  let conclusions = [];
  let degraded = [];              // [{source, reason, step}]
  let es = null;
  let curToolSeq = 0;
  // M3：系统提示词。source = 'server' 表示后端存档的真实下发内容；
  // 'local-fallback' 表示后端没有存档（老 run），本地模板重算，会在UI 上标注。
  let prompt = { text: null, source: null, meta: null };

  /* ---------- DOM ---------- */
  const tasksSlot = h('div', null);
  const titleEl = h('div.mtitle', { text: '加载中…' });
  const tagsEl = h('div.mtags');
  const stream = h('div.stream');
  const stepSlot = h('div', null);
  const degradedSlot = h('div');
  const toolsSlot = h('div');
  const conclSlot = h('div');
  const goalSlot = h('div');
  const promptSlot = h('div');

  const btnStep = h('button.ghost', { onclick: onStep });
  const btnAll = h('button.ghost', { onclick: onAll });
  const btnEv = h('button.ghost', {
    onclick: () => onGo('evidence', runId),
    title: '查看证据溯源',
  }, '查看证据');

  /* 追问输入区
     ⚠️ 对接方案 §4 未定义「追问」接口（§3.2 里 AGH 只做解读/追问增强，
     依赖 M4 的 ACP 通道）。所以这里做成显式禁用 + 说明，
     避免给用户一个"能发但发不出去"的假输入框。
     后端补上 POST /api/runs/{id}/message 后，把下面 disabled 去掉即可。 */
  const userInput = h('div.cbox', {
    contenteditable: 'false',
    'data-ph': '追问通道待接入（对接方案 M4：ACP 增强通道）',
    role: 'textbox',
    'aria-multiline': 'true',
    'aria-disabled': 'true',
    title: '后端尚未提供追问接口，接入后开放',
  });

  function setHead() {
    if (!state) return;
    titleEl.textContent = state.goal || '(无目标)';
    tagsEl.replaceChildren();
    tagsEl.appendChild(h('span.tag.a', { text: state.workflow }));
    tagsEl.appendChild(h('span.tag', { text: state.run_id }));

    const order = state.steps_order || Object.keys(state.steps || {});
    const done = order.filter((s) => state.steps[s] === 'DONE').length;
    if (done) tagsEl.appendChild(h('span.tag', { text: `${done}/${order.length} 步` }));

    // 来源可用性：四源固定集合，以 toolcalls 的 sources_status 为准
    const ALL_SRC = ['arxiv', 'crossref', 'openalex', 'semantic_scholar'];
    const srcStatus = {};
    for (const t of toolcalls) {
      for (const [k, v] of Object.entries(t.sources_status || {})) srcStatus[k] = v;
    }
    const nSrcTotal = Object.keys(srcStatus).length ? ALL_SRC.length : 0;
    if (nSrcTotal) {
      const bad = ALL_SRC.filter((s) => srcStatus[s] !== undefined && !String(srcStatus[s]).startsWith('ok')).length
        + degraded.filter((d) => !ALL_SRC.includes(d.source)).length;
      tagsEl.appendChild(h('span.tag', {
        class: bad ? 'warn' : '',
        text: bad ? `${Math.max(nSrcTotal - bad, 0)} 源可用 / ${bad} 降级` : `${nSrcTotal} 源全可用`,
        title: Object.entries(srcStatus).map(([k, v]) => `${k}: ${v}`).join('\n'),
      }));
    } else if (state.degraded) {
      tagsEl.appendChild(h('span.tag.warn', { text: '已降级运行' }));
    }
    if (conclusions.length) {
      tagsEl.appendChild(h('span.tag', { text: `${conclusions.length} 条结论` }));
    }
  }

  function renderStepBar() {
    stepSlot.replaceChildren(state ? StepBar({ state }) : h('div.skel', { style: { height: '62px' } }));
  }

  function renderDegraded() {
    if (!degraded.length) { degradedSlot.replaceChildren(); return; }
    const uniq = [...new Map(degraded.map((d) => [d.source, d])).values()];
    degradedSlot.replaceChildren(h('div.dgbar', null,
      h('span.dot.warn'),
      h('span.dgt', null,
        h('b', { text: '已自动降级：' }),
        uniq.map((d, i) => h('span', null,
          (i ? '、' : '') + d.source,
          h('span.dgr', { text: `（${d.reason}）` }),
        )),
      ),
      h('span.dgn', { text: '任务未中断，其余来源已覆盖检索完备性' }),
    ));
  }

  function renderTools() {
    toolsSlot.replaceChildren();
    if (!toolcalls.length) {
      toolsSlot.appendChild(h('div.empty', null,
        h('div.et', { text: '尚未执行任何步骤' }),
        h('div.ed', { text: '点右上「执行下一步」或「跑完整个流程」，每一步的工具调用与来源状态都会记录在这里。' }),
      ));
      return;
    }
    toolcalls.forEach((tc, i) => {
      toolsSlot.appendChild(ToolCard(tc, i === 0));
    });
  }

  function renderConclusions() {
    conclSlot.replaceChildren();
    if (!conclusions.length) return;
    const lbl = h('div.lbl', { text: '结论' });
    conclSlot.appendChild(lbl);
    for (const c of conclusions) {
      conclSlot.appendChild(ConclusionCard(c, (id) => onGo('evidence', runId, id)));
    }
  }

  function renderGoalAndPrompt() {
    goalSlot.replaceChildren(h('div.msg.usermsg', null,
      h('div.mhead2', { text: '你' }),
      h('div.mbody', { text: state?.goal || '' }),
    ));
    if (!state?.workflow) { promptSlot.replaceChildren(); return; }

    // M3：后端有存档就显示后端那份（用户看到的 = 后端实际用的）；
    // 没有才回退本地模板，并且明确标注是本地重算，不假装是后端下发的。
    if (prompt.source === 'local-fallback') {
      // 带上 lit_source，否则本地重算的那份会比后端少一行【检索来源】
      prompt.text = buildSystemPrompt(state.goal, state.workflow, state.lit_source);
    }
    if (!prompt.text) { promptSlot.replaceChildren(); return; }

    const isServer = prompt.source === 'server';
    const badge = isServer
      ? h('span.pvbadge.ok', {
        text: '后端已存档',
        title: `下发方式：${prompt.meta?.delivery || '未知'}\n存档时间：${prompt.meta?.archived_at || '—'}`,
      })
      : h('span.pvbadge.warn', {
        text: '本地重算',
        title: prompt.meta?.reason || '后端未返回提示词存档，此处由前端模板按 state 重新生成',
      });

    promptSlot.replaceChildren(h('details.pv', { open: true },
      h('summary.pvh', null,
        h('span', { text: '已施加的系统约束' }),
        badge,
        h('span.pvhint', { text: '（点击展开/收起）' }),
      ),
      h('pre.pvb', { text: prompt.text }),
      isServer ? null : h('div.pvnote', {
        text: '注意：此 run 创建于提示词存档功能之前，这段是前端按模板重算的，可能与后端实际约束不完全一致。',
      }),
    ));
  }

  function renderActions() {
    const order = state?.steps_order || [];
    const cur = order.find((s) => state?.steps?.[s] === 'RUNNING');
    const next = order.find((s) => state?.steps?.[s] === 'PENDING');
    const running = !!cur;
    const finished = order.length > 0 && !cur && !next;

    btnStep.textContent = running ? `执行中 · ${STEP_LABELS[cur] || cur}` : (next ? `下一步：${STEP_LABELS[next] || next}` : '无可执行步骤');
    btnStep.disabled = running || !next;

    btnAll.replaceChildren(icon(ICONS.play, 12), document.createTextNode(finished ? '已全部完成' : '跑完整个流程'));
    btnAll.disabled = running || !next;
    btnAll.title = running
      ? `正在执行「${STEP_LABELS[cur] || cur}」，结束后可继续`
      : finished ? '所有步骤均已完成' : '从当前步骤一路跑到最后一步';

    if (cur) {
      // 当前步骤正在跑 → 追加一张骨架工具卡
      if (!toolsSlot.querySelector('.skeltool')) {
        toolsSlot.appendChild(ToolCardPending(null));
        toolsSlot.lastElementChild.classList.add('skeltool');
      }
    } else {
      toolsSlot.querySelector('.skeltool')?.remove();
    }
  }

  /* ---------- SSE ---------- */
  function connect() {
    es?.close();
    es = api.subscribeEvents(runId, {
      onEvent: ({ type, data }) => {
        switch (type) {
          case 'step': {
            if (!state) return;
            state.steps[data.step] = data.status;
            if (data.status === 'RUNNING') state.run_status = 'RUNNING';
            if (data.elapsed_ms) {
              const tc = toolcalls.find((t) => t.step === data.step);
              if (tc) tc.elapsed_ms = data.elapsed_ms;
            }
            renderStepBar(); renderActions(); setHead();
            break;
          }
          case 'tool': {
            curToolSeq++;
            const idx = toolcalls.findIndex((t) => t.step === data.step);
            if (idx >= 0) toolcalls[idx] = data; else toolcalls.push({ ...data, step_index: curToolSeq });
            toolsSlot.querySelector('.skeltool')?.remove();
            renderTools(); setHead(); renderActions();
            break;
          }
          case 'degraded': {
            degraded.push(data);
            state && (state.degraded = true);
            renderDegraded(); setHead();
            break;
          }
          case 'conclusion': {
            if (!conclusions.some((c) => c.cid === data.cid)) conclusions.push(data);
            renderConclusions(); setHead();
            break;
          }
          case 'done': {
            state && (state.run_status = data.run_status || 'DONE');
            renderStepBar(); renderActions(); setHead();
            onReloadRuns?.();
            toast('流水线执行完成', 'ok');
            break;
          }
          case 'message': {
            // AGH 通道的逐块文本（方案 §1.2）→ 增量拼接，按 turnId 覆盖去重
            appendAgentChunk(data);
            break;
          }
        }
      },
      onError: (e) => {
        stream.prepend(h('div.errbar', null,
          h('span.dot.fail'),
          h('span', null, h('b', { text: '事件流断开：' }), e.message,
            '。状态可能已变化，', h('a.hlink', { href: '#', onclick: (ev) => { ev.preventDefault(); ctx.onReload(); } }, '点击刷新'), '。'),
        ));
      },
    });
  }

  /* AGH 逐块文本：同一 turnId 后到者覆盖，避免重复渲染（方案 §1.2 实测坑） */
  const chunks = new Map();
  function appendAgentChunk(data) {
    const turn = data.turnId || data.turn_id || 'default';
    chunks.set(turn, (chunks.get(turn) || '') + (data.text || ''));
    const full = chunks.get(turn);
    let node = stream.querySelector(`.agentblk[data-turn="${CSS.escape(turn)}"]`);
    if (!node) {
      node = h('div.agentblk', { 'data-turn': turn },
        h('div.mhead2', { text: '助手' }),
        h('div.mbody'),
      );
      stream.appendChild(node);
    }
    node.querySelector('.mbody').textContent = full;
    stream.scrollTop = stream.scrollHeight;
  }

  /* ---------- 动作 ---------- */
  async function onStep() {
    const order = state?.steps_order || [];
    const next = order.find((s) => state.steps[s] === 'PENDING');
    if (!next) return;
    try {
      btnStep.disabled = true;
      const r = await api.runStep(runId, next);
      if (r?.state) { state = r.state; renderStepBar(); setHead(); renderActions(); }
    } catch (e) {
      toast(`推进失败：${e.message}`, 'err');
      btnStep.disabled = false;
    }
  }

  async function onAll() {
    try {
      btnAll.disabled = true; btnStep.disabled = true;
      const r = await api.runAll(runId);
      if (r?.state) { state = r.state; renderStepBar(); setHead(); renderActions(); }
    } catch (e) {
      toast(`启动失败：${e.message}`, 'err');
      btnAll.disabled = false; btnStep.disabled = false;
    }
  }

  /* ---------- 装配 ---------- */
  const page = h('section.view.on', null,
    Rail('workbench', (k) => onGo(k, runId)),
    h('div.body', null,
      tasksSlot,
      h('main.main', null,
        h('div.mhead', null,
          h('div', null, titleEl, tagsEl),
          h('div.hactions', null, btnEv, btnStep, btnAll),
        ),
        stream,
        h('div.comp', null,
          h('div.compin.off', null,
            userInput,
            h('div.cbar', null,
              h('div.chips', null,
                h('span.chip-hint', { text: '追问 / 追加指令的接口尚未接入（对接方案 §4 未定义，依赖 M4 的 ACP 通道）；推进流水线请用右上角按钮。' }),
              ),
              h('button.send', { disabled: true, title: '待接入', 'aria-label': '发送（待接入）' }, icon(ICONS.arrowRight, 15)),
            ),
          ),
        ),
      ),
    ),
  );

  // 用户消息 + 提示词 + 步骤条 + 降级条 + 执行过程 + 结论
  stream.append(
    h('div', null, goalSlot),
    h('div', null, promptSlot),
    h('div', null, stepSlot),
    h('div', null, degradedSlot),
    h('div.blk', null, h('div.lbl', { text: '执行过程' }), toolsSlot),
    h('div.blk', null, conclSlot),
  );

  function paintTaskList() {
    tasksSlot.replaceChildren(TaskList({ runs, current: runId, onPick: onPickRun, onNew: () => onGo('new') }));
  }
  paintTaskList();

  renderTools();
  renderActions();

  // 初始加载
  (async () => {
    try {
      const snap = await api.getRun(runId);
      state = snap.state || snap;
      toolcalls = snap.toolcalls || [];
      conclusions = snap.conclusions || [];
      // M3：优先用后端存档的提示词；没有则标记 local-fallback 由renderGoalAndPrompt 重算
      prompt = snap.system_prompt
        ? { text: snap.system_prompt, source: 'server', meta: snap.prompt_meta || null }
        : { text: null, source: 'local-fallback', meta: snap.prompt_meta || null };
      if (Array.isArray(snap.events)) snap.events.forEach(() => {});
      // 从已有工具卡推断降级源
      toolcalls.forEach((t) => {
        for (const [s, v] of Object.entries(t.sources_status || {})) {
          if (!String(v).startsWith('ok')) degraded.push({ source: s, reason: String(v), step: t.step });
        }
      });
      curToolSeq = toolcalls.length;
      renderGoalAndPrompt();
      renderStepBar();
      renderDegraded();
      renderTools();
      renderConclusions();
      renderActions();
      setHead();
      connect();
    } catch (e) {
      stream.replaceChildren(h('div.errbar', null,
        h('span.dot.fail'),
        h('span', null, h('b', { text: '无法加载该 run：' }), e.message),
      ));
    }
  })();

  page._refresh = () => { paintTaskList(); };
  page._updateRuns = (list) => { ctx.runs = list; paintTaskList(); };
  return page;
}