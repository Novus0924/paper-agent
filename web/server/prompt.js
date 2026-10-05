/**
 * server/prompt.js —— M3 系统提示词注入（对接方案 §5）
 * ============================================================
 * 为什么要这个文件：
 *   §5.1 实测确认 ACP 的 session/new 只有 cwd / additionalDirectories /
 *   mcpServers / _meta，**没有 system prompt 字段**；AGH 的系统提示词是
 *   内置 section，不开放运行时注入。→ 只能走 §5.2 的「首轮前缀 + 明示」。
 *
 * ★ 与前端那份buildSystemPrompt() 的关系（重要）：
 *   前端也有一份同名模板（src/api/constants.js），但那份是**给用户看的预览**。
 *   本文件是**真正下发给后端的那一份**，两者必须逐字一致 —— 不一致的话
 *   「明示」就成了欺骗。所以这里写死一份，后端把结果落盘，
 *   前端 GET 回来渲染，保证「用户看到的 = 后端实际用的」。
 *
 * 落盘位置：<web>/.data/prompts/<run_id>.json
 *   ⚠️ 刻意**不写进 paper-agent/runs/<id>/**。原因是那个目录里
 *   events.jsonl / provenance.jsonl 是 Python 侧的 append-only 哈希链账本
 *   （见 core/paper_agent/state.py 与 chaos.py 注释），随手加文件可能破坏
 *   完整性校验。前端工程自己的数据放自己的目录，互不污染。
 */

import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.resolve(__dirname, '..', '.data');
const PROMPT_DIR = path.join(DATA_DIR, 'prompts');

/** 步骤id → 与 core/paper_agent/state.py 的 WORKFLOWS 严格一致 */
const WORKFLOWS = {
  research: ['R1_search', 'R2_read', 'R3_analyze', 'R4_verify', 'R5_write', 'R6_review'],
  materials: ['P1_lit_search', 'P2_clean_data', 'P3_run_experiment', 'P4_verify', 'P5_report'],
};

/**
 * 步骤中文名。
 * ⚠️ 必须与 src/api/constants.js 的 STEP_LABELS **完全一致** —— 两边模板要逐字对齐，
 *    否则「用户看到的预览」和「后端实际下发的」会不一致（那等于欺骗）。
 *    这里直接 import 前端那份常量做单一真源，避免以后只改一边。
 */
const { STEP_LABELS } = await import('../src/api/constants.js');

/** 检索来源的人话说明（只写 CLI 真正支持的那几个，见 resolveLitSource） */
const SRC_CN = {
  auto: '先试 arXiv，失败自动降级',
  arxiv: '仅 arXiv 实时检索',
  local: '离线内置语料，不联网',
};

/**
 * 构造首轮系统提示词（方案 §5.2 的模板，逐字沿用）
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

/** 提示词存档路径（run_id 由调用方保证已过白名单校验） */
function promptPath(runId) {
  return path.join(PROMPT_DIR, `${runId}.json`);
}

/**
 * 落盘一份提示词存档。
 * 失败不抛——提示词存档是「可审计的附加物」，不该因为写不了盘就让建任务失败。
 */
export async function savePrompt(runId, payload) {
  try {
    await fsp.mkdir(PROMPT_DIR, { recursive: true });
    const file = {
      run_id: runId,
      created_at: new Date().toISOString(),
      ...payload,
    };
    await fsp.writeFile(promptPath(runId), JSON.stringify(file, null, 2), 'utf8');
    return true;
  } catch {
    return false;
  }
}

/** 读取提示词存档；没有就返回 null（前端据此回退到本地模板并标注） */
export async function loadPrompt(runId) {
  try {
    return JSON.parse(await fsp.readFile(promptPath(runId), 'utf8'));
  } catch {
    return null;
  }
}

/** 同步版（仅用于 /api/health 报数量） */
export function countPrompts() {
  try {
    return fs.readdirSync(PROMPT_DIR).filter((n) => n.endsWith('.json')).length;
  } catch {
    return 0;
  }
}

export const PROMPT_WORKFLOWS = WORKFLOWS;