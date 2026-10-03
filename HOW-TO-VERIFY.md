# HOW‑TO‑VERIFY — 验收核验操作手册

本手册给出**每一条验收用例的执行步骤与哈希比对命令**。
所有命令在项目根目录执行；Windows 下 `export` 用 `set`，`sha256sum` 用
`certutil -hashfile <file> SHA256` 或 Git Bash 的 `sha256sum`。

> 约定：`ROOT` = 项目根目录；`RUN_ID` = 某次 run 实例 id（形如
> `run-YYYYMMDD-HHMMSS-xxxxxx`）。

```bash
cd <ROOT>
export PYTHONPATH=<ROOT>/core
PY=python
```

---

## 1. 业务流水线 — 正常路径

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

（或运行 `tests/test_provenance.py`，其中 `test_conclusion_requires_existing_evidence`
即校验该不变量。）

---

## 5. 单元测试

```bash
python -m unittest discover -s tests -p "test_*.py"
# 期望：Ran 159 tests ... OK  （零 skip —— 单测默认 paper-agent_LIT_SOURCE=local 强制离线）
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

## 6. AGH 联调（拿到 API Key 后）

```bash
pnpm install --frozen-lockfile
pnpm --filter @agnes/cli build:local
node packages/cli/dist/local/agnes.mjs serve
agnes plugins install file:./plugins/paper-agent-tools
agnes plugins trust ext:paper-agent/tools
agnes plugins enable ext:paper-agent/tools
agnes -p "你的科研目标 prompt"
agnes export SESSION_ID --format agnes -o session.jsonl
```

**验收项**：`session.jsonl` 至少含 ≥6 条连续 `tool_use` / `tool_result` 交互记录：

```bash
# 统计 tool_use / tool_result 事件数
grep -c '"tool_use"\|"tool_result"' session.jsonl   # 期望 >=6（连续结构化）
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

## 7. 审计交付包

从完成的 run 收集以下文件打包（见 `audit-pack-template/` 结构）：

| 文件 | 来源 |
| --- | --- |
| `state.json` | `runs/<run_id>/state.json` |
| `events.jsonl` | `runs/<run_id>/events.jsonl` |
| `provenance.jsonl` | `runs/<run_id>/provenance.jsonl` |
| `conclusions.jsonl` | `runs/<run_id>/conclusions.jsonl` |
| `agh-session.jsonl` | 联调导出的 `session.jsonl` |
| `verification.json` | `runs/<run_id>/verification/verification.json` |
| `HOW-TO-VERIFY.md` | 本文件 |

```bash
mkdir -p audit-pack && cp \
  runs/$RUN_ID/state.json \
  runs/$RUN_ID/events.jsonl \
  runs/$RUN_ID/provenance.jsonl \
  runs/$RUN_ID/conclusions.jsonl \
  runs/$RUN_ID/verification/verification.json \
  HOW-TO-VERIFY.md \
  audit-pack/
cp session.jsonl audit-pack/agh-session.jsonl 2>/dev/null || true
tar -czf audit-pack.tar.gz audit-pack
```



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
