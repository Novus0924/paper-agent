/* ============================================================
 * constants.js —— 领域常量（唯一真源，Batch 3 · B3-1 抽出）
 * 从 data.js 抽出：工作流 / 步骤标签 / 工作流元数据 / 检索来源 /
 * kind·tier 元数据 / 系统提示词模板 / 状态标签 / 导航与路由键。
 * 纯数据 + 纯函数，无 DOM、无网络；挂在 window.PA_CONST。
 * 加载顺序：constants.js → data.js → components.js → store.js → api.js → views.js → app.js
 * ============================================================ */
(function () {
  'use strict';

  /* ---------- 工作流与步骤 ---------- */
  const WORKFLOWS = {
    research: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write', 'R6_review'],
    materials: ['P1_lit_search', 'P2_clean_data', 'P3_run_experiment', 'P4_verify', 'P5_report'],
  };
  const STEP_LABELS = {
    R1_search: '检索', R2_read: '精读', R3_analyze: '分析',
    R4_verify: '核验', R5_write: '撰写', R6_review: '自审',
    P1_lit_search: '检索', P2_clean_data: '清洗', P3_run_experiment: '实验',
    P4_verify: '验证', P5_report: '报告',
  };
  const WORKFLOW_META = {
    research: { label: 'research', desc: '六步文献综述：检索 → 精读 → 分析 → 核验 → 撰写 → 自审。不限领域', steps: WORKFLOWS.research },
    materials: { label: 'materials', desc: '五步材料实验：检索 → 清洗 → 实验 → 验证 → 报告。含电解质数据集', steps: WORKFLOWS.materials },
  };

  /* ---------- 检索来源 ---------- */
  const LIT_SOURCES = [
    { id: 'auto', label: 'auto', desc: '先试 arXiv，失败自动降级', cliValue: 'auto', effective: true },
    { id: 'arxiv', label: 'arXiv', desc: '仅 arXiv 实时检索', cliValue: 'arxiv', effective: true },
    { id: 'local', label: '本地语料', desc: '离线内置语料，不联网', cliValue: 'local', effective: true },
    { id: 'crossref', label: 'CrossRef', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
    { id: 'openalex', label: 'OpenAlex', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
    { id: 'semantic_scholar', label: 'Semantic Scholar', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
  ];

  /* ---------- kind / tier 元数据 ---------- */
  const KIND_META = {
    literature: '文献', data: '数据', note: '精读笔记', analysis: '分析',
    factcheck: '核验', draft: '草稿', review: '自审', experiment: '实验',
  };
  const TIER_META = { fact: 'fact', artifact: 'artifact' };

  /* ---------- 状态标签 ---------- */
  const RUN_STATUS_LABEL = { PLANNED: '待执行', RUNNING: '运行中', DONE: '已完成', FAILED: '失败' };
  const STEP_STATUS_LABEL = { PENDING: '待执行', RUNNING: '运行中', DONE: '完成', FAILED: '失败', SKIPPED: '跳过' };

  /* ---------- 系统提示词模板（逐字对齐 web/shared/prompt.mjs buildSystemPrompt） ---------- */
  function buildSystemPrompt(goal, workflow, litSource) {
    const steps = WORKFLOWS[workflow] || WORKFLOWS.research;
    const chain = steps.map((s) => `${s}(${STEP_LABELS[s] || s})`).join(' → ');
    const lines = [
      '【角色】你是一个科研文献分析助手。',
      '【硬约束】',
      '1. 只使用已提供的检索结果作答，不得凭记忆补充文献；',
      '2. 每条结论必须标注来源编号；',
      '3. 资料不足时明确说「证据不足」，不要编造。',
      `【工作流】${workflow}：${chain}`,
    ];
    const srcCn = { auto: '先试 arXiv，失败自动降级', arxiv: '仅 arXiv 实时检索', local: '离线内置语料，不联网' };
    if (litSource && srcCn[litSource]) lines.push(`【检索来源】${litSource} —— ${srcCn[litSource]}`);
    lines.push(`【本次目标】${goal}`);
    return lines.join('\n');
  }

  /* ---------- 导航模型 + 路由键（从 app.js 抽出，纯元数据） ---------- */
  const NAV = [
    { key: 'overview', label: '总览', icon: 'grid' },
    { key: 'new', label: '新建任务', icon: 'plus' },
    { key: 'monitor', label: '运行监控', icon: 'activity' },
    { key: 'evidence', label: '证据溯源', icon: 'link' },
    { key: 'report', label: '报告与导出', icon: 'file' },
    { key: 'library', label: '文献资源', icon: 'book' },
    { key: 'health', label: '环境体检', icon: 'heart' },
    { key: 'agh', label: 'AGH 集成', icon: 'box' },
    { sep: true },
    { key: 'settings', label: '设置', icon: 'gear' },
    { key: 'recovery', label: '故障演练', icon: 'shield' },
  ];
  // 10 个可路由视图键（顺序与 NAV 中的非分隔项一致）
  const ROUTE_KEYS = ['overview', 'new', 'monitor', 'evidence', 'report', 'library', 'health', 'agh', 'settings', 'recovery'];

  window.PA_CONST = {
    WORKFLOWS, STEP_LABELS, WORKFLOW_META, LIT_SOURCES, KIND_META, TIER_META,
    buildSystemPrompt, RUN_STATUS_LABEL, STEP_STATUS_LABEL, NAV, ROUTE_KEYS,
  };
})();
