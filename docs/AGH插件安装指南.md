# paper-agent AGH 插件安装指南

> 目的：让任何人**克隆本仓库后，10 分钟内把 `paper-agent-tools` 插件装进 Agnes Harness（AGH）并跑通第一次会话**。
>
> 本文所有坑位均在真实机器上踩过并实测验证（Windows 10/11 + Git Bash + PowerShell；macOS/Linux 见文末差异说明）。
> 文中 `<AGH>` 等尖括号占位符请替换成你自己的路径。

---

## 0. 前置条件

| 依赖 | 要求 | 检查命令 |
|---|---|---|
| AGH | 已从源码构建，存在入口 `agnes.mjs` | `ls <AGH 安装目录>/packages/cli/dist/local/agnes.mjs` |
| Node | **≥ 24**（AGH 要求；低版本会有行为差异） | `node -v` |
| Python | **3.10+**，**零第三方依赖**（仅标准库，无需 pip install 任何东西） | `python --version` |
| paper-agent | 本仓库已克隆 | 当前目录能看到 `plugins/paper-agent-tools/` |

---

## 1. 先懂三个机制（决定了下文每一步为什么长这样）

安装排障中 90% 的问题都源于不了解这三条。**读这一节约省两小时。**

### 机制 ① AGH 安装 `file:` 插件 = 拷贝，运行时看不到你的仓库

AGH 执行 `package add "file:./plugins/paper-agent-tools"` 时，会把插件**复制**进自己的仓库（`~/.agh/data/profiles/<profile>/packages/paper-agent-tools/`）。之后：

- 插件运行时 `__dirname` 指向的是 **AGH 的拷贝目录**，不是你的项目目录；
- **改仓库里的插件源码，对已安装的那份不生效**（跑的是拷贝快照），改完必须重装；
- 插件是「JS 薄壳」，真正的业务在仓库里的 Python 核心（`core/paper_agent/`）。拷贝目录里**没有** Python 核心，所以插件靠两个**环境变量**在运行期找到它们：

| 环境变量 | 含义 | 示例值 |
|---|---|---|
| `paper-agent_PYTHON` | Python 解释器**绝对路径** | `C:/Python312/python.exe` 或 `/usr/bin/python3` |
| `paper-agent_ROOT` | **本仓库的绝对路径**（Python 核心所在） | `D:/works/paper-agent` |

> ⚠️ **最大的坑**：`paper-agent_ROOT` 缺失时，插件会退化用 `__dirname`（拷贝目录）当根，
> 报 `ModuleNotFoundError: No module named 'paper_agent'`——**看起来像依赖没装，实际是环境变量没传到**。
> 不要去翻 pip / site-packages，先查环境变量（见第 5 节排查表第 1 条）。

### 机制 ② 两个环境变量只在 **daemon 启动那一刻** 注入

daemon 是长驻进程，插件从 **daemon 进程的环境**里读这两个变量：

- 你在自己 shell 里 `export` 对**已在跑的** daemon 无效；
- **唯一办法**：先 `daemon stop`，再带着变量重启；
- 变量名带连字符，**bash 的 `export` 写不了这种名字**（`not a valid identifier`），必须用 `env` 前缀或持久化到用户账户（见第 3 步）。

### 机制 ③ 插件安装确认只在交互式 TTY 下有效（无 bypass）

AGH 源码（`bin.ts` 的 `confirmPackageInstall`）写死：非 TTY 环境（管道 / 重定向 / 自动化脚本）**直接判定为取消**（`Installation cancelled.`），没有任何 `--yes` / `--force` 后门。这是安全设计——装插件 = 以本机权限执行 JS，必须人类确认。

所以：**要么在真实终端里人工敲 `y`，要么走 Web 页面点确认**（首选是第 4 步路线 A 的一键脚本，其次 Web 页面）。

---

## 2. 安装路线图

```
★ 快速路径（推荐）：bash demo/install_plugin.sh
   —— 一条命令自动完成下面全部步骤（路径探测/daemon 重启/两个哈希自动提取/
      trust+enable/验证/冒烟），只有「安装确认」一步需要你在真实终端敲 y。

手动展开（理解原理用 / 脚本失效时的兜底）：
第1步 配置环境变量（持久化） → 第2步 重启 daemon → 第3步 只读预检
  → 第4步 安装+信任+启用【人工确认】 → 第5步 验证（status + 冒烟测试）
```

```bash
bash demo/install_plugin.sh --check    # 先只读预检（不装）
bash demo/install_plugin.sh           # 安装（幂等，可重复运行）
bash demo/install_plugin.sh --reinstall  # 插件源码更新后强制重装
```

---

## 3. 第 1 步：配置环境变量（一次配好，永久生效）

### Windows（PowerShell，推荐持久化到用户账户）

```powershell
# 三个值都换成你自己的
[Environment]::SetEnvironmentVariable("paper-agent_ROOT",   "D:\works\paper-agent", 'User')
[Environment]::SetEnvironmentVariable("paper-agent_PYTHON", "C:\Python312\python.exe", 'User')
```

设完后**必须新开终端**（旧终端读不到），验证：

```powershell
# PowerShell 取带连字符的变量必须用 ${env:...} 写法
${env:paper-agent_ROOT}
${env:paper-agent_PYTHON}
```

### macOS / Linux（写入 shell 配置）

```bash
# bash 的 export 写不了带连字符的名字，用这种方式写进 ~/.bashrc 或 ~/.zshrc：
# （若你的 shell 是 zsh，zsh 的 export 反而支持连字符名，直接 export 也可以）
env "paper-agent_ROOT=/home/me/works/paper-agent" \
    "paper-agent_PYTHON=/usr/bin/python3" true   # 仅示意；实际持久化见下

# 最稳的持久化：用 printf 写成 env 调用行，或使用 zsh
```

> 简化建议：bash 用户可以不持久化，直接在下文所有命令前加 `env` 前缀（见第 4 步路线 C 的写法；或直接用路线 A 脚本，它自动处理）。
> 取值时也要用 `printenv 'paper-agent_ROOT'`（bash 的 `${...}` 不认连字符名）。

---

## 4. 第 2–4 步：启动 daemon、预检、安装

### 路线 A（首选）：一键脚本 `demo/install_plugin.sh`

在仓库根目录、**真实终端**里运行：

```bash
bash demo/install_plugin.sh            # 或先 --check 做只读预检
```

它会自动完成：仓库根定位（按脚本位置，无硬编码）→ AGH 入口探测（参数 > `AGH_ENTRY` > 常见克隆位置）→ node ≥24 / python ≥3.10 校验 → **用正确环境变量在仓库根重启 daemon** → `inspect` 自动提取 integrity → 安装（提示你敲 `y`）→ **从审计日志自动提取 capabilityHash** → trust + enable → `package status` 三字段终验 → 插件链路冒烟测试。

幂等性：已装好则直接跳到验证；`--reinstall` 强制重装（改了插件源码后用）。
任何一步失败都会打印**指向根因的中文提示**与修复建议，不会静默。

> 下面的手动路线仅供理解原理，或脚本在特殊环境失效时兜底。

先在本机终端里定义三个公共变量（下面所有命令都用它们；**`AGH` 必须是绝对路径**，`node agnes.mjs` 这种相对路径写法会因为找不到模块而报错）：

```bash
AGH="<AGH 安装目录>/packages/cli/dist/local/agnes.mjs"    # ← 改我
PY="<Python 解释器绝对路径>"                                 # ← 改我（Windows 用 C:/... 盘符正斜杠形式）
ROOT="<paper-agent 仓库绝对路径>"                            # ← 改我

cd "$ROOT"
```

### 第 2 步：重启 daemon（带着环境变量，且**必须在仓库根目录启动**）

```bash
# 1) 停掉可能存在的旧 daemon（不停的话新变量注入不进去）
node "$AGH" daemon stop

# 2) 在仓库根目录启动（★ file:./ 相对路径按 daemon 的启动工作目录解析）
#    若变量已持久化（第 1 步做过且新开了终端），直接：
node "$AGH" daemon start
#    若没持久化，用 env 前缀注入：
env "paper-agent_PYTHON=$PY" "paper-agent_ROOT=$ROOT" node "$AGH" daemon start

# 3) 确认
node "$AGH" daemon status      # 期望 "running":true, "socketReachable":true
```

> ⚠️ **两个易错点**：
> ① daemon 可能被任何 AGH 命令**自动拉起**（比如 `package status`）——谁先调用，谁就把自己的工作目录"钉"给 daemon。换目录操作前务必 `daemon stop`。
> ② 冷启动约需 20–30 秒，期间无输出属正常，别急着 Ctrl+C。

### 第 3 步：只读预检（安全，可反复跑）

```bash
node "$AGH" package inspect "file:./plugins/paper-agent-tools"
```

期望输出：

```
Preview paper-agent-tools@0.1.0
integrity sha256-<64位十六进制>          ← 记下来，trust 时要用
contributions none                       ← ★ 正常！不是错误（见下）
warnings Package provenance has not been independently verified.
```

> `contributions none` 是**预期行为**：AGH 把 `agnes.plugins`（可执行插件声明）与 `contributions`（静态元数据）分开处理，官方测试用例也断言该场景为空。**插件没有写错。**
> 若报 `The package source could not be accepted.` → daemon 的工作目录不在仓库根，回到第 2 步重来（stop → cd → start）。

### 第 4 步：安装 + 信任 + 启用 —— **必须人工**

#### 路线 B：Web 页面，全程点选，不用记任何参数

```bash
node "$AGH" serve          # 冷启动约 20–30 秒
# 就绪后打开 http://127.0.0.1:4177/
```

在 Web 页面的插件管理里：

1. 添加包，来源填 `file:./plugins/paper-agent-tools`；
2. 预览确认（核对 package ID `paper-agent-tools`、version `0.1.0`、integrity 与第 3 步一致）；
3. 按页面引导完成 **trust**（信任）与 **enable**（启用）；
4. 该窗口保持打开（serve 与 daemon 绑定生死，关掉 serve 端口就停了）。

#### 路线 C：CLI 真实终端，`y` 确认（= 路线 A 脚本的手动展开）

```bash
# 必须在真实终端（Windows Terminal / PowerShell / Git Bash 窗口）里敲，管道/脚本不行
node "$AGH" package add "file:./plugins/paper-agent-tools"
# 提示 Install paper-agent-tools@0.1.0 (sha256-...)? [y/N]  ← 敲 y 回车
```

CLI 路线装完后，插件处于 `installed-disabled-untrusted` 状态，还需手动 trust + enable：

```bash
# 取 integrity
INTEGRITY=$(node "$AGH" package inspect "file:./plugins/paper-agent-tools" | grep -o 'sha256-[0-9a-f]*')

# 取 capabilityHash（inspect 不输出它，要从审计日志取；路径 = ~/.agh/profiles/<profile>/.agnes-package-audit.jsonl）
CAP_HASH=$(python -c "
import json, os
p = os.path.expanduser('~/.agh/profiles/local-dev/.agnes-package-audit.jsonl')
ev = [json.loads(l) for l in open(p, encoding='utf-8')]
ev = [e for e in ev if e['id'] == 'paper-agent-tools' and e['operation'] == 'install']
print(ev[-1]['capabilityDiff']['next'] if ev else 'NOT_FOUND')
")

# trust + enable
node "$AGH" package trust paper-agent-tools "$INTEGRITY" "$CAP_HASH"
node "$AGH" package enable paper-agent-tools
```

> 上面 python 命令里的 profile 名按实际情况改（默认 `local-dev`，可在 AGH 配置里查）。

---

## 5. 第 5 步：验证装好了

### 5.1 看 `package status`（三个字段缺一不可）

```bash
node "$AGH" package status
```

期望：

```
paper-agent-tools@0.1.0 desired=enabled actual=running trusted=true
```

| 字段 | 含义 | 必须 |
|---|---|---|
| `desired` | 你请求的期望状态 | `enabled` |
| `actual` | **实际运行状态** | `running` |
| `trusted` | 是否已审核授权 | `true` |

**只看到 `desired=enabled` 不算成功。**

### 5.2 冒烟测试：不经 AGH 直接验插件（无需 TTY，随时可跑）

> 路线 A（`install_plugin.sh`）**结尾会自动跑 ①**；手动安装（路线 B/C）需要自己跑。

仓库自带两个自检脚本（`tools/` 目录），它们绕过 AGH 直接加载插件、调 Python 核心，**安装前后都能用来区分"插件坏了"还是"AGH 配置问题"**：

```bash
cd <paper-agent 仓库根目录>

# ① 静态自检：能否加载、7 个工具是否齐全、meta 8 键是否完整
env "paper-agent_PYTHON=$PY" "paper-agent_ROOT=$ROOT" node tools/verify-plugin-offline.mjs
# 期望：注册工具数 = 7；meta 8 键校验 = PASS；inject = ["extension"]

# ② 端到端自检：真跑 sciret_plan → status → cite，外加一条路径穿越拦截
env "paper-agent_PYTHON=$PY" "paper-agent_ROOT=$ROOT" node tools/verify-plugin-e2e.mjs
# 期望：plan 返回 ok:true + run_id；非法 run_id ../../etc/passwd 被 H1 校验拦下
```

> Windows Git Bash 用户注意：个别环境下 `env ... node ...` 会**静默无输出**（node 被加载但没执行）。遇到这种情况，先按第 1 步把变量持久化到用户账户、**新开终端**，然后直接 `node tools/verify-plugin-offline.mjs`（不经 env）。

### 5.3 真实会话：问它一句

在 AGH 会话（Web 页面或 TUI）里输入：

> 请使用科研流水线工具：sciret_plan 规划一个"硫化物固态电解质电导率排序"任务并返回 run_id；然后 sciret_status 查看状态。

只要返回了 `run_id`（形如 `run-20261004-092413-05cb1d`），链路就通了。完整流程（P1–P5 执行、verify、report、cite）见仓库 `README.md` 的「AGH 联调」一节。

---

## 6. 故障排查表（全部真实踩过）

> 用路线 A 脚本的话，下表 2/3/5/6/7 号坑它都会自动规避或当场报出根因。

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 0 | `install_plugin.sh` 报「AGH 入口无任何输出」 | 个别 Git Bash 的 `env→node` 静默失败（脚本自检步骤拦下） | 按报错里的 PowerShell 命令持久化两个变量 → **新开终端**重跑脚本 |
| 1 | 会话里调 `sciret_*` 报 `ModuleNotFoundError: No module named 'paper_agent'` | daemon 启动时没带 `paper-agent_ROOT` / `paper-agent_PYTHON`（机制①②） | 重跑 `bash demo/install_plugin.sh`（会用正确环境重启 daemon）→ **新开会话**再试（旧会话可能还连着老 daemon） |
| 2 | `Cannot find module '...\agnes.mjs'` | 用了相对路径 `node agnes.mjs` | `agnes.mjs` 在 AGH 安装目录里，**永远用绝对路径** |
| 3 | `package inspect` 报 `The package source could not be accepted.` | daemon 启动时的工作目录不在仓库根（机制②的 `file:./` 解析） | `daemon stop` → `cd <仓库根>` → `daemon start` → 重试；期间别在别的目录跑 AGH 命令 |
| 4 | `package add` 输出 `Installation cancelled.` | 非 TTY 环境（机制③），无 bypass | 换真实终端人工敲 `y`，或走 Web 页面 |
| 5 | `export "paper-agent_PYTHON=..."` 报 `not a valid identifier` | bash 变量名不允许连字符 | 用 `env "name=value" cmd` 前缀，或持久化到用户账户；取值用 `printenv` |
| 6 | AGH 命令**零输出**、退出码 0 | 个别 Git Bash 的 `env → node` 链路静默失败 | 变量持久化后新开终端，**直接** `node <AGH绝对路径> <子命令>`，不经 env |
| 7 | `package status` 显示 `desired=enabled` 但工具还是不可用 | `actual` 不是 `running` 或 `trusted` 不是 `true` | 补做 trustcapabilityHash 从审计日志取，见第 4 步路线 C；或重跑路线 A 脚本自动补全）和 enable |
| 8 | 改了插件源码，重装前行为不变 | AGH 跑的是**拷贝快照**（机制①） | 重新 `package add`；integrity 变了的话旧 trust 记录失效，需重做 trust → enable |
| 9 | `serve` 后浏览器 `ERR_CONNECTION_REFUSED` | 冷启动 20–30 秒静默期 | 等 30 秒再刷新；仍不行看服务日志 |
| 10 | `inspect` 显示 `contributions none` | **正常**，不是错误 | 不用处理 |
| 11 | 换了终端/目录后插件时好时坏 | daemon 被别的目录的调用自动拉起，工作目录被"钉"偏 | 养成习惯：换目录前 `daemon stop`，在仓库根重启 |

---

## 7. macOS / Linux 差异

- 路径与 Python：`PY=/usr/bin/python3`，`ROOT=$HOME/works/paper-agent` 等；
- 环境变量：zsh 的 `export` 支持连字符名，可直接 `export paper-agent_ROOT=...`；bash 不支持，用 `env` 前缀或写进 `~/.profile` 的等价方案；
- 审计日志路径：`~/.agh/profiles/<profile>/.agnes-package-audit.jsonl`（`os.path.expanduser('~')` 会自动解析）；
- 机制①②③（拷贝、环境变量注入时机、TTY 确认）与平台无关，全部适用。

---

## 8. 验收清单（装完逐项打勾）

> 路线 A 脚本会自动完成并打印其中大部分项的结果。

- [ ] `bash demo/install_plugin.sh` 全程绿（或 `--check` 预检通过后手动路线全绿）
- [ ] `daemon status` → `running:true` 且 `socketReachable:true`
- [ ] `package inspect` → `Preview paper-agent-tools@0.1.0`，integrity 已记录
- [ ] 安装已人工确认（Web 页面或终端 `y`）
- [ ] `package status` → `desired=enabled actual=running trusted=true`
- [ ] `tools/verify-plugin-offline.mjs` → 7 工具 + meta 8 键 PASS
- [ ] `tools/verify-plugin-e2e.mjs` → 拿到 `run_id`，非法 run_id 被拦
- [ ] 真实会话里 `sciret_plan` 返回 `run_id`

全部打勾即接入完成。会话证据导出（`evidence/session-*.jsonl`）与审计包归集见仓库 `README.md`「AGH 联调」与 `HOW-TO-VERIFY.md`。
