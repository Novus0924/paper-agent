#!/usr/bin/env node
/**
 * tools/verify-plugin-e2e.mjs — 插件端到端自检（真调 Python CLI，但**不经过 AGH**）
 *
 * 用途：不需要 AGH、不需要 daemon、不需要 TTY、不需要联网。
 *       它把插件当普通 ES 模块加载，捕获 `registerTool` 注册上来的工具，
 *       然后**真的调用 execute()**（内部 spawn Python CLI），验证"薄壳 → Python 核心"
 *       这条链路是通的。
 *
 * 与 verify-plugin-offline.mjs 的分工：
 *   offline = 静态契约（工具面/8 键 meta/schema/零依赖）——不跑 Python
 *   e2e     = 真实调用链路（plan → status → cite + 边界拦截）——真跑 Python
 *
 * 覆盖的断言：
 *   1. Python 解释器可用、且能导入 core/paper_agent
 *   2. sciret_plan    → ok:true 且拿到合法 run_id
 *   3. sciret_status  → ok:true（读回刚建的 run）
 *   4. sciret_cite    → ok:true（证据回查通道可用）
 *   5. H1 边界：非法 run_id 被拦（且**不落到 spawn**）
 *      对照组：同一时刻把解释器换成不存在的路径 —— 合法 run_id 报 "cannot launch python"，
 *      非法 run_id 仍报 "invalid run_id"。两者并存才能证明 H1 真的是**短路**而非巧合。
 *
 * 用法（在仓库根目录）：
 *   node tools/verify-plugin-e2e.mjs
 *   node tools/verify-plugin-e2e.mjs --cleanup     # 跑完删掉本次自检创建的 run 目录
 *   PAPER_AGENT_PYTHON=/abs/path/python node tools/verify-plugin-e2e.mjs
 *
 * 退出码：0 = 全部通过；1 = 有失败项。
 */
import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.PAPER_AGENT_ROOT || process.env["paper-agent_ROOT"] || path.resolve(__dirname, "..");
const PLUGIN_ENTRY = path.join(ROOT, "plugins", "paper-agent-tools", "index.mjs");
const CORE_DIR = path.join(ROOT, "core");

const CLEANUP = process.argv.includes("--cleanup");
const AS_JSON = process.argv.includes("--json");

// ---------- 解释器解析：环境变量优先，否则按平台常见命名 ----------
function resolvePython() {
  const explicit = process.env.PAPER_AGENT_PYTHON || process.env["paper-agent_PYTHON"];
  if (explicit && explicit.trim()) return explicit.trim();
  return process.platform === "win32" ? "python" : "python3";
}
const PY = resolvePython();

// 把解析结果写回插件读得到的变量名，保证插件与自检"看到同一个解释器"
process.env["paper-agent_PYTHON"] = PY;
process.env["PAPER_AGENT_PYTHON"] = PY;
process.env["paper-agent_ROOT"] = ROOT;
process.env["PAPER_AGENT_ROOT"] = ROOT;
// 自检只跑 plan/status/cite（不执行任何 step），因此不需要联网；
// 仍显式钉死为离线源，避免将来有人误加 step 调用时静默打外网。
process.env["paper-agent_LIT_SOURCE"] = "local";

// ---------- 迷你断言框架 ----------
const results = [];
function record(id, title, ok, detail = "") {
  results.push({ id, title, ok: !!ok, detail: String(detail || "") });
  return !!ok;
}
function report(id, title, fn) {
  try {
    const r = fn();
    if (r === true || r === undefined) return record(id, title, true);
    if (r && typeof r === "object") return record(id, title, r.ok, r.detail);
    return record(id, title, false, "检查函数返回了非真值");
  } catch (err) {
    return record(id, title, false, `${err?.name || "Error"}: ${err?.message || err}`);
  }
}
const preview = (s, n = 300) => {
  const t = String(s ?? "");
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

// ---------- 0. 预检：Python 与核心模块 ----------
/** 异步跑一次解释器（与插件的 spawn 写法一致；不用 spawnSync，避免个别
 *  受限环境把同步建进程直接判 EBUSY）。 */
function probePython(py, timeoutMs = 30_000) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(py, ["-c", "import sys; import paper_agent; print(sys.version.split()[0])"], {
        cwd: ROOT,
        env: { ...process.env, PYTHONPATH: CORE_DIR },
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (err) {
      resolve({ ok: false, code: err?.code || err?.name, message: err?.message || String(err) });
      return;
    }
    let stdout = "", stderr = "";
    const timer = setTimeout(() => { try { child.kill("SIGKILL"); } catch { /* ignore */ } }, timeoutMs);
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, code: err?.code || err?.name, message: err?.message || String(err) });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout: stdout.trim(), stderr: stderr.trim() });
    });
  });
}

const pre = await probePython(PY);
const pythonOk = report("python.available", `Python 解释器可用且能导入 core/paper_agent（${PY}）`, () => {
  if (!pre.ok) {
    if (pre.code === "ENOENT" || /not found|No such file/i.test(String(pre.message))) {
      return { ok: false, detail: `${pre.code}: 解释器不存在或不在 PATH（可用 PAPER_AGENT_PYTHON 指定绝对路径）` };
    }
    return { ok: false, detail: `${pre.code}: ${preview(pre.message || pre.stderr, 400)}` };
  }
  return { ok: true, detail: `Python ${pre.stdout}；core=${CORE_DIR}` };
});

// ---------- 1. 加载插件并捕获工具 ----------
const tools = new Map();
let mod = null;
try {
  mod = await import(`${pathToFileURL(PLUGIN_ENTRY).href}?v=${Date.now()}`);
} catch (err) {
  mod = null;
  record("plugin.load", "加载插件并捕获 registerTool 注册的工具",
    false, `${err?.name || "Error"}: ${err?.message || err}`);
}
if (mod) {
  const captured = [];
  const ctx = {
    extension: () => ({
      registerTool: (t) => captured.push(t),
      ctx: { log: { info() {}, warn() {}, error() {} } },
    }),
    skills: { register() {} },
  };
  let applyErr = "";
  try {
    mod.paperAgentTools.apply(ctx);
  } catch (err) {
    applyErr = `${err?.name || "Error"}: ${err?.message || err}`;
  }
  for (const t of captured) tools.set(t.name, t);
  report("plugin.load", "加载插件并捕获 registerTool 注册的工具", () => {
    if (applyErr) return { ok: false, detail: `apply() 抛错：${applyErr}` };
    if (tools.size === 0) return { ok: false, detail: "没有捕获到任何工具" };
    return { ok: true, detail: `${tools.size} 个工具` };
  });
}

// 统一的调用助手：把 AGH 的包装结构剥开，返回 structured + 原始 content 文本
async function call(toolName, args) {
  const t = tools.get(toolName);
  if (!t) throw new Error(`工具未注册：${toolName}`);
  const res = await t.execute(args);
  const structured = res?.structured ?? null;
  const text = res?.content?.[0]?.text ?? "";
  return { structured, text, res };
}

let createdRunId = "";
const canRun = pythonOk && tools.size > 0;

if (canRun) {
// ---------- 2. plan ----------
let planStructured = null;
await reportAsync("tool.sciret_plan", "sciret_plan 建 run 并返回合法 run_id（真调 Python）", async () => {
  const { structured, text } = await call("sciret_plan", {
    goal: "verify-plugin-e2e 冒烟：硫化物固态电解质离子电导率排序",
  });
  planStructured = structured;
  if (!structured) return { ok: false, detail: `无 structured 返回；text=${preview(text)}` };
  if (structured.ok !== true) return { ok: false, detail: `ok!=true：${preview(JSON.stringify(structured))}` };
  const rid = String(structured.run_id || "");
  if (!/^run-[\w-]+$/.test(rid)) return { ok: false, detail: `run_id 不合规：${JSON.stringify(rid)}` };
  createdRunId = rid;
  return { ok: true, detail: `run_id=${rid} status=${structured.run_status} workflow=${structured.workflow}` };
});

// ---------- 3. status ----------
await reportAsync("tool.sciret_status", "sciret_status 能读回刚建的 run", async () => {
  if (!createdRunId) return { ok: false, detail: "上一步未拿到 run_id，跳过" };
  const { structured, text } = await call("sciret_status", { run_id: createdRunId });
  if (!structured) return { ok: false, detail: `无 structured 返回；text=${preview(text)}` };
  if (structured.ok !== true) return { ok: false, detail: `ok!=true：${preview(JSON.stringify(structured))}` };
  return { ok: true, detail: `run_status=${structured.run_status ?? "(未提供)"}` };
});

// ---------- 4. cite ----------
await reportAsync("tool.sciret_cite", "sciret_cite 证据回查通道可用", async () => {
  if (!createdRunId) return { ok: false, detail: "上一步未拿到 run_id，跳过" };
  const { structured, text } = await call("sciret_cite", { run_id: createdRunId });
  if (!structured) return { ok: false, detail: `无 structured 返回；text=${preview(text)}` };
  if (structured.ok !== true) return { ok: false, detail: `ok!=true：${preview(JSON.stringify(structured))}` };
  return { ok: true };
});

// ---------- 5. H1 边界 + 对照组 ----------
await reportAsync("guard.h1.runid", "H1 边界：非法 run_id 被拦，且不外泄到 spawn", async () => {
  const goodPython = PY;
  // 把解释器换成绝对不存在的路径，构造"若真去 spawn 必然报 cannot launch python"的环境
  const bogus = process.platform === "win32"
    ? "C:/__no_such_python__/python.exe"
    : "/__no_such_python__/python3";

  const badIds = ["../../etc/passwd", "run-$(whoami)", "run-a; rm -rf /"];
  const problems = [];
  try {
    process.env["paper-agent_PYTHON"] = bogus;
    process.env["PAPER_AGENT_PYTHON"] = bogus;

    for (const bad of badIds) {
      const { structured } = await call("sciret_status", { run_id: bad });
      const err = String(structured?.error || "");
      if (structured?.ok !== false) problems.push(`${JSON.stringify(bad)} 竟然没被拒（ok=${structured?.ok}）`);
      else if (!err.includes("invalid run_id")) problems.push(`${JSON.stringify(bad)} 的报错不含 invalid run_id：${preview(err, 120)}`);
    }

    // 对照组：同一 bogus 环境 + 合法 run_id → 必须报"无法启动解释器"
    const ctrl = await call("sciret_status", { run_id: createdRunId || "run-20260101-000000-abcdef" });
    const ctrlErr = String(ctrl.structured?.error || "");
    if (!ctrlErr.includes("cannot launch python")) {
      problems.push(`对照组未出现 cannot launch python（说明 H1 断言不可靠）：${preview(ctrlErr, 160)}`);
    }
  } finally {
    process.env["paper-agent_PYTHON"] = goodPython;
    process.env["PAPER_AGENT_PYTHON"] = goodPython;
  }

  return problems.length
    ? { ok: false, detail: problems.join(" | ") }
    : { ok: true, detail: `拦下 ${badIds.length} 种恶意 run_id；对照组确认短路（未落到 spawn）` };
});
} else {
  record("tool.sciret_plan", "sciret_plan 建 run 并返回合法 run_id（真调 Python）", false, "前置条件不满足，跳过");
  record("tool.sciret_status", "sciret_status 能读回刚建的 run", false, "前置条件不满足，跳过");
  record("tool.sciret_cite", "sciret_cite 证据回查通道可用", false, "前置条件不满足，跳过");
  record("guard.h1.runid", "H1 边界：非法 run_id 被拦，且不外泄到 spawn", false, "前置条件不满足，跳过");
}

/** report() 的异步版本（execute 是 async）。 */
async function reportAsync(id, title, fn) {
  try {
    const r = await fn();
    if (r === true || r === undefined) return record(id, title, true);
    if (r && typeof r === "object") return record(id, title, r.ok, r.detail);
    return record(id, title, false, "检查函数返回了非真值");
  } catch (err) {
    return record(id, title, false, `${err?.name || "Error"}: ${err?.message || err}`);
  }
}

// ---------- 清理（可选） ----------
const runDir = createdRunId ? path.join(ROOT, "runs", createdRunId) : "";
let cleanupNote = "";
if (CLEANUP && runDir) {
  // 只删本次自检自己创建的那一个 run 目录，且必须严格落在 runs/ 下、目录名等于 run_id
  const insideRuns = path.dirname(path.resolve(runDir)) === path.resolve(ROOT, "runs");
  if (insideRuns && path.basename(path.resolve(runDir)) === createdRunId && existsSync(runDir)) {
    try {
      rmSync(runDir, { recursive: true, force: true });
      cleanupNote = `已清理 ${runDir}`;
    } catch (err) {
      cleanupNote = `清理失败（保留原状）：${err?.message || err}`;
    }
  } else {
    cleanupNote = `跳过清理（路径校验未通过）：${runDir}`;
  }
}

// ---------- 输出 ----------
const failed = results.filter((r) => !r.ok);
const pad = (s, n) => String(s).padEnd(n, " ");

if (AS_JSON) {
  console.log(JSON.stringify({
    ok: failed.length === 0,
    root: ROOT,
    python: PY,
    tools_captured: tools.size,
    run_id: createdRunId || null,
    cleanup: cleanupNote || null,
    checks: results,
  }, null, 2));
} else {
  console.log("paper-agent 插件端到端自检（真调 Python CLI，但绕过 AGH；无需 daemon / TTY / 联网）");
  console.log(`仓库根:   ${ROOT}`);
  console.log(`解释器:   ${PY}`);
  console.log(`插件入口: ${PLUGIN_ENTRY}`);
  console.log("-".repeat(72));
  for (const r of results) {
    console.log(`${r.ok ? "PASS" : "FAIL"}  ${pad(r.id, 22)} ${r.title}`);
    if (r.detail) console.log(`      ${r.ok ? "→" : "✗"} ${preview(r.detail, 400)}`);
  }
  console.log("-".repeat(72));
  if (createdRunId) console.log(`本次自检创建的 run: runs/${createdRunId}${CLEANUP ? "" : "（用 --cleanup 可自动删除）"}`);
  if (cleanupNote) console.log(cleanupNote);
  if (failed.length === 0) {
    console.log(`结果: 全部通过（${results.length} 项）— 薄壳 → Python 核心链路已打通。`);
    console.log("→ 说明插件与 Python 核心都没问题。若 AGH 会话里仍不可用，请查 AGH 侧：环境变量、daemon 启动 cwd、trust/enable。");
  } else {
    console.log(`结果: 失败 ${failed.length}/${results.length} 项 — ${failed.map((r) => r.id).join(", ")}`);
    console.log("→ 链路未打通，按上方 FAIL 详情逐条排查（多数是解释器路径或 core/ 位置问题）。");
  }
}

process.exit(failed.length === 0 ? 0 : 1);
