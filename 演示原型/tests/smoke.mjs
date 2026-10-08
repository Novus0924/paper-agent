#!/usr/bin/env node
/**
 * tests/smoke.mjs —— 零依赖冒烟测试（Batch 3 · B3-5）
 * ------------------------------------------------------------
 * 直接 `node tests/smoke.mjs` 即可跑，不需要 jsdom / 构建 / 安装。
 * 做法：用 node:vm 在带最小 `window` 的沙箱里按加载顺序执行经典脚本
 * （constants→data→components→store→api→views），再对真实运行时对象做断言：
 *   - 常量：工作流/步骤标签/路由键/提示词模板/状态标签
 *   - 视图：10 路由键均有对应视图函数
 *   - 数据：7 工具真名、字段形状、21 条证据全 fact、C1..C5、6 个 run
 *   - 工具名真源：所有 toolcalls 的 tool 均为 sciret_run_step（禁幻觉名）
 *   - api（mock）：createRun/getRun/runAll/stopAuto 行为
 *
 * 退出码：0=全绿；1=有失败。
 */
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.resolve(HERE, '..', 'assets');

/* ---------- 断言小工具 ---------- */
let pass = 0;
const fails = [];
function ok(cond, msg) {
  if (cond) { pass++; console.log('  \u2713 ' + msg); }
  else { fails.push(msg); console.log('  \u2717 ' + msg); }
}
function eq(a, b, msg) {
  const same = JSON.stringify(a) === JSON.stringify(b);
  ok(same, msg + (same ? '' : `  (got ${JSON.stringify(a)})`));
}

/* ---------- 在 vm 沙箱里加载经典脚本 ---------- */
const sandbox = {
  window: {},
  console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  URLSearchParams,
};
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);

const LOAD_ORDER = ['constants.js', 'data.js', 'components.js', 'store.js', 'api.js', 'views.js'];
for (const f of LOAD_ORDER) {
  const code = fs.readFileSync(path.join(ASSETS, f), 'utf8');
  vm.runInContext(code, ctx, { filename: `assets/${f}` });
}
const W = sandbox.window;
const C = W.PA_CONST, D = W.PA_DATA, V = W.PA_VIEWS, API = W.PA_API, STORE = W.PA_STORE;

/* ============================================================
 * 1. 常量（constants.js）
 * ============================================================ */
console.log('\n[1] 常量 constants.js');
ok(!!C, 'window.PA_CONST 已定义');
eq(C.WORKFLOWS.research.length, 6, 'research 工作流 6 步');
eq(C.WORKFLOWS.materials.length, 5, 'materials 工作流 5 步');
ok(C.WORKFLOWS.research.concat(C.WORKFLOWS.materials).every((s) => !!C.STEP_LABELS[s]), '每个步骤都有中文标签');
eq(C.ROUTE_KEYS.length, 10, 'ROUTE_KEYS = 10 个路由键');
const navKeys = C.NAV.filter((n) => !n.sep).map((n) => n.key);
eq(navKeys, C.ROUTE_KEYS, 'NAV 非分隔项键序 == ROUTE_KEYS');
const p = C.buildSystemPrompt('目标X', 'research', 'auto');
ok(p.includes('R1_search(检索)') && p.includes('目标X') && p.includes('【硬约束】'), 'buildSystemPrompt 含步骤链/目标/硬约束');
ok(!!C.RUN_STATUS_LABEL.PLANNED && !!C.STEP_STATUS_LABEL.RUNNING, '状态标签齐全');
ok(D.WORKFLOWS === C.WORKFLOWS && D.buildSystemPrompt === C.buildSystemPrompt, 'PA_DATA 与 PA_CONST 常量同源（视图层零改动保障）');

/* ============================================================
 * 2. 视图（views.js）—— 路由可达性
 * ============================================================ */
console.log('\n[2] 视图 views.js');
ok(!!V, 'window.PA_VIEWS 已定义');
const missing = C.ROUTE_KEYS.filter((k) => typeof V[viewName(k)] !== 'function');
eq(missing, [], '10 路由键均有对应视图函数');
function viewName(k) { return ({ overview: 'overview', new: 'newTask', monitor: 'monitor', evidence: 'evidence', report: 'report', library: 'library', health: 'health', agh: 'agh', settings: 'settings', recovery: 'recovery' })[k]; }

/* ============================================================
 * 3. 数据形状（data.js）
 * ============================================================ */
console.log('\n[3] 数据形状 data.js');
const EXPECT_TOOLS = ['sciret_plan', 'sciret_run_step', 'sciret_status', 'sciret_verify', 'sciret_report', 'sciret_cite', 'sciret_resume'];
eq(D.TOOLS.map((t) => t.name), EXPECT_TOOLS, '7 个 sciret_* 工具真名');
eq(D.PROVENANCE.length, 21, 'provenance 21 条');
ok(D.PROVENANCE.every((e) => e.tier === 'fact' || e.tier === 'artifact'), 'tier ∈ {fact,artifact}');
ok(D.PROVENANCE.every((e) => e.ev_id && e.producer_step && /^[0-9a-f]{64}$/.test(e.chain_hash)), '每条含 ev_id/producer_step/64-hex chain_hash');
eq(D.CONCLUSIONS.map((c) => c.cid), ['C1', 'C2', 'C3', 'C4', 'C5'], '结论 C1..C5');
eq(D.RUNS.length, 6, 'run 列表 6 个');
ok(!!D.runsById[D.SHOWCASE_ID], 'SHOWCASE_ID 在 runsById 中');
ok(D.AGH_SESSION.events.filter((e) => e.kind === 'tool/call').length >= 5, 'AGH 会话 ≥5 次 tool/call');
ok(D.AGH_SESSION.events.every((e) => /^sciret_/.test(e.tool)), 'AGH 会话工具名全为 sciret_*');

/* ============================================================
 * 4. 工具名真源 —— 禁幻觉名
 * ============================================================ */
console.log('\n[4] 工具名真源');
const FORBIDDEN = ['sciret_search_papers', 'sciret_parse_paper', 'sciret_analyze_paper', 'sciret_verify_facts', 'sciret_self_review', 'sciret_clean_dataset', 'sciret_run_experiment'];
const allToolValues = [];
D.RUNS.forEach((r) => (r.toolcalls || []).forEach((tc) => allToolValues.push(tc.tool)));
D.TOOLS.forEach((t) => allToolValues.push(t.name));
D.AGH_SESSION.events.forEach((e) => allToolValues.push(e.tool));
ok(allToolValues.every((t) => /^sciret_/.test(t)), '所有运行时工具名均 sciret_* 前缀');
ok(allToolValues.every((t) => !FORBIDDEN.includes(t)), '无任何幻觉工具名');
ok(D.RUNS.every((r) => (r.toolcalls || []).every((tc) => tc.tool === 'sciret_run_step')), '所有 run 的 toolcalls.tool 权威值 = sciret_run_step');

/* ============================================================
 * 5. api.js（mock 模式行为）
 * ============================================================ */
console.log('\n[5] api.js（mock）');
ok(!!API && typeof API.createRun === 'function', 'PA_API.createRun 存在');
eq(API.mode(), 'mock', '默认 mode = mock');
const rid = API.createRun('冒烟目标', 'materials', 'local');
ok(/^run-/.test(rid), 'createRun 返回 run_id');
const r = API.getRun(rid);
ok(!!r && r.run_status === 'PLANNED', 'getRun 返回 PLANNED run');
eq(r.steps_order, C.WORKFLOWS.materials, 'steps_order == materials 工作流');
ok(r.steps_order.every((s) => r.steps[s] === 'PENDING'), '初始步骤全 PENDING');
API.runAll(rid);
eq(r.steps[r.steps_order[0]], 'RUNNING', 'runAll 后首步立即 RUNNING');
ok(API.isAuto(rid) === true, 'runAll 后 isAuto=true');
API.stopAuto(rid);
ok(API.isAuto(rid) === false, 'stopAuto 后 isAuto=false');
ok(!!STORE && typeof STORE.on === 'function' && typeof STORE.emit === 'function', 'store 提供 on/emit');

/* ============================================================
 * 5.5 api.js（Batch 3 · live 能力静态断言 + 模式默认值）
 * ============================================================ */
console.log('\n[5.5] api.js（live 能力·静态断言）');
const apiSrc = fs.readFileSync(path.join(ASSETS, 'api.js'), 'utf8');
ok(apiSrc.indexOf('EventSource') >= 0, 'api.js 实现 live SSE（EventSource）');
ok(apiSrc.indexOf('/api/runs/') >= 0, 'api.js 对接后端 REST（/api/runs/）');
ok(apiSrc.indexOf("on('step'") >= 0, 'api.js 归一化 step 事件');
ok(apiSrc.indexOf("on('conclusion'") >= 0, 'api.js 归一化 conclusion 事件');
ok(apiSrc.indexOf("on('degraded'") >= 0, 'api.js 归一化 degraded 事件（橙色特色）');
ok(apiSrc.indexOf('normalizeState') >= 0 && apiSrc.indexOf('normalizeProv') >= 0, 'api.js 提供状态/证据归一化');
ok(typeof API.ensureLoaded === 'function' && typeof API.loadRuns === 'function', 'api 提供 ensureLoaded/loadRuns（live 按需拉取）');
ok(API.isLive() === false, 'node 沙箱（无 location.search）默认仍为 mock');
for (const f of ['tokens.css', 'constants.js', 'store.js', 'api.js']) {
  ok(fs.existsSync(path.join(ASSETS, f)), 'B3 资产存在：assets/' + f);
}
ok(fs.existsSync(path.join(ASSETS, '..', 'README.md')), 'README.md 存在（B3-6）');

/* ============================================================
 * 汇总
 * ============================================================ */
console.log('\n────────────────────────────');
console.log(`PASS=${pass}  FAIL=${fails.length}`);
if (fails.length) { fails.forEach((f) => console.log('  FAIL: ' + f)); }
console.log('SMOKE_PASS =', fails.length === 0);
process.exit(fails.length === 0 ? 0 : 1);
