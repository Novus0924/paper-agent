// 端到端自检：绕过 AGH，直接把插件接到 Python CLI 真跑一遍
// sciret_plan -> sciret_status -> sciret_cite，外加一条 H1 路径穿越拦截用例。
//
// 用法（在 paper-agent 仓库根目录，两个环境变量必须先给到）：
//   env "paper-agent_PYTHON=<Python 绝对路径>" \
//       "paper-agent_ROOT=<paper-agent 仓库绝对路径>" \
//       node tools/verify-plugin-e2e.mjs
//
// 插件路径按本脚本位置相对解析，与克隆目录无关，可直接随仓库分发。
const pluginUrl = new URL("../plugins/paper-agent-tools/index.mjs", import.meta.url);
const { paperAgentTools } = await import(pluginUrl);

const tools = {};
paperAgentTools.apply({
  extension: () => ({ registerTool: (t) => { tools[t.name] = t; }, on() {}, ctx: { log: { info() {} } } }),
});

const show = (label, r) => {
  const s = JSON.stringify(r.structured ?? r);
  console.log(`${label}: ${s.length > 500 ? s.slice(0, 500) + " …" : s}`);
};

console.log("=== 1) sciret_plan ===");
const plan = await tools.sciret_plan.execute({ goal: "验证插件到 Python 的端到端链路" });
show("plan", plan);
const runId = plan.structured?.run_id ?? plan.structured?.run?.id;
console.log("run_id =", runId);
if (!runId) { console.log("拿不到 run_id，后续跳过"); process.exit(0); }

console.log("\n=== 2) sciret_status ===");
show("status", await tools.sciret_status.execute({ run_id: runId }));

console.log("\n=== 3) sciret_cite（只读，列证据）===");
show("cite", await tools.sciret_cite.execute({ run_id: runId }));

console.log("\n=== 4) 非法 run_id 应被 H1 拦住 ===");
show("badId", await tools.sciret_status.execute({ run_id: "../../etc/passwd" }));
