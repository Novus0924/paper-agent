# audit-pack-template

黑客松提交物：一个 run 实例的**完整可交付审计包**。
把下表文件按结构归集，打包即提交。

## 目录结构（打包后）

```
audit-pack/
├── state.json            # run 主状态快照（步骤/尝试次数/degraded/顶层状态）
├── events.jsonl          # 事件流水账本（append-only）
├── provenance.jsonl      # 证据流水账本（append-only，ev_id 自增）
├── conclusions.jsonl     # 科研结论‑证据绑定记录
├── agh-session.jsonl     # AGH 导出的会话执行审计记录（联调后产生）
├── verification.json     # P4 复现验证结果（5 项校验）
├── report.md             # P5 生成的最终科研报告（可选，含证据索引）
└── HOW-TO-VERIFY.md      # 验收核验手册（随包提交）
```

## 构建

```bash
RUN_ID=<某次完成的 run id>
mkdir -p audit-pack
cp runs/$RUN_ID/state.json            audit-pack/
cp runs/$RUN_ID/events.jsonl          audit-pack/
cp runs/$RUN_ID/provenance.jsonl     audit-pack/
cp runs/$RUN_ID/conclusions.jsonl    audit-pack/
cp runs/$RUN_ID/verification/verification.json audit-pack/
cp runs/$RUN_ID/report.md            audit-pack/
cp HOW-TO-VERIFY.md                  audit-pack/
# 联调后补充 AGH 会话记录：
cp session.jsonl                     audit-pack/agh-session.jsonl
tar -czf audit-pack.tar.gz audit-pack
```

或直接运行：

```bash
bash audit-pack-template/build_audit_pack.sh <RUN_ID>
```

## 机器可校验要点

- `provenance.jsonl` 每条含 `ev_id / kind / ref / sha256 / producer_step`；
  文件类证据的 `sha256` 应与实际产物哈希一致。
- `conclusions.jsonl` 每条 `evidence_ids` 必须全部能在 `provenance.jsonl` 找到
  （结论‑证据强绑定不变量）。
- `events.jsonl` 为 append-only，事件时间戳单调不减。
- `verification.json` 的 5 项校验可独立复核（见 HOW-TO-VERIFY §3 用例 D）。
