<#
.SYNOPSIS
    Register daily Windows scheduled tasks for finnews-bot.

.DESCRIPTION
    Creates one task per time of day. Each task runs finnews.py silently with
    pythonw.exe (no console window) and logs to logs\run.log.
    Existing tasks with the same name are replaced.

.PARAMETER Times
    One or more HH:mm strings. Default: 09:00, 17:00.

.PARAMETER NamePrefix
    Task name prefix. Default: FinNews.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -Times 08:30,20:00
#>
param(
    [string[]]$Times = @("09:00", "17:00"),
    [string]$NamePrefix = "FinNews",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $Python) {
    $candidates = @(
        (Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"),
        "pythonw.exe",
        "python.exe"
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
        if (Test-Path $c) { $Python = $c; break }
    }
}
if (-not $Python) { throw "pythonw.exe / python.exe not found. Pass -Python explicitly." }
Write-Host "Python: $Python"
Write-Host "Root  : $root"

foreach ($t in $Times) {
    $name = "$NamePrefix-" + ($t -replace ":", "")
    $action = New-ScheduledTaskAction -Execute $Python -Argument "finnews.py" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $t
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Description "finnews-bot daily digest at $t" -Force | Out-Null
    Write-Host "Registered $name at $t"
}

Write-Host ""
Write-Host "Check : Get-ScheduledTask -TaskName '$NamePrefix-*' | Format-Table TaskName,State"
Write-Host "Run   : Start-ScheduledTask -TaskName '$NamePrefix-0900'"
Write-Host "Remove: Get-ScheduledTask -TaskName '$NamePrefix-*' | Unregister-ScheduledTask -Confirm:`$false"
