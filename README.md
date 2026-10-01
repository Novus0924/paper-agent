# paper-agent

CS/ML 科研论文 Agent（Agnes Harness / AGH 黑客松参赛作品）。

## 目录结构

```
paper-agent/
├── docs/            # 合规与流程文档
│   ├── sources.md       # 数据来源声明（arXiv / Semantic Scholar / scikit-learn）
│   └── ai_disclosure.md # AI 工具使用边界声明
├── plugins/
│   └── paper-tools/     # AGH 插件：arxiv_search / citation_check
├── pipeline/          # 五步流水线（检索 → 抽取 → 实验 → 图表 → 结论）
├── schemas/           # 数据 schema（RawPaper 等）
├── tests/
│   └── fixtures/      # 离线测试样例
├── evidence/          # AGH 执行记录导出件（.jsonl 不入库，开源前需审查）
└── submission/        # 提交材料
```

## 合规红线

- 实验：公开小数据集上的真实运行；文献元数据：真实检索；不做论文全文批量抓取。
- Agnes Key 只放环境变量 `AGNES_API_KEY`，绝不写入仓库。

## 开发纪律

- 每个任务结束 commit；测试不联网（联网放 integration 标记）。
- 本仓库是唯一可提交/开源仓库；AGH 仓库只读。
