/**
 * api/constants.js —— 领域常量
 * ------------------------------------------------------------
 * 步骤 id 与 core/paper_agent/state.py 的 WORKFLOWS 严格一致
 */

// P2-4：WORKFLOWS / STEP_LABELS / buildSystemPrompt 统一从共享单一真源引入
// （web/shared/prompt.mjs），前端与后端不再各写一份，从结构上避免漂移。
import { WORKFLOWS, STEP_LABELS, buildSystemPrompt } from '../../shared/prompt.mjs';

export { WORKFLOWS, STEP_LABELS, buildSystemPrompt };

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
 * 系统提示词模板（对接方案 §5.2）—— 已下沉为**共享单一真源**（P2-4）。
 *
 * buildSystemPrompt 现由 web/shared/prompt.mjs 提供并在本文件 re-export；
 * 后端 server/prompt.js 引用同一份，从结构上消除"两份模板可能漂移"。
 * server/verify-prompt-parity.mjs 保留为兜底回归（仍逐组比对两端产物）。
 */