/**
 * paper-agent AGH hot-tool plugin — 薄壳层（文档 §4.8）。
 *
 * 设计原则（分层解耦红线）：
 *  - JS 仅做参数序列化 + 子进程调用 + 结果包装；全部科研业务在 Python CLI
 *  - 通过环境变量注入：paper-agent_PYTHON（解释器）、paper-agent_ROOT（项目根）
 *  - 严格遵循 AGH hot-tool-plugin 范式；如与官方示例冲突，以官方
 *    examples/hot-tool-plugin 与 develop/backend.md 为准（§8 第4条）
 *
 * 10 工具：
 *   流水线：sciret_plan / sciret_run_step / sciret_status / sciret_verify
 *          / sciret_report / sciret_cite / sciret_resume
 *   第二批（真实检索 + 判断）：sciret_search / sciret_freeze_prepare
 *          / sciret_freeze_commit
 */

import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const KIND = Symbol.for("TypeBox.Kind");

/** 读环境变量，同时兼容连字符与下划线两种写法。
 *  （连字符名在部分 shell 下无法 export，见 core/paper_agent/llm.py 的同类说明） */
function envAny(names) {
  for (const n of names) {
    const v = process.env[n];
    if (v && String(v).trim()) return String(v).trim();
  }
  return "";
}

/** 项目根：环境变量优先；未设置则由插件位置推导（plugins/paper-agent-tools → 上溯两级）。
 *  这样即便没有注入环境变量，插件也能正确定位 core/ 与 data/。 */
function projectRoot() {
  return envAny(["PAPER_AGENT_ROOT", "paper-agent_ROOT"])
    || path.resolve(__dirname, "..", "..");
}

/** Python 解释器：环境变量优先，否则用 PATH 上的 python。 */
function pythonExe() {
  return envAny(["PAPER_AGENT_PYTHON", "paper-agent_PYTHON"]) || "python";
}

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
const writeMeta = (replay, wallMs) => ({
  isReadOnly: false,
  isDestructive: false,
  isConcurrencySafe: false,
  isOpenWorld: false,
  replay,
  costHint: { wallMs },
  deferLoading: false,
  requiresApproval: "never",
});

// ---------- spawn Python CLI（薄壳核心）----------
function cliArgs(args, chaos) {
  const out = ["-m", "paper_agent.cli"];
  for (const a of args) out.push(a);
  if (chaos) out.push("--chaos", chaos);
  return out;
}

function runCli(argv, timeoutMs = 120_000) {
  const py = pythonExe();
  const root = projectRoot();
  const env = {
    ...process.env,
    "paper-agent_ROOT": root,
    PAPER_AGENT_ROOT: root,
    PYTHONPATH: path.join(root, "core"),
  };
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
    const chaos = (ctx.chaos && String(ctx.chaos).trim()) || undefined;
    const argv = cliArgs(argsOf(ctx), chaos);
    const r = await runCli(argv, timeoutMs);
    return wrap(r.structured ?? r);
  };
}

/** 把逗号分隔的字符串解析成数组（用于 ack 码）。 */
function csv(s) {
  return String(s || "").split(",").map((x) => x.trim()).filter(Boolean);
}

/** 解析检索式：优先 JSON 数组，退化为 "|" 分隔的字符串。 */
function parseQueries(s) {
  if (!s) return [];
  try {
    const v = JSON.parse(s);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return String(s).split("|").map((x) => x.trim()).filter(Boolean);
  }
}

/** 把裁决 JSON 写到临时文件，返回路径（CLI 的 --verdicts 需要文件）。 */
function writeVerdicts(verdicts) {
  const text = typeof verdicts === "string" ? verdicts : JSON.stringify(verdicts);
  JSON.parse(text); // 提前校验，避免把坏 JSON 传给子进程
  const dir = path.join(os.tmpdir(), "paper-agent-verdicts");
  mkdirSync(dir, { recursive: true });
  const p = path.join(dir, `verdicts-${process.pid}-${Date.now()}.json`);
  writeFileSync(p, text, "utf8");
  return p;
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

  // ---- 第二批：真实检索与冻结快照（判断由会话内模型给出）----

  {
    name: "sciret_search",
    description:
      "Network literature search over Crossref/OpenAlex METADATA only (never fetches full text). Returns candidate papers (DOI/title/authors/year/venue) for a research goal, so you can judge relevance.",
    parameters: objectSchema(
      {
        goal: str("research goal"),
        queries: optStr('optional JSON array of explicit queries, e.g. ["sulfide ionic conductivity"]; omit to derive from goal'),
        sources: optStr("comma-separated: crossref,openalex (default both)"),
        rows: optStr("results per query (default 10)"),
      },
      ["goal"],
    ),
    meta: READONLY_META,
    execute: makeRunner((c) => {
      const a = ["search", "--goal", c.goal];
      for (const q of parseQueries(c.queries)) a.push("--query", q);
      if (c.sources) a.push("--sources", c.sources);
      if (c.rows) a.push("--rows", String(c.rows));
      return a;
    }, 240_000),
  },

  {
    name: "sciret_freeze_prepare",
    description:
      "Prepare a frozen input snapshot: fetch both legs (literature + dataset) and return the objects awaiting YOUR judgment, namely the material families and a rule-based reference verdict for each. Does NOT write a snapshot yet — call sciret_freeze_commit after you decide.",
    parameters: objectSchema(
      {
        goal: str("research goal"),
        literature: optStr("bootstrap (offline, default) | network (live Crossref/OpenAlex search)"),
        rows: optStr("results per query when literature=network"),
      },
      ["goal"],
    ),
    meta: writeMeta("never", 300_000),
    execute: makeRunner((c) => {
      const a = ["freeze", "--goal", c.goal, "--prepare"];
      if (c.literature) a.push("--literature", c.literature);
      if (c.rows) a.push("--rows", String(c.rows));
      return a;
    }, 300_000),
  },

  {
    name: "sciret_freeze_commit",
    description:
      "Commit YOUR relevance judgments to freeze the snapshot. verdicts must cover EVERY family returned by sciret_freeze_prepare, each marked relevant or excluded with a reason. Judgments are recorded as auditable 'judgment'-tier evidence and never become conclusions. Anomalies (zero hits / no leg overlap / extreme hit-rate / self-contradiction) will halt the flow and must be explicitly acknowledged.",
    parameters: objectSchema(
      {
        pending_id: str("pending id returned by sciret_freeze_prepare"),
        verdicts: str('JSON object: {"queries":["..."],"families":{"<family>":{"verdict":"relevant|excluded","reason":"..."}}} — a flat map {"<family>":"relevant|excluded"} is also accepted'),
        model_name: optStr("your model identity, recorded in the audit trail"),
        ack: optStr("comma-separated anomaly codes you explicitly acknowledge (only after human review)"),
      },
      ["pending_id", "verdicts"],
    ),
    meta: writeMeta("never", 300_000),
    execute: makeRunner((c) => {
      const a = ["freeze", "--commit", c.pending_id,
                 "--verdicts", writeVerdicts(c.verdicts),
                 "--judged-by", "model"];
      if (c.model_name) a.push("--model-name", c.model_name);
      for (const code of csv(c.ack)) a.push("--ack", code);
      return a;
    }, 300_000),
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
