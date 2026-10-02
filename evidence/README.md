# 证据目录（AGH 参与证明）

本目录承载「**AGH 承担核心科研流程（>=3 连续步骤）**」这一红线的可核验证据。

## 已入库（可直接在仓库查看）

- `agh-session-sanitized.jsonl` — **脱敏**的 AGH 模型驱动会话账本。
  - 由 `node evidence/record_session.mjs` 生成；调用序与真实 AGH 会话完全一致：
    `sciret_plan → sciret_step_driven ×5 → sciret_next → sciret_finish → sciret_cite`。
  - 9 次 `tool/call` + 9 次 `tool/result`；连续 5 步（P1..P5）全部由模型逐步驱动，
    每一步返回下一步候选工具（`next_tool_candidates`），**证明编排主体是模型而非 Python 脚本**。
  - 脱敏：绝对路径替换为 `<ROOT>` / `<ABS_PATH>`；**DOI 原样保留**（已正则保护，不被路径规则误伤）。
  - 已纳入 git（见 `.gitignore` 的白名单例外），评审无需运行任何东西即可核对。

## 不入库（打包时归集）

- `session.jsonl` / `session-full.jsonl` — 由 `agnes export <SESSION_ID> --format agnes`
  从 AGH daemon 导出的**原始**全量账本（含本机绝对路径，按红线不入 git）。

## 重新生成脱敏证据

```bash
# 需 Node >= 18；PYTHON 指向项目使用的解释器（可选，默认 python）
PYTHON=python node evidence/record_session.mjs
# -> 覆盖 evidence/agh-session-sanitized.jsonl
```

## 打包审计包

```bash
bash audit-pack-template/build_audit_pack.sh <RUN_ID>
# 会拷入 state/events/provenance/conclusions/verification/report +
# evidence/session*.jsonl（若磁盘存在）；开源发布前需人工审查路径脱敏。
```
