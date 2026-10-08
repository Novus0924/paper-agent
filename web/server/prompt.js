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

/**
 * P2-4：WORKFLOWS / STEP_LABELS / buildSystemPrompt 已下沉为共享单一真源
 * （web/shared/prompt.mjs），前端 `src/api/constants.js` 与后端本文件都从那里引用，
 * 从结构上消除"两份模板"。`server/verify-prompt-parity.mjs` 保留为兜底回归。
 */
import { WORKFLOWS, STEP_LABELS, buildSystemPrompt } from '../shared/prompt.mjs';

export { buildSystemPrompt };


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