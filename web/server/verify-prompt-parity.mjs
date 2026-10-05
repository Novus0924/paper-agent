/**
 * server/verify-prompt-parity.mjs —— 前后端提示词模板一致性校验
 * ============================================================
 * 为什么需要这个脚本：
 *   前端 src/api/constants.js 与后端 server/prompt.js 各有一份
 *   buildSystemPrompt()（一份用于提交前预览，一份用于真正下发并存档）。
 *   两份**必须逐字一致**——不一致的话「明示」就成了欺骗：
 *   用户看到的约束 ≠ 实际施加的约束。
 *
 *   光靠注释提醒不可靠，改了一边忘了另一边是迟早的事，所以用脚本卡住。
 *
 * 用法：node server/verify-prompt-parity.mjs
 * 退出码 0 = 一致，1 = 有差异（并打印差异详情）
 *
 * 零第三方依赖，可直接 node 跑。
 */

import { buildSystemPrompt as frontend } from '../src/api/constants.js';
import { buildSystemPrompt as backend } from './prompt.js';

/** 覆盖：两个工作流 × CLI 真正支持的三个来源 × 一个会被归一化的非法值 */
const CASES = [
  ['固态聚合物电解质界面阻抗表征', 'research', 'auto'],
  ['卤化物钙钛矿载流子俘获机制', 'research', 'arxiv'],
  ['材料合成路线与性能关联', 'research', 'local'],
  ['数据集清洗与实验验证', 'materials', 'auto'],
  ['电极界面产物表征', 'materials', 'local'],
  // 前端会灰显的来源：后端归一化为 auto，两边都应落到同一结果
  ['非法来源应被归一化', 'materials', 'crossref'],
];

/** 目标里带换行/特殊字符的边界情况 */
const EDGE = [
  ['', 'research', 'auto'],                                  // 空目标
  ['目标含\n换行与【方括号】', 'research', 'auto'],            // 特殊字符
  ['A'.repeat(500), 'research', 'auto'],                     // 超长
  ['未知工作流 fallback', 'no-such-workflow', 'auto'],        // 非法工作流
];

let failed = 0;
const rows = [];

for (const [goal, workflow, litSource] of [...CASES, ...EDGE]) {
  const a = frontend(goal, workflow, litSource);
  const b = backend(goal, workflow, litSource);
  const ok = a === b;
  if (!ok) failed++;
  rows.push({ workflow, litSource, goal: goal.slice(0, 18) + (goal.length > 18 ? '…' : ''), ok });
}

const W = { workflow: 10, litSource: 12, goal: 24 };
const line = (r) => `  ${r.ok ? '✓' : '✗'} ${r.workflow.padEnd(W.workflow)}${r.litSource.padEnd(W.litSource)}${r.goal}`;
console.log('前后端提示词模板一致性校验');
console.log('─'.repeat(56));
rows.forEach((r) => console.log(line(r)));
console.log('─'.repeat(56));

if (failed) {
  console.log(`\n✗ ${failed}/${rows.length} 组不一致。差异详情：\n`);
  for (const [goal, workflow, litSource] of [...CASES, ...EDGE]) {
    const a = frontend(goal, workflow, litSource);
    const b = backend(goal, workflow, litSource);
    if (a === b) continue;
    console.log(`── ${workflow} / ${litSource} ──`);
    const al = a.split('\n'), bl = b.split('\n');
    for (let i = 0; i < Math.max(al.length, bl.length); i++) {
      if (al[i] === bl[i]) continue;
      console.log(`  第 ${i + 1} 行:`);
      console.log(`前端: ${JSON.stringify(al[i])}`);
      console.log(`后端: ${JSON.stringify(bl[i])}`);
    }
  }
  console.log('\n→ 修 src/api/constants.js 的 buildSystemPrompt 或 server/prompt.js 的同名函数，'
    + '两边必须产出完全相同的字符串。');
  process.exit(1);
}

console.log(`✓ 全部 ${rows.length} 组逐字一致（含边界用例）`);
console.log('  提示词模板可用：提交前预览 = 后端下发内容');
process.exit(0);