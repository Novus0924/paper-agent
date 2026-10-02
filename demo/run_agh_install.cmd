@echo off
rem demo\run_agh_install.cmd — AGH 插件安装（真实控制台 TTY，人工/代理确认 [y/N]）
rem 用法: 由 `cmd /c start` 拉起独立窗口；或在交互终端直接双击运行。
chcp 65001 >nul
cd /d "C:\Users\ASUS\Desktop\黑客松\paper-agent"
set "PAPER_AGENT_ROOT=C:\Users\ASUS\Desktop\黑客松\paper-agent"
set "PYTHONIOENCODING=utf-8"
echo === [1/2] agh package add (需要在本窗口输入 y 确认安装) ===
node "C:\Users\ASUS\Desktop\黑客松\agnes-harness\packages\cli\dist\local\agnes.mjs" package add "file:./plugins/paper-agent-tools"
echo.
echo === [2/2] agh package status ===
node "C:\Users\ASUS\Desktop\黑客松\agnes-harness\packages\cli\dist\local\agnes.mjs" package status
echo.
pause
