# demo 脚本索引

> 安装插件的首选入口是 **`install_plugin.sh`**；完整安装步骤与故障排查见
> [../docs/AGH插件安装指南.md](../docs/AGH插件安装指南.md)。

## AGH 插件安装相关

| 脚本 | 用途 | 用法 |
|---|---|---|
| `install_plugin.sh` | ★ **一键安装**（幂等；自动探测路径、重启 daemon、提取 integrity/capabilityHash、trust+enable、冒烟测试） | `bash demo/install_plugin.sh [agnes.mjs 路径]` |
| 同上 · 预检 | 只读环境预检，不安装 | `bash demo/install_plugin.sh --check` |
| 同上 · 重装 | 插件源码更新后强制重装 | `bash demo/install_plugin.sh --reinstall` |
| `run_agh_install.cmd` | 纯 cmd 环境最小安装（只做 add+status；推荐改用上面的 sh） | `demo\run_agh_install.cmd <agnes.mjs 路径>` |
| `reinstall_plugin.ps1` | Windows 自动化重装（真实控制台 + 键盘注入确认；需 AGH_ENTRY） | `.\reinstall_plugin.ps1`（参数 `-Root` `-Agh` 可覆盖） |

**注意**：AGH 的安装确认只在**真实终端**（TTY）里有效——安全设计，无 bypass。
`install_plugin.sh` 在需要确认时会提示你在终端里输入 `y`。

## AGH 会话联调（装好插件后）

| 脚本 | 用途 | 用法 |
|---|---|---|
| `demo_agh_session.sh` | 真实会话联调：inspect→install→trust→enable→`-p` 会话→export 证据→审计包 | 先 `export AGH_ENTRY=<agnes.mjs 绝对路径>` 再 `bash demo/demo_agh_session.sh` |

## Python 核心演示（无需 AGH）

| 脚本 | 用途 |
|---|---|
| `demo_e2e.sh` | 端到端正常流程 + 确定性 SHA-256 双跑核验 |
| `demo_failure.sh` | 四大故障恢复用例自动化（重试/降级/resume/复现 FAIL） |
| `demo_trust.sh <RUN_ID>` | 信任机制现场演示：账本篡改与伪造验证双双被拦截 |
