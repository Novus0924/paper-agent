/**
 * mock/data.js —— Mock 数据源
 * ------------------------------------------------------------
 * 字段名 100% 取自真实 run 产物，不是编的：
 *   state.json         → run_id / workflow / lit_source / goal / degraded
 *                        run_status(PLANNED|RUNNING|DONE|FAILED)
 *                        steps{step_id: PENDING|RUNNING|DONE|FAILED|SKIPPED}
 *                        steps_order[] / attempts{} / created_at / updated_at
 *   provenance.jsonl   → ev_id / kind(literature|data|analysis) / tier(fact|artifact)
 *                        ref(DOI) / sha256 / chain_hash / producer_step
 *                        meta{title, year, sources[]}
 *   conclusions.jsonl  → cid / text / evidence_ids[]
 *   factcheck.json     → citations{consistency_rate, n, results[]}
 *   review/review.json → converged / final{overall, n_blocking, scores{}, blocking_issues[]}
 *   toolcalls/*.json   → 各步骤的工具调用记录（含 sources_status 四源状态）
 *
 * 步骤 id 与顺序对齐 core/paper_agent/state.py:
 *   materials: P1_lit_search P2_clean_data P3_run_experiment P4_verify P5_report
 *   research : R1_search R2_read R3_analyze R4_verify R5_write R6_review
 */

import { WORKFLOWS, STEP_LABELS } from './constants.js';

/** 生成 run_id，格式与真实一致：run-YYYYMMDD-HHMMSS-xxxxxx */
export function genRunId(date = new Date()) {
  const p = (n, w = 2) => String(n).padStart(w, '0');
  const ymd = `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}`;
  const hms = `${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
  const hex = Array.from({ length: 6 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('');
  return `run-${ymd}-${hms}-${hex}`;
}

const iso = (d) => d.toISOString().replace(/\.\d+Z$/, 'Z');

/** 假文献池 */
const LIT = [
  { title: 'A Survey of Hallucination in Large Language Models', doi: '10.12677/airr.2026.151016', year: 2026, src: 'crossref' },
  { title: 'Retrieval-Augmented Generation for Hallucination Mitigation', doi: '10.12677/ml.2026.146511', year: 2026, src: 'crossref' },
  { title: 'Chain-of-Verification Reduces Hallucination in LLMs', doi: '10.48550/arXiv.2309.11495', year: 2023, src: 'arxiv' },
  { title: 'Self-RAG: Learning to Retrieve, Generate, and Critique', doi: '10.48550/arXiv.2310.11511', year: 2023, src: 'arxiv' },
  { title: 'Knowledge Editing for Factuality in Language Models', doi: '10.12677/ai.2026.204311', year: 2026, src: 'openalex' },
  { title: 'Contrastive Decoding for Open-Ended Generation', doi: '10.48550/arXiv.2210.15097', year: 2022, src: 'arxiv' },
  { title: 'Attribution Weight Estimation for Hallucination Detection', doi: '10.12677/tp.2026.188204', year: 2026, src: 'openalex' },
  { title: 'Toolformer: Language Models Can Teach Themselves to Use Tools', doi: '10.48550/arXiv.2302.04761', year: 2023, src: 'arxiv' },
  { title: 'Faithful Summarization via Fact-Level Entailment', doi: '10.12677/nlp.2026.199877', year: 2026, src: 'crossref' },
  { title: 'Detecting and Mitigating Hallucination in Retrieval Pipelines', doi: '10.48550/arXiv.2402.15012', year: 2024, src: 'openalex' },
];

const hash = (seed, len = 64) => {
  // 确定性伪随机（同一 seed 每次结果一致，避免刷新后哈希跳变）
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  let out = '';
  for (let i = 0; i < len; i += 8) {
    h = Math.imul(h ^ (h >>> 13), 0x5bd1e995) >>> 0;
    out += h.toString(16).padStart(8, '0');
  }
  return out.slice(0, len);
};

/** 造 provenance（N 条） */
function makeProvenance(n = 10) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const l = LIT[i % LIT.length];
    if (i % 4 === 3) {
      // artifact：本地解析出的 PDF
      const sha = hash(`pdf${i}`);
      out.push({
        ev_id: `EV-${String(i + 1).padStart(4, '0')}`,
        kind: 'data',
        tier: 'artifact',
        ref: `file://literature/paper_${i}.pdf`,
        sha256: sha,
        chain_hash: hash('chain' + i),
        producer_step: 'R2_read',
        meta: { title: `已下载并解析全文 PDF（${i} 册）`, bytes: 1_200_000 + i * 37_000, pages: 8 + i },
      });
    } else {
      out.push({
        ev_id: `EV-${String(i + 1).padStart(4, '0')}`,
        kind: 'literature',
        tier: 'fact',
        ref: l.doi,
        sha256: '',
        chain_hash: hash('chain' + i),
        producer_step: 'R1_search',
        meta: { title: l.title, year: l.year, sources: [l.src], doc_id: `${l.src[0].toUpperCase() + l.src.slice(1)}:${l.doi}` },
      });
    }
  }
  return out;
}

/** 造 conclusions */
function makeConclusions(prov) {
  const ids = prov.map((p) => p.ev_id);
  const litIds = prov.filter((p) => p.tier === 'fact').map((p) => p.ev_id);
  return [
    {
      cid: 'C1',
      text: '多源检索（来源=auto）命中 10 篇；各源状态：arxiv=ok:10、crossref=ok:10、openalex=ok:10、semantic_scholar=unavailable:HTTPError。不可用源已自动切换，任务未中断，检索完备性由三源交叉覆盖保证。',
      evidence_ids: ids.slice(0, 10),
    },
    {
      cid: 'C2',
      text: '幻觉缓解的主流路线可归为三类：解码侧约束、检索增强、事后校验。其中检索增强在本批样本中占比最高（6/10 篇直接涉及 RAG）。',
      evidence_ids: litIds.slice(0, 3),
    },
    {
      cid: 'C3',
      text: '事实验证阶段对 3 条含数字的陈述做了引用一致性核验，一致率 1.00，说明结论均可回溯到已登记证据。',
      evidence_ids: litIds.slice(3, 6),
    },
  ];
}

/** 造 toolcalls（每步一条，含 sources_status） */
function makeToolcalls(workflow, degraded) {
  const steps = WORKFLOWS[workflow];
  const srcStatus = degraded
    ? { arxiv: 'ok:10', crossref: 'ok:10', openalex: 'ok:10', semantic_scholar: 'unavailable:HTTPError' }
    : { arxiv: 'ok:10', crossref: 'ok:10', openalex: 'ok:10', semantic_scholar: 'ok:10' };

  // ⚠️ 工具名必须与 plugins/paper-agent-tools/index.mjs 真实注册的 7 个一致，
  //    以及 toolcalls/*.json 的真源（权威值 sciret_run_step）。此前这里是
  //    sciret_search_papers / sciret_parse_paper 等**幻觉名**（P0-1 缺陷），已纠正。
  const nameOf = {
    R1_search: ['sciret_run_step', { step: 'R1_search', source: 'auto', n_hits: 10 }, srcStatus],
    R2_read: ['sciret_run_step', { step: 'R2_read', n_files: 3, n_sections: 42 }, null],
    R3_analyze: ['sciret_run_step', { step: 'R3_analyze', n_gaps: 2, n_timeline_nodes: 7 }, null],
    R4_verify: ['sciret_run_step', { step: 'R4_verify', n_cited: 3, consistency: 1.0 }, null],
    R5_write: ['sciret_run_step', { step: 'R5_write', n_words: 3120, n_citations: 10 }, null],
    R6_review: ['sciret_run_step', { step: 'R6_review', score: 7.56, converged: false }, null],
    P1_lit_search: ['sciret_run_step', { step: 'P1_lit_search', source: 'auto', n_hits: 10 }, srcStatus],
    P2_clean_data: ['sciret_run_step', { step: 'P2_clean_data', n_rows_in: 1840, n_rows_out: 1791 }, null],
    P3_run_experiment: ['sciret_run_step', { step: 'P3_run_experiment', n_exp: 4, n_failed: 0 }, null],
    P4_verify: ['sciret_verify', { step: 'P4_verify', n_checked: 1791 }, null],
    P5_report: ['sciret_report', { step: 'P5_report', n_figs: 5, n_tables: 3 }, null],
  };

  return steps.map((sid, i) => {
    const [tool, input, sources] = nameOf[sid] || ['sciret_run_step', { step: sid }, null];
    return {
      step: sid,
      tool,
      step_index: i + 1,
      elapsed_ms: 800 + Math.floor(hash(sid).slice(0, 4).charCodeAt(0) * 47) % 5200,
      status: 'completed',
      input: { ...input, goal: input.goal || '' },
      sources_status: sources,
    };
  });
}

/** 造一个完整 run 对象 */
export function makeRun({ goal, workflow = 'research', lit_source = 'auto', degraded = true, run_status = 'DONE', steps_done = null } = {}) {
  const run_id = genRunId();
  const steps = WORKFLOWS[workflow];
  const now = new Date();
  const created = new Date(now.getTime() - 1000 * 60 * 27);

  // steps_done=null → 全部完成；否则前 n 步 DONE，第 n+1 步 RUNNING
  let stepMap;
  if (steps_done === null) {
    stepMap = Object.fromEntries(steps.map((s) => [s, 'DONE']));
  } else {
    stepMap = Object.fromEntries(steps.map((s, i) => [
      s, i < steps_done ? 'DONE' : i === steps_done ? 'RUNNING' : 'PENDING',
    ]));
  }

  const state = {
    run_id,
    goal,
    workflow,
    lit_source,
    degraded,
    run_status,
    steps: stepMap,
    steps_order: steps,
    attempts: Object.fromEntries(steps.map((s) => [s, 1])),
    created_at: iso(created),
    updated_at: iso(now),
  };

  const provenance = makeProvenance(10);
  const conclusions = makeConclusions(provenance);

  return {
    state,
    provenance,
    conclusions,
    toolcalls: makeToolcalls(workflow, degraded),
    factcheck: {
      citations: {
        consistency_rate: 1.0,
        n: 3,
        results: [
          { claim: '检索命中 10 篇（多源交叉）', consistency: 1.0, evidence: { claim_numbers: ['10'], source_excerpt: 'multi-source hit 10' } },
          { claim: 'RAG 路线占比最高，6/10 篇', consistency: 1.0, evidence: { claim_numbers: ['6', '10'], source_excerpt: '6 of 10 papers involve RAG' } },
          { claim: '一致性核验覆盖 3 条含数字陈述', consistency: 1.0, evidence: { claim_numbers: ['3'], source_excerpt: 'n_cited=3' } },
        ],
      },
    },
    review: {
      converged: false,
      final: {
        overall: 7.56,
        n_blocking: 1,
        iteration: 1,
        scores: { 技术正确性: 10.0, 写作清晰度: 9.41, 相关工作覆盖度: 9.4, 实验充分性: 7.0, 贡献度: 2.0 },
        blocking_issues: [
          { tag: 'no_citation_ratio', severity: 'blocking', detail: '1 处陈述标注 [需补充引用]，必须补证或删除' },
        ],
        actions: ['为 [需补充引用] 的陈述补上真实引用，无法补证则删除该句'],
        detailed_comments: [],
        signals: {},
      },
    },
  };
}

/** 预置任务列表（含各种状态，用于左侧栏） */
export function seedRuns() {
  const research = makeRun({
    goal: '大语言模型幻觉缓解方法：检索并处理相关论文',
    workflow: 'research', degraded: true, run_status: 'RUNNING', steps_done: 5,
  });
  // 强制第 6 步 RUNNING（自审进行中）
  const rs = research.state.steps_order;
  research.state.steps[rs[5]] = 'RUNNING';

  const mat = makeRun({
    goal: '固态电解质界面阻抗的机理与表征方法',
    workflow: 'materials', lit_source: 'crossref', degraded: true,
  });
  const arxivLit = makeRun({
    goal: '锂金属负极枝晶生长的抑制策略综述',
    workflow: 'research', lit_source: 'arxiv', degraded: false,
  });
  const failed = makeRun({
    goal: '钠离子电池储能系统的经济性评估',
    workflow: 'research', degraded: false, run_status: 'FAILED',
  });
  failed.state.steps[failed.state.steps_order[1]] = 'FAILED';

  const old = makeRun({
    goal: '钙钛矿太阳能电池的稳定性衰减机理',
    workflow: 'research', degraded: false,
  });
  // 归档态：改时间戳让它看起来久远
  const d = new Date(Date.now() - 1000 * 60 * 60 * 24 * 23);
  old.state.created_at = iso(d);
  old.state.updated_at = iso(d);

  const list = [research, mat, arxivLit, failed, old];

  // 让第一个 run 的 R4 步骤就是上一轮核验过的真实数据
  list.forEach((r) => { r.__t = Date.now(); });
  old.__t = d.getTime();
  arxivLit.__t = Date.now() - 1000 * 60 * 60 * 2;
  return list;
}

export { STEP_LABELS };