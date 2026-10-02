# AGH 执行记录导出（真实会话证据）

由 `agnes export <SESSION_ID> --format agnes` 从 AGH daemon 导出的 JSONL 执行账本：

- `session.jsonl` — 首轮科研会话（2026-10-02）：plan→run_step P1..P5→verify→report→cite→status，
  10 次 tool/call + 10 次 tool/result，run `run-20261002-030119-61a0ec` DONE、verify PASS。
- `session-full.jsonl` — 同一 workspace 会话追加"故障注入与断点续跑"轮后的全量导出：
  21 次 tool/call + 21 次 tool/result，**7 个 `sciret_*` 工具全部出现**；含
  `chaos=kill_after_p2` 真实杀死子进程（exit 137）后 `sciret_resume` 续跑到 DONE 的完整链路
  （run `run-20261002-033525-356ccf`）。

格式说明：导出用 `tool/call` / `tool/result` 记录类型（非字面 `tool_use`），工具名在
`data.name`；赛事闸门要求 ≥6 条工具交互记录，本证据为 42 条。

`*.jsonl` 含本机绝对路径，按红线 **不入 git**（.gitignore 已排除）；提交打包时从磁盘归集
（`bash audit-pack-template/build_audit_pack.sh <RUN_ID>` 会把两份导出拷入 `audit-pack/`），
开源发布前需人工审查路径脱敏。
