# 数据来源声明

| 来源 | 说明 | 条款 / 署名 |
| --- | --- | --- |
| arXiv API（`http://export.arxiv.org/api/query`） | 文献元数据检索（标题、作者、摘要、arXiv ID、URL） | 遵守 arXiv API 使用条款与限速（建议 ≤1 req/s） |
| Semantic Scholar Graph API | 引用关系检查（citation_check 兜底） | 免费层；CC-BY 署名要求 |
| scikit-learn 内置数据集 | 实验数据来源（BSD，离线零下载） | BSD License |

## 明确声明

- 文献元数据 = **真实检索**（arXiv / S2 API 实际调用结果）。
- 实验 = **公开小数据集上的真实运行**（sklearn 内置数据集 + matplotlib 出图）。
- **不做论文全文批量抓取**（版权红线）。
