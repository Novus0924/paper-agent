/**
 * api/constants.js —— 领域常量
 * ------------------------------------------------------------
 * 步骤 id 与 core/paper_agent/state.py 的 WORKFLOWS 严格一致
 */

export const WORKFLOWS = {
  research: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write', 'R6_review'],
  materials: ['P1_lit_search', 'P2_clean_data', 'P3_run_experiment', 'P4_verify', 'P5_report'],
};

/** 步骤中文名（短标签，用于步骤条） */
export const STEP_LABELS = {
  R1_search: '检索', R2_read: '精读', R3_analyze: '分析',
  R4_verify: '核验', R5_write: '撰写', R6_review: '自审',
  P1_lit_search: '检索', P2_clean_data: '清洗', P3_run_experiment: '实验',
  P4_verify: '验证', P5_report: '报告',
};

/** 工作流说明（新任务页用） */
export const WORKFLOW_META = {
  research: {
    label: 'research',
    desc: '六步文献综述：检索 → 精读 → 分析 → 核验 → 撰写 → 自审。不限领域',
    steps: WORKFLOWS.research,
  },
  materials: {
    label: 'materials',
    desc: '五步材料实验：检索 → 清洗 → 实验 → 验证 → 报告。含电解质数据集',
    steps: WORKFLOWS.materials,
  },
};

/**
 * 检索来源
 *
 * ⚠️ 实测校准（2026-10-05）：paper_agent.cli 的 --lit-source 只接受
 *    "" | local | arxiv | auto 四值，传其他值会被 argparse 直接拒绝退出。
 *    所以 crossref / openalex / semantic_scholar 这三个值在当前 CLI 下
 *    会被后端归一化为 auto（auto = 先试 arxiv 再降级，语义上最接近多源）。
 *    `cliValue` 字段是真实下发给 CLI 的值；`effective:false` 的项会灰显。
 *    详见 server/paper-agent-server.js 的 resolveLitSource()。
 */
export const LIT_SOURCES = [
  { id: 'auto', label: 'auto', desc: '先试 arXiv，失败自动降级', cliValue: 'auto' },
  { id: 'arxiv', label: 'arXiv', desc: '仅 arXiv 实时检索', cliValue: 'arxiv' },
  { id: 'local', label: '本地语料', desc: '离线内置语料，不联网', cliValue: 'local' },
  { id: 'crossref', label: 'CrossRef', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
  { id: 'openalex', label: 'OpenAlex', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
  { id: 'semantic_scholar', label: 'Semantic Scholar', desc: 'CLI 暂不支持，将按 auto 执行', cliValue: 'auto', effective: false },
];

/** 状态枚举（state.py: StepStatus / RunStatus） */
export const STEP_STATUS = {
  PENDING: 'PENDING', RUNNING: 'RUNNING', DONE: 'DONE',
  FAILED: 'FAILED', SKIPPED: 'SKIPPED',
};
export const RUN_STATUS = {
  PLANNED: 'PLANNED', RUNNING: 'RUNNING', DONE: 'DONE', FAILED: 'FAILED',
};

/** provenance 的 kind → 中文 + 徽标色 */
export const KIND_META = {
  literature: { label: '文献' },
  data: { label: '数据' },
  note: { label: '精读笔记' },
  analysis: { label: '分析' },
  factcheck: { label: '核验' },
  draft: { label: '草稿' },
  review: { label: '自审' },
  experiment: { label: '实验' },
};

/**
 * tier → 徽章
 * ⚠️ 实测（research 全流程跑完21 条 provenance）：**全部是 fact，artifact 为 0**。
 *    artifact 只在「下载并解析本地 PDF 成文件」时才会产生。
 *    所以 artifact 计数为 0 是正常状态，不是 bug。
 */
export const TIER_META = {
  fact: { label: 'fact' },
  artifact: { label: 'artifact' },
};

/**
 * 系统提示词模板（对接方案 §5.2）
 *
 * ⚠️ 这份模板必须与 server/prompt.js 的 buildSystemPrompt() **逐字一致**。
 *    两边各写一份是因为用途不同：那份是**提交前给用户看的预览**，
 *    后端那份是**真正生成并存档的下发内容**。
 *    工作台渲染的是后端返回的存档版本（prompt.source==='server'），
 *    所以「用户最终看到的」永远等于「后端实际用的」。
 *    ⚠️ 改这个函数时请同步改server/prompt.js，否则预览与实际会不一致。
 */
export function buildSystemPrompt(goal, workflow, litSource) {
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
  // 与后端 SRC_CN 保持一致；只写 CLI 真正支持的三个值
  const srcCn = {
    auto: '先试 arXiv，失败自动降级',
    arxiv: '仅 arXiv 实时检索',
    local: '离线内置语料，不联网',
  };
  if (litSource && srcCn[litSource]) {
    lines.push(`【检索来源】${litSource} —— ${srcCn[litSource]}`);
  }
  lines.push(`【本次目标】${goal}`);
  return lines.join('\n');
}