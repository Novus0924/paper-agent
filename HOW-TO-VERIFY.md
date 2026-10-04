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

**验收项**：五步全部 DONE，`degraded=false`，`verification=PASS`。

### 1a. 模型驱动主导路径（推荐；等价 AGH 会话内逐步调用）

```bash
$PY -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking"
# 取出 RUN_ID（JSON 输出字段 run_id）
$PY -m paper_agent.cli step-driven --run $RUN_ID --step P1_lit_search
$PY -m paper_agent.cli step-driven --run $RUN_ID --step P2_clean_data
$PY -m paper_agent.cli step-driven --run $RUN_ID --step P3_run_experiment
$PY -m paper_agent.cli step-driven --run $RUN_ID --step P4_verify
$PY -m paper_agent.cli step-driven --run $RUN_ID --step P5_report
$PY -m paper_agent.cli next   --run $RUN_ID     # 只读，观察剩余步骤
$PY -m paper_agent.cli finish --run $RUN_ID     # RUNNING -> DONE
```

判定：每次 `step-driven` 返回 `next_tool_candidates` / `remaining_steps`；
`finish` 返回 `run_status=="DONE"`。**关键点**：若不逐步调用，run 会停留在 `RUNNING`，
不会自行完成 —— 编排主体是模型。

### 1b. 一次性兜底路径（非主导，仅供离线确定性复现）

```bash
$PY -m paper_agent.cli run-all --run $RUN_ID
```

判定：输出 JSON 中 `run_status=="DONE"` 且 `results.P4_verify.status=="PASS"`。

也可一键跑：

```bash
bash demo/demo_e2e.sh
```

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
bash demo/demo_e2e.sh
```

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

### 1c. P1 文献检索来源 — 在线 arXiv / 离线本地

P1 检索后端可切换，**默认 `auto`**（先试 arXiv，不可用自动回落本地语料）：

```bash
# 实时检索 arXiv（不局限于内置 5 篇语料）
$PY -m paper_agent.cli run-all --goal "argyrodite solid electrolyte conductivity" \
    --lit-source arxiv
# 判定：results.P1_lit_search.source=="arxiv"
#       且 runs/<run_id>/literature/arxiv_snapshot.json 已生成（快照冻结）

# 纯离线确定性基线
$PY -m paper_agent.cli run-all --goal "..." --lit-source local
# 判定：results.P1_lit_search.source=="local"
```

**确定性验证（快照冻结契约）**：在线检索只在 run 首跑发生一次，之后同一 run
复跑/续跑**只读快照、不再联网**。

```bash
# 1) 首跑得到 arxiv 快照
RID=$(... run-all --lit-source arxiv ... | jq -r .run_id)
ls runs/$RID/literature/arxiv_snapshot.json

# 2) 删掉检索输出后重跑 P1：若仍能重建且 note=="snapshot_reused"，即证明未联网
rm runs/$RID/literature/literature_hits.json
# （P1 已 DONE，如需复跑该步请用 run-step 到新 run；此处只需确认快照被读取）

# 离线单测直接覆盖该契约（不依赖网络）：
$PY -m unittest tests.test_litsearch -v
```

**可选在线用例**（默认不定义，故常规运行零 skip）：

```bash
RUN_ONLINE=1 $PY -m unittest tests.test_litsearch.TestOnlineArxivSearch -v
```

---

## 2. 实验确定性 — 两次执行 SHA-256 一致

**验收项**：相同输入两次执行实验脚本，`results.csv` 逐字节一致。

```bash
IN=runs/$RUN_ID/clean/conductivity_clean.csv
$PY experiments/arrhenius_rank.py --input $IN --outdir runs/$RUN_ID/verify_a --seed 0
$PY experiments/arrhenius_rank.py --input $IN --outdir runs/$RUN_ID/verify_b --seed 0

# Git Bash / Linux
sha256sum runs/$RUN_ID/verify_a/results/results.csv \
          runs/$RUN_ID/verify_b/results/results.csv
# 两个哈希必须完全相同

# Windows PowerShell
certutil -hashfile runs/$RUN_ID/verify_a/results/results.csv SHA256
certutil -hashfile runs/$RUN_ID/verify_b/results/results.csv SHA256
```

> 注意：`summary.json` 中的 `generated_at` 为唯一可变时间戳，**不参与**哈希比对；
> 复现校验只对 `results.csv` 与结构化字段做 SHA‑256 / 容差比对。

---

## 3. 故障用例

一键自动化：

```bash
bash demo/demo_failure.sh
```

或逐用例手动：

### 用例 A：`p1_fail_first`（重试 1 次成功，DONE，degraded=false）

```bash
$PY -m paper_agent.cli run-all --goal "sulfide solid electrolyte conductivity" \
     --chaos p1_fail_first
# 判定：run_status==DONE, degraded==false
# 验证恰有 1 次 retry 事件：
grep -c '"type": "retry"' runs/$RUN_ID/events.jsonl   # 期望 1
```

### 用例 B：`p1_fail_all`（重试耗尽触发降级，DONE，degraded=true，含 degrade 事件）

```bash
$PY -m paper_agent.cli run-all --goal "garnet solid electrolyte" --chaos p1_fail_all
# 判定：run_status==DONE, degraded==true
grep -c '"type": "degrade"' runs/$RUN_ID/events.jsonl   # 期望 >=1
```

### 用例 C：P2 完成后中断，resume 只跑剩余步骤

```bash
$PY -m paper_agent.cli plan --goal "argyrodite conductivity ranking"   # 得 RUN_ID
$PY -m paper_agent.cli run-step --run $RUN_ID --step P1_lit_search
$PY -m paper_agent.cli run-step --run $RUN_ID --step P2_clean_data
# 模拟 P2 后进程被杀（P3/P4/P5 仍 PENDING），断点续跑：
$PY -m paper_agent.cli resume --run $RUN_ID
# 判定：run_status==DONE；results.P1/P2.reused==true；attempts.P1==attempts.P2==1
```

### 用例 D：`mutate_summary`（复现 FAIL，P4 FAILED，run FAILED，5 项校验可查）

```bash
$PY -m paper_agent.cli run-all --goal "sulfide ranking" --chaos mutate_summary
# 判定：run_status==FAILED, results.P4_verify.status==FAIL
$PY -c "import json;d=json.load(open('runs/$RUN_ID/verification/verification.json',encoding='utf-8'));print(d['status'], [c['name'] for c in d['checks']])"
# 期望：FAIL 且 5 项校验名齐全（results_csv_sha256 / n_rows /
# top3_material_id_set / top3_scores_positional / family_mean_log10_cond）
```

---

## 4. 证据与报告

**验收项**：`report.md` 每条结论携带 `[EV-XXXX]`；`sciret_cite` 可回查 DOI / SHA‑256。

```bash
$PY -m paper_agent.cli report --run $RUN_ID
# 检查 report.md 中 C1-C5 是否都带 [EV-xxxx]
cat runs/$RUN_ID/report.md

# 回查文献证据（输出 DOI + 作者 + 年份）
$PY -m paper_agent.cli cite --run $RUN_ID --ev EV-0001
# 回查文件证据（输出 sha256 前 16 位）
$PY -m paper_agent.cli cite --run $RUN_ID --ev EV-0009
# 列出全部证据
$PY -m paper_agent.cli cite --run $RUN_ID
```

证据一致性机器核验（每条结论引用的 EV 必须存在于 provenance.jsonl）：

```bash
$PY - <<'PY'
import json, sys
run = sys.argv[1] if len(sys.argv)>1 else ""
import glob
files = glob.glob(f"runs/{run}/") if run else []
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

全量单测（含上述契约，离线强制）：

```bash
python -m unittest discover -s tests -p "test_*.py"
# 期望：200+ 项单测 ... OK  （零 skip —— 单测默认 paper-agent_LIT_SOURCE=local 强制离线）
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

其中 `tests/test_data_integrity.py` 是数据红线的守门测试（8 项离线 + 1 项可选联网）：
`tests/test_litsearch.py` 是 P1 检索后端的守门测试（15 项，含快照冻结契约）。

```bash
python -m unittest tests.test_data_integrity -v
# 可选：真实联网核验 DOI 可解析性（默认跳过）
RUN_ONLINE=1 python -m unittest tests.test_data_integrity.TestOnlineDoiResolvable -v
```

守门内容：DOI 形态与可疑字符、语料 DOI 唯一性、CSV↔语料双向一致（无孤儿文献）、
**材料年份必须等于所引文献年份**、同 formula 家族一致，以及「历史错误 DOI 残留」回归护栏。

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
# 期望：200+ 项单测 ... OK
```

**证据的真实来源**（不再提供脱敏自证账本）：

```bash
# AGH daemon 原生写的会话事件库（含完整信封 + integrity 哈希链）
#   ~/.agh/data/sessions.db   —— events 表
# 或用官方导出
agnes export <SESSION_ID> --format agnes -o session.jsonl
grep -c '"type":"tool/call"'   session.jsonl   # 期望 >=6（连续结构化）
grep -c '"type":"tool/result"' session.jsonl
```

> 真实信封形如 `{seq,ts,id,type,actor,origin,trust,source_event_seqs,
> data:{toolUseId,name,args,...},integrity_mode,integrity_prev,integrity_digest}`。
> 原始导出含本机绝对路径，按红线不入 git。打通步骤与当前卡点
> （第三方工具尚未暴露给模型）见 `evidence/AGH-真实会话落地报告.md`。

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
# 期望：200+ 项单测 ... OK
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

---

## 8. 科研全流程（research）· 量化验证 · 异常恢复（PRD v0.3）

> 对应 PRD F-1~F-7 与 F-4.8；逐条实现映射见 `docs/PRD-v0.3-需求实现映射.md`。

### 8a. research 工作流端到端（R1–R6）

```bash
$PY -m paper_agent.cli run-all --workflow research \
    --goal "sulfide solid electrolyte ionic conductivity" --lit-source local
# 期望：run_status == "DONE"，degraded == false（离线内置语料）
RID=$(...)   # 从输出 JSON 取 run_id

# 产物齐备性（应全部存在）
ls runs/$RID/literature/research_hits.json runs/$RID/reading/reading_report.json \
   runs/$RID/analysis/innovations.json runs/$RID/analysis/gaps.json \
   runs/$RID/factcheck/factcheck.json runs/$RID/writing/review.md \
   runs/$RID/writing/references.bib runs/$RID/review/review_report.md runs/$RID/report.md

$PY -m paper_agent.cli report --run $RID
# 判定：report.md 含「顶层状态: DONE」+ C1..C5 结论，每条带 [EV-XXXX] 证据标记
```

**验收项**：六步全部 DONE；report.md 的 C1–C5 均绑定 `[EV-XXXX]`；综述每句带 `[doc_id]` 引用
（无依据句标 `[需补充引用]`）。

### 8b. 单点能力（也可经 AGH 会话按 `sciret_*` 调用）

```bash
$PY -m paper_agent.cli search-papers --goal "sulfide solid electrolyte" --sources arxiv,openalex,crossref
$PY -m paper_agent.cli parse-paper   --source 2301.12345 --allow-network   # 或本地 PDF 路径
$PY -m paper_agent.cli analyze-paper --run $RID
$PY -m paper_agent.cli verify-facts  --run $RID
$PY -m paper_agent.cli write-review  --run $RID
$PY -m paper_agent.cli self-review   --run $RID
```

### 8c. 量化验证（F-7.1~F-7.4）

```bash
$PY -m paper_agent.cli eval
```

**验收项**：输出 `reports.{search,read,innovation,citation}` 四套指标；`search` 含 **纯关键词基线**
对比与 `failures` 列表；`innovation` 含 **混淆矩阵**；每套均带 `scale_note`（声明为 demo 规模标注）。

参考值（离线 demo，会随语料/标注变化）：search Recall 1.000 / NDCG@10 0.987（基线 0.900 / 0.662）；
read 三项准确率 1.000；innovation 识别率 0.80 / 幻觉率 0.00；citation 准确率 1.000 / 幻觉率 0.00。

### 8d. 异常恢复三场景（F-4.8）

```bash
# ① 外部 API 超时降级：SS 源超时 → 标注不可用并切源，任务不中断
$PY -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos ss_timeout

# ② PDF 解析失败恢复：无文本层 → OCR 不可用 → 标「低质量解析/低置信度」
$PY -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos scan_pdf

# ③ 长任务中断恢复：第 N 篇失败跳过继续（不阻塞整体）
$PY -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos batch_fail_at=2

# ③' 真实崩溃 + 断点续跑：子进程被 SIGKILL(137) → resume 续跑
$PY -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos kill_after_r3
echo "exit=$?"   # 期望 137
$PY -m paper_agent.cli resume --run <RUN_ID>
# 期望：run_status == "DONE"，已 DONE 步骤直接复用，events/provenance 账本 append-only 完整
```

**验收项**：
- 场景① `run_status==DONE`，`research_hits.json` 的 `unavailable_sources` 含 `semantic_scholar`，`n_documents>=1`；
- 场景② `reading_report.scanned_or_low_conf>0`，且对应笔记 `status=="scanned"`、`confidence=="low"`；
- 场景③ `reading_report.n_failed==1`（失败项 doc_id 可查）、`n_read>=1`，且 R3–R6 仍全部 DONE；
- 场景③' 先退出码 137，`resume` 后六步全 DONE，`report.md` 存在。

---

# 第六部分 · AGH 插件接入核验（无需 AGH / daemon / TTY）

插件本身是否健康，与"AGH 那边配好了没有"是两件事。下面两个脚本把前者单独隔离出来，
**安装前后都能跑**，用来定位故障到底在插件侧还是 AGH 侧（安装步骤见插件安装指南）。

```bash
cd <ROOT>

# ① 静态自检（离线，13 项）：模块加载 / package.json 声明 / inject 一致性 / apply 注册 /
#    工具数与命名规范 / description / meta 8 键 / 只读工具的审批等级 / parameters schema /
#    execute / Skill 注册 / 薄壳零依赖
node tools/verify-plugin-offline.mjs
# 期望：13 项 PASS；注册工具数 = 20；meta 8 键校验 = PASS；inject = ["extension","skills"]

# ② 端到端自检（真调 Python CLI，6 项）：解释器可用 / 加载 / plan / status / cite / H1 边界
node tools/verify-plugin-e2e.mjs --cleanup
# 期望：6 项 PASS；plan 返回 ok:true + run_id；非法 run_id ../../etc/passwd 被 H1 拦下
```

两个脚本均 `0=通过 / 1=失败`，支持 `--json`（机器可读，CI 可直接解析）。

**判定口径**：

| 观测 | 结论 |
|---|---|
| 两个都 PASS | 插件与 Python 核心均健康 ⇒ 故障在 AGH 侧（环境变量注入 / daemon 启动 cwd / trust+enable） |
| ① FAIL | 插件自身问题（工具面 / meta / schema / 依赖），先修插件 |
| ② 的 `python.available` FAIL | 解释器路径或 `core/` 位置不对，与 AGH 无关 |
| ② 的 `guard.h1.runid` FAIL | run_id 边界校验被破坏 —— 属安全问题，优先修 |

> 这两个脚本本身也在 CI 里被守门：`tests/test_docs_consistency.py::TestPluginSmokeScripts`
> 断言它们**存在且真实通过**，并有一个负向用例确认"工具数被改错时必须 FAIL"，
> 避免自检退化成永远绿的摆设。

> 注：脚本只用**异步 `spawn`**（与插件实现一致），不用 `spawnSync`/`execFileSync` ——
> 个别受限环境会把同步建进程判 `EBUSY`，从而产生与真实故障无关的假报错。
