/**
 * paper-agent AGH hot-tool plugin — 薄壳层（文档 §4.8）。
 *
 * 设计原则（分层解耦红线）：
 *  - JS 仅做参数序列化 + 子进程调用 + 结果包装；全部科研业务在 Python CLI
 *  - 通过环境变量注入：paper-agent_PYTHON（解释器）、paper-agent_ROOT（项目根）
 *  - 严格遵循 AGH hot-tool-plugin 范式；如与官方示例冲突，以官方
 *    examples/hot-tool-plugin 与 develop/backend.md 为准（§8 第4条）
 *
 * 7 工具：sciret_plan / sciret_run_step / sciret_status / sciret_verify
 *         / sciret_report / sciret_cite / sciret_resume
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KIND = Symbol.for("TypeBox.Kind");

// ---------- TypeBox schema helpers（对齐 AGH 标准写法）----------
function objectSchema(properties, required = []) {
  return {
    [KIND]: "Object",
    type: "object",
    properties,
    required,
    additionalProperties: false,
  };
}
const str = (desc = "") => ({ [KIND]: "String", type: "string", description: desc });
const optStr = (desc = "") => ({ [KIND]: "String", type: "string", description: desc });

// chaos 模式取值（可选；缺省 = 正常路径）
const CHAOS_DESC =
  "chaos injection mode: p1_fail_first | p1_fail_all | kill_after_p2 | mutate_summary (omit for normal path)";

// ---------- AGH 工具返回包装 ----------
function wrap(resultObj) {
  const text = JSON.stringify(resultObj);
  return { content: [{ type: "text", text }], structured: resultObj };
}

// ---------- 工具 meta（AGH checkToolMeta 要求 8 键齐全；replay 按各工具真实语义声明） ----------
const READONLY_META = {
  isReadOnly: true,
  isDestructive: false,
  isConcurrencySafe: true,
  isOpenWorld: false,
  replay: "safe",
  costHint: { wallMs: 5_000 },
  deferLoading: false,
  requiresApproval: "never",
};
// 写工具：产物只写本项目 runs/ 隔离目录，非破坏性；幂等性由状态机终态守卫保证。
// 防御 M4：写类工具由 requiresApproval:"never" 收紧为 "destructive"——
// 模型驱动路径下写操作需人工审批；注意若 AGH approvals.mode 被设为 off
// 仍会被旁路（宿主配置责任，见 AGH security.md）。
const writeMeta = (replay, wallMs) => ({
  isReadOnly: false,
  isDestructive: false,
  isConcurrencySafe: false,
  isOpenWorld: false,
  replay,
  costHint: { wallMs },
  deferLoading: false,
  requiresApproval: "destructive",
});

// 防御 H1（边界校验）：run_id 来自不可信输入（LLM 工具参数），在 spawn 前先做
// 白名单校验，与 Python 侧 state.py 的强校验形成双保险。
function validateRunId(runId) {
  return typeof runId === "string" && /^run-[\w-]+$/.test(runId);
}

// ---------- spawn Python CLI（薄壳核心）----------
function cliArgs(args, chaos) {
  const out = ["-m", "paper_agent.cli"];
  for (const a of args) out.push(a);
  if (chaos) out.push("--chaos", chaos);
  return out;
}

// 防御 M5（最小环境变量）：Python 核心为纯标准库实现，仅需项目约定变量与 PATH。
// 原 `{ ...process.env }` 把整份环境（含 AGNES_* / LLM API key / 各类 secret）透传
// 给子进程，提示注入一旦诱导出站请求即可外泄密钥。现改为显式白名单。
const ENV_ALLOWLIST = [
  "PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "SYSTEMDRIVE", "WINDIR",
  "LANG", "LC_ALL", "TMP", "TEMP", "TMPDIR",
  "paper-agent_PYTHON", "paper-agent_ROOT", "paper-agent_LIT_SOURCE",
];

function curatedEnv(root) {
  const env = {};
  for (const k of ENV_ALLOWLIST) {
    if (process.env[k] !== undefined) env[k] = process.env[k];
  }
  env["paper-agent_ROOT"] = root;
  env["PYTHONPATH"] = path.join(root, "core");
  return env;
}

function runCli(argv, timeoutMs = 120_000) {
  const py = process.env["paper-agent_PYTHON"] || "python";
  const root = process.env["paper-agent_ROOT"] || __dirname;
  const env = curatedEnv(root);
  return new Promise((resolve) => {
    const proc = spawn(py, argv, { env, cwd: root, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => proc.kill("SIGKILL"), timeoutMs);
    proc.stdout.on("data", (d) => (stdout += d));
    proc.stderr.on("data", (d) => (stderr += d));
    proc.on("close", (code) => {
      clearTimeout(timer);
      let parsed = null;
      try {
        parsed = stdout ? JSON.parse(stdout) : null;
      } catch {
        parsed = { ok: false, error: `non-JSON stdout: ${stdout || "(empty)"}` };
      }
      resolve({
        ok: code === 0 && !!(parsed && parsed.ok !== false),
        exitCode: code,
        structured: parsed,
        stderr: stderr.trim() || undefined,
      });
    });
    proc.on("error", (err) => {
      clearTimeout(timer);
      resolve({ ok: false, exitCode: -1, structured: { ok: false, error: err.message } });
    });
  });
}

/** 统一的工具执行器：调用 CLI，按 AGH 返回格式包装。 */
function makeRunner(argsOf, timeoutMs) {
  return async function execute(ctx) {
    // 防御 H1：run_id 边界白名单校验（与 Python 侧 state.py 双保险）
    if (ctx.run_id !== undefined && !validateRunId(ctx.run_id)) {
      return wrap({ ok: false,
                    error: `invalid run_id ${String(ctx.run_id)}: must match ^run-[\\w-]+$` });
    }
    const chaos = (ctx.chaos && String(ctx.chaos).trim()) || undefined;
    const argv = cliArgs(argsOf(ctx), chaos);
    const r = await runCli(argv, timeoutMs);
    return wrap(r.structured ?? r);
  };
}

// ---------- 7 工具定义 ----------
const TOOLS = [
  {
    name: "sciret_plan",
    description: "Plan a new research pipeline run: create isolated run instance with 5-step state machine and append-only ledgers.",
    parameters: objectSchema(
      { goal: str("research goal / query text"), chaos: optStr(CHAOS_DESC) },
      ["goal"],
    ),
    meta: writeMeta("never", 10_000),
    execute: makeRunner((c) => ["plan", "--goal", c.goal]),
  },
  {
    name: "sciret_run_step",
    description: "Run a single pipeline step P1..P5 for a given run (idempotent reuse for terminal steps).",
    parameters: objectSchema(
      {
        run_id: str("run instance id, e.g. run-YYYYMMDD-HHMMSS-xxxxxx"),
        step: str("P1_lit_search|P2_clean_data|P3_run_experiment|P4_verify|P5_report"),
        chaos: optStr(CHAOS_DESC),
      },
      ["run_id", "step"],
    ),
    meta: writeMeta("idempotent", 180_000),
    execute: makeRunner((c) => ["run-step", "--run", c.run_id, "--step", c.step], 180_000),
  },
  {
    name: "sciret_status",
    description: "Read-only: return current run/step status, attempts, and degraded flag for a run.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: READONLY_META,
    execute: makeRunner((c) => ["status", "--run", c.run_id]),
  },
  {
    name: "sciret_verify",
    description: "P4 reproducibility verification: re-run experiment to isolated dir and run 5 tolerance checks.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: writeMeta("idempotent", 180_000),
    execute: makeRunner((c) => ["verify", "--run", c.run_id], 180_000),
  },
  {
    name: "sciret_report",
    description: "P5 report generation: build report.md from real artifacts with bound evidence IDs.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: writeMeta("idempotent", 30_000),
    execute: makeRunner((c) => ["report", "--run", c.run_id]),
  },
  {
    name: "sciret_cite",
    description: "Read-only: resolve evidence citation (DOI/author/year for literature; sha256 prefix for artifacts).",
    parameters: objectSchema(
      {
        run_id: str("run instance id"),
        ev: optStr("EV-XXXX evidence id; omit to list all evidence"),
        chaos: optStr(CHAOS_DESC),
      },
      ["run_id"],
    ),
    meta: READONLY_META,
    execute: makeRunner((c) => {
      const a = ["cite", "--run", c.run_id];
      if (c.ev) a.push("--ev", c.ev);
      return a;
    }),
  },
  {
    name: "sciret_resume",
    description: "Resume a run (breakpoint continue): only PENDING/FAILED steps execute; DONE/SKIPPED reused.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: writeMeta("idempotent", 180_000),
    execute: makeRunner((c) => ["resume", "--run", c.run_id], 180_000),
  },
];

// ---------- AGH 扩展入口（官方 Cordis 对象插件范式，对齐 examples/hot-tool-plugin） ----------
export const paperAgentTools = {
  inject: ["extension"],
  apply(ctx) {
    const agnes = ctx.extension();
    for (const t of TOOLS) {
      agnes.registerTool({
        name: t.name,
        description: t.description,
        parameters: t.parameters,
        meta: t.meta,
        execute: t.execute,
      });
    }
  },
};
