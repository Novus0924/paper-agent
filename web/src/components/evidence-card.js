/**
 * components/evidence-card.js —— 证据页组件
 * ------------------------------------------------------------
 * 数据源：§4.4 GET /api/runs/{id}/evidence
 *   provenance[] → ev_id / kind / tier / ref / sha256 / chain_hash / producer_step / meta
 *   conclusions[] → cid / text / evidence_ids[]
 *   factcheck.citations → consistency_rate / n / results[]
 *   review.final → overall / n_blocking / scores{} / blocking_issues[]
 *
 * 字段要点（实测校正）：
 *   - `tier` 才是 fact / artifact；`kind` 是 literature / data / analysis
 *   - 前端徽章显示 tier（fact/artifact），kind 作为中文标注补充
 */

import { h, icon, ICONS, shortHash, bytes, copy, toast, relTime } from '../lib/dom.js';
import { KIND_META, TIER_META, STEP_LABELS } from '../api/constants.js';

/* ---------- Verdict 四格 ---------- */
/** 固定四源（core/paper_agent 的检索源集合） */
const ALL_SOURCES = ['arxiv', 'crossref', 'openalex', 'semantic_scholar'];
const SRC_LABEL = { arxiv: 'arXiv', crossref: 'CrossRef', openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar' };

export function VerdictCards({ evidence }) {
  const { provenance = [], conclusions = [], factcheck = {}, review = {}, toolcalls = [] } = evidence;

  const rate = factcheck?.citations?.consistency_rate;
  const ratePct = rate === null || rate === undefined ? null : `${Math.round(rate * 100)}%`;
  const nCite = factcheck?.citations?.n ?? conclusions.length;
  const nFact = provenance.filter((p) => p.tier === 'fact').length;
  const nArt = provenance.filter((p) => p.tier === 'artifact').length;

  /* 来源可用性：以 toolcalls 里的 sources_status 为真源（四源固定集合）。
     若没有 toolcalls 则退回按 provenance.meta.sources 统计实际出现过的源。 */
  const srcStatus = {};
  for (const tc of toolcalls || []) {
    for (const [k, v] of Object.entries(tc.sources_status || {})) srcStatus[k] = v;
  }
  let nSrcTotal, nSrcOk, okList = [], badList = [];
  if (Object.keys(srcStatus).length) {
    nSrcTotal = ALL_SOURCES.length;
    for (const s of ALL_SOURCES) {
      const st = srcStatus[s];
      if (st === undefined) continue;
      String(st).startsWith('ok') ? okList.push(s) : badList.push(s);
    }
    // sources_status 里出现过四源之外的源也计入总数
    for (const s of Object.keys(srcStatus)) {
      if (!ALL_SOURCES.includes(s)) { nSrcTotal++; String(srcStatus[s]).startsWith('ok') ? okList.push(s) : badList.push(s); }
    }
  } else {
    const seen = new Set();
    for (const p of provenance) for (const s of (p.meta?.sources || [])) seen.add(s);
    nSrcTotal = Math.max(seen.size, 1);
    nSrcOk = evidence.state?.degraded ? nSrcTotal - 1 : nSrcTotal;
  }
  const degraded = badList.length > 0 || evidence.state?.degraded === true;
  const shownOk = okList.length || nSrcOk || 0;
  const shownTotal = nSrcTotal;

  const vc = (k, v, sub, cls = '', title = '') => h('div.vc', { title: title || undefined },
    h('div.vk', { text: k }),
    h(`div.vv${cls ? '.' + cls : ''}`, { text: v }),
    h('div.vn', { text: sub }),
  );

  const srcTitle = [
    ...okList.map((s) => `${SRC_LABEL[s] || s} 可用`),
    ...badList.map((s) => `${SRC_LABEL[s] || s} 不可用（${srcStatus[s]}）`),
  ].join('\n');

  return h('div.verdicts', null,
    vc('引用一致性', ratePct ?? '—',
      ratePct === null ? '无核验数据' : `${nCite} 处引用全部通过`,
      rate === 1 ? 'g' : rate === null ? '' : 'w'),
    vc('自审评分', review?.final?.overall ?? '—',
      review?.converged === false ? `${review.final.n_blocking} 项待修` : '已收敛',
      review?.converged === false ? 'w' : review?.converged ? 'g' : ''),
    vc('证据条目', String(provenance.length || 0),
      `fact ${nFact} / artifact ${nArt}`),
    vc('来源可用', `${shownOk}/${shownTotal}`,
      degraded ? '已自动降级切源' : '全部可用',
      degraded ? 'w' : 'g', srcTitle),
  );
}

/* ---------- 复现校验 / 自审明细 ---------- */
export function ReviewPanel({ evidence }) {
  const review = evidence.review || {};
  const fin = review.final || {};
  const scores = fin.scores || {};
  const issues = fin.blocking_issues || [];
  const actions = fin.actions || [];
  if (!Object.keys(scores).length && !issues.length) return null;

  return h('div.rvpanel', null,
    h('div.lbl', { text: '自审明细' }),
    h('div.rvgrid', null,
      h('div.rvcard', null,
        h('div.rvk', { text: '维度得分' }),
        h('div.kvs', null, ...Object.entries(scores).map(([k, v]) =>
          h('div.kvrow', null,
            h('span.k', { text: k }),
            h('span.vv2', { text: Number(v).toFixed(2), class: v >= 9 ? 'g' : v >= 7 ? '' : 'w' }),
          ))),
      ),
      h('div.rvcard', null,
        h('div.rvk', { text: `阻断项 · ${issues.length}` }),
        issues.length
          ? h('div.iss', null, ...issues.map((b) =>
              h('div.issrow', null,
                h('span.dot.warn'),
                h('span.it', { text: b.detail || b.tag }),
              )))
          : h('div.rvnone', { text: '无阻断项' }),
        actions.length ? h('div.rvacc', null,
          h('div.rvak', { text: '建议动作' }),
          ...actions.map((a) => h('div.issrow', null, h('span.dot.idle'), h('span.it', { text: a }))),
        ) : null,
      ),
    ),
  );
}

/* ---------- EV 卡片 ---------- */
export function EvidenceCard(p, highlight) {
  const tier = TIER_META[p.tier] || { label: p.tier || '?' };
  const kind = KIND_META[p.kind] || { label: p.kind || '—' };
  const m = p.meta || {};
  const isHi = highlight && highlight === p.ev_id;

  const meta = h('div.emeta');
  const add = (k, v, title) => { if (v !== '' && v !== null && v !== undefined) meta.appendChild(h('span.mi', { title: title || v }, h('b', { text: k + ' ' }), String(v))); };

  add('DOI', p.ref?.startsWith('10.') ? p.ref : (m.doc_id || p.ref));
  add('年份', m.year);
  add('来源', (m.sources || []).join('/'));
  if (p.sha256) add('sha256', shortHash(p.sha256, 8, 8), p.sha256);
  add('链哈希', shortHash(p.chain_hash, 8, 8), p.chain_hash);
  if (m.bytes) add('大小', bytes(m.bytes));
  if (m.pages) add('页数', `${m.pages} 页`);
  add('解析', m.parser_version ? `全文 ${m.parser_version}` : (p.sha256 ? '全文成功' : ''));

  return h(`div.evcard${isHi ? '.hi' : ''}`, { 'data-ev': p.ev_id, id: `ev-${p.ev_id}` },
    h('div.evtop', null,
      h('span.eid', { text: p.ev_id }),
      h('span.tier', { class: p.tier === 'artifact' ? 'art' : 'fact', text: tier.label }),
      h('span.kbadge', { text: kind.label }),
      h('span.producer', { text: STEP_LABELS[p.producer_step] ? `${p.producer_step}` : (p.producer_step || '—'),
        title: p.producer_step || '' }),
      h('button.evcopy', {
        title: '复制 ev_id', 'aria-label': `复制 ${p.ev_id}`,
        onclick: async (e) => {
          e.stopPropagation();
          const ok = await copy(p.ev_id);
          toast(ok ? `已复制 ${p.ev_id}` : '复制失败', ok ? 'ok' : 'err');
        },
      }, icon(ICONS.copy, 11)),
    ),
    h('div.etitle2', { text: m.title || p.ref || '(无标题)' }),
    meta.childElementCount ? meta : null,
  );
}

/* ---------- 结论↔证据 绑定视图 ---------- */
export function ConclusionBindings({ conclusions, provenance, toolcalls }) {
  if (!conclusions?.length) return null;
  const byId = new Map(provenance.map((p) => [p.ev_id, p]));

  // conclusions.jsonl 的 text 里含各源状态（形如 {'arxiv': 'ok:10', ...}），
  // 直接铺在正文里可读性差。这里额外抽出来渲染成标签，正文保持原样不篡改。
  const srcOf = (c) => {
    const t = c.text || '';
    if (!/ok:\d+/.test(t)) return null;
    for (const tc of toolcalls || []) {
      if (Object.keys(tc.sources_status || {}).length) return tc.sources_status;
    }
    return null;
  };

  return h('div', null,
    h('div.lbl', { text: `结论 ↔ 证据绑定（${conclusions.length} 条）` }),
    ...conclusions.map((c) => {
      const ss = srcOf(c);
      return h('div.cbind', null,
        h('div.cbid', { text: c.cid }),
        h('div.cbtext', { text: c.text }),
        ss ? h('div.srcrow', { style: { marginTop: '0', marginBottom: 'var(--s3)' } },
          ...Object.entries(ss).map(([k, v]) => {
            const ok = String(v).startsWith('ok');
            return h('span.src', {
              class: ok ? 'ok' : 'no',
              text: `${SRC_LABEL[k] || k} · ${ok ? `ok ${String(v).split(':')[1]}` : '不可用'}`,
              title: String(v),
            });
          }),
        ) : null,
        h('div.cbevs', null, ...(c.evidence_ids || []).map((id) => {
          const p = byId.get(id);
          return h('a.cbev', {
            href: `#ev-${id}`,
            text: id,
            title: p ? (p.meta?.title || p.ref) : '该证据未在 provenance 中找到',
            style: p ? null : { opacity: .5 },
          });
        })),
      );
    }),
  );
}