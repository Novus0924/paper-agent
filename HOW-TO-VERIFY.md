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
# 期望：Ran 242 tests ... OK
#   含 test_security_scan.py 的 14 项安全防御专项用例
#       test_recovery.py 的 P5 幂等门禁回归用例 test_case_F2
#       test_plugin_tools.py 的 9 项插件薄壳安全用例（JS 侧用 node 实跑验证）
#       test_test_isolation.py 的 3 项测试隔离元测试
```

---

## 6. AGH 联调（拿到 API Key 后）

> 若插件已装好（`agh package status` 显示 `paper-agent-tools` 为
> `desired=enabled actual=running trusted=true`），可**跳过安装直接看证据**——
> `evidence/` 下已有真实导出的账本。

```bash
# ① 确认插件就位
<agnes.mjs> package status --profile <profile>

# ② 找会话 id 并导出（★ 不需要 TTY，也不依赖 `agh sessions list`）
#    会话 id 直接查 sqlite：
#      ~/.agh/data/tables/_40agnes_2fdaemon.db
#      表 session_workspaces → session_key / title / last_seq
#    详细说明见 evidence/README.md「复现方法」。
<agnes.mjs> export <SESSION_ID> --format agnes --profile <profile> \
            -o evidence/session-<SESSION_ID>.jsonl
```

### ★ 验收项：核对内容真实性（**别只确认文件存在**）

```bash
# 一键复核（强烈推荐）：逐行解析 + 核对 call/result 配对 + 工具覆盖率 + 涉及的 run
python evidence/verify_export.py evidence/session-6139563e.jsonl
```

预期关键输出：

```
总行数 1364 | JSON 解析失败 0
tool/call 71 | tool/result 71
成功配对 71 | 孤立 call 0 | 孤立 result 0
★ 插件工具覆盖: 7/7
★ 插件调用合计: ok=32 fail=2
```

**赛事闸门要求 ≥6 条工具交互记录**，本证据单文件即有 71 条 `tool/call`。

### ⚠️ 手工 grep 时的三个坑

```bash
# ✅ 正确的记录类型是tool/call 与 tool/result（**斜杠**，不是下划线）
grep -c '"type":"tool/call"'   evidence/session-6139563e.jsonl   # → 71
grep -c '"type":"tool/result"' evidence/session-6139563e.jsonl   # → 71

# ❌ 下面这种 grep 永远返回 0 —— 记录类型里没有下划线形式
# grep -c '"tool_use"\|"tool_result"' session.jsonl
```

1. **记录类型是 `tool/call` / `tool/result`（斜杠）**，不是 `tool_use` / `tool_result`。
2. **工具名位置不统一**：`tool/call` 在 `data.name`；`tool/result` 在 **`origin`**
   （形如 `"tool:sciret_plan"`），`data` 里没有名字字段。配对要靠 **`data.toolUseId`**。
3. **账本里出现 `kill_after_p2` 不代表真的杀过进程**——那是 `tool_describe` 返回的
   schema 枚举文本。真实容错证据在 `runs/*/state.json` 的 `attempts` 与
   `events.jsonl` 的 `degrade` 事件里。

---

## 7. 审计交付包

一键生成（推荐，脚本已处理缺失文件与文件名通配）：

```bash
bash audit-pack-template/build_audit_pack.sh <RUN_ID>
# → audit-pack/  +  AUDIT_PACK_OK
```

| 文件 | 来源 |
| --- | --- |
| `state.json` | `runs/<run_id>/state.json` |
| `events.jsonl` | `runs/<run_id>/events.jsonl` |
| `provenance.jsonl` | `runs/<run_id>/provenance.jsonl` |
| `conclusions.jsonl` | `runs/<run_id>/conclusions.jsonl` |
| `session-*.jsonl` | `evidence/session-*.jsonl`（通配拷贝，按会话 id 命名） |
| `verify_export.py` | `evidence/verify_export.py`（复核工具，一并带走） |
| `verification.json` | `runs/<run_id>/verification/verification.json` —— ⚠️ **仅 materials 工作流产出**；research 的 R4 结果在 `toolcalls/` 与 `events.jsonl` 里，脚本会 `(skip)` 属正常 |
| `HOW-TO-VERIFY.md` | 本文件 |

```bash
tar -czf audit-pack.tar.gz audit-pack
```

> 🔴 **打包前必做**：`*.jsonl` 含本机绝对路径（`C:\Users\...`、`D:\workBubbyStore\...`），
> 开源发布前需人工审查/脱敏。

