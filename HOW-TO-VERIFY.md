# HOW‑TO‑VERIFY — 验收核验操作手册

本手册给出**每一条验收用例的执行步骤与哈希比对命令**。
所有命令在项目根目录执行；Windows 下 `export` 用 `set`，`sha256sum` 用
`certutil -hashfile <file> SHA256` 或 Git Bash 的 `sha256sum`。

> 约定：`ROOT` = 项目根目录；`RUN_ID` = 某次 run 实例 id（形如
> `run-YYYYMMDD-HHMMSS-xxxxxx`）；`SNAP` = 快照 id（形如 `snap-...`）。
> 
> **两条路径**：默认走**快照主线**（真实数据）；
> 加 `export PAPER_AGENT_SNAPSHOT=none` 可强制走 **legacy 路径**（内置演示语料）。

```bash
cd <ROOT>
export PYTHONPATH=<ROOT>/core
PY=python
```

---

# 第一部分 · 快照主线（真实数据）

## 0. 一键验收（推荐）

```bash
bash demo/demo_mainline.sh
# 期望：14 passed, 0 failed → 末行 DEMO_MAINLINE_OK
```

该脚本覆盖 [1] 快照强校验 → [2] 全链路 599→562→排序→P4 PASS →
[3] 两次运行逐字节一致 → [4] 删除判断记录后必须失败 → [5] 判断留痕 →
[6] fact/judgment 证据回查。

## 1. 快照强校验（含篡改检测）

**验收项**：逐文件 SHA-256 与聚合内容哈希全部吻合。

```bash
SNAP=$(ls -d snapshots/snap-* | tail -1)
$PY - "$SNAP" <<'PY'
import sys, json
sys.path.insert(0, "core")
from paper_agent import snapshot as S
snap = S.Snapshot(".", sys.argv[1].split("/")[-1])
print(json.dumps(snap.load(), ensure_ascii=False, indent=2)[:600])
print("verify:", snap.verify())   # 期望 (True, [])
PY
```

篡改检测（改一个字节即应被发现）：

```bash
cp "$SNAP/materials.csv" /tmp/m.csv
printf 'x' >> "$SNAP/materials.csv"
$PY -c "import sys;sys.path.insert(0,'core');from paper_agent import snapshot as S;print(S.Snapshot('.','$(basename $SNAP)').verify())"
# 期望：(False, ['hash mismatch: materials.csv ...', 'content hash mismatch ...'])
cp /tmp/m.csv "$SNAP/materials.csv"    # 恢复
```

## 2. 真实数据全链路

**验收项**：599 行输入 → 562 行可用（排除 37 行上界值）→ 排序 → P4 PASS。

```bash
$PY -m paper_agent.cli run-all --goal "sulfide solid electrolyte ionic conductivity ranking" \
    > /tmp/run.json
$PY -c "
import json; d=json.load(open('/tmp/run.json',encoding='utf-8'))
p2=d['results']['P2_clean_data']
print('run_status      :', d['run_status'], '| degraded:', d['degraded'])
print('P1 文献腿 DOI   :', d['results']['P1_lit_search']['n_hits'])
print('P1 快照         :', d['results']['P1_lit_search']['snapshot_id'])
print('P2 行数         :', p2['input_rows'], '->', p2['output_rows'], '| 排除', p2['excluded_rows'])
print('P4 状态         :', d['results']['P4_verify']['status'])
print('RUN_ID          :', d['run_id'])
"
# 期望：DONE / degraded False / DOI 223 / 599 -> 562 / 排除 37 / P4 PASS
```

## 3. 确定性（核心契约）

**验收项**：相同快照两次独立运行，`results.csv` 逐字节一致。

```bash
IN="$SNAP/materials.csv"
$PY experiments/arrhenius_rank.py --input "$IN" --outdir /tmp/vA --seed 0 >/dev/null
$PY experiments/arrhenius_rank.py --input "$IN" --outdir /tmp/vB --seed 0 >/dev/null
sha256sum /tmp/vA/results/results.csv /tmp/vB/results/results.csv
# 期望：两个哈希完全相同
```

> 唯一可变字段是 `summary.json.generated_at`（UTC 时间戳），**不参与**哈希比对。

## 4. 判据 4 — 判断记录是报告生成的硬前置

**验收项**：删掉快照的判断记录 → 流水线必须失败；恢复后必须重新通过。

```bash
cp "$SNAP/judgments.jsonl" /tmp/j.bak
rm "$SNAP/judgments.jsonl"
$PY -m paper_agent.cli run-all --goal "sulfide ranking"
# 期望：run_status=FAILED，P1 报 "file missing: judgments.jsonl"
cp /tmp/j.bak "$SNAP/judgments.jsonl"
```

## 5. 三级信任模型 — 判断不得支撑结论

**验收项**：`link_conclusion` 拒绝任何非 fact 级证据。

```bash
$PY -m unittest tests.test_provenance -v 2>&1 | tail -20
# 关键用例：test_conclusion_rejects_judgment_evidence / test_invariant_checker_detects_non_fact_binding
```

## 6. 判断留痕与被排除项可反驳

```bash
$PY - "$RUN_ID" <<'PY'
import sys, json
sys.path.insert(0, "core")
from paper_agent.provenance import ProvenanceLedger
prov = ProvenanceLedger(f"runs/{sys.argv[1]}", sys.argv[1])
print("judgments:", len(prov.judgments()), "| excluded:", len(prov.excluded_judgments()),
      "| facts:", len(prov.facts()))
for r in prov.excluded_judgments()[:3]:
    m = r["meta"]
    print(f'  {r["ev_id"]} 排除 {m["subject"]}：{m["rationale"]}')
PY
```

## 7. 报告与证据绑定

```bash
cat runs/$RUN_ID/report.md
# 检查：① "输入来源与判断留痕"章节含快照 id 与内容哈希
#      ② C1–C5 每条都带 [EV-xxxx]
#      ③ 证据索引表含"层级"列（fact / judgment）
$PY -m paper_agent.cli cite --run $RUN_ID --ev EV-0001     # judgment 级示例
$PY -m paper_agent.cli cite --run $RUN_ID                  # 列出全部证据
```

## 8. 离线可跑性（判据 5）

**验收项**：无网络、无 key、无第三方库也能跑通主线。

```bash
$PY -c "import sys; mods=[m for m in ('requests','pandas','numpy') if m in sys.modules]; print('已加载第三方库:', mods)"
# 期望：已加载第三方库: []  （核心只用标准库）
```

---

# 第二部分 · legacy 路径（内置演示语料，回归用）

> 以下用例演示的是**早期内置演示语料**路径，用于保证重构无回归。
> **必须**先禁用快照，否则会走快照主线而与断言不符。

```bash
export PAPER_AGENT_SNAPSHOT=none
```

## 9. 端到端正常路径

```bash
bash demo/demo_e2e.sh        # 期望末行 DEMO_E2E_OK
```

## 10. 四大故障恢复用例

```bash
bash demo/demo_failure.sh    # 期望 DEMO_FAILURE: 8 passed, 0 failed
```

逐用例手动执行方式见 `docs/redesign-decisions.md` 与 `demo/demo_failure.sh` 内注释
（用例 A 重试 / B 降级 / C 断点续跑 / D 复现 FAIL）。

## 11. 单元测试

```bash
$PY -m unittest discover -s tests -p "test_*.py"
# 期望：Ran 88 tests ... OK
```

---

# 第三部分 · 数据源核验

## 12. 数据源探针（离线可复跑）

```bash
$PY tools/probe_obelix.py --input data/external/obelix/all.csv
# 期望：n_rows 599 / usable 562 / upper_bound 37 / doi_coverage 1.0

# 联网核对 DOI 可解析性（可选，需网络）
$PY tools/probe_obelix.py --input data/external/obelix/all.csv --doi-sample 10
# 期望：crossref 10/10、openalex 10/10
```

## 13. 重新生成快照（离线）

```bash
$PY tools/freeze_snapshot.py --goal "sulfide solid electrolyte ionic conductivity ranking"
# 期望：ok=true、verify_problems=[]、stats.in_scope_rows 约 130
```

---

# 第四部分 · 第二批（联网检索 / 判断 / 异常打断）

## 14. 联网文献腿（需网络；只取元数据，不抓全文）

```bash
$PY -m paper_agent.cli search --goal "argyrodite Li6PS5Cl ionic conductivity" --rows 5
# 期望：ok=true，hits 含真实 DOI/标题/作者/年份，errors 为空
```

离线回归（不联网）：`$PY -m unittest tests.test_litsearch -v` → 20 用例。

## 15. 三段式冻结：prepare → （推理）→ commit

```bash
# 1) 取待判对象（离线可用）
$PY -m paper_agent.cli freeze --goal "sulfide solid electrolyte ionic conductivity ranking" --prepare
# 期望：pending_id / families（42 个化学族）/ rule_scope / rule_queries

# 2) 产出裁决 JSON（模型或人工）：{"queries":[...],"families":{族:verdict}}
#    三种形状都接受：扁平映射、列表带理由、嵌套 {族:{verdict,reason}}

# 3) 提交裁决
$PY -m paper_agent.cli freeze --commit <PENDING_ID> --verdicts <file> \
    --judged-by model --model-name <name>
# 期望：ok=true、stats.judged_by=model、stats.model=<name>，并写出新快照
```

**单元级验证"判断确实改变结果"**（判据 2）：

```bash
$PY -m unittest tests.test_freezing -v 2>&1 | grep -A2 model_judgment_changes_scope
# 期望通过：规则式 in_scope 130 行 ≠ 模型裁决 in_scope 368 行
```

## 16. 异常驱动打断（判据 3）

```bash
# 用搜不到东西的检索式触发零命中
$PY tools/freeze_snapshot.py --goal "zzzqqq" --literature network \
    --query "zxqvbnmklpoiuytrewq" --rows 3 --root /tmp/x
echo "退出码=$?"   # 期望 3（停下）
# 输出应含：异常码列表 + 每项的 --ack 确认方式 + "流程已停下"
# 且**不会写出任何快照**
```

人工确认后放行：

```bash
$PY tools/freeze_snapshot.py --goal "..." --ack zero_hits --ack judge_hit_rate
```

**注意**：**低对接率不是异常**（实测文献腿 373 篇 ∩ 数据腿 222 篇 = 8 篇，属正常）。
回归用例：`tests.test_anomaly.TestNoOverlap.test_low_join_rate_is_NOT_anomaly`。

## 17. 反判据：模型判断是否只是装饰

```bash
# 自检：应当判定为装饰品 → 退出码 5
$PY tools/compare_judges.py --goal "sulfide solid electrolyte ionic conductivity" --judge-b rule
echo "退出码=$?"   # 期望 5

# 离线对比（预设模型响应）
$PY tools/compare_judges.py --goal "..." --responses /tmp/model_responses.json
# 期望：退出码 0、列出裁决差异

# 真实模型（需 OpenAI 兼容端点）
export PAPER_AGENT_LLM_BASE_URL=... PAPER_AGENT_LLM_MODEL=... PAPER_AGENT_LLM_API_KEY=...
$PY tools/compare_judges.py --goal "..."
# 退出码 0 = model_matters；5 = model_is_decorration（可接 CI 当失败）
```

## 18. 三维度离线回归

```bash
$PY -m unittest discover -s tests -p "test_*.py"
# 期望：Ran 205 tests ... OK
```

---

# 第五部分 · 审计交付包

```bash
SNAP=<snapshot_id>; RUN_ID=<run_id>
mkdir -p audit-pack
cp runs/$RUN_ID/state.json            audit-pack/
cp runs/$RUN_ID/events.jsonl          audit-pack/
cp runs/$RUN_ID/provenance.jsonl      audit-pack/
cp runs/$RUN_ID/conclusions.jsonl     audit-pack/
cp runs/$RUN_ID/verification/verification.json audit-pack/
cp runs/$RUN_ID/report.md             audit-pack/
cp -r snapshots/$SNAP                 audit-pack/input-snapshot/
cp HOW-TO-VERIFY.md                   audit-pack/
tar -czf audit-pack.tar.gz audit-pack
```

**机器可校验要点**：

- `provenance.jsonl` 每条含 `ev_id / tier / kind / ref / sha256 / producer_step`
- `conclusions.jsonl` 每条 `evidence_ids` 必须全部存在**且全部为 fact 级**
- 快照目录逐文件哈希必须与 `manifest.json` 一致
- `events.jsonl` append-only，时间戳单调不减
