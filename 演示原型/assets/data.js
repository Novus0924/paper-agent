/* ============================================================
 * data.js —— 全部假数据（结构严格取自真实 runs/ 产物字段）
 * 零依赖、无网络、无环境变量；挂在 window.PA_DATA 全局。
 * 字段陷阱遵守：
 *   - tier ∈ {fact, artifact}；artifact 常为 0（正常）
 *   - kind ∈ {literature,data,note,analysis,factcheck,draft,review,experiment}
 *   - toolcalls[].tool 权威值 = sciret_run_step（禁止 sciret_search_papers 幻觉名）
 * ============================================================ */
(function () {
  'use strict';

  /* ---------- 确定性伪哈希（64 位 hex，形状对齐真实 chain_hash / sha256） ---------- */
  function fnv(str) {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }
  function hash64(seed) {
    let out = '';
    let s = String(seed);
    for (let i = 0; i < 8; i++) {
      out += fnv(s + ':' + i).toString(16).padStart(8, '0');
    }
    return out.slice(0, 64);
  }

  /* ---------- 领域常量：已抽至 constants.js（唯一真源，Batch 3 · B3-1） ---------- */
  // 本文件只保留 mock 数据；常量统一从 window.PA_CONST 取，避免双份真源漂移。
  const C = window.PA_CONST;

  /* ---------- 真实文献（DOI 可核对） ---------- */
  const LITERATURE = [
    { ev: 'EV-0001', title: 'A lithium superionic conductor', authors: 'Kamaya, N. et al.', year: 2011, doi: '10.1038/nmat3066', venue: 'Nature Materials', source: 'crossref', cites: 2841 },
    { ev: 'EV-0002', title: 'High-power all-solid-state batteries using sulfide superionic conductors', authors: 'Kato, Y. et al.', year: 2016, doi: '10.1038/nenergy.2016.30', venue: 'Nature Energy', source: 'crossref', cites: 2310 },
    { ev: 'EV-0003', title: 'Fast lithium ion conduction in garnet-type Li7La3Zr2O12', authors: 'Murugan, R. et al.', year: 2007, doi: '10.1002/anie.200701144', venue: 'Angew. Chem. Int. Ed.', source: 'crossref', cites: 3905 },
    { ev: 'EV-0004', title: 'Thin-film lithium and lithium-ion batteries', authors: 'Bates, J. B. et al.', year: 2000, doi: '10.1016/S0167-2738(00)00602-5', venue: 'Solid State Ionics', source: 'crossref', cites: 1420 },
    { ev: 'EV-0005', title: 'Li6PS5X: a class of crystalline Li-rich solids with an unusually high ionic mobility', authors: 'Deiseroth, H.-J. et al.', year: 2008, doi: '10.1002/anie.200703900', venue: 'Angew. Chem. Int. Ed.', source: 'crossref', cites: 1157 },
  ];

  /* ---------- provenance：21 条（全部 fact；artifact=0 属正常） ---------- */
  const PROV_EXTRA = [
    { ev: 'EV-0006', step: 'R1_search', kind: 'literature', title: 'Interfacial resistance in all-solid-state lithium batteries', doi: '10.1016/j.jpowsour.2018.06.058', year: 2018, cites: 642, venue: 'J. Power Sources' },
    { ev: 'EV-0007', step: 'R1_search', kind: 'literature', title: 'Solid-state battery interfaces: impedances and characterization', doi: '10.1039/C9EE02062G', year: 2019, cites: 508, venue: 'Energy Environ. Sci.' },
    { ev: 'EV-0008', step: 'R1_search', kind: 'literature', title: 'Chemo-mechanical expansion of sulfide electrolytes', doi: '10.1016/j.joule.2019.02.009', year: 2019, cites: 470, venue: 'Joule' },
    { ev: 'EV-0009', step: 'R1_search', kind: 'literature', title: 'Impedance spectroscopy of ion-conducting ceramics', doi: '10.1016/j.ssi.2020.115355', year: 2020, cites: 289, venue: 'Solid State Ionics' },
    { ev: 'EV-0010', step: 'R1_search', kind: 'literature', title: 'Machine learning for ionic conductivity screening', doi: '10.1038/s41524-020-00458-5', year: 2020, cites: 233, venue: 'npj Comput. Mater.' },
  ];
  const PROV_NOTES = [
    { ev: 'EV-0011', step: 'R2_read', kind: 'note', title: '精读笔记 · Kamaya2011 · LGPS 体相电导', ref: 'note:Kato2016:bulk' },
    { ev: 'EV-0012', step: 'R2_read', kind: 'note', title: '精读笔记 · Kato2016 · 界面阻抗测试方法', ref: 'note:Kato2016:iface' },
    { ev: 'EV-0013', step: 'R2_read', kind: 'note', title: '精读笔记 · Murugan2007 · LLZO 晶界贡献', ref: 'note:Murugan2007:gb' },
    { ev: 'EV-0014', step: 'R2_read', kind: 'note', title: '精读笔记 · Bates2000 · LiPON 薄膜堆叠', ref: 'note:Bates2000:film' },
  ];
  const PROV_ANALYSIS = [
    { ev: 'EV-0015', step: 'R3_analyze', kind: 'analysis', title: '分析方法对比矩阵（EIS / DRT / 三电极）', ref: 'analysis:method-matrix' },
    { ev: 'EV-0016', step: 'R3_analyze', kind: 'analysis', title: 'Research Gap · 界面阻抗长期稳定性数据缺失', ref: 'gap:iface-stability' },
    { ev: 'EV-0017', step: 'R3_analyze', kind: 'analysis', title: 'Research Gap · 跨温度域可比基准缺失', ref: 'gap:cross-temp' },
  ];
  const PROV_TAIL = [
    { ev: 'EV-0018', step: 'R4_verify', kind: 'factcheck', title: '事实核验报告（引用一致性 100%）', ref: 'factcheck:v1' },
    { ev: 'EV-0019', step: 'R5_write', kind: 'draft', title: '综述草稿 · 含引用标记正文', ref: 'draft:review-v1' },
    { ev: 'EV-0020', step: 'R5_write', kind: 'draft', title: '综述草稿 · 参考文献表', ref: 'draft:refs-v1' },
    { ev: 'EV-0021', step: 'R6_review', kind: 'review', title: '自审记录 · 综合 7.67 / 1 项阻断', ref: 'review:v1' },
  ];

  function makeProv(rows) {
    return rows.map((r, i) => {
      const isLit = r.kind === 'literature';
      return {
        ev_id: r.ev,
        tier: 'fact',
        kind: r.kind,
        ref: isLit ? r.doi : r.ref,
        sha256: isLit ? '' : hash64('sha:' + r.ev),
        chain_hash: hash64('chain:' + r.ev),
        producer_step: r.step,
        meta: isLit
          ? { title: r.title, doi: r.doi, year: r.year, venue: r.venue || '', cites: r.cites || 0, sources: ['crossref', 'arxiv'].slice(0, 1 + (i % 2)) }
          : { title: r.title, ref: r.ref },
      };
    });
  }

  const PROVENANCE = makeProv([
    { ev: 'EV-0001', step: 'R1_search', kind: 'literature', title: LITERATURE[0].title, doi: LITERATURE[0].doi, year: 2011, cites: LITERATURE[0].cites, venue: LITERATURE[0].venue },
    { ev: 'EV-0002', step: 'R1_search', kind: 'literature', title: LITERATURE[1].title, doi: LITERATURE[1].doi, year: 2016, cites: LITERATURE[1].cites, venue: LITERATURE[1].venue },
    { ev: 'EV-0003', step: 'R1_search', kind: 'literature', title: LITERATURE[2].title, doi: LITERATURE[2].doi, year: 2007, cites: LITERATURE[2].cites, venue: LITERATURE[2].venue },
    { ev: 'EV-0004', step: 'R1_search', kind: 'literature', title: LITERATURE[3].title, doi: LITERATURE[3].doi, year: 2000, cites: LITERATURE[3].cites, venue: LITERATURE[3].venue },
    { ev: 'EV-0005', step: 'R1_search', kind: 'literature', title: LITERATURE[4].title, doi: LITERATURE[4].doi, year: 2008, cites: LITERATURE[4].cites, venue: LITERATURE[4].venue },
  ].concat(PROV_EXTRA, PROV_NOTES, PROV_ANALYSIS, PROV_TAIL));

  const provByEv = {};
  PROVENANCE.forEach((p) => { provByEv[p.ev_id] = p; });

  /* ---------- conclusions：C1..C5（文案照真实产物） ---------- */
  const CONCLUSIONS = [
    { cid: 'C1', evidence_ids: ['EV-0001', 'EV-0002', 'EV-0003', 'EV-0004', 'EV-0005', 'EV-0006', 'EV-0007', 'EV-0008', 'EV-0009', 'EV-0010'],
      text: "多源检索（来源=auto）命中 10 篇；各源状态：{'arxiv': 'ok:10', 'crossref': 'ok:18', 'openalex': 'ok:0', 'semantic_scholar': 'unavailable:HTTPError'}；不可用源：['semantic_scholar']（已自动切换源，任务未中断）。" },
    { cid: 'C2', evidence_ids: ['EV-0012', 'EV-0013', 'EV-0014'],
      text: '论文精读 3 篇成功、0 篇失败（失败已跳过并标注，不阻塞流程）；扫描件/低置信度 0 篇。' },
    { cid: 'C3', evidence_ids: ['EV-0016', 'EV-0017'],
      text: '创新点拆解共识别 0 个创新点，识别 Research Gap 3 个。' },
    { cid: 'C4', evidence_ids: ['EV-0018'],
      text: '事实验证：引用/观点一致性率 100.00%，检出文献间潜在矛盾 0 处。' },
    { cid: 'C5', evidence_ids: ['EV-0019'],
      text: '综述草稿含引用标记；自评审综合分 7.67/10，结论 Reject/Accept? → 需大修（Major Revision）。' },
  ];

  /* ---------- factcheck ---------- */
  const FACTCHECK = {
    citations: {
      consistency_rate: 1.0,
      n: 3,
      tally: { '✅ 一致': 3 },
      results: [
        { source: 'arXiv:1909.10760', consistency: 0.972, verdict: '✅ 一致' },
        { source: 'arXiv:2206.01439', consistency: 0.976, verdict: '✅ 一致' },
        { source: 'arXiv:2305.07530', consistency: 0.977, verdict: '✅ 一致' },
      ],
    },
    contradictions: { n_contradictions: 0, n_claims_considered: 2 },
    data_consistency: [
      { doc_id: 'arXiv:1909.10760', n_checks: 4, n_pass: 4, status: 'PASS' },
      { doc_id: 'arXiv:2206.01439', n_checks: 4, n_pass: 4, status: 'PASS' },
      { doc_id: 'arXiv:2305.07530', n_checks: 4, n_pass: 4, status: 'PASS' },
    ],
  };

  /* ---------- review ---------- */
  const REVIEW = {
    converged: false,
    iterations: 1,
    final: {
      overall: 7.67,
      n_blocking: 1,
      verdict: 'Reject/Accept? → 需大修（Major Revision）',
      scores: { 写作清晰度: 9.47, 实验充分性: 7.5, 技术正确性: 10.0, 相关工作覆盖度: 9.4, 贡献度: 2.0 },
      blocking_issues: [{ tag: 'no_citation_ratio', severity: 'blocking', detail: '1 处陈述标注 [需补充引用]，必须补证或删除' }],
      strengths: ['相关工作覆盖较充分，纳入 10 篇，年份跨度 7 年', '引用可溯源，引用一致性率 100.0%'],
      weaknesses: ['[blocking] 1 处陈述标注 [需补充引用]，必须补证或删除'],
      actions: ['为 [需补充引用] 的陈述补上真实引用，无法补证则删除该句'],
      summary: '本文围绕草稿组织 19 条陈述，纳入文献 10 篇、创新点 0 个，综合评分 7.67/10。Reject/Accept? → 需大修（Major Revision）',
      signals: { cite_rate: 1.0, n_dangling: 0, n_docs: 10, n_innovations: 0, n_numeric: 9, n_statements: 19, unsupported: 1, year_span: 7 },
    },
  };

  /* ---------- 四源状态（R1 检索） ---------- */
  const SOURCES_STATUS = {
    arxiv: 'ok:10',
    crossref: 'ok:18',
    openalex: 'ok:0',
    semantic_scholar: 'unavailable:HTTPError',
  };
  const UNAVAILABLE = ['semantic_scholar'];

  /* ---------- toolcalls：R1..R6（tool 权威值 = sciret_run_step） ---------- */
  function makeToolcalls(runId) {
    const at = (m) => `2026-10-08T06:44:${String(m).padStart(2, '0')}Z`;
    return [
      { step: 'R1_search', tool: 'sciret_run_step', invoked_at: at(58),
        input: { run_id: runId, step: 'R1_search' },
        output: { n_hits: 10, sources_status: SOURCES_STATUS, unavailable: UNAVAILABLE } },
      { step: 'R2_read', tool: 'sciret_run_step', invoked_at: at(58),
        input: { run_id: runId, step: 'R2_read' },
        output: { n_read: 3, n_failed: 0, n_low_confidence: 0 } },
      { step: 'R3_analyze', tool: 'sciret_run_step', invoked_at: at(59),
        input: { run_id: runId, step: 'R3_analyze' },
        output: { n_innovations: 0, n_gaps: 3 } },
      { step: 'R4_verify', tool: 'sciret_run_step', invoked_at: at(59),
        input: { run_id: runId, step: 'R4_verify' },
        output: { consistency_rate: 1.0, n_contradictions: 0 } },
      { step: 'R5_write', tool: 'sciret_run_step', invoked_at: at(60),
        input: { run_id: runId, step: 'R5_write' },
        output: { n_statements: 19, cite_rate: 1.0 } },
      { step: 'R6_review', tool: 'sciret_run_step', invoked_at: at(60),
        input: { run_id: runId, step: 'R6_review' },
        output: { overall: 7.67, n_blocking: 1, verdict: '需大修（Major Revision）' } },
    ];
  }

  /* ---------- 运行列表（6 个 run：1 RUNNING / 1 degraded / 1 FAILED@P4） ---------- */
  const SHOWCASE_ID = 'run-20261008-064350-b354f6';
  const RUNS = [
    {
      run_id: 'run-20261008-075441-c881ac', workflow: 'research', run_status: 'RUNNING', degraded: false,
      goal: '固态电解质界面阻抗表征方法综述', lit_source: 'auto', created_at: '2026-10-08T07:54:41Z', updated_at: '2026-10-08T07:55:10Z',
      steps_order: C.WORKFLOWS.research,
      steps: { R1_search: 'DONE', R2_read: 'DONE', R3_analyze: 'RUNNING', R4_verify: 'PENDING', R5_write: 'PENDING', R6_review: 'PENDING' },
      attempts: { R1_search: 1, R2_read: 1, R3_analyze: 1 },
      _rank: 0,
    },
    {
      run_id: SHOWCASE_ID, workflow: 'research', run_status: 'DONE', degraded: true,
      goal: '固态电解质界面阻抗的表征方法综述', lit_source: 'auto', created_at: '2026-10-08T06:43:50Z', updated_at: '2026-10-08T06:44:01Z',
      steps_order: C.WORKFLOWS.research,
      steps: { R1_search: 'DONE', R2_read: 'DONE', R3_analyze: 'DONE', R4_verify: 'DONE', R5_write: 'DONE', R6_review: 'DONE' },
      attempts: { R1_search: 1, R2_read: 1, R3_analyze: 1, R4_verify: 1, R5_write: 1, R6_review: 1 },
      toolcalls: makeToolcalls(SHOWCASE_ID), conclusions: CONCLUSIONS, n_evidence: 21,
      _rank: 1,
    },
    {
      run_id: 'run-20261008-064702-fede6b', workflow: 'materials', run_status: 'DONE', degraded: false,
      goal: '硫化物固态电解质离子电导率数据集清洗与建模', lit_source: 'local', created_at: '2026-10-08T06:47:02Z', updated_at: '2026-10-08T06:47:40Z',
      steps_order: C.WORKFLOWS.materials,
      steps: { P1_lit_search: 'DONE', P2_clean_data: 'DONE', P3_run_experiment: 'DONE', P4_verify: 'DONE', P5_report: 'DONE' },
      attempts: { P1_lit_search: 1, P2_clean_data: 1, P3_run_experiment: 1, P4_verify: 1, P5_report: 1 },
      n_evidence: 9, _rank: 2,
    },
    {
      run_id: 'run-20261008-064952-4eb61a', workflow: 'materials', run_status: 'FAILED', degraded: false,
      goal: 'OBELiX 数据集复现校验（容差检查）', lit_source: 'local', created_at: '2026-10-08T06:49:52Z', updated_at: '2026-10-08T06:50:30Z',
      steps_order: C.WORKFLOWS.materials,
      steps: { P1_lit_search: 'DONE', P2_clean_data: 'DONE', P3_run_experiment: 'DONE', P4_verify: 'FAILED', P5_report: 'PENDING' },
      attempts: { P1_lit_search: 1, P2_clean_data: 1, P3_run_experiment: 1, P4_verify: 2, P5_report: 0 },
      n_evidence: 6, _rank: 3,
    },
    {
      run_id: 'run-20261008-070248-15e0bb', workflow: 'research', run_status: 'DONE', degraded: false,
      goal: '钠离子固态电解质研究进展调研', lit_source: 'arxiv', created_at: '2026-10-08T07:02:48Z', updated_at: '2026-10-08T07:03:20Z',
      steps_order: C.WORKFLOWS.research,
      steps: { R1_search: 'DONE', R2_read: 'DONE', R3_analyze: 'DONE', R4_verify: 'DONE', R5_write: 'DONE', R6_review: 'DONE' },
      attempts: { R1_search: 1, R2_read: 1, R3_analyze: 1, R4_verify: 1, R5_write: 1, R6_review: 1 },
      n_evidence: 14, _rank: 4,
    },
    {
      run_id: 'run-20261008-072945-866930', workflow: 'research', run_status: 'DONE', degraded: true,
      goal: '固态电池界面工程综述（含跨源降级）', lit_source: 'auto', created_at: '2026-10-08T07:29:45Z', updated_at: '2026-10-08T07:30:22Z',
      steps_order: C.WORKFLOWS.research,
      steps: { R1_search: 'DONE', R2_read: 'DONE', R3_analyze: 'DONE', R4_verify: 'DONE', R5_write: 'DONE', R6_review: 'DONE' },
      attempts: { R1_search: 1, R2_read: 1, R3_analyze: 1, R4_verify: 1, R5_write: 1, R6_review: 1 },
      n_evidence: 18, _rank: 5,
    },
  ];

  const runsById = {};
  RUNS.forEach((r) => { runsById[r.run_id] = r; });

  /* ---------- KPI（对齐规格：任务 6 / 通过率 92% / 证据 21 / 来源 3.75） ---------- */
  const KPI = [
    { id: 'runs', label: '累计任务', value: '6', unit: '个 run', sub: '1 运行中 · 1 已降级 · 1 失败', go: 'overview' },
    { id: 'pass', label: '平均步骤通过率', value: '92', unit: '%', sub: '跨 6 个 run 加权', go: 'evidence' },
    { id: 'ev', label: '证据条目总数', value: '21', unit: '条', sub: 'fact 21 · artifact 0', go: 'evidence' },
    { id: 'src', label: '来源可用均值', value: '3.75', unit: '/4 源', sub: 'semantic_scholar 偶发不可用', go: 'evidence' },
  ];

  /* ---------- 信任指标条 ---------- */
  const TRUST = {
    chain: { label: '哈希链完整', value: '21/21', ok: true, detail: '每条 provenance 的 chain_hash 逐条串联校验通过' },
    sources: { label: '来源可用', value: '3.75/4', ok: true, detail: 'arxiv / crossref / openalex 正常；semantic_scholar 降级' },
    degraded: { label: '降级次数', value: '2', ok: false, detail: '两次自动切源，均为「任务未中断」' },
  };

  /* ---------- 审计包清单 ---------- */
  const AUDIT_PACK = [
    { name: 'report.md', desc: '可交付报告（结论带 [EV] 角标）', hash: hash64('report.md'), ok: true },
    { name: 'provenance.jsonl', desc: 'append-only 证据台账', hash: hash64('provenance.jsonl'), ok: true },
    { name: 'events.jsonl', desc: '状态机事件流', hash: hash64('events.jsonl'), ok: true },
    { name: 'conclusions.jsonl', desc: '结论 ↔ 证据绑定', hash: hash64('conclusions.jsonl'), ok: true },
    { name: 'verify_export.py', desc: '独立复核脚本（离线校验哈希链）', hash: hash64('verify_export.py'), ok: true },
  ];

  /* ---------- report.md（Markdown 原文，前端最小渲染） ---------- */
  const REPORT_MD = [
    '# 固态电解质界面阻抗的表征方法综述',
    '',
    '## 摘要',
    '本文围绕固态电解质界面阻抗的表征方法，系统梳理了检索到的 10 篇文献与 3 篇精读笔记，',
    '对比了 EIS、DRT、三电极等主流表征手段，形成 5 条带证据绑定的结论 [EV-0001]。',
    '需要说明：本次检索中 semantic_scholar 数据源不可用，系统已自动切换来源，**任务未中断**。',
    '',
    '## 1. 研究背景与检索策略',
    '采用 workflow=research 六步流水线：检索 → 精读 → 分析 → 核验 → 撰写 → 自审。',
    '检索来源 lit_source=auto，命中 10 篇，各源状态记录于 [EV-0010]。',
    '',
    '## 2. 界面阻抗表征方法对比',
    '- EIS（电化学阻抗谱）：频域信息完整，但需等效电路拟合 [EV-0012]',
    '- DRT（弛豫时间分布）：无需预设等效电路，适合复杂界面 [EV-0013]',
    '- 三电极法：可分离正负极界面贡献，但装配难度高 [EV-0014]',
    '',
    '## 3. 证据溯源与一致性',
    '引用一致性率 100.00%（3 处引用全部一致）[EV-0018]，未检出文献间矛盾。',
    '',
    '## 4. 结论与待办',
    '- 综述结论：界面阻抗表征需多维方法交叉验证 [EV-0019]',
    '- 待办（自审阻断项）：1 处陈述标注 [需补充引用]，必须补证或删除 [EV-0021]',
    '',
    '> 综合自审评分 **7.67/10**（写作清晰度 9.47 · 技术正确性 10.0 · 贡献度 2.0）。',
  ].join('\n');

  /* ---------- 数据集 ---------- */
  const DATASETS = [
    { name: 'OBELiX', files: 'OBELiX.csv', rows_raw: 599, rows_cleaned: 599, license: 'CC-BY-4.0', source: 'https://github.com/be-a-researcher/OBELiX', desc: '固态电解质离子电导率结构化数据集（599 条记录），用于回归建模与校验。' },
    { name: 'conductivity_raw', files: 'conductivity_raw.csv', rows_raw: 1284, rows_cleaned: 599, license: 'CC-BY-4.0', source: 'https://github.com/be-a-researcher/OBELiX', desc: '原始电导率记录经 P2 清洗后的中间产物。' },
  ];

  /* ---------- AGH 7 工具目录（名称/描述/meta 与 index.mjs 一致） ---------- */
  const READONLY_META = { isReadOnly: true, requiresApproval: 'never', replay: 'safe', wallMs: 5000 };
  const writeMeta = (replay, wallMs) => ({ isReadOnly: false, requiresApproval: 'destructive', replay, wallMs });
  const TOOLS = [
    { name: 'sciret_plan', desc: 'Plan a new pipeline run: create isolated run instance with a step state machine and append-only ledgers. workflow=materials runs P1..P5 (default); workflow=research runs the six-step R1_search..R6_review pipeline.', params: [['goal', 'string', true], ['workflow', 'string?', false], ['chaos', 'string?', false]], meta: writeMeta('never', 10000) },
    { name: 'sciret_run_step', desc: 'Run a single pipeline step for a given run (idempotent reuse for terminal steps). research steps: R1_search|R2_read|R3_analyze|R4_verify|R5_write|R6_review.', params: [['run_id', 'string', true], ['step', 'string', true], ['chaos', 'string?', false]], meta: writeMeta('idempotent', 180000) },
    { name: 'sciret_status', desc: 'Read-only: return current run/step status, attempts, and degraded flag for a run.', params: [['run_id', 'string', true]], meta: READONLY_META },
    { name: 'sciret_verify', desc: 'P4 reproducibility verification: re-run experiment to isolated dir and run 5 tolerance checks.', params: [['run_id', 'string', true]], meta: writeMeta('idempotent', 180000) },
    { name: 'sciret_report', desc: 'P5 report generation: build report.md from real artifacts with bound evidence IDs.', params: [['run_id', 'string', true]], meta: writeMeta('idempotent', 30000) },
    { name: 'sciret_cite', desc: 'Read-only: resolve evidence citation (DOI/author/year for literature; sha256 prefix for artifacts).', params: [['run_id', 'string', true], ['ev', 'string?', false]], meta: READONLY_META },
    { name: 'sciret_resume', desc: 'Resume a run (breakpoint continue): only PENDING/FAILED steps execute; DONE/SKIPPED reused.', params: [['run_id', 'string', true]], meta: writeMeta('idempotent', 180000) },
  ];

  /* ---------- AGH 会话回放（固定脚本，不连 AGH） ---------- */
  const AGH_SESSION = {
    session_id: 'c16d830d-9f50-4899-a044-56630eb119c4',
    run_id: 'run-20261008-072945-866930',
    started_at: '2026-10-08T07:27:52Z',
    events: [
      { kind: 'tool/call', tool: 'sciret_plan', input: { goal: '固态电解质界面阻抗表征方法综述', workflow: 'research' }, at: '07:27:55Z' },
      { kind: 'tool/result', tool: 'sciret_plan', output: { run_id: 'run-20261008-072945-866930', run_status: 'PLANNED', steps_order: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write', 'R6_review'] }, at: '07:27:56Z' },
      { kind: 'tool/call', tool: 'sciret_run_step', input: { run_id: 'run-20261008-072945-866930', step: 'R1_search' }, at: '07:28:01Z' },
      { kind: 'tool/result', tool: 'sciret_run_step', output: { n_hits: 10, unavailable: ['semantic_scholar'] }, at: '07:28:09Z' },
      { kind: 'tool/call', tool: 'sciret_status', input: { run_id: 'run-20261008-072945-866930' }, at: '07:28:12Z' },
      { kind: 'tool/result', tool: 'sciret_status', output: { run_status: 'RUNNING', degraded: true, steps: { R1_search: 'DONE', R2_read: 'RUNNING' } }, at: '07:28:12Z' },
      { kind: 'tool/call', tool: 'sciret_run_step', input: { run_id: 'run-20261008-072945-866930', step: 'R2_read' }, at: '07:28:20Z' },
      { kind: 'tool/result', tool: 'sciret_run_step', output: { n_read: 3, n_failed: 0 }, at: '07:28:36Z' },
      { kind: 'tool/call', tool: 'sciret_cite', input: { run_id: 'run-20261008-072945-866930', ev: 'EV-0001' }, at: '07:28:40Z' },
      { kind: 'tool/result', tool: 'sciret_cite', output: { ev_id: 'EV-0001', doi: '10.1038/nmat3066', year: 2011, tier: 'fact' }, at: '07:28:40Z' },
    ],
  };

  /* ---------- 环境体检（6 项：4 ✓ / 2 🟠） ---------- */
  const HEALTH = [
    { id: 'python', name: 'Python 解释器（≥3.10）', status: 'ok', detail: 'Python 3.11.9', fix: '' },
    { id: 'root', name: '项目根目录存在性校验', status: 'ok', detail: 'paper-agent/ 已就绪', fix: '' },
    { id: 'runs', name: 'runs/ 目录可写', status: 'ok', detail: '最近写入 run-20261008-075441-c881ac', fix: '' },
    { id: 'env', name: '环境变量契约', status: 'warn', detail: 'paper-agent_ROOT 未生效（当前为空）',
      fix: '在启动 daemon 的那个终端里执行：export paper-agent_ROOT="<paper-agent 绝对路径>" 然后重启 daemon（不要重复 export，见 P0-2）。' },
    { id: 'port', name: '端口可用（8787 / 5173）', status: 'warn', detail: '8787 被占用（疑似上一次后端未退出）',
      fix: '结束占用 8787 的进程后重试：lsof -ti:8787 | xargs kill（Windows: netstat -ano | findstr :8787）。' },
    { id: 'agh', name: 'AGH 插件状态（7 工具注册）', status: 'ok', detail: 'paper-agent-tools@0.1.0 · 7/7 工具已注册 · trusted', fix: '' },
  ];

  const SETTINGS = {
    theme: 'dark',
    defaultWorkflow: 'research',
    defaultSource: 'auto',
  };

  /* ---------- 导出 ---------- */
  // mock 数据 + 领域常量（来自 constants.js）一并挂到 PA_DATA，
  // 视图层（views.js / components.js）继续从 window.PA_DATA 读，无需改动。
  window.PA_DATA = Object.assign({
    hash64, LITERATURE, PROVENANCE, provByEv, CONCLUSIONS, FACTCHECK, REVIEW,
    SOURCES_STATUS, UNAVAILABLE, SHOWCASE_ID, RUNS, runsById, KPI, TRUST, AUDIT_PACK,
    REPORT_MD, DATASETS, TOOLS, AGH_SESSION, HEALTH, SETTINGS,
  }, C);
})();
