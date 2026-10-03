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
 * 工具清单（17 个，两条工作流）：
 *  驱动型（主导）：sciret_step_driven / sciret_next / sciret_finish
 *  基础型：        sciret_plan / sciret_run_step / sciret_status / sciret_resume
 *  可信框架：      sciret_verify / sciret_report / sciret_cite
 *  科研全流程：    sciret_search_papers / sciret_parse_paper / sciret_analyze
 *                  sciret_factcheck / sciret_write_review / sciret_self_review / sciret_eval
 *
 * 两条工作流（sciret_plan 的 workflow 参数选择）：
 *   materials（默认）: P1_lit_search .. P5_report（可复现实验底座）
 *   research          : R1_search .. R6_review（PRD 科研全流程）
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
const optNum = (desc = "") => ({ [KIND]: "Number", type: "number", description: desc });
const optBool = (desc = "") => ({ [KIND]: "Boolean", type: "boolean", description: desc });

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
    description: "Plan a new research run: create isolated run instance with a step state machine and append-only ledgers. workflow=materials (5 steps P1..P5, reproducible experiment) or workflow=research (6 steps R1..R6: search -> read -> analyze -> verify -> write -> review).",
    parameters: objectSchema(
      { goal: str("research goal / query text"),
        workflow: optStr("materials (default) | research"),
        chaos: optStr(CHAOS_DESC) },
      ["goal"],
    ),
    meta: writeMeta("never", 10_000),
    execute: makeRunner((c) => {
      const a = ["plan", "--goal", c.goal];
      if (c.workflow) a.push("--workflow", c.workflow);
      return a;
    }),
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
        step: str("materials: P1_lit_search|P2_clean_data|P3_run_experiment|P4_verify|P5_report ; research: R1_search|R2_read|R3_analyze|R4_verify|R5_write|R6_review"),
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
  // ===== 科研全流程单点工具（research 工作流的能力入口）=====
  {
    name: "sciret_search_papers",
    description:
      "Multi-source academic search (arXiv / Semantic Scholar / OpenAlex / CrossRef) with " +
      "DOI-exact + title/first-author fuzzy dedup, per-source timeout skip (task never " +
      "blocks), relevance ranking. Set local=true for the offline built-in corpus.",
    parameters: objectSchema(
      {
        goal: str("query keywords / research question"),
        sources: optStr("comma list: arxiv,semantic_scholar,openalex,crossref (default all)"),
        max_results: optNum("max documents (default 10)"),
        local: optBool("use offline built-in corpus"),
        chaos: optStr(CHAOS_DESC),
      },
      ["goal"],
    ),
    meta: READONLY_META,
    execute: makeRunner((c) => {
      const a = ["search-papers", "--goal", c.goal];
      if (c.sources) a.push("--sources", c.sources);
      if (c.max_results) a.push("--max", String(c.max_results));
      if (c.local) a.push("--local");
      return a;
    }),
  },
  {
    name: "sciret_parse_paper",
    description:
      "Deep-read a paper into a structured note (sections, key info with locators, " +
      "figure/table captions, reproducibility links, language detection). Zero-dependency " +
      "PDF text extraction; scanned PDFs (no text layer) auto-degrade with low confidence. " +
      "source = local PDF path | arXiv id | DOI.",
    parameters: objectSchema(
      {
        source: str("local PDF path | arXiv id (e.g. 2301.12345) | DOI"),
        allow_network: optBool("allow fetching arXiv PDF (default false)"),
        out_dir: optStr("write note.json / note.md here"),
        chaos: optStr(CHAOS_DESC),
      },
      ["source"],
    ),
    meta: writeMeta("idempotent", 120_000),
    execute: makeRunner((c) => {
      const a = ["parse-paper", "--source", c.source];
      if (c.allow_network) a.push("--allow-network");
      if (c.out_dir) a.push("--out-dir", c.out_dir);
      return a;
    }, 120_000),
  },
  {
    name: "sciret_analyze",
    description:
      "Innovation mining (5 categories: method/theory/data/application/engineering) with " +
      "per-point provenance, comparison matrix, technology timeline and Research-Gap " +
      "identification. Input: --note <note.json> or --run <run_id> (batch over read notes).",
    parameters: objectSchema(
      {
        note: optStr("path to a structured note json"),
        run_id: optStr("analyze all notes of this run"),
        out_dir: optStr("write innovations/gaps/timeline artifacts here"),
        chaos: optStr(CHAOS_DESC),
      },
      [],
    ),
    meta: writeMeta("idempotent", 60_000),
    execute: makeRunner((c) => {
      const a = ["analyze-paper"];
      if (c.note) a.push("--note", c.note);
      if (c.run_id) a.push("--run", c.run_id);
      if (c.out_dir) a.push("--out-dir", c.out_dir);
      return a;
    }),
  },
  {
    name: "sciret_factcheck",
    description:
      "Fact verification: citation truthfulness (✅ consistent / ⚠️ partial / ❌ inconsistent / " +
      "❓ source unavailable), intra-paper data consistency, and cross-paper contradiction " +
      "detection. Use run_id for the research workflow's R4 step.",
    parameters: objectSchema(
      {
        run_id: optStr("run the research R4 fact-check step"),
        claims_file: optStr("json: [{claim, source_text, source_ref}]"),
        chaos: optStr(CHAOS_DESC),
      },
      [],
    ),
    meta: writeMeta("idempotent", 120_000),
    execute: makeRunner((c) => {
      const a = ["verify-facts"];
      if (c.run_id) a.push("--run", c.run_id);
      if (c.claims_file) a.push("--claims-file", c.claims_file);
      return a;
    }, 120_000),
  },
  {
    name: "sciret_write_review",
    description:
      "Generate a citation-grounded literature review draft (every factual sentence carries a " +
      "[doc_id] tag; unsupported sentences are marked [需补充引用]) plus BibTeX/RIS export and " +
      "APA/IEEE/Chicago citation strings. Fact-statement citations are never fabricated.",
    parameters: objectSchema(
      {
        topic: optStr("review topic"),
        run_id: optStr("run the research R5 writing step"),
        docs_file: optStr("json with hits/documents when no run_id"),
        out_dir: optStr("write review.md / references.bib here"),
        chaos: optStr(CHAOS_DESC),
      },
      [],
    ),
    meta: writeMeta("idempotent", 60_000),
    execute: makeRunner((c) => {
      const a = ["write-review"];
      if (c.run_id) a.push("--run", c.run_id);
      if (c.topic) a.push("--topic", c.topic);
      if (c.docs_file) a.push("--docs-file", c.docs_file);
      if (c.out_dir) a.push("--out-dir", c.out_dir);
      return a;
    }),
  },
  {
    name: "sciret_self_review",
    description:
      "Simulated peer review on 5 dimensions (contribution / technical correctness / experimental " +
      "sufficiency / clarity / related-work coverage) with a conference-review template " +
      "(Summary/Strengths/Weaknesses/Detailed Comments/Score) and a revise-until-clear loop.",
    parameters: objectSchema(
      {
        run_id: optStr("run the research R6 self-review step"),
        draft: optStr("path to a draft markdown when no run_id"),
        docs_file: optStr("json with hits/documents when using draft"),
        chaos: optStr(CHAOS_DESC),
      },
      [],
    ),
    meta: writeMeta("idempotent", 60_000),
    execute: makeRunner((c) => {
      const a = ["self-review"];
      if (c.run_id) a.push("--run", c.run_id);
      if (c.draft) a.push("--draft", c.draft);
      if (c.docs_file) a.push("--docs-file", c.docs_file);
      return a;
    }),
  },
  {
    name: "sciret_eval",
    description:
      "Quantitative evaluation (PRD F-7): search quality (Recall/Precision/NDCG@10 vs keyword " +
      "baseline), reading quality, innovation-extraction accuracy (identification / " +
      "classification / hallucination + confusion matrix) and citation credibility. " +
      "Writes eval_report.json/.md.",
    parameters: objectSchema(
      {
        run_id: optStr("attach the evaluation to this run (runs/<id>/evaluation/)"),
        out_dir: optStr("write the report here"),
        chaos: optStr(CHAOS_DESC),
      },
      [],
    ),
    meta: writeMeta("idempotent", 300_000),
    execute: makeRunner((c) => {
      const a = ["eval"];
      if (c.run_id) a.push("--run", c.run_id);
      if (c.out_dir) a.push("--out-dir", c.out_dir);
      return a;
    }, 300_000),
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
            "驱动 sciret_* 工具完成科研任务：① materials 工作流（文献检索→数据清洗→真实实验→" +
            "复现验证→报告）；② research 工作流（多源检索→精读→创新点拆解→事实验证→综述写作→自评审）。" +
            "由模型逐步决策每一步。",
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

    // 观测型钩子（返回值被忽略，仅用于留痕；不同 AGH 版本 event API 可能缺省）
    try {
      if (typeof agnes.on === "function") {
        agnes.on("session_start", () => {
          agnes.ctx.log.info(
            "sciret_* tools (17, two workflows: materials P1..P5 / research R1..R6) are available; " +
            "pipeline orchestration is model-driven");
        });
      }
    } catch {
      /* 事件通道不可用不影响工具可用性 */
    }
  },
};

/** 内联的 Skill 正文 —— 与 .agh/skills/sciret-research-pipeline/SKILL.md 保持同源语义。 */
const SKILL_BODY = `你是科研智能体助手。本 Skill 定义两条**由你逐步决策**的科研工作流。

## 核心规则
1. 你必须自己逐步调用工具，不能一次调用就指望流程跑完。sciret_step_driven 每次只执行一个步骤。
2. 每一步执行后，必须先读返回结果，再决定下一步，不要盲目前进。
3. 禁止在收到 FAILED 信号后继续下一步。必须显式决策：重试还是终止。
4. 禁止凭记忆或猜测填写结论。所有数值/引用必须来自工具返回的结构化字段。
5. 禁止编造引用；无依据的事实陈述必须标注 [需补充引用]。

## 工作流一：materials（可复现实验底座）
sciret_plan(goal="...") 拿到 run_id，然后按序 sciret_step_driven：
P1_lit_search -> P2_clean_data -> P3_run_experiment -> P4_verify -> P5_report
- P1：看 n_hits 与 DOI；n_hits==0 则改写 goal 重开 run
- P2：看 input_rows->output_rows 与清洗动作
- P3：看 results_sha256 与 summary.top3
- P4：PASS 才能继续；FAIL 必须停止并说明哪项校验失败
- P5：确认报告每条结论带 [EV-XXXX]

## 工作流二：research（PRD 科研全流程）
sciret_plan(goal="...", workflow="research") 拿到 run_id，然后按序 sciret_step_driven：
R1_search -> R2_read -> R3_analyze -> R4_verify -> R5_write -> R6_review
- R1：多源检索。看 sources_status / unavailable_sources；某源不可用会自动切源（不中断），
      必须在汇报中声明"某源未响应，已切换其它源"。
- R2：批量精读。看 n_read / n_failed；失败篇目会被标注并跳过（不阻塞），扫描件会标低置信度。
- R3：创新点拆解 + Research Gap。每条创新点带 locator，禁止编造。
- R4：事实验证。看引用一致性率与文献间矛盾。
- R5：综述草稿。看悬空引用（consistency.ok）与 [需补充引用] 数量。
- R6：自评审。看各维度分数与 verdict；有阻塞性问题需说明修改方向。
也可以直接用单点工具：sciret_search_papers / sciret_parse_paper / sciret_analyze /
sciret_factcheck / sciret_write_review / sciret_self_review / sciret_eval。

## 决策协议
sciret_step_driven 返回：result / remaining_steps / next_tool_candidates /
requires_decision / decision_reason。读完后在 next_tool_candidates 里选一个调用。

## 故障恢复（PRD F-4.8）
- 某步骤 FAILED：调用 sciret_resume 重试；仍失败则说明原因后终止。
- 场景1 外部 API 超时降级：检索源超时 → 自动切换其它源，任务不中断（结果中标注切源）。
- 场景2 PDF 解析失败恢复：扫描件无文本层 → 走 OCR 路径，不可用则标注"低质量解析"。
- 场景3 长任务中断恢复：批量精读单篇失败 → 标注失败项并跳过，整体流程继续；
  进程真实崩溃后调用 sciret_resume 从断点续跑（DONE 步骤直接复用）。
- degraded=true：必须显式声明，不能假装没发生。

## 收尾与量化验证
- 全部步骤完成调用 sciret_finish 收敛状态，再用 sciret_cite 回查文献/文件证据。
- 需要量化指标时调用 sciret_eval（检索 Recall/Precision/NDCG@10、精读、创新点、引用可信度）。
- research 工作流用 sciret_report 生成报告；materials 工作流 P5 已含报告。

## 汇报要求
必须包含：工作流名与步骤状态/尝试次数、关键产物数值、降级声明（若 degraded=true）、
证据索引 [EV-XXXX]。禁止编造任何数值与引用。`;

