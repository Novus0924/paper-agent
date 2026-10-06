# paper-agent 科研报告（research 工作流）— run-20261006-094401-eb9a60

- 研究问题: solid-state electrolyte ionic conductivity review
- 工作流: research（R1 检索 → R2 精读 → R3 创新点 → R4 验证 → R5 写作 → R6 评审）
- 顶层状态: DONE
- 检索来源配置: lit_source=local
- 生成: 2026-10-06T09:44:02Z

## 工作流状态总表

| 步骤 | 状态 | 尝试次数 |
| --- | --- | --- |
| R1_search | DONE | 1 |
| R2_read | DONE | 1 |
| R3_analyze | DONE | 1 |
| R4_verify | DONE | 1 |
| R5_write | DONE | 1 |
| R6_review | DONE | 1 |



## 科研结论（证据绑定）

- **C1 多源检索**：多源检索（来源=local）命中 5 篇；各源状态：{'local': 'ok:5'}；不可用源：无。 `[EV-0001; EV-0002; EV-0003; EV-0004; EV-0005]`
- **C2 论文精读**：论文精读 3 篇成功、0 篇失败（失败已跳过并标注，不阻塞流程）；扫描件/低置信度 0 篇。 `[EV-0013; EV-0014; EV-0015]`
- **C3 创新点/Gap**：创新点拆解共识别 4 个创新点，识别 Research Gap 0 个。 `[EV-0017; EV-0018]`
- **C4 事实验证**：事实验证：引用/观点一致性率 100.00%，检出文献间潜在矛盾 0 处。 `[EV-0019]`
- **C5 写作/自评审**：综述草稿含引用标记；自评审综合分 8.6/10，结论 Accept（P0 草稿级）。 `[EV-0020]`

## 证据索引表

| EV | 类型 | 引用 | SHA-256(前16) | 生产步骤 |
| --- | --- | --- | --- | --- |
| EV-0001 | literature | 10.1038/nmat3066 |  | R1_search |
| EV-0002 | literature | 10.1038/nenergy.2016.30 |  | R1_search |
| EV-0003 | literature | 10.1016/0167-2738(92)90421-F |  | R1_search |
| EV-0004 | literature | 10.1002/anie.200701144 |  | R1_search |
| EV-0005 | literature | 10.1002/anie.200800627 |  | R1_search |
| EV-0006 | data | literature\research_hits.json | 09e0ce279cddf678 | R1_search |
| EV-0007 | query_generation | solid-state electrolyte ionic conductivity review |  | R1_search |
| EV-0008 | relevance | 10.1038/nmat3066 |  | R2_read |
| EV-0009 | relevance | 10.1038/nenergy.2016.30 |  | R2_read |
| EV-0010 | relevance | 10.1016/0167-2738(92)90421-F |  | R2_read |
| EV-0011 | relevance | 10.1002/anie.200701144 |  | R2_read |
| EV-0012 | relevance | 10.1002/anie.200800627 |  | R2_read |
| EV-0013 | note | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-094401-eb9a60\reading\notes\L001.json | 3683982c7bae8acc | R2_read |
| EV-0014 | note | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-094401-eb9a60\reading\notes\L002.json | 671e955133129c08 | R2_read |
| EV-0015 | note | C:/Users/ASUS/Desktop/黑客松/paper-agent\runs\run-20261006-094401-eb9a60\reading\notes\L004.json | dc3e5cadfc35deb5 | R2_read |
| EV-0016 | data | reading\reading_report.json | 7d4ea842b7f2adc6 | R2_read |
| EV-0017 | analysis | analysis\innovations.json | 681a2469fa0fc138 | R3_analyze |
| EV-0018 | analysis | analysis\gaps.json | c994d56dbdebaac5 | R3_analyze |
| EV-0019 | factcheck | factcheck\factcheck.json | 80c58de63d770c94 | R4_verify |
| EV-0020 | draft | writing\review.md | 8e54e1d958080ebc | R5_write |
| EV-0021 | data | writing\references.bib | 4ec355c4ff9b21da | R5_write |
| EV-0022 | review | review\review_report.md | 2dbf4a4abeb42d3b | R6_review |

## 复现命令

```bash
cd C:\Users\ASUS\Desktop\黑客松\paper-agent
PYTHONPATH=core python -m paper_agent.cli run-all --workflow research --goal "<goal>" --lit-source local
PYTHONPATH=core python -m paper_agent.cli resume --run run-20261006-094401-eb9a60
PYTHONPATH=core python -m paper_agent.cli report --run run-20261006-094401-eb9a60
# 异常恢复场景（PRD F-4.8）：
#   场景1 API超时降级  : --chaos ss_timeout
#   场景2 扫描件解析降级: --chaos scan_pdf
#   场景3 批量失败跳过  : --chaos batch_fail_at=2
#   长任务崩溃+续跑    : --chaos kill_after_r3 然后 resume

```

> 数据红线：所有结论均来自真实检索元数据与本地解析产物；检索测试集为 demo 规模小样本标注，
> 用于演示指标口径，不代表真实世界性能。严禁伪造数据。
