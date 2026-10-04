# 数据来源声明

本项目对**素材内容**坚持「本地自带、真实可核对」；**文献检索**可选联网，且只取**元数据**
（标题/作者/年份/venue/摘要/DOI/被引数），**不做论文全文批量抓取**（版权红线）。
本项目**主线不联网**（读仓库内的冻结快照）；**增强线联网时只调元数据接口，
不抓论文全文**（版权红线）。全部数据为公开、可核对、带出处的真实素材。

## 1. 本地自带素材（离线可复现基线）

| 来源 | 位置 | 说明 | 条款 / 署名 |
| --- | --- | --- | --- |
| 文献语料（5 篇） | `data/literature.json` | 固态电解质领域**真实 DOI** 论文的标题与要点摘录（人工整理，非批量抓取） | DOI 可回查：`sciret_cite` 输出含 EV 证据链 |
| 电导率原始数据集 | `data/conductivity_raw.csv` | 7 行**带缺陷演示数据**（单位混杂 mS/cm 与 S/cm、缺激活能、有整行重复）；数值标注 `as-reported`，出处为文献 DOI | 仅用于流水线演示，非系统综述结论 |
| 确定性实验 | `experiments/arrhenius_rank.py` | 对清洗后数据的**本地真实计算**（Arrhenius 特征打分排序 + 图表），零第三方依赖，相同输入两次运行 `results.csv` 逐字节一致 | 本项目原创代码 |

## 数据源清单

| 来源 | 位置 | 说明 | 许可 / 署名 |
|---|---|---|---|
| **OBELiX 数据集**（数值来源） | `data/external/obelix/all.csv`（599 行快照） | 599 条已合成锂固态电解质材料，含**室温实验实测离子电导率**（S/cm）、化学组成、空间群、晶格参数；**每条带原始实验论文 DOI**（321 条另附 CIF） | **CC-BY-4.0**；Therrien, F. et al. (2025). *OBELiX: A Curated Dataset of Crystal Structures and Experimentally Measured Ionic Conductivities for Lithium Solid-State Electrolytes.* arXiv:2502.14234 |
| **Crossref**（文献腿，联网） | API `api.crossref.org/works` | 论文元数据（DOI / 标题 / 作者 / 年份 / 期刊）；**只取元数据，不取全文** | 公开接口；调用时带 `mailto` 进入 polite pool |
| **OpenAlex**（文献腿，联网） | API `api.openalex.org/works` | 同上，与 Crossref 互补（实测两者结果零重叠） | 公开接口，CC0 |
| 冻结输入快照 | `snapshots/snap-*/` | 数据腿 + 文献腿 + 判断批次；含逐文件 SHA-256 与聚合内容哈希 | 由本项目生成 |
| 演示语料（legacy 降级路径） | `data/literature.json`（5 篇） | 早期演示用文献卡片；**不再参与主线**，仅保留为离线降级路径与回归测试 | 真实 DOI，可回查 |
| 演示数据（legacy 降级路径） | `data/conductivity_raw.csv`（7 行） | 早期演示用带缺陷数据；**不再参与主线** | 见文件内 `as-reported` 标注 |
| 实验计算 | `experiments/arrhenius_rank.py` | 对清洗后数据的本地真实计算，零第三方依赖，无随机源 | 本项目原创代码 |

## OBELiX 数据的关键事实（探针实测，见 `docs/redesign-decisions.md` §8）

- 599 行中 **562 行**含可用数值（93.82%）
- **37 行**为**上界记法**（`<1E-10` / `<1E-8`）：**不作为可比数值参与排序**，
  但**不静默丢弃**——已登记于 `clean/excluded_rows.json` 留证
- DOI 覆盖率 **100%**（599/599），唯一 DOI **223** 个；抽样 10 个在 Crossref
  与 OpenAlex 均为 10/10 可解析
- `Family` 字段为**化学族**（43 个取值），其中 33 行为空，清洗时归入 `unknown`
- 数据源自带质量注记 136 条（如晶格参数与 CIF 不匹配、部分占据修正），
  清洗时标注为 `quality_flag` 但**不删除**，供人工复核

## 2. 可选联网检索（只取元数据，结果快照冻结）

`--lit-source arxiv|auto`，或 research 工作流的 `R1_search`（默认多源）会调用下列**官方公开 API**：

| 数据源 | 用途 | 费用 | 实现 |
| --- | --- | --- | --- |
| arXiv Atom API | 预印本检索（CS/AI 主力源） | 免费 | `litsearch.search_arxiv` |
| Semantic Scholar API | 引用图谱 + 全领域检索 | 免费（需 key） | `litsearch.search_semantic_scholar` |
| OpenAlex API | 全领域文献元数据补充 | 免费 | `litsearch.search_openalex` |
| CrossRef API | DOI 元数据校验 | 免费 | `litsearch.search_crossref` |
| Unpaywall API | 开放获取 PDF 定位（可选，常量预留） | 免费 | `litsearch.UNPAYWALL_API` |

**确定性契约**：在线检索结果**首跑即快照冻结**到 `runs/<run_id>/literature/`，
同一 run 复跑只读快照、不再联网；快照本身作为 `data` 证据登记（含 SHA-256）。
单元测试默认 `paper-agent_LIT_SOURCE=local` 强制离线，因此为**零 skip**。

## 3. 明确声明

- 文献元数据 = **真实 DOI，可公开回查**（**截至 2026-10-02 经 doi.org / Crossref REST API 逐条权威核验**，
  标题 / 作者 / 期刊 / 年份均与记录一致）：
  - L001 `10.1038/nmat3066` — Kamaya et al., *Nature Materials* 2011（LGPS）
  - L002 `10.1038/nenergy.2016.30` — Kato et al., *Nature Energy* 2016
  - L003 `10.1002/anie.200701144` — Murugan et al., *Angew. Chem. Int. Ed.* 2007（LLZO）
  - L004 `10.1016/0167-2738(92)90442-r` — Bates et al., *Solid State Ionics* 1992（LiPON）
  - L005 `10.1002/anie.200703900` — Deiseroth et al., *Angew. Chem. Int. Ed.* 2008（argyrodite）

  > 上列 5 个 DOI 为**核验后的最终值**；`tests/test_data_integrity.py` 以守门测试防止历史错误 DOI 回归。
- 实验 = **自带数据集上的真实本地运行**；所有 run 产物（`runs/<run_id>/`）与双账本
  （`events.jsonl` / `provenance.jsonl`）可逐条审计。
- 结论 C1–C5 逐条绑定 `[EV-XXXX]` 证据锚点（`sciret_cite` 可回查文件与 SHA-256）：
  事实级证据指向文件哈希或 DOI；判断级证据记录对象、裁决与理由（含被排除项），可被复核与反驳。
- **严禁伪造数据**：`as-reported` 数值保留原文献出处；数值只能来自外部数据集原样搬运与本地
  确定性计算，模型不得生成任何数值进入计算链路；`mutate_summary` 等故障注入仅用于演示验证器
  抓篡改，注入行为在 events 账本中显式记录，不进入正常路径产物。
- demo 规模量化指标（F-7.1~F-7.4）为**小样本人工可核查标注**，仅用于演示指标口径与
  相对基线改进，**不代表真实世界性能**（每份报告均带 `scale_note`）。
- **不做论文全文批量抓取**（版权红线）；仅使用公开数据集的**元数据与数值**，
  以及数据集自带的 DOI 作为证据锚点。
- 早期 `data/literature.json` 与 `data/conductivity_raw.csv` 中所有数值均标注
  `as-reported`，仅用于演示与回归，**不得作为科研结论引用**。
