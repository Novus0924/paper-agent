/**
 * components/conclusion-card.js —— 结论卡
 * ------------------------------------------------------------
 * 数据源：§4.3 SSE event: conclusion  { cid, text, evidence_ids[] }
 * 文件源：conclusions.jsonl（字段完全一致）
 */

import { h } from '../lib/dom.js';

export function ConclusionCard(c, onEvClick) {
  const evs = h('div.evs');
  const ids = c.evidence_ids || [];
  const show = ids.slice(0, 6);
  for (const id of show) {
    evs.appendChild(h('button.ev', {
      text: id,
      title: `查看证据 ${id}`,
      style: { cursor: 'pointer' },
      onclick: () => onEvClick?.(id),
    }));
  }
  if (ids.length > show.length) {
    evs.appendChild(h('span.ev', { text: `+${ids.length - show.length}` }));
  }

  return h('div.concl', { 'data-cid': c.cid },
    h('div.cid', { text: c.cid }),
    h('div.ctext', { text: c.text || '' }),
    ids.length ? evs : null,
  );
}