# paper-agent-tools（AGH 插件）

AGH hot-tool 插件：**JS 薄壳层**——只做参数序列化 + 子进程调用 + 结果包装，
全部科研业务在仓库的 Python 核心（`core/paper_agent/`，零第三方依赖）。

## 7 个工具

`sciret_plan` / `sciret_run_step` / `sciret_status` / `sciret_verify` /
`sciret_report` / `sciret_cite` / `sciret_resume`

双工作流：`research`（R1_search–R6_review，默认）/ `materials`（P1–P5，显式选择）。

## 运行期要求（重要）

AGH 安装 `file:` 包时会把本插件**拷贝**到 `~/.agh/data/profiles/<profile>/packages/` 下运行，
插件自身看不到原仓库——必须由 **daemon 启动时的环境变量** 指向仓库与 Python：

| 变量 | 含义 |
|---|---|
| `paper-agent_PYTHON` | Python ≥ 3.10 解释器绝对路径 |
| `paper-agent_ROOT` | paper-agent 仓库绝对路径（Python 核心所在） |

变量缺失时工具会返回带修复指引的中文错误（而非难排查的 `ModuleNotFoundError`）。

## 安装

见仓库根 `demo/install_plugin.sh`（一键幂等安装）与 `docs/AGH插件安装指南.md`。

```
bash demo/install_plugin.sh            # 安装（幂等；确认环节需真实终端）
bash demo/install_plugin.sh --check    # 只读预检
```
