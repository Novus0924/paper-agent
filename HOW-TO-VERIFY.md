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

**验收项**：`run-all` 五步全部 DONE，`degraded=false`，`verification=PASS`。

```bash
$PY -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity ranking"
# 取出 RUN_ID（JSON 输出字段 run_id）
$PY -m paper_agent.cli run-all --run $RUN_ID
```

判定：输出 JSON 中 `run_status=="DONE"` 且 `results.P4_verify.status=="PASS"`。

也可一键跑：

```bash
bash demo/demo_e2e.sh
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
# 期望：Ran 152 tests ... OK（含 test_security_scan.py 的 14 项安全防御专项用例，
#       以及 test_recovery.py 的 P5 幂等门禁回归用例 test_case_F2）
```

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
