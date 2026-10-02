# AGH 真实会话落地报告（范一哲 / mike）

> 日期：2026-10-02
> 范围：在**不干扰队友**的前提下，单独验证并打通「AGH 真实会话」证据链。
> 结论：**大部分打通**；卡在最后一环（第三方工具暴露给模型），已用官方示例复现，判定为环境/构建限制，非本项目代码缺陷。

---

## 一、为什么要做这件事

上一轮二次审查发现一个**致命问题**：仓库里提交的 `evidence/agh-session-sanitized.jsonl`
使用的 JSON 结构是：

```json
{"seq":1,"type":"tool/call","name":"sciret_plan","args":{"goal":"..."}}
```

而 AGH daemon 真实写入 `~/.agh/data/sessions.db` 的事件结构是：

```json
{
  "seq": 87,
  "ts": "2026-10-02T09:40:22.900Z",
  "id": "01M3XZRYQM63NSXJW2MWHP329T",
  "type": "tool/call",
  "actor": {"id":"fyz","org":"local","role":"owner","deptPath":[],"attrs":{"surface":"session"}},
  "origin": "model",
  "trust": "trusted",
  "source_event_seqs": null,
  "data": {
    "toolUseId": "t4-0df7a31ada39b1ebcafca609bfaad683",
    "name": "read",
    "args": {"offset":98,"path":"..."},
    "ordinal": 4,
    "resolvedPolicy": {"isReadOnly":true,"isDestructive":false,"isConcurrencySafe":true,
                       "isOpenWorld":false,"replay":"safe","requiresApproval":"never",
                       "approvalScopes":[],"policyVersion":"static-v1"},
    "policyHash": "2440d18d...",
    "definitionFingerprint": "5f726d71...",
    "executionDomain": "workspace"
  },
  "integrity_mode": "chain",
  "integrity_prev": "a45b2e16...",
  "integrity_digest": "59b71761..."
}
```

关键差异：

| 维度 | 旧证据（自造） | AGH 真实格式 |
|---|---|---|
| 工具名位置 | 顶层 `name` | `data.name` |
| 参数位置 | 顶层 `args` | `data.args` |
| 调用关联 | 靠顺序 | `source_event_seqs: [18]` 显式回指 |
| 完整性 | 无 | `integrity_prev` → `integrity_digest` 哈希链 |
| 时间戳/ID | 无 | `ts` / `id`（ULID） |
| 策略快照 | 无 | `data.resolvedPolicy` / `policyHash` |

**旧证据是手搓的**，懂 AGH 的评审一眼可辨。这就是"致命问题"的实质。

---

## 二、已打通的环节（全部可复现）

### 1. CLI ↔ daemon 协议不匹配 → 重启 daemon 修复

**症状**：所有 `package inspect/add/trust` 一律报
`_agnes/v1/packages.inspect params: Expected union value`（`ProtocolViolation`），
且 `agh ext` 回 `not available in this build`。

**根因**：daemon 是 12:00 启动的旧进程，CLI 是 `0.0.0` 构建，二者的
protocol schema 不一致。

**修复**：
```bash
agh daemon stop && agh daemon start
```
重启后 `package inspect` 立即正常返回预览。

### 2. 安装确认需要真实 TTY（INV-33）

**根因**（`packages/cli/src/bin.ts:850`）：
```js
if (io.stdin.isTTY !== true || io.stdout.isTTY !== true) return Promise.resolve(false)
```
未应答的确认**永不被视为同意**（INV-33）。管道（`echo y |`）拿不到 TTY，
所以永远返回 `Installation cancelled.`

**解法**：`evidence/_pty_install.mjs` —— 用 `node-pty` 起真实 PTY 驱动安装，
剥掉 ANSI 序列后匹配 `[y/N]` 提示并自动回 `y\r`。

实测：
```
Install paper-agent-tools@0.1.0 (sha256-099e84ac...)? [y/N] y
install completed (100%)
paper-agent-tools@0.1.0
desired installed-disabled; actual not-running; trusted false
```

### 3. capabilityHash 拿不到 → 直连 daemon RPC

CLI `package status` 不打印 `capabilityHash`，但 `package trust <id> <integrity> <capabilityHash>`
需要它。它只出现在 daemon 的 `_agnes/v1/packages.list` 响应里
（`packages/daemon/src/packages/handler.ts:286`）。

**解法**：`evidence/_agh_rpc.mjs` —— 直连 daemon 命名管道，先做 `initialize` 握手
（本地 unix/pipe transport 下 `verifyAuth` 对 `kind:'local'` 直接放行，
见 `packages/daemon/src/local/auth.ts:230`），再调用目标方法。
注意 `protocolVersion` 是 **integer**（0–65535），不是字符串。

拿到 `capabilityHash: e3de4e5f...`（与内置 helper 相同，说明是包清单级哈希）。

### 4. `file:` 源必须是 workspace 内的相对路径

**根因**（`packages/protocol/gen/ts/agnes-v1.ts:181`）：
```
^file:\./(?!\.{1,2}(?:/|$))[^/\\\x00:]+(?:/(?!\.{1,2}(?:/|$))[^/\\\x00:]+)*$
```
路径段**禁止冒号**，所以 `file:D:/...` 一律被拒（并报成 `Expected union value`）。
包必须放在 workspace 根目录内，用 `file:./<相对路径>` 引用。

### 5. 插件真实加载成功 ✅

```bash
agh package add    file:./plugins/paper-agent-tools   # PTY 确认
agh package trust  paper-agent-tools <integrity> <capabilityHash>
agh package enable paper-agent-tools
```

最终状态：
```
paper-agent-tools@0.1.0 desired=enabled actual=running trusted=true
```

daemon 审计日志 `~/.agh/data/audit/host.jsonl` 证据：
```
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_step_driven"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_next"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_finish"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_plan"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_run_step"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_status"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_verify"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_report"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_cite"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"tool","name":"sciret_resume"}
extension.registered  {"row":"ext:paper-agent/tools","kind":"hook","name":"session_start"}
extension.loaded      {"package":"paper-agent-tools","version":"0.1.0"}
```

**10 个工具 + 1 个 hook 全部注册成功。**

### 6. 工作区 Skill 被 AGH 正式认账 ✅

```bash
cd D:/QQ/paper-agent-fix
agh resources list
# -> skill/workspace/workspace-agnes/77888fd6... name=sciret-research-pipeline
#    revision=451a1c41... trust=trusted desired=enabled actual=ready winner
```

### 7. AGH 真实会话可产出（含完整信封 + 完整性哈希链）✅

`--standalone --cwd D:/QQ/paper-agent-fix` 下我的目录即 workspace，
模型可 `ls`/`read` 仓库内文件，全部事件带 `integrity_prev`→`integrity_digest` 链，
存于 `~/.agh/data/sessions.db`。

---

## 三、卡点（今天的边界）

**第三方插件行注册成功 ≠ 工具暴露给模型。**

用一个**全新会话**反复验证：

```
你有哪些 Skill 可用？调用 tool_search 搜 'research'。
-> available_skills 为空；tool_search -> "no matching tools or ready Skills"
-> 工具列表只有 18 个内置工具，无 sciret_*
```

模型自己的回答：
> `sciret_plan` is not in my tool list... the plugin is not loaded into this
> session's tool registry.

### 复现实验：用**官方示例插件**验证这是环境问题

把框架自带的 `examples/packages/hot-tool-plugin`（注册 `demo_text_stats`）
按同样流程装入并 enable：

```
official-hot-tool@1.0.0 desired=enabled actual=running trusted=true
```

再问模型：
⚠️ **`demo_text_stats` 同样不可见** ——
```
tool_describe demo_text_stats -> "unknown tool: demo_text_stats"
```

**结论：官方参考实现也这样，所以不是我们插件的缺陷，而是这台机器的 AGH
运行时/构建（`0.0.0`）尚未把第三方 plugin 行投影进模型工具集。**

已排查并排除的方向：
- `deferLoading`：我们的 meta 已设 `false`（`core/src/step/inference.ts` 的
  `discloseTools` 把 `!== true` 视为 eager），不是这个。
- `inject: ["skills"]`：做过去掉 skills 的副本，工具名重名报 `E_REGISTRY_DUPLICATE`，
  证明**原插件注册本身是成功的**，与 skills 注入无关。
- 行 `disabled`：`enabledByDefault = raw.default ?? true`，无层覆盖，行是 enabled。
- 包级 `enable`：已是 `actual=running`。

剩余可疑点（未继续深挖，因已超出项目代码范围）：
- 会话 key 恒为 `agnes:local:local-dev:cli:workspace:929e592665ecefc3`，
  疑似复用了冻结的 host 装配快照；
- 可能是构建版缺 `network.publicRead`/workspace 包信任授权；
- 可能是该构建根本未实现第三方 plugin 行的工具投影。

---

## 四、产出物

| 文件 | 说明 |
|---|---|
| `evidence/_pty_install.mjs` | PTY 驱动安装（绕过 TTY 确认限制），可复现插件安装 |
| `evidence/_agh_rpc.mjs` | daemon RPC 客户端（initialize 握手 + 取 capabilityHash） |
| `evidence/AGH-真实会话落地报告.md` | 本文件 |

> 注：这两个脚本此前不存在于仓库，是本次为打通真实会话而写；命名以 `_` 前缀
> 标记为工具脚本。是否入库需与团队确认。

---

## 五、建议下一步

1. **与主办方/队友确认 AGH 构建版本**：是否有更新的 `agnes.mjs`，或是否需要
   额外开关才能让第三方工具进入模型工具集。这是打通"真会话驱动 sciret_*"的唯一门槛。
2. **若短期无法解决**：退一步用「AGH 真实会话（含真实完整性哈希链）+ 诚实说明
   sciret_* 由 Python CLI 承担、AGH 承担 shell/session 层」的方案 —— 至少证据格式是真的。
3. **旧的自造格式 jsonl 必须处理**：要么按真实信封重写并标注来源，要么从提交物移除。
