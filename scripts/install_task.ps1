<#
.SYNOPSIS
    Register daily Windows scheduled tasks for finnews-bot.

.DESCRIPTION
    Creates one task per schedule slot. Each task runs finnews.py silently with
    pythonw.exe (no console window) and logs to logs\run.log.

    Schedule model: two delivery slots per day plus one catch-up run per slot.
      09:00  -> --slot am   (primary morning digest)
      13:30  -> --slot am   (catch-up if the PC was asleep at 09:00)
      17:00  -> --slot pm   (primary evening digest)
      21:30  -> --slot pm   (catch-up if the PC was asleep at 17:00)

    The script itself writes a per-slot marker, so a catch-up run is a no-op when
    the slot already delivered. That makes extra retries free and safe.

    Reliability:
      - WakeToRun: wake the machine from sleep (-NoWake to disable)
      - StartWhenAvailable: run a missed occurrence as soon as possible
      - MultipleInstances=IgnoreNew: never stack runs

.PARAMETER Python
    Path to pythonw.exe. Auto-detected (DSH runtime first, then PATH).

.PARAMETER NoWake
    Do not wake the machine from sleep.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install_task.ps1 -NoWake
#>
param(
    [string]$Python = "",
    [string]$NamePrefix = "FinNews",
    [switch]$NoWake
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
        if (Test-Path $c) { $Python = $c; break }
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) { throw "pythonw.exe / python.exe not found. Pass -Python explicitly." }
Write-Host "Python: $Python"
Write-Host "Root  : $root"

$schedule = @(
    @{ Time = "09:00"; Slot = "am"; Note = "morning digest" },
    @{ Time = "13:30"; Slot = "am"; Note = "morning catch-up" },
    @{ Time = "17:00"; Slot = "pm"; Note = "evening digest" },
    @{ Time = "21:30"; Slot = "pm"; Note = "evening catch-up" }
)

foreach ($s in $schedule) {
    $name = "$NamePrefix-" + ($s.Time -replace ":", "")

    $action = New-ScheduledTaskAction -Execute $Python `
        -Argument ("finnews.py --slot " + $s.Slot) -WorkingDirectory $root

    $daily = New-ScheduledTaskTrigger -Daily -At $s.Time

    $settingsArgs = @{
        StartWhenAvailable         = $true
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimit         = (New-TimeSpan -Minutes 20)
        MultipleInstances          = "IgnoreNew"
    }
    if (-not $NoWake) { $settingsArgs["WakeToRun"] = $true }
    $settings = New-ScheduledTaskSettingsSet @settingsArgs

    Register-ScheduledTask -TaskName $name -Action $action -Trigger $daily `
        -Settings $settings -Description ("finnews-bot " + $s.Note + " at " + $s.Time) -Force | Out-Null
    Write-Host ("Registered {0} at {1} (slot {2}, wake: {3})" -f $name, $s.Time, $s.Slot, (-not $NoWake))
}

Write-Host ""
Write-Host "Check : Get-ScheduledTask -TaskName '$NamePrefix-*' | Format-Table TaskName,State"
Write-Host "Run   : Start-ScheduledTask -TaskName '$NamePrefix-0900'"
Write-Host "Info  : Get-ScheduledTaskInfo -TaskName '$NamePrefix-0900'"
Write-Host "Remove: Get-ScheduledTask -TaskName '$NamePrefix-*' | Unregister-ScheduledTask -Confirm:`$false"
