[CmdletBinding()]
param(
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$mainScript = Join-Path $projectRoot "main.py"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "codexpet-start.log"

$messages = @'
{
  "requestReceived": "\u6536\u5230\u542f\u52a8\u8bf7\u6c42\u3002Restart=",
  "venvMissing": "\u5c1a\u672a\u521b\u5efa .venv\uff0c\u8bf7\u5148\u8fd0\u884c scripts\\setup_environment.ps1\u3002",
  "mainMissing": "\u627e\u4e0d\u5230\u4e3b\u7a0b\u5e8f\uff1a",
  "alreadyRunning": "CodexPet \u5df2\u5728\u8fd0\u884c\u3002",
  "alreadyRunningLog": "\u68c0\u6d4b\u5230\u5df2\u8fd0\u884c\uff0c\u672a\u91cd\u590d\u542f\u52a8\uff1a",
  "restartStopping": "\u51c6\u5907\u91cd\u542f\uff0c\u505c\u6b62\u5df2\u6709 CodexPet \u8fdb\u7a0b\uff1a",
  "stopFailed": "\u65e0\u6cd5\u505c\u6b62\u5df2\u6709 CodexPet \u8fdb\u7a0b\uff1a",
  "startRequested": "\u5df2\u53d1\u9001\u542f\u52a8\u8bf7\u6c42\uff0c\u542f\u52a8\u8fdb\u7a0b ID\uff1a",
  "startMissing": "\u542f\u52a8\u540e\u672a\u68c0\u6d4b\u5230 CodexPet \u8fdb\u7a0b\u3002",
  "started": "CodexPet \u5df2\u542f\u52a8\u3002",
  "startedLog": "\u542f\u52a8\u786e\u8ba4\u5b8c\u6210\uff0c\u5f53\u524d\u8fdb\u7a0b\uff1a",
  "failedLog": "\u542f\u52a8\u5931\u8d25\uff1a",
  "failedPrefix": "CodexPet \u542f\u52a8\u5931\u8d25\uff1a",
  "logPath": "\u65e5\u5fd7\u8def\u5f84\uff1a"
}
'@ | ConvertFrom-Json

function Write-CodexPetLog {
    param([string]$Message)

    if (-not (Test-Path -LiteralPath $logDirectory)) {
        New-Item -ItemType Directory -Path $logDirectory | Out-Null
    }
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

function Get-CodexPetProcess {
    $mainNeedle = $mainScript
    $runNeedle = Join-Path $projectRoot "scripts\run.ps1"

    Get-CimInstance Win32_Process | Where-Object {
        if (-not $_.CommandLine) { return $false }
        $commandLine = $_.CommandLine
        $commandLine.IndexOf($mainNeedle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $commandLine.IndexOf($runNeedle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    } | Sort-Object ProcessId -Unique
}

function Stop-CodexPetProcess {
    $processes = @(Get-CodexPetProcess)
    if ($processes.Count -eq 0) {
        return
    }

    Write-CodexPetLog "$($messages.restartStopping)$($processes.ProcessId -join ', ')"
    foreach ($process in ($processes | Sort-Object ProcessId -Descending)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    $deadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = @(Get-CodexPetProcess)
    } while ($remaining.Count -gt 0 -and (Get-Date) -lt $deadline)

    if ($remaining.Count -gt 0) {
        throw "$($messages.stopFailed)$($remaining.ProcessId -join ', ')"
    }
}

try {
    Write-CodexPetLog "$($messages.requestReceived)$Restart"

    if (-not (Test-Path -LiteralPath $python)) {
        throw $messages.venvMissing
    }
    if (-not (Test-Path -LiteralPath $mainScript)) {
        throw "$($messages.mainMissing)$mainScript"
    }

    $running = @(Get-CodexPetProcess)
    if ($running.Count -gt 0 -and -not $Restart) {
        Write-Host $messages.alreadyRunning
        Write-CodexPetLog "$($messages.alreadyRunningLog)$($running.ProcessId -join ', ')"
        exit 0
    }

    if ($Restart) {
        Stop-CodexPetProcess
    }

    $started = Start-Process -FilePath $python -ArgumentList @($mainScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-CodexPetLog "$($messages.startRequested)$($started.Id)"

    Start-Sleep -Seconds 2
    $afterStart = @(Get-CodexPetProcess)
    if ($afterStart.Count -eq 0) {
        throw $messages.startMissing
    }

    Write-Host $messages.started
    Write-CodexPetLog "$($messages.startedLog)$($afterStart.ProcessId -join ', ')"
    exit 0
} catch {
    $message = $_.Exception.Message
    try {
        Write-CodexPetLog "$($messages.failedLog)$message"
    } catch {
    }
    Write-Error "$($messages.failedPrefix)$message$($messages.logPath)$logPath"
    exit 1
}
