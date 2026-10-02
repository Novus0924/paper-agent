/**
 * paper-agent AGH hot-tool plugin — 薄壳层（文档 §4.8）。
 *
 * 设计原则（分层解耦红线）：
 *  - JS 仅做参数序列化 + 子进程调用 + 结果包装；全部科研业务在 Python CLI
 *  - 通过环境变量注入：paper-agent_PYTHON（解释器）、paper-agent_ROOT（项目根）
 *  - 严格遵循 AGH hot-tool-plugin 范式；如与官方示例冲突，以官方
 *    examples/packages/hot-tool-plugin 与 develop/backend.md 为准（§8 第4条）
 *
 * 【架构变更】编排权归还 AGH：
 *  旧形态下 Python 侧的 run-all 是写死的 for 循环，AGH 沦为"启动器"。
 *  本版本新增 sciret_step_driven / sciret_next / sciret_finish，让大模型在 AGH
 *  会话内逐步驱动流水线：每次只执行一步，返回决策上下文，由模型决定下一步。
 *  run-all 降级为"确定性兜底路径"，仍保留但不再是主导。
 *
 * 工具清单（10 个）：
 *  驱动型（主导）：sciret_step_driven / sciret_next / sciret_finish
 *  基础型：        sciret_plan / sciret_run_step / sciret_status / sciret_resume
 *  可信框架：      sciret_verify / sciret_report / sciret_cite
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
  const py = process.env["paper-agent_PYTHON"] || "python";
  const root = process.env["paper-agent_ROOT"] || __dirname;
  const env = {
    ...process.env,
    "paper-agent_ROOT": root,
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

// ---------- 工具定义 ----------
const TOOLS = [
  // ===== 驱动型工具（主导路径：编排权在模型侧）=====
  {
    name: "sciret_step_driven",
    description:
      "★主导路径★ Execute ONE pipeline step and return a decision context " +
      "(result + remaining_steps + next_tool_candidates + requires_decision). " +
      "You MUST read the returned context and decide the next tool call yourself. " +
      "Use this instead of sciret_run_step when orchestrating the pipeline.",
    parameters: objectSchema(
      {
        run_id: str("run instance id, e.g. run-YYYYMMDD-HHMMSS-xxxxxx"),
        step: str("P1_lit_search|P2_clean_data|P3_run_experiment|P4_verify|P5_report"),
        chaos: optStr(CHAOS_DESC),
      },
      ["run_id", "step"],
    ),
    meta: writeMeta("idempotent", 180_000),
    execute: makeRunner((c) => ["step-driven", "--run", c.run_id, "--step", c.step], 180_000),
  },
  {
    name: "sciret_next",
    description:
      "Read-only: inspect remaining steps and the recommended next tool candidates " +
      "for a run WITHOUT executing anything. Use it to re-orient after an interruption.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: READONLY_META,
    execute: makeRunner((c) => ["next", "--run", c.run_id]),
  },
  {
    name: "sciret_finish",
    description:
      "Converge the run status (RUNNING -> DONE/FAILED) once you have confirmed all " +
      "five steps reached terminal states. Refuses if steps are still pending.",
    parameters: objectSchema(
      { run_id: str("run instance id"), chaos: optStr(CHAOS_DESC) },
      ["run_id"],
    ),
    meta: writeMeta("idempotent", 30_000),
    execute: makeRunner((c) => ["finish", "--run", c.run_id], 30_000),
  },
  // ===== 基础型工具 =====
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
    description:
      "Execute a single pipeline step P1..P5 for a given run (idempotent reuse for " +
      "terminal steps). Deterministic fallback path: prefer sciret_step_driven when " +
      "you are orchestrating, since it also returns the decision context.",
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

// ---------- AGH 扩展入口（官方 Cordis 对象插件范式，对齐 examples/packages/hot-tool-plugin） ----------
export const paperAgentTools = {
  // extension: 工具注册 API；skills: 运行时 Skill 贡献 API（见官方 docs/guide/skills.md）
  inject: ["extension", "skills"],
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

    // 运行时贡献一个 Skill：把"五步编排协议"交给大模型。
    // 依据 AGH 官方 docs/guide/skills.md 的 Cordis 运行时贡献 API：
    //   普通受信插件可 inject: ['skills']，在 apply 中 ctx.skills.register({...})
    // 该 Skill 的正文引导模型逐步决策，而不是让 Python 侧硬编码顺序。
    try {
      const skills = ctx.skills;
      if (skills && typeof skills.register === "function") {
        skills.register({
          name: "sciret-research-pipeline",
          description:
            "驱动 sciret_* 工具完成固态电解质电导率科研流水线" +
            "（文献检索→数据清洗→真实实验→复现验证→报告），由模型逐步决策每一步",
          body: SKILL_BODY,
        });
      }
    } catch {
      // Skill 注册失败不应阻断工具注册：工具仍可用，只是缺少编排引导语。
      // 不静默吞掉语义——在日志中留痕（AGH 提供 agnes.ctx.log）。
      try {
        agnes.ctx?.log?.warn?.(
          "sciret-research-pipeline skill registration unavailable; tools remain registered",
        );
      } catch {
        /* 日志通道不可用时保持静默，不影响工具可用性 */
      }
    }

    // 观测型钩子（返回值被忽略，仅用于留痕）
    agnes.on("session_start", () => {
      agnes.ctx.log.info("sciret_* tools (10) are available; pipeline orchestration is model-driven");
    });
  },
};

/** 内联的 Skill 正文 —— 与 .agh/skills/sciret-research-pipeline/SKILL.md 保持同源语义。 */
const SKILL_BODY = `你是固态电解质材料科研助手。本 Skill 定义一条**由你逐步决策**的科研流水线。

## 核心规则
1. 你必须自己逐步调用工具，不能一次调用就指望流程跑完。sciret_step_driven 每次只执行一个步骤。
2. 每一步执行后，必须先读返回结果，再决定下一步，不要盲目前进。
3. 禁止在收到 FAILED 信号后继续下一步。必须显式决策：重试还是终止。
4. 禁止凭记忆或猜测填写结论。所有数值必须来自工具返回的结构化字段。

## 五步流水线
先调用 sciret_plan(goal="...") 拿到 run_id，然后按顺序用 sciret_step_driven 执行：
P1_lit_search -> P2_clean_data -> P3_run_experiment -> P4_verify -> P5_report

每步要判断的要点：
- P1：看 n_hits 与 DOI 列表；若 n_hits==0 则改写 goal 重开 run
- P2：看 input_rows->output_rows 与 actions（去重/单位归一/中位数插补）
- P3：看 results_sha256 与 summary.top3，确认子进程退出码为 0
- P4：看 status，PASS 才能继续；FAIL 必须停止并说明哪一项校验失败
- P5：确认报告已生成且每条结论带 [EV-XXXX] 证据标记

## 决策协议
sciret_step_driven 会返回：result / remaining_steps / next_tool_candidates /
requires_decision / decision_reason。读完后在 next_tool_candidates 里选一个调用。

## 故障恢复
- 某步骤 FAILED：调用 sciret_resume(run_id=...) 重试；仍失败则查 sciret_verify 后终止并说明原因。
- degraded=true：P1 重试耗尽后降级为全量语料，必须在结论中显式声明，不能假装没发生。
- 中间状态恢复：调用 sciret_resume，只跑 PENDING/FAILED，DONE 步骤直接复用。

## 收尾
五步完成后调用 sciret_finish(run_id=...) 收敛状态，再用 sciret_cite 回查文献证据与文件证据。

## 汇报要求
必须包含：五步状态与尝试次数、实验 top3（material_id + formula + score）、复现验证结论、
降级声明（若 degraded=true）、证据索引 [EV-XXXX]。禁止编造任何数值。`;

