#!/usr/bin/env node
/**
 * tools/verify-plugin-offline.mjs — 插件静态自检（离线）
 *
 * 用途：**不需要 AGH、不需要 daemon、不需要联网、不需要 TTY**，直接加载
 *       `plugins/paper-agent-tools/index.mjs`，用一个假的 AGH ctx 触发 `apply()`，
 *       把注册上来的工具逐个按 AGH 真实规则体检。
 *
 * 为什么有价值：它是"插件坏了"与"AGH 配置错了"的分界线。
 *   本脚本通过 → 插件本身没问题，问题在 AGH 侧（环境变量 / daemon cwd / trust）。
 *   本脚本失败 → 插件本身有问题，先修插件再看 AGH。
 *
 * 校验规则来源（不是猜的，逐条对齐 AGH 源码 packages/cli/dist/local/agnes.mjs）：
 *   - `checkToolMeta`（约 16217 行）：8 个必填 meta 键、布尔字段类型、
 *     replay ∈ {safe,never,idempotent}、costHint 形状、requiresApproval ∈ {never,destructive,always}
 *   - `TOOL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/`
 *   - `TOOL_DESCRIPTION_MAX_LENGTH = 4096`
 *   - `TOOL_PARAMETERS_MAX_BYTES = 262144`、`TOOL_PARAMETERS_MAX_DEPTH = 32`
 *
 * 用法（在仓库根目录）：
 *   node tools/verify-plugin-offline.mjs
 *   node tools/verify-plugin-offline.mjs --json      # 机器可读输出
 *   EXPECTED_TOOL_COUNT=20 node tools/verify-plugin-offline.mjs
 *
 * 退出码：0 = 全部通过；1 = 有失败项。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PLUGIN_DIR = path.join(ROOT, "plugins", "paper-agent-tools");
const PLUGIN_ENTRY = path.join(PLUGIN_DIR, "index.mjs");
const PLUGIN_PKG = path.join(PLUGIN_DIR, "package.json");

// ---------- AGH 侧的真实常量（与上面源码注释逐条对应） ----------
const KIND = Symbol.for("TypeBox.Kind");
const TOOL_META_KEYS = [
  "isReadOnly", "isDestructive", "isConcurrencySafe", "isOpenWorld",
  "replay", "costHint", "deferLoading", "requiresApproval",
];
const REPLAY = new Set(["safe", "never", "idempotent"]);
const RISK = new Set(["never", "destructive", "always"]);
const TOOL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const TOOL_DESCRIPTION_MAX_LENGTH = 4096;
const TOOL_PARAMETERS_MAX_BYTES = 262144;
const TOOL_PARAMETERS_MAX_DEPTH = 32;
const COST_HINT_KEYS = new Set(["credits", "wallMs"]);

// 期望工具数（改动插件时同步 +1/-1，或用环境变量临时覆盖）
const EXPECTED_TOOL_COUNT = Number(process.env.EXPECTED_TOOL_COUNT || 20);

const AS_JSON = process.argv.includes("--json");

// ---------- 迷你断言框架 ----------
const results = [];
function check(id, title, fn) {
  let ok = false, detail = "", fatal = false;
  try {
    const r = fn();
    if (r === true || r === undefined) { ok = true; detail = ""; }
    else if (r && typeof r === "object") { ok = !!r.ok; detail = r.detail || ""; }
    else { ok = false; detail = "检查函数返回了非真值"; }
  } catch (err) {
    ok = false;
    fatal = true;
    detail = `${err?.name || "Error"}: ${err?.message || err}`;
  }
  results.push({ id, title, ok, detail, fatal });
  return ok;
}
const list = (xs) => (xs || []).join(", ") || "(空)";
const preview = (s, n = 120) => {
  const t = String(s ?? "");
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

/** 复刻 AGH checkToolMeta —— 返回问题列表（空数组 = 通过）。 */
function checkToolMetaMirror(meta) {
  const problems = [];
  if (typeof meta !== "object" || meta === null) return ["meta: expected object"];
  for (const k of TOOL_META_KEYS) {
    if (!Object.hasOwn(meta, k)) problems.push(`missing key: ${k}`);
  }
  if (problems.length) return problems;
  for (const k of ["isReadOnly", "isDestructive", "isConcurrencySafe", "isOpenWorld"]) {
    if (typeof meta[k] !== "boolean") problems.push(`${k}: expected boolean`);
  }
  if (!REPLAY.has(String(meta.replay))) {
    problems.push(`replay: expected safe | never | idempotent (got ${JSON.stringify(meta.replay)})`);
  }
  const cost = meta.costHint;
  if (cost !== undefined) {
    if (typeof cost !== "object" || cost === null || Array.isArray(cost)) {
      problems.push("costHint: expected { credits?: number; wallMs?: number } | undefined");
    } else {
      for (const k of ["credits", "wallMs"]) {
        const v = cost[k];
        if (v !== undefined && (typeof v !== "number" || !Number.isFinite(v))) {
          problems.push(`costHint.${k}: expected finite number | undefined`);
        }
      }
      const extra = Object.keys(cost).filter((k) => !COST_HINT_KEYS.has(k));
      if (extra.length) problems.push(`costHint: unknown key ${list(extra)}`);
    }
  }
  if (meta.deferLoading !== undefined && typeof meta.deferLoading !== "boolean") {
    problems.push("deferLoading: expected boolean | undefined");
  }
  if (meta.requiresApproval !== undefined && !RISK.has(String(meta.requiresApproval))) {
    problems.push(`requiresApproval: expected never | destructive | always (got ${JSON.stringify(meta.requiresApproval)})`);
  }
  return problems;
}

/** 递归求 JSON 结构最大深度（Symbol 键不参与，与 AGH 一致按可序列化结构算）。 */
function depthOf(v, d = 0) {
  if (v === null || typeof v !== "object") return d;
  const vals = Array.isArray(v) ? v : Object.values(v);
  if (vals.length === 0) return d + 1;
  return Math.max(...vals.map((x) => depthOf(x, d + 1)));
}

// ---------- 开始体检 ----------
let pkg = null, mod = null, registered = [], skills = [];

let loadError = "";
try {
  pkg = JSON.parse(readFileSync(PLUGIN_PKG, "utf8"));
  // 带 cache-bust 查询串，避免同一进程内二次 import 拿到旧模块
  mod = await import(`${pathToFileURL(PLUGIN_ENTRY).href}?v=${Date.now()}`);
} catch (err) {
  loadError = `${err?.name || "Error"}: ${err?.message || err}`;
}

const pluginOk = check("module.load", "插件模块可加载且导出 paperAgentTools", () => {
  if (loadError) return { ok: false, detail: loadError };
  if (typeof pkg !== "object" || pkg === null) return { ok: false, detail: "package.json 缺失或不是合法 JSON" };
  const p = mod?.paperAgentTools;
  if (typeof p !== "object" || p === null) return { ok: false, detail: "未导出对象 paperAgentTools" };
  if (typeof p.apply !== "function") return { ok: false, detail: "paperAgentTools.apply 不是函数" };
  if (!Array.isArray(p.inject)) return { ok: false, detail: "paperAgentTools.inject 不是数组" };
  return { ok: true, detail: `导出 paperAgentTools（apply + inject），v${pkg.version ?? "?"}` };
});

// 模块没加载成功时，后续检查全部失去前提 —— 直接跳到报告，避免刷屏的次生错误。
// （下方 if 块内为保持与检查项一一对应，不做缩进；块尾有显式结束标记。）
if (pluginOk) {

check("plugin.package", "package.json 声明了 agnes.plugins（可执行插件入口）", () => {
  const p = pkg?.agnes?.plugins;
  if (!Array.isArray(p) || p.length === 0) return { ok: false, detail: "package.json 缺少 agnes.plugins 数组" };
  const first = p[0];
  const problems = [];
  if (first.export !== "paperAgentTools") problems.push(`export 应为 paperAgentTools，实际 ${JSON.stringify(first.export)}`);
  if (first.id !== "ext:paper-agent/tools") problems.push(`id 应为 ext:paper-agent/tools，实际 ${JSON.stringify(first.id)}`);
  return problems.length
    ? { ok: false, detail: list(problems) }
    : { ok: true, detail: `id=${first.id} export=${first.export} version=${pkg.version}` };
});

check("plugin.inject", "inject 与 package.json 声明一致且含 extension", () => {
  const injected = mod?.paperAgentTools?.inject;
  const declared = pkg?.agnes?.plugins?.[0]?.inject;
  const problems = [];
  if (!Array.isArray(injected)) problems.push("plugin.inject 不是数组");
  if (!Array.isArray(declared)) problems.push("package.json agnes.plugins[0].inject 不是数组");
  if (Array.isArray(injected) && Array.isArray(declared)) {
    const a = [...injected].sort().join(",");
    const b = [...declared].sort().join(",");
    if (a !== b) problems.push(`两处不一致：插件=${JSON.stringify(injected)} package.json=${JSON.stringify(declared)}`);
  }
  if (Array.isArray(injected) && !injected.includes("extension")) {
    problems.push("缺少 extension（工具注册 API 必需）");
  }
  return problems.length
    ? { ok: false, detail: list(problems) }
    : { ok: true, detail: `inject=${JSON.stringify(injected)}` };
});

// 用假 ctx 触发 apply()，把注册结果接出来
check("plugin.apply", "apply() 在假 ctx 下可完成注册（不依赖 AGH 运行时）", () => {
  const extensionApi = {
    registerTool: (t) => { registered.push(t); },
    ctx: { log: { info() {}, warn() {}, error() {} } },
    on: () => {}, // 触发插件的观测型钩子注册分支
  };
  const ctx = {
    extension: () => extensionApi,
    skills: { register: (s) => { skills.push(s); } },
  };
  mod.paperAgentTools.apply(ctx);
  return { ok: true, detail: `${registered.length} 工具 + ${skills.length} skill` };
});

check("tools.count", `注册工具数 = ${EXPECTED_TOOL_COUNT}`, () => (
  registered.length === EXPECTED_TOOL_COUNT
    ? { ok: true, detail: String(registered.length) }
    : { ok: false, detail: `实际 ${registered.length}（若本次改动确实增删了工具，请同步 EXPECTED_TOOL_COUNT 与文档）` }
));

check("tools.names", "工具名唯一、符合 AGH 命名规范、统一 sciret_ 前缀", () => {
  const problems = [];
  const seen = new Map();
  for (const t of registered) {
    const n = String(t?.name ?? "");
    if (!TOOL_NAME_PATTERN.test(n)) problems.push(`${JSON.stringify(n)} 不符合 ${TOOL_NAME_PATTERN}`);
    if (!n.startsWith("sciret_")) problems.push(`${n} 缺少 sciret_ 前缀`);
    if (seen.has(n)) problems.push(`重名：${n}`);
    seen.set(n, true);
  }
  return problems.length ? { ok: false, detail: list(problems) } : { ok: true, detail: `唯一 ${seen.size} 个` };
});

check("tools.description", `每个工具都有非空 description 且 ≤ ${TOOL_DESCRIPTION_MAX_LENGTH} 字符`, () => {
  const problems = [];
  for (const t of registered) {
    const d = t?.description;
    if (typeof d !== "string" || !d.trim()) problems.push(`${t?.name}: description 为空`);
    else if (d.length > TOOL_DESCRIPTION_MAX_LENGTH) problems.push(`${t?.name}: description ${d.length} 字符超限`);
  }
  return problems.length ? { ok: false, detail: list(problems) } : { ok: true };
});

check("tools.meta", "meta 8 键齐全且取值合法（镜像 AGH checkToolMeta）", () => {
  const problems = [];
  for (const t of registered) {
    for (const p of checkToolMetaMirror(t?.meta)) problems.push(`${t?.name}: ${p}`);
  }
  return problems.length ? { ok: false, detail: list(problems) } : { ok: true, detail: `${registered.length}/${registered.length} 通过` };
});

check("tools.meta.readonly_approval", "只读工具 requiresApproval=never 且 isReadOnly=true（回归守卫）", () => {
  const problems = [];
  for (const t of registered) {
    const m = t?.meta || {};
    if (m.isReadOnly === true && m.requiresApproval !== "never") {
      problems.push(`${t?.name}: isReadOnly=true 但 requiresApproval=${JSON.stringify(m.requiresApproval)}`);
    }
    if (m.isReadOnly === false && m.requiresApproval !== "destructive") {
      problems.push(`${t?.name}: 写工具 requiresApproval 应为 destructive，实际 ${JSON.stringify(m.requiresApproval)}`);
    }
  }
  return problems.length
    ? { ok: false, detail: list(problems) }
    : { ok: true, detail: "只读=never / 写=destructive" };
});

check("tools.parameters", "parameters 是合法 TypeBox Object schema（Kind/type/required/additionalProperties）", () => {
  const problems = [];
  for (const t of registered) {
    const p = t?.parameters;
    if (typeof p !== "object" || p === null) { problems.push(`${t?.name}: parameters 不是对象`); continue; }
    if (p[KIND] !== "Object") problems.push(`${t?.name}: ${String(KIND)} 应为 "Object"，实际 ${JSON.stringify(p[KIND])}`);
    if (p.type !== "object") problems.push(`${t?.name}: type 应为 "object"，实际 ${JSON.stringify(p.type)}`);
    if (typeof p.properties !== "object" || p.properties === null || Array.isArray(p.properties)) {
      problems.push(`${t?.name}: properties 应为对象`);
    }
    if (!Array.isArray(p.required)) problems.push(`${t?.name}: required 应为数组`);
    if (p.additionalProperties !== false) problems.push(`${t?.name}: additionalProperties 应为 false`);
    if (p.properties && Array.isArray(p.required)) {
      for (const r of p.required) {
        if (!Object.hasOwn(p.properties, r)) problems.push(`${t?.name}: required "${r}" 不在 properties 里`);
      }
      for (const [k, v] of Object.entries(p.properties)) {
        if (typeof v !== "object" || v === null) problems.push(`${t?.name}.${k}: 字段 schema 不是对象`);
        else if (typeof v.type !== "string") problems.push(`${t?.name}.${k}: 字段 schema 缺 type`);
      }
    }
    const bytes = Buffer.byteLength(JSON.stringify(p) ?? "", "utf8");
    if (bytes > TOOL_PARAMETERS_MAX_BYTES) problems.push(`${t?.name}: parameters ${bytes} 字节超过 ${TOOL_PARAMETERS_MAX_BYTES}`);
    const depth = depthOf(p);
    if (depth > TOOL_PARAMETERS_MAX_DEPTH) problems.push(`${t?.name}: parameters 深度 ${depth} 超过 ${TOOL_PARAMETERS_MAX_DEPTH}`);
  }
  return problems.length ? { ok: false, detail: list(problems) } : { ok: true, detail: `${registered.length}/${registered.length} 通过` };
});

check("tools.execute", "每个工具都挂载了可调用的 execute", () => {
  const problems = [];
  for (const t of registered) {
    if (typeof t?.execute !== "function") problems.push(`${t?.name}: execute 不是函数`);
  }
  return problems.length ? { ok: false, detail: list(problems) } : { ok: true };
});

check("skills.register", "注册了 sciret-research-pipeline Skill 且正文非空", () => {
  const s = skills.find((x) => x?.name === "sciret-research-pipeline");
  if (!s) return { ok: false, detail: `未注册该 Skill（已注册：${list(skills.map((x) => x?.name))}）` };
  if (typeof s.body !== "string" || s.body.trim().length < 100) return { ok: false, detail: "Skill 正文缺失或过短" };
  if (typeof s.description !== "string" || !s.description.trim()) return { ok: false, detail: "Skill 缺 description" };
  return { ok: true, detail: `${s.body.length} 字符` };
});

check("deps.thin", "薄壳零依赖：源码中的 import 全部是 node: 内置模块", () => {
  const src = readFileSync(PLUGIN_ENTRY, "utf8");
  const specs = new Set();
  for (const m of src.matchAll(/^\s*import\s[^;]*?from\s+["']([^"']+)["']/gm)) specs.add(m[1]);
  for (const m of src.matchAll(/import\(\s*["']([^"']+)["']\s*\)/g)) specs.add(m[1]);
  const bad = [...specs].filter((s) => !s.startsWith("node:"));
  return bad.length
    ? { ok: false, detail: `出现了非内置依赖：${list(bad)}` }
    : { ok: true, detail: list([...specs]) };
});

} // ← 结束 if (pluginOk)

// ---------- 输出 ----------
const failed = results.filter((r) => !r.ok);
const pad = (s, n) => String(s).padEnd(n, " ");

if (AS_JSON) {
  console.log(JSON.stringify({
    ok: failed.length === 0,
    plugin: { entry: PLUGIN_ENTRY, version: pkg?.version ?? null },
    registered_tools: registered.length,
    expected_tools: EXPECTED_TOOL_COUNT,
    skills: skills.map((s) => s?.name).filter(Boolean),
    checks: results,
  }, null, 2));
} else {
  console.log("paper-agent 插件静态自检（离线，无需 AGH / daemon / 联网 / TTY）");
  console.log(`插件入口: ${PLUGIN_ENTRY}`);
  console.log(`版本:     ${pkg?.version ?? "(未知)"}   期望工具数: ${EXPECTED_TOOL_COUNT}`);
  console.log("-".repeat(72));
  for (const r of results) {
    console.log(`${r.ok ? "PASS" : "FAIL"}  ${pad(r.id, 26)} ${r.title}`);
    if (r.detail) console.log(`      ${r.ok ? "→" : "✗"} ${preview(r.detail, 300)}`);
  }
  console.log("-".repeat(72));
  if (failed.length === 0) {
    console.log(`结果: 全部通过（${results.length} 项）；注册工具数 = ${registered.length}；Skill = ${list(skills.map((s) => s?.name))}`);
    console.log("→ 插件本身没有问题。若 AGH 会话里仍不可用，请查 AGH 侧：环境变量(paper-agent_ROOT/paper-agent_PYTHON)、daemon 启动 cwd、trust/enable 状态。");
  } else {
    console.log(`结果: 失败 ${failed.length}/${results.length} 项 — ${list(failed.map((r) => r.id))}`);
    console.log("→ 这是插件自身的问题，先修插件再看 AGH。");
  }
}

process.exit(failed.length === 0 ? 0 : 1);
