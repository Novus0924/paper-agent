# AGH 执行记录导出（真实会话证据）

由 `agnes export <SESSION_ID> --format agnes` 从 AGH daemon 导出的 JSONL 执行账本。
**每条记录都是 daemon 原始事件，未经人工编辑**；下文所有数字均可用
`python evidence/verify_export.py <本目录下的jsonl>` 复核。

## 文件清单

| 文件 | 会话 ID | 状态 | 工具调用 | 覆盖 |
|---|---|---|---|---|
| `session-6139563e.jsonl` | `6139563e-...b01a` | ⚠️ **本机缺文件**（见下方迁移说明） | 71次 call / 71 次 result（严格配对） | **7/7 `sciret_*` 工具全覆盖** |
| `session-aa3929f6.jsonl` | `aa3929f6-...4f25` | ⚠️ **本机缺文件**（同上） | 13 次 call / 13 次 result（严格配对） | 2/7（`plan` + `run_step`） |
| `session-bcc6541d.jsonl` | `bcc6541d-...df68` | ✅ **本机在档**（2026-10-06 导出） | 4 次 call / 4 次 result（ok=4 fail=0） | 3/7（`plan` + `run_step` + `cite`） |

> **迁移状态说明（2026-10-06 如实标注）**：`6139563e` / `aa3929f6` 是旧开发环境
> （`D:\workBubbyStore\hkx-v3`，lenovo 机器）daemon 库中的会话，**daemon 库未随迁移**——
> 本机 `~/.agh/data/tables/_40agnes_2fdaemon.db` 的 `session_workspaces` 表查无此二 id，
> `agnes export` 报 `CAPABILITY_DENIED`，文件无法重导出。下文对这两个文件的分析保留作
> 历史参考。**本机当前在档的唯一 sciret 工具会话证据为 `session-bcc6541d.jsonl`**
> （2026-10-05「使用sciret工具规划并执行LLM幻觉缓解研究」，关联 run-20261005-074025-249766，
> 复核输出：插件工具覆盖 3/7、调用合计 ok=4 fail=0）。

### `session-6139563e.jsonl`（主证据）

- 会话标题「硫化物电解质科研流水线」，时间跨度 `2026-10-04T04:19Z` → `2026-10-05T15:45Z`。
- 逐工具调用次数（`tool/call` 计数）：

  | 工具 | 次数 | 工具 | 次数 |
  |---|---|---|---|
  | `sciret_run_step` | 17 | `sciret_status` | 4 |
  | `sciret_plan` | 5 | `sciret_cite` | 3 |
  | `sciret_resume` | 3 | `sciret_verify` | 1 |
  | | | `sciret_report` | 1 |

  合计 **34 次插件调用**（成功 32 / 失败 2，见下"已知瑕疵"）。
- **两条工作流都跑过**：`sciret_plan` 的 5 次调用里`workflow=research` 4 次、`workflow=materials` 1 次。
- **三个科研领域**：硫化物固态电解质电导率排序、图神经网络在药物发现中的应用、大语言模型幻觉缓解方法。
- 涉及的 run（**目录均真实存在于 `runs/`，可交叉核对**）：

  | run id | 工作流 | 终态 | 步数 |
  |---|---|---|---|
  | `run-20261004-060645-9646ba` | materials | DONE | 5/5 |
  | `run-20261004-093918-14786a` | research | DONE | 6/6 |
  | `run-20261004-094544-e4d553` | research | DONE | 6/6 |

  三个 run 都带 `provenance.jsonl`（18–21 条）+ `conclusions.jsonl`（5 条）+ `report.md`（5–7KB）。

### `session-aa3929f6.jsonl`（补充证据）

会话标题「LLM幻觉缓解方法研究任务规划」，13 次调用全部成功，
对应run `run-20261005-074406-666d16`。用于佐证"同一套工具在另一个会话里也稳定可用"。

## 格式说明

- 导出用 `tool/call` / `tool/result` 记录类型（**不是**字面 `tool_use`）。
- 工具名位置**不统一**，校验时容易踩：
  - `tool/call` 的工具名在 **`data.name`**；
  - `tool/result` 的工具名在 **`origin`**（形如 `tool:sciret_plan`），`data` 里没有名字字段。
  - 配对要靠 **`data.toolUseId`** 关联，不能靠顺序或工具名。
- 只有插件工具（走 Python CLI）才返回 `data.structured.ok`；
  内置工具（`shell` / `todo` / `read` …）的 `structured` 为 `null`，
  成败要看 `data.isError`——**一律按 `structured.ok` 判定会把内置工具全判成失败**。
- 赛事闸门要求 ≥6 条工具交互记录；主证据单文件即有 **71 条 `tool/call` + 71 条 `tool/result`**。

## 已知瑕疵（如实记录，不掩盖）

1. **2 次 `sciret_plan` 失败**，均在会话最开头（seq=23 / seq=41），报
   `ModuleNotFoundError: No module named 'paper_agent'`。
   这是**当时 daemon 缺`paper-agent_ROOT` 环境变量**导致的历史故障，
   后续补齐变量后同一会话内即恢复成功。保留原始失败记录是因为它恰好证明了
   "环境变量缺失 → 插件退化为不可用"这条诊断链（见项目记忆第3 条坑位）。
2. **本目录不含"真实kill 子进程（exit 137）"的证据**。插件 schema 里有
   `chaos` 参数（枚举含 `kill_after_p2`），`tool_describe` 的返回里会出现该字符串，
   **但那是参数说明文本，不是执行记录**。真实的容错降级证据在磁盘的 run 目录里：
   `runs/run-20261004-030014-789f54` 与 `run-20261004-030253-7d141a` 的
   `state.json` 记录 `P1_lit_search` 尝试 3 次、`events.jsonl` 记录
   `degrade: exhausted 3 attempts: chaos: p1_fail_all`，
   两个 run 最终仍为 **DONE**（`degraded=true`）——这才是可核查的"失败重试 + 降级 + 续跑"链路。

## 复现方法

```bash
# ⚠️ export 不依赖 TTY，可脚本化；也不依赖 `agh sessions list`
bash agh.sh daemon start                                   # 确保 daemon 在跑
bash agh.sh export6139563e-3160-4da5-b227-4ad287f0b01a \
     --format agnes --profile local-dev -o evidence/session-6139563e.jsonl

# 复核内容真实性（不要只看文件是否存在）
python evidence/verify_export.py evidence/session-6139563e.jsonl
```

> 已知坑：本机会话表里有一条 `generation=0` 的坏行，其 `cwd` 恰是
> `D:\workBubbyStore\hkx-v3\paper-agent`，会让 `agh sessions list` 稳定报
> `RESULT_INVALID`；但 `export` 直接读账本、**不碰 `session.list`**，所以不受影响。
> 若不知道会话 id，可查 `~/.agh/data/tables/_40agnes_2fdaemon.db` 的 `session_workspaces` 表
> （`session_key` / `title` / `last_seq`），按 `last_seq` 大小找完整会话。

## 打包与脱敏

`*.jsonl` 含本机绝对路径（`D:\workBubbyStore\...`、`C:\Users\lenovo\...`），
按红线**不入 git**（`.gitignore` 第 25 行 `evidence/*.jsonl` 已排除）；
提交打包时从磁盘归集（`bash audit-pack-template/build_audit_pack.sh <RUN_ID>`
会把导出拷入 `audit-pack/`），**开源发布前需人工审查路径脱敏**。
