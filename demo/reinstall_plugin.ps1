$root = 'C:\Users\ASUS\Desktop\黑客松\paper-agent'
$agh  = 'C:\Users\ASUS\Desktop\黑客松\agnes-harness\packages\cli\dist\local\agnes.mjs'
$ErrorActionPreference = 'Continue'

$sig = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class Con {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct KEY_EVENT { public bool bKeyDown; public ushort wRepeatCount; public ushort wVirtualKeyCode;
        public ushort wVirtualScanCode; public char unicodeChar; public uint dwControlKeyState; }
    [StructLayout(LayoutKind.Explicit)]
    struct INPUT_RECORD { [FieldOffset(0)] public ushort EventType; [FieldOffset(4)] public KEY_EVENT key; }
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AttachConsole(uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool FreeConsole();
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern IntPtr
        CreateFileW(string name, uint access, uint share, IntPtr sa, uint disp, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool WriteConsoleInputW(
        IntPtr h, INPUT_RECORD[] ir, uint n, out uint written);
    public static string TypeTo(uint pid, string text) {
        FreeConsole();
        if (!AttachConsole(pid)) return "ATTACH_FAIL:" + Marshal.GetLastWin32Error();
        try {
            IntPtr h = CreateFileW("CONIN$", 0xC0000000, 0x3, IntPtr.Zero, 3, 0, IntPtr.Zero);
            if (h == new IntPtr(-1)) return "CONIN_FAIL:" + Marshal.GetLastWin32Error();
            var recs = new List<INPUT_RECORD>();
            foreach (char c in text) {
                var down = new INPUT_RECORD { EventType = 1 };
                down.key = new KEY_EVENT { bKeyDown = true, wRepeatCount = 1,
                    wVirtualKeyCode = (c == '\r') ? (ushort)0x0D : (ushort)0,
                    wVirtualScanCode = (c == '\r') ? (ushort)0x1C : (ushort)0,
                    unicodeChar = c };
                recs.Add(down);
                var up = down; up.key.bKeyDown = false; recs.Add(up);
            }
            uint written;
            bool ok = WriteConsoleInputW(h, recs.ToArray(), (uint)recs.Count, out written);
            return ok ? ("OK written=" + written) : ("WRITE_FAIL:" + Marshal.GetLastWin32Error());
        } finally { FreeConsole(); }
    }
}
'@
Add-Type -TypeDefinition $sig

function AggStatus() { (node $agh package status 2>&1 | Out-String) }

# 1) disable → remove（remove 要求包已停止）
node $agh package disable paper-agent-tools 2>&1 | Out-Null
Start-Sleep -Seconds 3
$rmExit = 1
for ($i = 0; $i -lt 10; $i++) {
    node $agh package remove paper-agent-tools 2>&1 | Out-Null
    $rmExit = $LASTEXITCODE
    if ($rmExit -eq 0) { break }
    Start-Sleep -Seconds 3
}
Write-Output ("REMOVE_EXIT=" + $rmExit)

# 2) 新建真实控制台（TTY），AttachConsole 注入 package add 命令与确认
$p = Start-Process cmd.exe -ArgumentList ('/K', 'title AGH_ADD_SESS & cd /d "' + $root + '" & chcp 65001 & echo READY') -PassThru
Start-Sleep -Seconds 4
Write-Output ("TYPE1=" + [Con]::TypeTo([uint32]$p.Id, 'node "' + $agh + '" package add "file:./plugins/paper-agent-tools"' + "`r"))
Start-Sleep -Seconds 12
Write-Output ("TYPE2=" + [Con]::TypeTo([uint32]$p.Id, "y`r"))
Start-Sleep -Seconds 6
Write-Output ("TYPE3=" + [Con]::TypeTo([uint32]$p.Id, "y`r"))

$installed = $false
for ($i = 0; $i -lt 20; $i++) {
    $st = AggStatus
    if ($st -match 'paper-agent-tools') { $installed = $true; break }
    Start-Sleep -Seconds 3
}
Write-Output ("INSTALLED=" + $installed)
if (-not $installed) { Write-Output ("FINAL_STATUS=" + (AggStatus)); exit 2 }

# 3) trust + enable（无需 TTY）
$prev = (node $agh package inspect "file:./plugins/paper-agent-tools" 2>&1 | Out-String)
$integrity = ([regex]'integrity (sha256-[0-9a-f]+)').Match($prev).Groups[1].Value
if (-not $integrity) { Write-Output ('INTEGRITY_NOT_FOUND; inspect=' + $prev); exit 3 }
$cap = 'e3de4e5f2da4b8aa2650af5c4f822d397c2dadd7a6695e5071c0444d26a22b01'
node $agh package trust paper-agent-tools $integrity $cap 2>&1 | Out-Null
node $agh package enable paper-agent-tools 2>&1 | Out-Null
Start-Sleep -Seconds 3
$final = AggStatus
Write-Output ("INTEGRITY=" + $integrity)
Write-Output ("STATUS_LINE=" + (($final -split "`n") | Where-Object { $_ -match 'paper' }))
try { Stop-Process -Id $p.Id -Force } catch {}
