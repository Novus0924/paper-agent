@echo off
rem demo\run_agh_install.cmd — AGH 插件安装（真实控制台 TTY，人工确认 [y/N]）
rem
rem 用法: demo\run_agh_install.cmd ^<agnes.mjs 绝对路径^>
rem   （推荐直接用 bash demo/install_plugin.sh —— 它自动完成 trust/enable/验证/冒烟，
rem    本文件只是给纯 cmd 环境的最小等价物，只做 add + status 两步。）
setlocal
chcp 65001 >nul

set "AGH_ENTRY=%~1"
if "%AGH_ENTRY%"=="" set "AGH_ENTRY=%AGH_ENTRY%"
if "%AGH_ENTRY%"=="" (
  echo 用法: %~nx0 ^<agnes.mjs 绝对路径^>
  echo   或先 set AGH_ENTRY=C:\...\agnes-harness\packages\cli\dist\local\agnes.mjs 再运行
  echo   （推荐改用：bash demo\install_plugin.sh，一条命令全搞定）
  exit /b 1
)

rem 仓库根 = 本脚本上一级目录（自动定位，无硬编码路径）
cd /d "%~dp0.."

rem 插件 spawn Python 用（变量名必须带连字符，与插件读取的一致；
rem 旧版写成 PAPER_AGENT_ROOT 是错的——那不是插件读的变量，会静默失效）
set "paper-agent_ROOT=%cd%"
set "paper-agent_PYTHON=python"
set "PYTHONIOENCODING=utf-8"

echo === [1/2] agh package add（需要在本窗口输入 y 确认安装） ===
node "%AGH_ENTRY%" package add "file:./plugins/paper-agent-tools"

echo.
echo === [2/2] agh package status ===
node "%AGH_ENTRY%" package status

echo.
echo 提示：安装后的 trust / enable / 验证 / 冒烟测试，请运行：
echo   bash demo/install_plugin.sh   （幂等，会自动补全剩余步骤）
pause
