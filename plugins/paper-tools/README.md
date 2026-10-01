# paper-tools（AGH 插件）

- `arxiv_search(query, max_results)` → arXiv 元数据检索
- `citation_check(ids)` → 解析 / 断链引用检查

核心逻辑放 `lib/*.mjs`（纯函数、可离线单测）；`index.mjs` 通过 `ctx.extension().registerTool` 注册到 AGH。
