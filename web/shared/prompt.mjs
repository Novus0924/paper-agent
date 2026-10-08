/**
 * web/shared/prompt.mjs —— 系统提示词模板的**单一真源**（P2-4）
 * ============================================================
 * 背景：系统提示词模板（buildSystemPrompt）历史上在**两处各写一份**：
 *   - 前端 `src/api/constants.js`（提交前给用户看的预览）
 *   - 后端 `server/prompt.js`（真正下发并存档的那一份）
 * 两份必须逐字一致 —— 不一致的话「明示」就成了欺骗（用户看到的约束 ≠
 * 实际施加的约束）。靠注释提醒不可靠，改一边忘另一边是迟早的事。
 *
 * 方案：把 WORKFLOWS / STEP_LABELS / buildSystemPrompt 下沉到本共享模块，
 * 前端与后端**都从这里引用**，从结构上消除"双份"。
 * `server/verify-prompt-parity.mjs` 保留为兜底回归（仍会逐组比对两端产物）。
 *
 * 兼容性：纯 ESM，零依赖；前端（浏览器原生 import）与后端（Node ESM）通用。
 */

/** 步骤 id → 与 core/paper_agent/state.py 的 WORKFLOWS 严格一致 */
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

/** 检索来源的人话说明（只写 CLI 真正支持的那几个，见 resolveLitSource） */
const SRC_CN = {
  auto: '先试 arXiv，失败自动降级',
  arxiv: '仅 arXiv 实时检索',
  local: '离线内置语料，不联网',
};

/**
 * 构造首轮系统提示词（方案 §5.2 的模板）。
 * @param {string} goal 研究目标
 * @param {string} workflow research | materials
 * @param {string} litSource 已归一化的 lit_source
 * @param {string[]} [extra] 追问轮追加的用户输入（§5.2：第一轮注入，之后不再重复）
 * @returns {string}
 */
export function buildSystemPrompt(goal, workflow, litSource, extra = []) {
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
  if (litSource && SRC_CN[litSource]) {
    lines.push(`【检索来源】${litSource} —— ${SRC_CN[litSource]}`);
  }
  lines.push(`【本次目标】${goal}`);
  if (extra.length) {
    lines.push('【追加要求】');
    extra.forEach((e, i) => lines.push(`${i + 1}. ${e}`));
  }
  return lines.join('\n');
}
