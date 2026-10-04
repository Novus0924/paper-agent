// 无 TTY 环境下验证 paper-agent 插件本体：能否加载 / 7 工具是否齐全 / meta 8 键是否完整 / 能否 spawn 到 Python。
//
// 用法（在 paper-agent 仓库根目录，两个环境变量必须先给到）：
//   env "paper-agent_PYTHON=<Python 绝对路径>" \
//       "paper-agent_ROOT=<paper-agent 仓库绝对路径>" \
//       node tools/verify-plugin-offline.mjs
//
// 插件路径按本脚本位置相对解析，与克隆目录无关，可直接随仓库分发。
const pluginUrl = new URL("../plugins/paper-agent-tools/index.mjs", import.meta.url);
const { paperAgentTools } = await import(pluginUrl);

const registered = [];
const stubAgnes = {
  registerTool(t) { registered.push(t); },
  on() {},
  ctx: { log: { info: () => {} } },
};
paperAgentTools.apply({ extension: () => stubAgnes });

console.log("inject =", JSON.stringify(paperAgentTools.inject));
console.log("注册工具数 =", registered.length);
for (const t of registered) {
  const keys = Object.keys(t.meta ?? {});
  console.log(`  - ${t.name}  metaKeys=${keys.length}  approval=${t.meta.requiresApproval}  readonly=${t.meta.isReadOnly}`);
}

// meta 必须 8 键（AGH checkToolMeta 要求）
const want = ["isReadOnly","isDestructive","isConcurrencySafe","isOpenWorld","replay","costHint","deferLoading","requiresApproval"];
let ok = true;
for (const t of registered) {
  for (const k of want) if (!(k in (t.meta ?? {}))) { console.log(`  !! ${t.name} 缺 meta 键 ${k}`); ok = false; }
}
console.log("meta 8 键校验 =", ok ? "PASS" : "FAIL");

// 真跑一个只读工具，验证能 spawn 到 Python 并拿到 JSON
const status = registered.find((t) => t.name === "sciret_status");
if (status) {
  console.log("--- 试跑 sciret_status（应返回 invalid run_id 校验失败，证明链路通）---");
  const r = await status.execute({ run_id: "not-a-valid-id" });
  console.log(JSON.stringify(r).slice(0, 400));
}
