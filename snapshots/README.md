# snapshots — 冻结输入快照

本目录存放**冻结的输入快照**。快照是复现契约的载体：模型的检索与筛选结果
一经产生就冻结于此，此后的复算、验证、出报告**只针对快照**。

```
snapshots/<snapshot_id>/
├── manifest.json      元数据 + 文件清单 + 逐文件 SHA-256 + 聚合 content_sha256
├── materials.csv      数据腿产出（已映射为标准列的材料数据）
├── literature.json    文献腿产出（论文 DOI 等元数据）
└── judgments.jsonl    判断批次（tier=judgment，随快照自包含）
```

## 强校验

```bash
python - <<'PY'
import sys; sys.path.insert(0, "core")
from paper_agent import snapshot as S
snap = S.open_snapshot(".")          # 默认取最新
print(snap.snapshot_id, snap.verify())   # 期望 (True, [])
PY
```

`verify()` 会逐文件重算 SHA-256 并与 `manifest.json` 比对，同时校验聚合
`content_sha256`。**任一文件被改动或丢失都会失败**——包括删掉 `judgments.jsonl`
（这会让流水线在 P1 直接失败、报告无法生成）。

## 为什么快照自包含判断批次

- 判据 4 要求"删除模型判断记录 → 报告必须生成失败"，判断批次必须可校验；
- 复算 run 能把判断批次**重新登记进自己的账本**（`register_judgments_into`），
  使每个 run 的审计闭环独立、不依赖其他 run 的目录。

## 内容哈希与时间戳

`content_sha256` **只覆盖文件内容**，不包含 `created_at` 等易变字段——
否则"相同输入两次运行哈希一致"这条确定性契约就失效了。

## 刷新快照

数据为**固定快照，不自动更新**。需要刷新时：

```bash
python tools/freeze_snapshot.py --goal "<科研目标>"
```

刷新会生成新的 `snapshot_id`（旧的保留，可回放）。数据源本身的更新流程见
`data/external/obelix/README.md`。
