# 交接文档（HANDOFF）— paper-agent

> 面向**接手本项目的下一个编程工具 / 工程师**。读完本文即可在无上下文记忆的情况下继续推进。
> 最后更新：**2026-10-03**（真实数据改造 + 第二批增强线之后）。
> **本文以仓库实际状态为准**；若与代码不一致，以 `git log` 与代码为准。

---

## 0. 30 秒速览

- **项目**：`paper-agent` —— 基于 **AGH（Agnes Harness）** 的可审计、可复现、可故障恢复的科研 Agent 流水线（JS 薄壳工具 + Python 核心业务 + 确定性实验），用于 2026 江苏省 AI+科学与工程创新实践黑客松。
  输入是**真实公开数据集**（OBELiX，599 条锂固态电解质的实验实测离子电导率，每条带原始论文 DOI），不是人工预制的演示数据。
- **工程完成度**：阶段 1–8 **全部完成并通过自验证**（单测 **200+ 项**、端到端 demo、四大故障用例 + 真实进程崩溃/断点续跑用例 E2/E3 + P5 幂等复用 F、审计不变量全 PASS）。
- **阶段 9–10（PRD v0.3 实现，2026-10-03）**：按负责人 `科研智能体需求文档 v0.3` 实现**科研全流程工作流 `research`（R1–R6）** + **量化验证（F-7.1~F-7.4）** + **三类异常恢复（F-4.8）**，单测扩至 **200+ 项**，插件扩至 **20 工具 + 1 Skill**。逐条映射见 `docs/PRD-v0.3-需求实现映射.md`，详见本文 §9。分支 `fix/agh-driven`（隔离克隆 `paper-agent-fix`），fast-forward 推送远端 `mike`。
- **AGH 联调已真实跑通**：插件经交互 TTY 确认安装 + trust + enable，`desired=enabled actual=running trusted=true`；两次真实 `-p` 会话共 21 次 tool/call + 21 次 tool/result，**7 个 sciret_* 工具全部出现**（含 `sciret_resume` 的 kill_after_p2 崩溃恢复演示）。导出在 `evidence/session.jsonl`（首轮）与 `evidence/session-full.jsonl`（崩溃恢复轮，同一 workspace 会话追加）。
- **编排改为模型驱动（阶段 7 重构）**：核心层新增**单步**工具 `sciret_step_driven`（一次只推进一步并返回决策上下文）、`sciret_next`、`sciret_finish`，插件共 **20 工具 + 1 Skill**（`.agh/skills/sciret-research-pipeline`）；`run-all` 降级为**确定性兜底**。真实证据由 AGH daemon 原生写出（`~/.agh/data/sessions.db`，含完整信封 + integrity 哈希链），打通步骤与当前卡点见 `evidence/AGH-真实会话落地报告.md`（注：此前的脱敏自造格式账本已删除）。
- **数据与计算修复**：5 篇文献 DOI 经 Crossref 权威核验更正；CSV 材料–年份–DOI 自洽；稳定性改由文献活化能导出（不再硬编码常数）；新增 Arrhenius σ(60°C) 外推。
- **P1 检索后端可切换（阶段 8）**：新增 `core/paper_agent/litsearch.py`（零依赖，仅标准库）——`--lit-source local|arxiv|auto`，默认 `auto`；`arxiv` 走 arXiv 官方 Atom API 实时检索，**不再局限于内置 5 篇语料**。确定性靠**快照冻结**保证：在线结果首跑写入 `runs/<id>/literature/arxiv_snapshot.json`，同一 run 复跑只读快照、不再联网，快照本身作为 `data` 证据留证。单测通过 `paper-agent_LIT_SOURCE=local` 强制离线（`tests/__init__.py`），故零 skip。**边界**：P1 与 P2/P3 解耦——换课题能换到真文献，但实验数据仍取 `data/conductivity_raw.csv`。
- **红线**：密钥只放环境变量 / `.env`（gitignore）；所有交付物收敛在 `paper-agent/` 项目目录内；数值只来自公开数据集与本地确定性计算，实验数据标注 `as-reported`，**严禁伪造**；**不抓论文全文**；**判断不得进结论**。

> AGH 会话逐步操作手册（含每步预期输出与 8 条故障对照表）：`docs/AGH-SESSION-RUNBOOK.md`；
> 手册含两条可直接粘贴的会话 prompt（5A 驱动既有流水线、5B 驱动新的检索/判断/冻结三件套）。

---

## 1. 与改造前的对比（别再按旧口径理解本项目）

| 维度 | 改造前（≤ `8933f5c`） | 现在（`8b0d530`） |
|---|---|---|
| 主数据源 | 人工预制 **7 行**演示 CSV | **OBELiX 599 行**真实数据（562 行可用） |
| 文献来源 | 内置 **5 篇**手写卡片 | 数据集自带 **223 个真实 DOI**；增强线可联网检索 Crossref/OpenAlex |
| 打分口径 | 自拟权重 `0.6/0.25/0.15` | **去掉全部自拟权重**，只按实测值排序 + 族统计 |
| 信任模型 | 二级（证据 / 结论） | **三级：fact / judgment / conclusion**，代码级强制 |
| 判断记录 | 无 | 43 条 judgment（含 36 条被排除项与理由），随快照自包含 |
| 可复现边界 | 声称全链路可复现 | 只承诺"**冻结快照之后**"逐字节可复现 |
| 异常处理 | 仅技术故障重试/降级 | 增加**判断类异常打断**（4 条规则 + 人工确认闸门） |
| 单测 | 39 | **200+** |
| AGH 工具 | 7 | **10** |
| AGH 会话 | 声称已闭环（旧机器，证据不在本机） | **本机未安装、未实跑** |

> 旧数据 `data/literature.json` 与 `data/conductivity_raw.csv` **已降级为 legacy 降级路径**，
> 不再参与主线，只用于回归测试（用 `PAPER_AGENT_SNAPSHOT=none` 切换）。
> 新手别误以为它们是主输入。

---

## 2. 提交历史（最新在上）

```
121aae5  docs: HANDOFF 重写为改造后状态（原文档停留在 7 工具/演示数据口径）
c7466ed  fix(sources): 输入数据结构不符时响亮失败（堵住静默产出垃圾的洞）
471477f  docs: AGH 会话内主路径操作手册（含预期输出与故障对照表）
a915614  fix(plugin): Python 解释器多候选回退 + 可操作的错误提示
d64a74d  fix(plugin): 项目根自动推导，不再强依赖环境变量注入
924b505  docs: 判据 2 与反判据的真实模型结论（DeepSeek 实测）
e9f55c3  docs: 第二批文档与验收（含两处实测修正、判据状态如实标注）
9fcb002  feat(freezing): 三段式冻结流程 + CLI 命令 + AGH 插件 3 工具
70e6e6f  feat(judge): 可插拔判断器 + 反判据对比（含 AGH 模型调用路径的实测否证）
ecf1a57  feat(anomaly): 双腿 DOI 对接 + 异常驱动打断（D7）
dcdcbe3  feat(litsearch): 联网文献腿（Crossref / OpenAlex 元数据检索）
7cd47ec  docs: 红线措辞修订 + 入口文档更新（第一批收尾）
22d3f64  demo: 双轨演示（真实数据主线 + legacy 回归）
0148e3d  feat(pipeline): 主链路切换到真实数据集（快照消费 + 真实清洗 + 实测值排序）
fea6757  feat(sources): 外部数据源适配层（OBELiX 数据腿）
80f1535  feat(snapshot): 冻结输入快照机制（复现契约的载体）
98d7e07  feat(provenance): 三级信任模型（fact / judgment / conclusion）
41c2d4e  tools: OBELiX 技术探针通过（改造方案闸门验证）
4429615  docs: 改造设计方案与竖版流程图（10 项决定 + 差异清单 + 红线修订）
8933f5c  Merge pull request #1 from Novus0924/leyon     ← 改造前的原作者提交（已推送）
```

- 分支：`main`；远端：`origin git@github-w:Novus0924/paper-agent.git`
  （SSH 别名 `github-w` → `~/.ssh/id_gh_work` → 认证到 GitHub 账号 **Novus0924**）
- **状态：19 个提交未推送**（按项目纪律，未经明确许可不推送）。
- **提交署名已统一为 `Novus0924 <18014082610@163.com>`**（仓库级 `user.name/user.email`
  已写入 `.git/config`）。此前这 19 个提交曾以另一个身份署名，为保证 GitHub 上
  全部提交都关联到你的账号，已用 `git filter-branch --env-filter` 改写
  `origin/main..HEAD` 范围的作者与提交者；**改写前后内容树指纹一致**
  （`c967a59bff3153547fe181c1c3f9f2434f1cf553`），文件内容一字未变，
  因此上面的 SHA 与改写前不同。已推送的历史（原作者的提交）**未改动**。
- ⚠️ **推送前请删掉备份分支** `backup/pre-author-rewrite`：它是改写前的旧历史，
  若用 `git push --all` / `--mirror` 会把旧署名的历史一起推上去。
  确认无误后执行：`git branch -D backup/pre-author-rewrite`
- 权威设计文档：`docs/redesign-decisions.md`（含决定、被否决方案、**两处实测修正**、判据状态）

---

## 3. 目录结构（真实，精确到文件）

```
paper-agent/
├── core/paper_agent/                 # Python 核心（零第三方依赖，仅标准库）
│   ├── state.py                      #   有限状态机 + run 生命周期 + append-only events
│   ├── provenance.py                 #   三级证据账本；link_conclusion 拒绝非 fact 证据
│   ├── snapshot.py                   #   冻结输入快照（逐文件 SHA-256 + 判断批次自包含）
│   ├── sources.py                    #   OBELiX 适配（列名归一 / 值分类 / **结构守卫**）
│   ├── litsearch.py                  #   联网文献腿（Crossref / OpenAlex 元数据）
│   ├── judge.py                      #   可插拔判断器 RuleJudge / ModelJudge + 反判据对比
│   ├── llm.py                        #   模型客户端（含 AGH 路径的实测结论）
│   ├── anomaly.py                    #   双腿 DOI 对接 + 4 条异常规则 + 确认闸门
│   ├── freezing.py                   #   三段式冻结 prepare → 推理 → commit
│   ├── chaos.py                      #   故障注入
│   ├── steps.py                      #   五步调度（快照主路径 + legacy 回退）
│   ├── verify.py                     #   P4 复现验证器（5 项递归容差比对）
│   ├── report.py                     #   P5 报告（判据 4 硬前置）
│   └── cli.py                        #   CLI 入口（stdout 单 JSON）；含 search / freeze
├── experiments/arrhenius_rank.py     # 确定性实验脚本（双 schema 自适应）
├── tools/
│   ├── freeze_snapshot.py            # 冻结快照（prepare / commit / 规则式一步到位）
│   ├── search_literature.py          # 联网检索 CLI
│   ├── compare_judges.py             # ★ 反判据：退出码即判据（0 有用 / 5 装饰品）
│   └── probe_obelix.py               # 数据源探针（只读、可离线复跑）
├── data/
│   ├── external/obelix/all.csv      # ★ 主数据源（599 行，CC-BY-4.0）+ README 署名
│   ├── literature.json               # 内置 5 篇真实 DOI 文献语料（local 来源 / 离线兜底）；legacy 降级路径
│   └── conductivity_raw.csv          # 带缺陷原始数据集（utf-8 BOM，7 行）；legacy 降级路径
├── snapshots/snap-20261002-065225-5e1fe9/   # ★ 冻结输入快照（已入库，供离线主线）
│   ├── manifest.json                 #   文件清单 + SHA-256 + 聚合 content_sha256
│   ├── literature.json               #   文献腿
│   ├── materials.csv                 #   数据腿（599 行）
│   └── judgments.jsonl               #   判断批次（43 条，tier=judgment）
├── plugins/paper-agent-tools/        # AGH 扩展（20 工具，JS 薄壳）
│   ├── package.json                  #   AGH 插件 manifest（对齐官方形态，见 §6）
│   └── index.mjs                     #   工具薄壳（spawn Python CLI，TypeBox 严格 schema）
├── tests/                            # 200+ 项单测
│   ├── _util.py                      # 共享：构建隔离临时根 + make_clean_csv
│   ├── test_state.py                 # 状态机转移/持久化/非法转移/append-only（10）
│   ├── test_provenance.py            # 证据账本/结论绑定/引文（10）
│   ├── test_recovery.py              # 故障用例 A/B/C/D + E2/E3 真实进程崩溃续跑 + F 幂等 + FAILED 终态（9）
│   └── test_repro.py                 # 确定性双跑 SHA-256 + verify 递归容差（11）
├── demo/
│   ├── demo_mainline.sh              # ★ 真实数据主线（14 断言；含判据 4 实测）
│   ├── demo_e2e.sh                   # legacy 路径端到端
│   └── demo_failure.sh               # legacy 路径四大故障用例
├── docs/
│   ├── redesign-decisions.md         # ★ 权威设计文档
│   ├── AGH-SESSION-RUNBOOK.md        # ★ AGH 会话逐步操作手册
│   ├── ai_disclosure.md              # AI 使用边界声明（三级模型口径）
│   ├── sources.md                    # 数据来源声明
│   └── diagrams/                     # 3 张竖版流程图
├── evidence/
│   └── model-judge-comparison.json   # 反判据机读结果（真实模型对比）
├── audit-pack-template/              # 审计交付包模板
├── README.md / HOW-TO-VERIFY.md     # 入口 / 验收手册
└── .env                              # 模型 key（gitignore，绝不入库）
```

---

## 4. 如何验证现状（接手第一步就跑这个）

```bash
# 择一：按本机实际项目根
cd C:/Users/ASUS/Desktop/黑客松/paper-agent      # 或 cd D:/workBubbyStore/hks/paper-agent
# ① 单元测试（200+ 项应全绿）
set PYTHONPATH=C:\Users\ASUS\Desktop\黑客松\paper-agent\core   # 或 export PYTHONPATH="$PWD/core"
python -m unittest discover -s tests -p "test_*.py"
PY="/c/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ⚠️ demo 脚本用 `printenv paper-agent_PYTHON || echo python` 找解释器，
#    而本机 PATH 上**没有 python** → 必须显式传，否则脚本会在第一步就失败。
PYEXP="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ① 单测（200+ 项应全绿）
PYTHONIOENCODING=utf-8 "$PY" -m unittest discover -s tests -p "test_*.py"

# ② 真实数据主线演示（14 断言）
env "paper-agent_PYTHON=$PYEXP" bash demo/demo_mainline.sh

# ③ legacy 回归（demo 脚本内部已自设 PAPER_AGENT_SNAPSHOT=none；
#    外部再设一次是为了双保险，两者都支持）
env "paper-agent_SNAPSHOT=none" "paper-agent_PYTHON=$PYEXP" bash demo/demo_e2e.sh
env "paper-agent_SNAPSHOT=none" "paper-agent_PYTHON=$PYEXP" bash demo/demo_failure.sh

# ④ 反判据自检（应当判定为装饰品 → 退出码 5）
PYTHONPATH="$PWD/core" "$PY" tools/compare_judges.py --goal "sulfide solid electrolyte" --judge-b rule
echo "退出码=$?"   # 期望 5

# ⑤ 快照强校验
"$PY" -c "import sys;sys.path.insert(0,'core');from paper_agent import snapshot as S;print(S.open_snapshot('.').verify())"
# 期望 (True, [])
```

**预期（以上五条均于 2026-10-03 本机实测）**：单测 `200+ 项单测 ... OK`；
② 末行 `DEMO_MAINLINE_OK`（14 passed, 0 failed）；③ `DEMO_E2E_OK` 与
`DEMO_FAILURE_OK`（8 passed, 0 failed）；④ 退出码 `5`；⑤ `(True, [])`。

---

## 5. 设计红线（改代码前必读）

1. **零第三方依赖**：Python 核心只用标准库。新增功能不得 import 非标准库包。
2. **确定性**：相同快照两次运行 `results.csv` 逐字节一致；`summary.json.generated_at`
   是唯一可变字段，**校验时排除**。可用 `paper-agent_MUTATE=1` 触发 P4 FAIL。
3. **append-only 账本**：`events.jsonl` / `provenance.jsonl` / `judgments.jsonl` 只追加不修改。
4. **状态机终态守卫**：DONE / SKIPPED 是终态；FAILED 步骤可重试，FAILED run 不可再 finish。
5. **三级信任模型（新增，最高优先级）**：
   - 只有 `tier=fact` 的证据能支撑结论；`link_conclusion` **代码级拒绝** judgment
   - judgment（含被排除项与理由）只影响流程走向，**不得进结论**
   - 使用快照的 run，**账本缺判断批次则拒绝生成报告**
6. **冻结快照承载复现契约**：判断结果一经产生立即冻结；只承诺"冻结之后"可复现。
   `content_sha256` **不含时间戳**（否则确定性契约自相矛盾）。
7. **异常驱动打断**：判断类异常（零命中 / 两腿交集为零 / 命中率反常 / 自相矛盾）
   必须停下等人工裁决，`--ack <code>` 显式确认，确认动作记入快照清单。
8. **输入结构守卫**：`sources.read_obelix(strict=True)` 在列名对不上时**必须抛
   `SchemaError`**，绝不允许"把不认识的数据当合法的空数据"（真实教训，见 §8.6）。
9. **utf-8-sig + UTF-8 stdout**：读 CSV 用 `encoding="utf-8-sig"`；CLI 强制 UTF-8。
10. **分层解耦**：AGH JS 薄壳只 spawn Python CLI，不 import 工具实现；调用留痕 `toolcalls/`。
11. **合规**：数值只来自公开数据集 + 本地确定性计算，**严禁伪造**；**不抓论文全文**；
    密钥只放环境变量 / `.env`，**绝不写仓库/文档/提交**。

---

## 6. 关键产物指纹

- 冻结快照 `snap-20261002-065225-5e1fe9`
  - `content_sha256` = `5a0071827742be0e719591f78b78be118f9caaf2bf007b02b25b1d3594cf556e`
  - `producer` = `bootstrap_rule_v1`（规则式判断），`judgment_batch.count` = 43
- 数据基线（改数据适配层时用）：599 行 / 562 numeric / 37 上界值 `<x` / 33 空 family / DOI 覆盖 100%（223 唯一）
- 5 项复现校验：`results_csv_sha256 / n_rows / top3_material_id_set / top3_scores_positional / family_mean_log10_cond`
- 插件 integrity（**每次改 `index.mjs` / `package.json` / 插件目录任何文件都会变，
  以实测为准**）：
  ```bash
  cd D:/workBubbyStore/hks/paper-agent
  node D:/agnes-harness-main/packages/cli/dist/local/agnes.mjs package inspect "file:./plugins/paper-agent-tools"
  ```
  最近一次实测（2026-10-03，补齐插件 `README.md` 之后）：
  `sha256-3b308d3b41a0d3011043c67dd3030dc9782befd302b37be4df067daa90e89586`
- **仓库里只有一个插件目录** `plugins/paper-agent-tools/`（20 工具）。
  原先还有一个 `plugins/paper-tools/`，只含一份描述**未实现**工具的 README 存根，
  零代码、全仓库无人引用 → **已删除**。
- **安装前请先跑 `docs/AGH-SESSION-RUNBOOK.md` 的「第 0.5 步 · 安装前自查」**
  （3 条，30 秒）：manifest 的 `files` 与实际文件是否一致、插件能否注册 20 工具、
  inspect 是否只剩 provenance 警告。**别等卡在交互确认框里才发现 manifest 有问题。**
- 反判据结论存档 `evidence/model-judge-comparison.json`（DeepSeek 实测 `model_matters`）

---

## 7. AGH 状态（最重要，新工具重点看这里）

### 7.1 事实（本机实测，不夸大）

- **AGH 源码**：`D:/agnes-harness-main`（已构建 `packages/cli/dist/local/agnes.mjs`）
- **provider 可用**：`AGH doctor provider --probe` → `✓ verified`
  （route `account-acct-1a50785c-…`；`~/.agh/secrets` 下有 `agnes-ai` 与 `deepseek` 两项凭据）
- **插件未安装**：`AGH package status` 只有官方 3 个 helper，**没有 `paper-agent-tools`**
- **会话从未实跑**：`evidence/` 下只有 `model-judge-comparison.json`，**没有 `session.jsonl`**
- 改造前的会话证据（旧机器 `C:\Users\ASUS\...`）**不在本机**，`*.jsonl` 已按红线 gitignore

### 7.2 为什么必须人工跑

AGH 的 `package add` 走 `io.confirm(preview)`，**交互式 TTY 才点头**，无 bypass flag
（装插件 = 以本机权限执行 JS，必须人类确认）。因此 install → trust → enable → 会话
这一环**无法在编程工具的非交互 shell 里代跑**。

### 7.3 两个必踩的坑（本机实测）

1. **相对路径由谁解析**：`file:./plugins/...` 是相对路径。**daemon 在运行时**由
   daemon 的工作目录解析——若 daemon 是从别处启动的，`package inspect` 会报
   `The package source could not be accepted`。**在项目根目录执行命令**即可；
   若 daemon 已在别处启动过，先 `daemon stop` 再从项目根 `daemon start`。
2. **本机 PATH 上没有任何 python**（`python` / `python3` / `py` 全不在）→ 必须先
   ```bash
   export PAPER_AGENT_PYTHON="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"
   ```
   否则 **20 个 AGH 工具全部报 `cannot launch python`**（插件已支持多候选回退并给出
   可操作提示，但显式设置最稳）。
   **同样的坑也影响 `demo/*.sh`**：它们用 `printenv paper-agent_PYTHON || echo python`
   找解释器，所以跑演示脚本也必须显式传 `paper-agent_PYTHON`（见 §4 的 `PYEXP`）。
   连字符名在部分 shell 无法 `export`，用 `env "名字=值" 命令` 的形式传。

### 7.4 怎么跑

见 **`docs/AGH-SESSION-RUNBOOK.md`**（逐步命令 + 每步预期输出 + 8 条故障对照表）。
手册里有两条可直接粘贴的会话 prompt：5A 驱动既有流水线、5B 驱动新的检索/判断/冻结三件套。

### 6.4 已否决的弯路（别再重走）

- **项目内隔离 AGH home（`.agh-home`）失败**：AGH 的 home 是**活运行时状态机**（credential store / daemon 身份 / sqlite lock 均绑定原路径），手动 `Copy-Item` 整个 `~/.agh` 或只拷 config+secrets 都报 `provider host assembly failed` / `credential store is unavailable`。**不要再尝试搬 home**。AGH 框架就用它默认 home 运行（类比 node_modules，是框架自带运行时，不是 paper-agent 交付物）。

### 6.5 联调闭环记录（2026-10-02 已完成）

- [x] 交互式 TTY 安装：`package add` 的人类确认无法 non-TTY 绕过（AGH 安全设计）。最终自动化方案：`demo/reinstall_plugin.ps1` 用 `Start-Process cmd` 开真实控制台 + `AttachConsole(pid)` + `WriteConsoleInput(CONIN$)` 注入命令行与 `y` 确认（等价真人键盘输入，走正常 TTY 确认路径）。
- [x] 两次真实 `-p` 会话（同一 workspace 会话追加轮次，session id `agnes:local:local-dev:cli:workspace:05d7ffbf5caefe74`）：
  - 首轮：plan→run_step P1..P5→verify→report→cite→status，10 次调用全成功，run `run-20261002-030119-61a0ec` DONE、verify PASS（SHA `a30bc79f…`）。
  - 崩溃恢复轮：run_step P2 带 `chaos=kill_after_p2` → 子进程被 `os._exit(137)` 真实杀死 → status 显示 P3 PENDING → `sciret_resume` 断点续跑至 DONE → verify/report/cite 复核。run `run-20261002-033525-356ccf`。**7/7 工具全部出现**。
- [x] 证据导出：`evidence/session.jsonl`（首轮）与 `evidence/session-full.jsonl`（21 tool/call + 21 tool/result，闸门 ≥6 通过）。`*.jsonl` 按红线 gitignore（含本机路径），提交包从磁盘归集。
- [x] 审计包：`bash audit-pack-template/build_audit_pack.sh <RUN_ID>` 现自动把两份会话导出拷入 `audit-pack/`（`audit-pack/` 亦 gitignore，交付时随包生成）。
- 期间修复的真实缺陷：① 插件入口改 Cordis 对象范式（`inject:['extension']`）；② tool meta 补全 8 必填键（replay/costHint/deferLoading/requiresApproval 等，`requiresApproval:'never'`）；③ `kill_after_p2` 从"文档声明"到真实实现（chaos.py + run_p2/run_all 双路径挂钩 + E2/E3 测试）；④ P5 报告 DONE 后重复调用抛 StateError → 改幂等复用（F 测试）。

> 7 工具名（会话中已全部出现）：`sciret_plan / sciret_run_step / sciret_status / sciret_verify / sciret_report / sciret_cite / sciret_resume`。
>
> **注（阶段 7 重构）**：此后新增 `sciret_step_driven / sciret_next / sciret_finish`，
> 工具总数 **20**，并把核心编排改为**模型驱动**（详见 §0 与 README「编排模型」）。
> 上表中的 7/7、21+21 为阶段 6 真实会话的历史事实，未改动。

---

## 8. 被实测否证的假设 / 已否决的弯路（**别再重走**）

1. **「两腿 DOI 能高重合对接」——否证**。实测文献腿 373 篇 ∩ OBELiX 222 篇 = **仅 8 篇
   （2.1%）**。文献腿给话题全景、数据腿是特定数据集的来源论文，天然只少量重叠。
   → 异常规则已修正为「低对接率只报指标，**只有交集为零**才判异常」，并有回归用例
   `test_low_join_rate_is_NOT_anomaly` 锁死。**别再改回宽松阈值。**
2. **「AGH 能从 Python 当补全 API 用」——否证**。`agh -p` 非交互下会挂起（daemon 启动后
   重测仍 150s 无输出）；`agh serve model-api` 起的是给人用的 Web 控制台
   （`/v1/models` 404、`POST /v1/chat/completions` 405）。→ 模型判断的主路径是
   **AGH 会话内判断**（LLM 调插件工具落盘裁决），会话外自动化用标准 OpenAI 兼容端点。
   **因此本项目不提供 AGH 专用客户端**，别再重写一个会挂起的。
3. **项目内隔离 AGH home（`.agh-home`）——原作者已验证失败**。AGH 的 home 是活运行时
   状态机（credential store / daemon 身份 / sqlite lock 均绑定原路径），搬 home 必报
   `provider host assembly failed`。**不要再尝试搬 home。**
4. **`file:` 源必须相对 `./`**。绝对路径 `file:D:\...` 触发 `ProtocolViolation`。
5. **带连字符的环境变量名**在部分 shell 无法 `export`。插件已同时支持
   `PAPER_AGENT_X` 与 `paper-agent_X` 两种写法；**优先用下划线版本**。
6. **喂错领域的数据会静默成功——已修**。实测把吸附容量 CSV 喂进去，旧实现退出码 0、
   报告 ok=true，却写出"4 行全 invalid、9 列里 8 列未解析"的无意义快照。
   → 已加 `SchemaError` 守卫（退出码 2 + 可操作提示）与 5 条回归用例。**别把守卫删掉。**
7. **Git Bash 的 `/tmp` ≠ Python 的 `/tmp`**。跨语言传路径统一用 `D:/...` 显式形式。

---

## 9. 环境矩阵（本机实测）

| 组件 | 要求 | 本机实际 |
|---|---|---|
| Python | 3.10+，零第三方依赖 | 3.11 / **3.13.14**（WorkBuddy 托管：`C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe`） |
| Node | ≥18（AGH 需 ≥24） | 24.15 / **v24.21.0**（`C:/Program Files/nodejs/node.exe`；注意 PATH 里可能先命中托管的 22.x） |
| pnpm | 10.34.5（AGH 构建） | 10.34.5 |
| bash + sha256sum | demo 脚本 | Git Bash（`C:\Program Files\Git\bin\bash.exe`） |
| AGH 源码 | 已构建 | `D:/agnes-harness-main`（本机构建路径见 `AGH_ENTRY`，脚本不再写死他人机器绝对路径） |
| 模型端点 | 标准 OpenAI 兼容 | `https://api.deepseek.com` + `deepseek-chat`（key 在 `DEEPSEEK_API_KEY`；已实测连通） |
| 网络 | 仅增强线需要 | 文献检索需联网；主线全程离线 |

### 踩坑备忘（Windows 特有）

- **WSL shim 拦截**：`bash -c "…"` 或带引号路径调 Git Bash 会被 `wsl.exe` 拦截报
  `No such file or directory`。解法：PowerShell 直接调脚本绝对路径，不要嵌套 `-c`。
- **PowerShell 展开 `${VAR}`**：会被外层展开 → 用脚本文件传参。
- **cmd vs PowerShell**：`Get-ChildItem` / `Select-String` 是 PowerShell cmdlet；
  `dir` / `findstr` / `%var%` 是 cmd。
- **中文路径 + 编码**：管道读含中文路径的 JSON 按 cp936/GBK 解码会崩；
  CLI 已加 `_ensure_utf8_stdio`，demo 脚本加 `export PYTHONIOENCODING=utf-8`。
- **文件偶发 `EBUSY`**：编辑时可能被杀软短暂占用，**直接重试同一次编辑**即可。

---

## 10. 未完成清单（下一步做什么）

> 代码、工程层与 AGH 真实会话联调 **100% 闭环**：插件 running+trusted，两次真实会话 7/7 工具全覆盖（含真实进程崩溃 + 断点续跑演示），证据与审计包在盘。剩余工作只有**赛事提交材料**（项目说明文档 / 演示视频脚本 / 独立完成声明，见任务清单）。改任何 Python 代码前先读 §4 红线、跑 §3 验证；改插件后重跑 `demo/reinstall_plugin.ps1`（会真实开一个确认窗口）。

| # | 事项 | 谁做 | 预估 |
|---|---|---|---|
| 1 | 装插件 + 跑一次 AGH 会话，导出 `evidence/session.jsonl`（≥6 条 tool 交互） | **人**（交互终端） | 15–25 分 |
| 2 | 逐篇论文相关性判断（把判断粒度从 42 个族降到 223 篇论文，**放大模型价值**） | 工具 | 半天 |
| 3 | 领域插件化（分析脚本注册表 + 适配器注册表 + 标准 schema 泛化 `value`/`unit`/`property`） | 工具 | 2–3 天 |
| 4 | 推送 18 个本地提交 | **人**点头后 | 1 分 |
| 5 | 赛事提交材料（项目说明 / 演示视频脚本 / 独立完成声明）复核 | 人 | — |

> 若时间只够做一件事：**做 #1**。它是赛题指定底座链路的唯一实证缺口。
> 若来不及做 #1，交付口径必须写明「插件已就绪，会话内链路待实跑」，
> **不要写成已跑通**。

---

## 9. 阶段 9–10：PRD v0.3 科研全流程实现（2026-10-03）

### 9.1 这次新增了什么（一句话）

在**不破坏原有 materials（P1–P5）可复现实验底座**的前提下，新增**第二条工作流 `research`（R1–R6）**，
把 PRD 的 `检索→精读→拆解→验证→写作→评审` 全链路落地，并补齐**量化验证（F-7）**与**三类异常恢复（F-4.8）**；
两条工作流**共用同一套**状态机、事件账本、证据账本、故障恢复与模型驱动编排。

范围口径（已与负责人确认）：**全量核心（P0–P2，不含面板）** · **坚持零第三方依赖** · 在 `fix/agh-driven` 分支开发并推 `mike`。

### 9.2 新增/重写文件清单

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `core/paper_agent/state.py` | 重写（泛化） | `MATERIALS_STEPS` / `RESEARCH_STEPS` / `WORKFLOWS` / `steps_for()`；`PipelineState(workflow=, steps=)`；**`load()` 必须整体重建 step 字典**（否则会混入构造器预置的默认工作流步骤） |
| `core/paper_agent/litsearch.py` | 扩展 | 多源：`semantic_scholar` / `openalex`（摘要反演重建）/ `crossref`；`dedup_documents`（DOI + 标题/首作者）；`score_relevance` / `rank_documents`；原 arXiv 能力保留 |
| `core/paper_agent/pdfparse.py` | 新增 | **零依赖** PDF 文本抽取（`zlib` + 内容流算子）+ 章节/关键信息(locator)/图表/可复现性 + 三档置信度 + OCR 降级 |
| `core/paper_agent/analyze.py` | 新增 | 创新点 5 分类 / 技术脉络 / Research Gap |
| `core/paper_agent/factcheck.py` | 新增 | 引用真实性核查 / 数据一致性 4 项 / 文献矛盾检测 |
| `core/paper_agent/writing.py` | 新增 | 综述生成（**强制引用**，无依据标 `[需补充引用]`）/ BibTeX·RIS / APA·IEEE·Chicago |
| `core/paper_agent/review.py` | 新增 | 5 维度模拟审稿（信号驱动打分）+ 迭代闭环 |
| `core/paper_agent/evaluate.py` | 新增 | F-7 四套指标（P/R/F1/NDCG@10、结构·关键信息·复现准确率、识别率·分类准确率·幻觉率·混淆矩阵、引用准确率·幻觉率） |
| `core/paper_agent/research.py` | 新增 | `ResearchPipeline`（R1–R6 + `step_context` + `run_all` + `resume`）；demo 版式 PDF；F-4.8 挂钩 |
| `core/paper_agent/report.py` | 扩展 | 新增 `generate_research_report()`（C1–C5 证据绑定） |
| `core/paper_agent/provenance.py` | 扩展 | `EVIDENCE_KINDS` 扩展：`note/analysis/factcheck/draft/review/evaluation` |
| `core/paper_agent/chaos.py` | 扩展 | `source_should_fail` / `force_scanned` / `batch_fail_index` / `kill_after_r3`（真实 `os._exit(137)`） |
| `core/paper_agent/steps.py` | 扩展 | `open_pipeline()` 按 workflow 装配编排器 |
| `core/paper_agent/cli.py` | 扩展 | `--workflow`；新增 `search-papers/parse-paper/analyze-paper/verify-facts/write-review/self-review/eval` |
| `plugins/paper-agent-tools/index.mjs` | 扩展 | 20 工具（+7 科研能力），`sciret_plan` 支持 `workflow` |
| `.agh/skills/.../SKILL.md` | 重写 | 两条工作流 + 决策协议 + F-4.8 三场景 |
| `tests/test_{litsearch_multi,pdfparse,analyze,factcheck,writing,review,evaluate,research}.py` | 新增 | 覆盖 F-1~F-7 与 F-4.8 |

### 9.3 关键工程决策（接手务必知道）

1. **`state.load()` 必须重建 step 字典**：`PipelineState.__init__` 会按默认工作流预置 `step_status`；
   载入既有 run 时若不**整体重建**（而非 update），research run 会混入 P1–P5 的 PENDING 条目 →
   `run_all()` 永不 DONE。这是本次踩过的真实坑，已修复并有 `tests/test_research.py::TestWorkflowIsolation` 守门。
2. **零依赖 PDF 解析的边界**：纯标准库无法覆盖 CID/自定义编码字体与复杂版式；此类文件给
   `confidence=low` + `warnings`，**绝不假装成功**。这是相对 PRD §6.1（建议 GROBID/PyMuPDF）的
   **有意偏差**（红线优先），已在映射文档中显式声明。
3. **降级信号要有信噪比**：置信度分三档（high / medium / low），"文本偏短的元数据版式"记 **medium**
   而非 low，避免 demo 正常路径被误判为 degraded；真正的问题（扫描件 / 解析失败 / 悬空引用 / 切源）才计降级。
4. **"未识别到 Gap"是元陈述**，不是关于文献的事实主张，故**不打** `[需补充引用]`；避免把覆盖度提示
   误判为无据主张而导致自评审永远阻塞。
5. **F-1.2 独立文献库未做**：以 run 内文献集 + 证据留痕替代（P0 非必须），边界已在映射文档声明。

### 9.4 怎么复验（PRD v0.3 部分）

```bash
export PYTHONPATH=core

# 全量单测：200+ 项 OK（离线零 skip）
python -m unittest discover -s tests -p "test_*.py"

# research 端到端：DONE / degraded=false
python -m paper_agent.cli run-all --workflow research \
  --goal "sulfide solid electrolyte ionic conductivity" --lit-source local
python -m paper_agent.cli report --run <RUN_ID>     # C1-C5 全带 [EV-XXXX]

# 量化验证：检索/精读/创新点/引用四套指标
python -m paper_agent.cli eval

# F-4.8 三场景
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos ss_timeout
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos scan_pdf
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos batch_fail_at=2
python -m paper_agent.cli run-all --workflow research --goal "sulfide" --lit-source local --chaos kill_after_r3
python -m paper_agent.cli resume --run <RUN_ID>
```

详见 `HOW-TO-VERIFY.md` §8 与 `docs/PRD-v0.3-需求实现映射.md`。

### 9.5 Windows 复验小坑（本次新增）

- **bash 无法 export 连字符环境变量**：`paper-agent_ROOT=... python ...` 与 `env "paper-agent_ROOT=..."` 在 Git Bash 下
  会失败/静默丢失。复验隔离根请用 **Python 进程内** `os.environ['paper-agent_ROOT']=tmp` 后再调用 `cli.main([...])`。
- 若在 Git Bash 里写 `/tmp/xxx`，Windows 原生 Python 会解析成 `D:\tmp\xxx`；跨工具传路径请用 `cygpath -w` 或直接写盘符路径。

---

## 11. 一句话交接

> 真实数据改造（第一批）与增强线（第二批）均已落地：599 行真实数据、
> 三级信任模型、冻结快照、异常打断、联网检索、模型判断与反判据，
> 200+ 项单测与三套演示脚本可复现；**唯一未验证的是 AGH 会话内链路**——
> 代码与契约齐备，但插件未装、会话未跑，这是接手后第一件该做的事。
> 改任何 Python 代码前先读 §5 红线、跑 §4 验证；改插件前先读 §7.3 的两个坑。
