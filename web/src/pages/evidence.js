/**
 * pages/evidence.js —— 界面二·证据溯源
 * ------------------------------------------------------------
 * 对应后端接口：GET /api/runs/{id}/evidence（§4.4）
 *   { provenance[], conclusions[], factcheck{}, review{}, state{}, toolcalls[] }
 *
 * 布局严格对齐设计稿（v2-frame2）：
 *   顶栏（标题 / run_id / 哈希链 / 返回工作台）
 *   → verdict 四格
 *   → 结论↔证据绑定
 *   → 自审明细
 *   → 证据条目（EV 卡片流）
 */

import { h, icon, ICONS, toast, appendAll } from '../lib/dom.js';
import { Rail } from '../components/rail.js';
import { VerdictCards, EvidenceCard, ReviewPanel, ConclusionBindings } from '../components/evidence-card.js';
import { runStatusOf } from '../components/task-list.js';
import * as api from '../api/client.js';

export function EvidencePage(ctx) {
  const { runId, runs, onGo, onPickRun } = ctx;
  let ev = null;

  const body = h('div.evwrap');
  const titleEl = h('div.mtitle', { text: '加载中…' });
  const tagsEl = h('div.mtags');

  const page = h('section.view.on', null,
    Rail('evidence', (k) => onGo(k, runId)),
    h('div.body', null,
      h('main.main', null,
        h('div.mhead', null,
          h('div', null, titleEl, tagsEl),
          h('div.hactions', null,
            h('button.ghost', { onclick: () => onGo('workbench', runId) },
              icon(ICONS.back, 12), document.createTextNode('返回工作台')),
          ),
        ),
        body,
      ),
    ),
  );

  function setHead(state) {
    if (!state) return;
    titleEl.textContent = state.goal || '(无目标)';
    tagsEl.replaceChildren(
      h('span.tag.a', { text: state.run_id }),
      h('span.tag', { text: state.workflow }),
    );
    const st = runStatusOf(state);
    tagsEl.appendChild(h('span.tag', {
      class: st.dot === 'fail' ? 'fail' : st.dot === 'warn' ? 'warn' : st.dot === 'ok' ? 'ok' : '',
      text: st.text,
    }));
    // 哈希链完整性
    const chainOk = (ev?.provenance || []).every((p) => !!p.chain_hash);
    tagsEl.appendChild(h('span.tag', {
      class: chainOk ? 'ok' : 'warn',
      text: chainOk ? '哈希链完整' : '哈希链不完整',
    }));
  }

  function renderFilter(prov) {
    const bar = h('div.evfilter');
    const counts = {
      all: prov.length,
      fact: prov.filter((p) => p.tier === 'fact').length,
      artifact: prov.filter((p) => p.tier === 'artifact').length,
    };
    let cur = 'all';
    const listSlot = h('div');

    const btns = [
      ['all', `全部 ${counts.all}`],
      ['fact', `fact ${counts.fact}`],
      ['artifact', `artifact ${counts.artifact}`],
    ].map(([k, label]) => {
      const b = h('button.chip', { class: k === 'all' ? 'on' : '', text: label, dataset: { k } });
      b.addEventListener('click', () => {
        cur = k;
        btns.forEach((x) => x.classList.toggle('on', x.dataset.k === k));
        draw();
      });
      return b;
    });

    const input = h('input.evsearch', {
      type: 'search', placeholder: '按标题 / DOI / ev_id 过滤…', 'aria-label': '过滤证据',
    });
    let kw = '';
    input.addEventListener('input', () => { kw = input.value.trim().toLowerCase(); draw(); });

    function draw() {
      let list = prov;
      if (cur !== 'all') list = list.filter((p) => p.tier === cur);
      if (kw) {
        list = list.filter((p) => {
          const hay = `${p.ev_id} ${p.ref || ''} ${p.meta?.title || ''} ${p.kind || ''} ${p.producer_step || ''}`.toLowerCase();
          return hay.includes(kw);
        });
      }
      listSlot.replaceChildren();
      if (!list.length) {
        listSlot.appendChild(h('div.empty', null,
          h('div.et', { text: '没有匹配的证据' }),
          h('div.ed', { text: '换个筛选条件或清空搜索词。' }),
        ));
        return;
      }
      for (const p of list) listSlot.appendChild(EvidenceCard(p, ctx.highlightEv));
    }

    // appendAll 会展开数组；原生 append 传数组会 toString 成 [object HTMLButtonElement]
    appendAll(bar, btns, h('span.evfsp'), input);
    draw();
    return h('div', null, bar, listSlot);
  }

  (async () => {
    try {
      ev = await api.getEvidence(runId);
      // 「来源可用」的实际值，由 VerdictCards 用 sources_status 算出
      const srcTotal = 4;
      const badSrc = [...new Set((ev.toolcalls || []).flatMap((t) =>
        Object.entries(t.sources_status || {})
          .filter(([, v]) => !String(v).startsWith('ok')).map(([k]) => k)))];
      const okN = srcTotal - badSrc.length;

      body.replaceChildren(h('div.evinner', null,
        VerdictCards({ evidence: ev }),
        h('div.degraded-note', null,
          h('span.dot', { class: badSrc.length ? 'warn' : 'ok' }),
          h('span', null, badSrc.length
            ? `「来源可用」为 ${okN}/${srcTotal}，表示多源检索中 ${badSrc.join('、')} 不可用、已自动降级切源；这是设计特性，不是运行失败。降级记录会写入 runs/<run_id>/events.jsonl。`
            : `四个检索源全部可用（${srcTotal}/${srcTotal}）。若某源不可用，此处会显示降级后的比例并提示已自动切源——降级是设计特性，不是运行失败。`),
        ),
        ConclusionBindings({
          conclusions: ev.conclusions,
          provenance: ev.provenance,
          toolcalls: ev.toolcalls,
        }),
        ReviewPanel({ evidence: ev }),
        h('div', { style: { marginTop: 'var(--s6)' } },
          h('div.lbl', { text: '证据条目' }),
          renderFilter(ev.provenance || []),
        ),
      ));
      setHead(ev.state);
      // 高亮从工作态跳转过来的 ev_id
      if (ctx.highlightEv) {
        const el = document.getElementById(`ev-${ctx.highlightEv}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('flash');
          setTimeout(() => el.classList.remove('flash'), 2200);
        }
      }
    } catch (e) {
      body.replaceChildren(h('div.evinner', null,
        h('div.errbar', { style: { margin: '0' } },
          h('span.dot.fail'),
          h('span', null, h('b', { text: '无法加载证据：' }), e.message),
        )));
    }
  })();

  return page;
}