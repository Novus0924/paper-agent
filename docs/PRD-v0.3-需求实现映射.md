# PRD v0.3 需求实现映射（逐条对照）

> 对标文档：`科研智能体需求文档 v0.3（参赛版+量化验证+异常恢复）`
> 实现仓库：`paper-agent`（分支 `fix/agh-driven`）
> 口径：**逐条给出「状态 / 实现位置 / 对外入口 / 证据与测试 / 复验命令」**。
> 状态图例：✅ 已实现 · ◑ 部分实现（含边界声明）· ⛔ 本期不做（已与负责人确认）

## 0. 本次实现范围（已确认）

| 维度 | 决定 |
| --- | --- |
| 范围 | **全量核心（P0–P2，不含面板）**：`检索→精读→拆解→验证→写作→评审` 全链路 + 量化验证（F-7）+ 异常恢复（F-4.8） |
| 依赖红线 | **坚持零第三方依赖**（Python 核心仅标准库）。因此 **不使用** PRD §6.1 建议的 `GROBID + PyMuPDF`，改为**纯标准库 PDF 文本抽取**（见 F-2.1）；**不引入** 本地向量库（F-1.1 语义检索以 SS/OpenAlex 的检索式能力覆盖） |
| 界面 | 不做 `research-panel` 前端面板（用 AGH 自带 CLI/Web） |
| 视频 | 不产出演示视频（脚本已更新，见 `submission/演示视频脚本.md`） |
| 交付 | 在隔离克隆 `paper-agent-fix` 的 `fix/agh-driven` 分支开发，提交后 fast-forward 推送远端 `mike` |

**架构定位（关键）**：两条工作流 `materials`（P1–P5，原有可复现实验底座）与 `research`（R1–R6，PRD 科研全流程）**共用同一套**状态机、事件账本、证据账本、故障恢复与模型驱动编排，避免出现平行代码库。

**步骤 ID 对照（供逐条核对）**

| 工作流 | 步骤 ID（有序） |
| --- | --- |
| `materials` | `P1_lit_search` → `P2_clean_data` → `P3_run_experiment` → `P4_verify` → `P5_report` |
| `research` | `R1_search` → `R2_read` → `R3_analyze` → `R4_verify` → `R5_write` → `R6_review` |

> **research 硬前置依赖**（单步驱动时缺前置会显式报 `StepDependencyError`，不做隐式代跑）：
> 其中 `R3_analyze` 依赖 `R1+R2`，`R5_write` 依赖 `R3`，`R6_review` 依赖 `R4+R5`。

---

## 1. 功能需求逐条映射

### 4.1 文献检索（Search）

#### F-1.1 多源学术检索工具 ✅

| 要求 | 实现 |
| --- | --- |
| 统一入口 | `litsearch.search_papers(goal, sources, max_results, timeout, backends)` |
| 数据源 | **arXiv**（Atom XML）· **Semantic Scholar** · **OpenAlex** · **CrossRef**，均为官方公开 API，零依赖（`urllib` + `json`/`xml`） |
| 检索模式 | 关键词检索；`OpenAlex` 摘要反演索引重建（`_openalex_abstract`） |
| 输出字段 | `doc_id / doi / title / authors / venue / year / keywords / abstract / url / source / citations` |
| 去重规则 | `dedup_documents`：**DOI 精确** → 无 DOI 时 **标题+首作者模糊**匹配；合并 `sources`，被引数取 max |
| 相关性评分 | `score_relevance`（标题权重 3 / 关键词 2 / 摘要 1）+ `rank_documents` |
| 失败降级 | `_per_source_timeout` 单源超时**自动跳过**，`unavailable_sources` 标注未覆盖源，不阻塞返回 |
| AGH 注册 | 工具 `sciret_search_papers`；Skill 方法论文档 `.agh/skills/sciret-research-pipeline/SKILL.md` |

- 代码：`core/paper_agent/litsearch.py`
- 测试：`tests/test_litsearch_multi.py`（13 例）+ `tests/test_litsearch.py`（16 例）
- 复验：`python -m paper_agent.cli search-papers --goal "sulfide solid electrolyte" --sources arxiv,openalex,crossref`

#### F-1.2 文献库管理 ◑

| 要求 | 实现 / 边界 |
| --- | --- |
| 存储位置 | ◑ 文献集合以 **run 内产物**（`literature/research_hits.json` + 快照冻结）为权威；未做跨 run 的独立 `~/.research-agent/library/` 目录与 SQLite |
| 核心操作 | ◑ 检索结果去重后即为"库"；支持按 `doc_id/doi/url` 回查引用（`sciret_cite`） |
| 边界声明 | 独立文献库（收藏/标签/筛选）属 PRD §4.1.2，**P0 未列为必须项**；本期以「run 内文献集 + 证据留痕」满足可追溯要求。若需独立库，建议 P1 增补且仍可零依赖（`sqlite3` 为标准库） |

---

### 4.2 论文精读（Read）

#### F-2.1 结构化论文解析 ✅

| 要求 | 实现 |
| --- | --- |
| 工具名 | `pdfparse.parse_paper` / `sciret_parse_paper` |
| 输入 | **本地 PDF 路径** / **arXiv ID**（联网下载）/ DOI 标识 |
| ① 全文文本 | `extract_pdf_text`：暴力扫描 `stream…endstream` → `zlib` 解 FlateDecode → 解析内容流文本算子（`Tj` / `TJ` / `'` / `"`，`Td`/`TD`/`T*` 换行），支持字面串转义（`\(` `\)` `\ddd`）与十六进制串（含 UTF-16BE） |
| ② 章节结构 | `split_sections`（英文 + 中文标题词表，19 类） |
| ③ 关键信息 | `extract_key_info`：方法 / 数据 / 结论 / 局限，**每条带 `locator`（章节名 + 字符偏移）** |
| ④ 图表说明 | `extract_figures_tables`：识别 `Figure/Fig./Table/图/表` + 编号 + `:`/`。` caption |
| ⑤ 可复现性 | `check_reproducibility`：代码仓库链接（github/gitlab/zenodo/huggingface/osf…）+ 数据集链接 |
| 中文支持 | `detect_language`（CJK 占比）+ `render_note(note, lang)` **输出笔记跟随原文语言** |
| 边界场景 | 无文本层 → `status="scanned"` / `confidence="low"` + 尝试 OCR（若系统有 `tesseract`+`pdftoppm`）否则 `ocr_unavailable` 显式降级。**绝不编造内容** |
| 置信度 | 三档：`n_chars≥800 & 可打印率≥0.9`→high；`≥200`→medium（短文本/元数据版式）；否则 low |

- 代码：`core/paper_agent/pdfparse.py`
- 测试：`tests/test_pdfparse.py`（15 例，含合成 PDF 夹具：未压缩流 / FlateDecode / TJ 数组 / 转义与十六进制 / 扫描件）
- 复验：`python -m paper_agent.cli parse-paper --source <pdf|arxiv-id>`

---

### 4.3 创新点拆解（Analyze）

#### F-3.1 单篇论文创新点提取 ✅

| 要求 | 实现 |
| --- | --- |
| 创新点分类 | `analyze.classify_innovation`：**方法/理论/数据/应用/工程** 五类（规则可解释） |
| 分析维度 | `extract_innovations`：每个创新点给出 `statement` + `categories` + `evidence`（原句 + `locator`） |
| 对比增强 | `build_comparison_matrix`：在文献集合上生成方法/数据/结论对比矩阵 |
| 输出 | `render_innovations_md`（创新点卡片）+ 对比矩阵表 |

#### F-3.2 领域技术脉络梳理 ✅

`analyze.technology_timeline(docs, analyses)` → 时间线式脉络（按年份排序，标注关键节点与局限）。

#### F-3.3 Research Gap 识别 ✅

`analyze.research_gap(...)`：汇总各篇 `limitations` → 聚类高频未解决问题 → 交叉验证空白 →
输出含 **重要性 / 空白证据 / 可行性** 的候选方向清单。

- 代码：`core/paper_agent/analyze.py`
- 测试：`tests/test_analyze.py`（14 例）
- 复验：`python -m paper_agent.cli analyze-paper --run <RUN_ID>`

---

### 4.4 事实验证（Verify）

#### F-4.1 引用真实性核查 ✅

`factcheck.verify_citation` / `verify_citations`：判定 **✅ 一致 / ⚠️ 部分一致 / ❌ 不一致 / ❓ 无法获取原文**，基于"被引文献可获取文本"的**包含关系 + 关键词覆盖**（`containment`）。

#### F-4.2 数据一致性检查 ✅

`factcheck.check_data_consistency`：4 项核查 —— 摘要 vs 实验数字 / 表格 vs 正文 / 图趋势 vs 结论 / 消融自洽性（无对应章节则 `跳过`，并如实标注）。

#### F-4.3 文献间矛盾检测 ✅

`factcheck.detect_contradictions`：多篇核心结论对比（方向词 up/down 对立 + 数值区间不重叠）→ 输出矛盾清单 + 可信度建议。

- 代码：`core/paper_agent/factcheck.py`
- 测试：`tests/test_factcheck.py`（9 例）
- 复验：`python -m paper_agent.cli verify-facts --run <RUN_ID>`

---

### 4.5 论文写作（Write）

#### F-5.1 文献综述生成 ✅

| 要求 | 实现 |
| --- | --- |
| 生成流程 | `writing.generate_review`：规划章节（Introduction / Related Work / Method Landscape / Open Problems / Conclusion）→ 分配论文 → 逐节写作 → `check_review_consistency` 全文一致性检查 |
| 引用规范 | 每处事实陈述带 `[doc_id]`；无法归因 → `[需补充引用]`；**禁止编造引用**（悬空引用检测） |
| 输出 | Markdown 草稿 + BibTeX + RIS |

> 说明：无 LLM 时采用**抽取式**写法（"元数据 + 摘要首句"），文风润色留给 AGH 会话内的大模型按 write-skill 完成。

#### F-5.2 单章节辅助写作 ◑

支持章节骨架（Abstract/Introduction/Related Work/Method/Experiment/Discussion/Conclusion 的章节计划）；
**交互式扩写/润色**由 AGH 会话内大模型按 Skill 协议完成（核心里不写 LLM 调用，保持零依赖与确定性）。

#### F-5.3 引用管理 ✅

`format_citation`（**APA / IEEE / Chicago**）· `generate_bibtex`（含重复键消解）· `generate_ris` · `dedup_citations` · `missing_fields`（缺失字段提醒）。

- 代码：`core/paper_agent/writing.py`
- 测试：`tests/test_writing.py`（13 例）
- 复验：`python -m paper_agent.cli write-review --run <RUN_ID>`

---

### 4.6 自评审（Review）

#### F-6.1 模拟审稿 ✅

| 要求 | 实现 |
| --- | --- |
| 审稿维度 | `review.DIMENSIONS`：贡献度 / 技术正确性 / 实验充分性 / 写作清晰度 / 相关工作覆盖度 |
| 输出格式 | `render_review_md`：Summary + Strengths + Weaknesses + Detailed Comments + Score |
| 迭代闭环 | `review_loop(draft, …, revise=None, max_iters=3)`：评审 → 修改回调 → 再评审，直到**阻塞性问题清零**；无回调则单轮评估 |
| 打分可解释 | 五个维度均由**可测量信号**按固定规则计算（引用一致性率 / 未支撑句 / 悬空引用 / 文献覆盖 / 数值证据密度），非拍脑袋 |

- 代码：`core/paper_agent/review.py`
- 测试：`tests/test_review.py`（7 例，含迭代收敛）
- 复验：`python -m paper_agent.cli self-review --run <RUN_ID>`

---

### 4.7 量化验证模块（Evaluation）✅

> 对应赛题"设置明确的结果验证方法"。

| 子项 | 指标 | 实现 | demo 实测 |
| --- | --- | --- | --- |
| **F-7.1 检索质量** | Recall / Precision / **NDCG@10**，含**纯关键词基线**对比 + 失败案例 | `evaluate.eval_search_quality` + `demo_search_testset` + `demo_search_baseline` | 系统 Recall **1.000** / Precision 0.345 / NDCG@10 **0.987**；基线 Recall 0.900 / Precision 0.365 / NDCG@10 0.662 → **Recall +0.10，NDCG +0.325**。诚实说明：小测试集上 **Precision 略低于基线（−0.02）**，因系统召回更多同族文献；主口径为 Recall 与 NDCG |
| **F-7.2 精读质量** | 结构提取准确率 / 关键信息抽取准确率 / 可复现性判断准确率 + **人工耗时对比** | `evaluate.eval_read_quality`（对 5 篇基准） | 三项均 **1.000**；系统耗时 **实测**（`time.perf_counter`，典型 ~0.001s/篇）vs 人工 900s/篇（PRD 15 分钟下界，人工值为标注常量不是实测） |
| **F-7.3 创新点提取** | 识别率 / 分类准确率 / **幻觉率** + **混淆矩阵** | `evaluate.eval_innovation` | 识别率 **0.80**、分类准确率 0.80、幻觉率 **0.00**；混淆矩阵可加总（含"未识别"列） |
| **F-7.4 引用可信度** | 引用准确率 / **引用幻觉率** | `evaluate.eval_citation`（对接 `factcheck.verify_citation`） | 引用准确率 **1.000**、幻觉率 **0.00**（≤5% 达标） |

- 代码：`core/paper_agent/evaluate.py`；工具 `sciret_eval`；CLI `python -m paper_agent.cli eval`
- 测试：`tests/test_evaluate.py`（10 例，含指标边界与 `run_all` 冒烟）
- **诚实声明**：测试集为 **demo 规模小样本标注**（10 条检索查询 / 5 篇精读 / 5 篇创新点 / 11 条引用核查），**用于演示指标口径与基线对比，不代表真实世界性能**；每条报告都带 `scale_note`。

---

### 4.8 异常恢复演示场景 ✅（三类全部可复现）

| 场景 | chaos 模式 | 期望行为 | 实测 |
| --- | --- | --- | --- |
| **① 外部 API 超时降级** | `ss_timeout` | Semantic Scholar 超时 → 标记不可用并**切源**（arXiv 等），任务不中断，结果标注切源 | DONE；`unavailable_sources=['semantic_scholar']`；`n_documents≥1`；非整体降级 |
| **② PDF 解析失败恢复** | `scan_pdf` | 无文本层 → 尝试 OCR 路径 → 不可用则标"低质量解析、低置信度" | DONE；`reading_report.scanned_or_low_conf>0`；笔记 `status=scanned`/`confidence=low` |
| **③ 长任务中断恢复** | `batch_fail_at=N` / `kill_after_r3` | 第 N 篇失败**跳过**继续；进程被真实杀死后 `sciret_resume` 断点续跑 | 批量：`n_failed=1`、失败项 `doc_id` 可查、下游 R3–R6 仍全 DONE；崩溃：退出码 **137** → `resume` → 全部 DONE，账本 append-only 完整 |

- 代码：`core/paper_agent/chaos.py`（`source_should_fail` / `force_scanned` / `batch_fail_index` / `_die()`）+ `core/paper_agent/research.py`
- 测试：`tests/test_research.py::TestExceptionRecovery`（6 例，含**离线路径下场景① 真实生效**的回归用例）+ `::TestCrashAndResume`（1 例，真实子进程 SIGKILL 137 → resume）
- 复验：
  ```bash
  python -m paper_agent.cli run-all --workflow research --goal "..." --lit-source local --chaos ss_timeout
  python -m paper_agent.cli run-all --workflow research --goal "..." --lit-source local --chaos scan_pdf
  python -m paper_agent.cli run-all --workflow research --goal "..." --lit-source local --chaos batch_fail_at=2
  python -m paper_agent.cli run-all --workflow research --goal "..." --lit-source local --chaos kill_after_r3
  python -m paper_agent.cli resume --run <RUN_ID>
  ```

---

## 2. 非功能需求映射（PRD §5）

| 类别 | 要求 | 实现 |
| --- | --- | --- |
| **隐私** | PDF 与分析数据本地存储 | ✅ 全部产物落在 `runs/<run_id>/`；仅调用学术 API / arXiv 下载 PDF 时传输必要参数 |
| **可追溯** | 结论可回溯到原文出处；禁止无引用陈述 | ✅ `provenance.py` 证据账本 `[EV-XXXX]`（含 SHA-256）；`key_info.locator`（章节+偏移）；`[需补充引用]` 标记 |
| **透明性** | 执行过程可展示 | ✅ `events.jsonl` / `toolcalls/*.json` / AGH daemon 原生会话记录 |
| **容错** | 单篇失败不阻塞 | ✅ 批量精读单项失败跳过并标注（F-4.8 场景③） |
| **性能目标** | 单篇精读 < 60s；检索响应 < 10s | ✅ 纯本地解析实测 ~0.001s/篇（远低于 60s）；检索按源设 timeout（默认 25s）且单源超时跳过 |
| **双语支持** | 中/英文论文 | ✅ 章节词表含中文；`detect_language` + 笔记语言跟随原文 |
| **AGH 版本兼容** | 不修改 AGH 核心 | ✅ 仅通过 `plugins/paper-agent-tools`（Cordis 插件）+ `.agh/skills/` 扩展 |

---

## 3. 与 PRD 的偏差 / 边界（必须诚实声明）

1. **PDF 解析不引入 GROBID/PyMuPDF**（PRD §6.1 建议）：因**零依赖红线**。纯标准库方案对 **CID/自定义编码字体、双栏、公式** 的覆盖有限，此类文件会给出 `confidence=low` + `warnings`，**绝不假装解析成功**。这是明确的边界，非隐瞒。
2. **语义检索**：PRD F-1.1 的"语义"以 **Semantic Scholar / OpenAlex 的检索式 + 相关性评分** 覆盖；**未上本地 embedding + 向量库**（与 PRD §9.2 第 5 条"P0 先不上本地向量库"一致）。
3. **独立文献库（F-1.2）**：以 run 内文献集 + 证据留痕替代跨 run 的 `library.db`，见上文 ◑ 声明。
4. **量化验证测试集规模**：为 demo 小样本（人工可核查导出），用于**演示指标口径与相对基线改进**；PRD §8 的"≥80% 识别率 / <5% 幻觉率"在 demo 集上**达标**（识别率 0.80、幻觉率 0.00），但**不承诺真实世界同等水平**。
5. **单章节辅助写作（F-5.2）**：核心层提供章节骨架与引用格式化；交互式润色交由 AGH 会话内大模型按 Skill 协议执行（核心里不内嵌 LLM 调用）。
6. **前端面板 / 演示视频**：本期不做（已确认）。

---

## 4. 复验命令汇总（一条链路走完）

```bash
# 0) 环境
export PYTHONPATH=core          # Windows: set PYTHONPATH=core

# 1) 全量单测（162 例，离线零 skip）
python -m unittest discover -s tests -p "test_*.py"

# 2) research 工作流端到端（模型驱动 / 兜底两种等价路径）
python -m paper_agent.cli plan --goal "sulfide solid electrolyte ionic conductivity" --workflow research
python -m paper_agent.cli run-all --workflow research --goal "<goal>" --lit-source local
python -m paper_agent.cli report --run <RUN_ID>          # 生成 C1-C5 证据绑定报告

# 3) 单点能力
python -m paper_agent.cli search-papers --goal "<goal>" --sources arxiv,openalex,crossref
python -m paper_agent.cli parse-paper   --source <pdf|2301.12345>
python -m paper_agent.cli analyze-paper --run <RUN_ID>
python -m paper_agent.cli verify-facts  --run <RUN_ID>
python -m paper_agent.cli write-review  --run <RUN_ID>
python -m paper_agent.cli self-review   --run <RUN_ID>

# 4) 量化验证
python -m paper_agent.cli eval

# 5) 异常恢复（F-4.8 三场景）
#    见 §1 4.8 复验命令
```

**工具清单（插件共 20 个 `sciret_*` = 编排底座 10 + 科研能力 7 + 可信增强 3）**：
`plan / step_driven / next / finish / run_step / status / verify / report / cite / resume`
（编排与底座 10 个）＋
`search_papers / parse_paper / analyze / factcheck / write_review / self_review / eval`（科研能力 7 个）＋
`search / freeze_prepare / freeze_commit`（可信增强：联网检索腿 + 三段式冻结，3 个）。

**AGH Skill**：`.agh/skills/sciret-research-pipeline/SKILL.md`（定义两条工作流与 F-4.8 决策协议）。

---

## 附：本轮复审修复（第二轮优化）

对完成后的实现做了一次**对抗式复审**，发现并修掉 3 个真问题 + 2 处不诚实表述：

| # | 级别 | 问题 | 影响 | 修复 |
|---|---|---|---|---|
| 1 | **重大** | `run_r1` 在 `--lit-source local` 时**直接短路**，从不经过多源层 | F-4.8 场景①（`ss_timeout`）在**所有文档给出的复验命令**下都是**空操作**：`unavailable_sources` 恒为 `[]`、`degraded` 恒 False。文档声称的验证结论**不成立** | local 分支不再短路：按 chaos 把受影响源标记为不可用并**切源**，产出 `note=local_source_failover` / `degraded=true`；新增回归用例 `test_scenario1_timeout_takes_effect_on_local_path` |
| 2 | **中** | `run_r3` 在 R2 未 DONE 时**隐式调用 `run_r2()`** | 模型只要求跑 R3，系统却偷偷把 R2 标记 DONE 并追加证据——破坏「调用-结果一一对应」，模型状态判断失准 | 移除隐式代跑；引入 `STEP_DEPS` 硬依赖表 + `StepDependencyError`，缺前置时**显式失败**并回传 `missing_deps` |
| 3 | **中** | R4/R5/R6 直接读前置产物，缺失时静默产出**空报告**仍标 DONE | 单步驱动下可能生成无内容却"成功"的报告 | R2–R6 全部加 `_check_deps` 前置校验；`run_step` 返回可读失败而非抛栈 |
| 4 | 诚实性 | `build_demo_evals` 把精读耗时**写死为 0.05s** | F-7.2 的「加速倍数」基于编造常量 | 改为 `time.perf_counter` **实测**（典型 ~0.001s）；文档同步标注人工值为 PRD 常量、非实测 |
| 5 | 诚实性 | 文档报检索 Precision 却**回避其低于基线**（0.345 < 0.365） | 选择性汇报 | 文档显式写明 Precision 略低于基线及原因，主口径改为 Recall/NDCG |

复验：`python -m unittest discover -s tests` → **162/162 通过**；四条 F-4.8 命令逐条实跑与文档一致。
