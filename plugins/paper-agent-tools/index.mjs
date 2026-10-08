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
 *
 * sciret_plan 支持 --workflow materials|research：research 工作流为六步
 * R1_search..R6_review，可继续经 sciret_run_step 单步驱动（同一状态机/账本）。
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
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

// ---------- 运行期配置自检（原先缺配置会静默退化成 ModuleNotFoundError）----------
//
// AGH 安装 file: 包时会把插件【拷贝】到
//   <用户目录>/.agh/data/profiles/<profile>/packages/<pkg-id>/
// 因此插件运行时已经【看不到】原项目目录，__dirname 指向拷贝点。
// 项目根只能靠 daemon 注入的环境变量传进来；缺了它，原先会退化成
// `python -m paper_agent.cli` → ModuleNotFoundError: No module named 'paper_agent'，
// 表面看像是"组件没装"，实际是"daemon 没带环境变量"——极易误诊。
// 这里改为在 spawn 之前就给出可执行的修复指引。
const CONFIG_HINT = [
  "运行期配置缺失：插件拿不到项目根。",
  "原因：AGH 会把插件拷贝到 ~/.agh/data/profiles/<profile>/packages/ 下运行，",
  "插件自身无法定位原项目目录，必须由 daemon 通过环境变量注入。",
  "修复：先停 daemon，在【启动 daemon 的那个终端】里设好下面两个变量，再启动 daemon：",
  '  paper-agent_PYTHON=<python 绝对路径，如 C:\\...\\Python312\\python.exe>',
  '  paper-agent_ROOT=<paper-agent 项目绝对路径>',
  "注意：daemon 若已在运行，必须 stop 后用带变量的环境重新 start，否则老 daemon 会复用旧环境。",
].join("\n");

/** 解析并校验运行期配置；不合法时返回带指引的错误对象。 */
function resolveRuntime() {
  const py = process.env["paper-agent_PYTHON"] || "python";
  const root = process.env["paper-agent_ROOT"];
  if (!root || !String(root).trim()) {
    return {
      ok: false,
      error: `${CONFIG_HINT}\n（当前 paper-agent_ROOT 未设置；插件实际运行于 ${__dirname}）`,
    };
  }
  const core = path.join(root, "core");
  if (!existsSync(path.join(core, "paper_agent"))) {
    return {
      ok: false,
      error: `${CONFIG_HINT}\n（paper-agent_ROOT=${root}，但 ${path.join(core, "paper_agent")} 不存在）`,
    };
  }
  return { ok: true, py, root };
}

function runCli(argv, timeoutMs = 120_000) {
  const cfg = resolveRuntime();
  if (!cfg.ok) return Promise.resolve({ ok: false, exitCode: -1, structured: { ok: false, error: cfg.error } });
  const root = cfg.root;
  const py = cfg.py;
  const env = curatedEnv(root);
  return new Promise((resolve) => {
    // windowsHide:true 防止 Windows 上每次调用工具都弹出一个命令行窗口。
    // daemon 以 DETACHED_PROCESS（无控制台）启动；子进程 python.exe 若不带
    // windowsHide 会自行分配一个新控制台 -> 每次 sciret_* 调用都会闪现一个
    // 终端窗口。与 web/server/paper-agent-server.js 的 spawn（已设 windowsHide:true）
    // 保持一致。
    const proc = spawn(py, argv, { env, cwd: root, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
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

/** 统一的工具执行器：调用 CLI，按 AGH 返回格式包装。
 *
 * MAINT-6：只读工具（sciret_status / sciret_cite）不透传 --chaos——
 * 读路径触发故障注入语义怪异（chaos 是写路径的故意设计，见各写工具 schema）。
 * allowChaos 由调用方按工具性质显式声明，默认 true 保持写路径行为不变。
 */
function makeRunner(argsOf, timeoutMs, { allowChaos = true } = {}) {
  return async function execute(ctx) {
    // 防御 H1：run_id 边界白名单校验（与 Python 侧 state.py 双保险）
    if (ctx.run_id !== undefined && !validateRunId(ctx.run_id)) {
      return wrap({ ok: false,
                    error: `invalid run_id ${String(ctx.run_id)}: must match ^run-[\\w-]+$` });
    }
    const chaos = allowChaos
      ? ((ctx.chaos && String(ctx.chaos).trim()) || undefined)
      : undefined;
    const argv = cliArgs(argsOf(ctx), chaos);
    const r = await runCli(argv, timeoutMs);
    return wrap(r.structured ?? r);
  };
}

// ---------- 7 工具定义 ----------
const TOOLS = [
  {
    name: "sciret_plan",
    description: "Plan a new pipeline run: create isolated run instance with a step state machine and append-only ledgers. workflow=research runs the six-step R1_search..R6_review pipeline (default); workflow=materials runs the five-step P1_lit_search..P5_report pipeline.",
    parameters: objectSchema(
      {
        goal: str("research goal / query text"),
        workflow: optStr("materials | research (omit for research default)"),
        chaos: optStr(CHAOS_DESC),
      },
      ["goal"],
    ),
    // MAINT-7：costHint.wallMs 必须等于实际生效的超时。plan 的 makeRunner
    // 未传 timeoutMs → 走 runCli 默认 120_000ms（:146），声明值原为 10_000，
    // 与生效值不符。此处把声明对齐为生效值（不改变任何运行行为）。
    meta: writeMeta("never", 120_000),
    execute: makeRunner((c) => {
      const a = ["plan", "--goal", c.goal];
      if (c.workflow) a.push("--workflow", c.workflow);
      return a;
    }),
  },
  {
    name: "sciret_run_step",
    description: "Run a single pipeline step for a given run (idempotent reuse for terminal steps). materials steps: P1_lit_search|P2_clean_data|P3_run_experiment|P4_verify|P5_report; research steps: R1_search|R2_read|R3_analyze|R4_verify|R5_write|R6_review.",
    parameters: objectSchema(
      {
        run_id: str("run instance id, e.g. run-YYYYMMDD-HHMMSS-xxxxxx"),
        step: str("P1_lit_search|P2_clean_data|P3_run_experiment|P4_verify|P5_report|R1_search|R2_read|R3_analyze|R4_verify|R5_write|R6_review"),
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
      { run_id: str("run instance id") },
      ["run_id"],
    ),
    meta: READONLY_META,
    // MAINT-6：只读工具不暴露/不透传 chaos（allowChaos:false）
    execute: makeRunner((c) => ["status", "--run", c.run_id], 120_000, { allowChaos: false }),
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
      },
      ["run_id"],
    ),
    meta: READONLY_META,
    // MAINT-6：只读工具不暴露/不透传 chaos（allowChaos:false）
    execute: makeRunner((c) => {
      const a = ["cite", "--run", c.run_id];
      if (c.ev) a.push("--ev", c.ev);
      return a;
    }, 120_000, { allowChaos: false }),
  },
  {
    name: "sciret_resume",
    // MAINT-3：对齐 B1 后真实语义——FAILED run 整体 resume 幂等早退，
    // 重试失败步骤应改用 sciret_run_step（FAILED→RUNNING 合法转移）。
    description: "Resume a run (breakpoint continue). RUNNING run: executes PENDING/FAILED steps, DONE/SKIPPED reused. Terminal run (DONE/FAILED): idempotent early-return reusing artifacts (FAILED runs list failed_steps — retry individual failed steps via sciret_run_step instead).",
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
