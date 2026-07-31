[CmdletBinding()]
param(
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$messages = @'
{
  "scriptMissing": "\u627e\u4e0d\u5230 CodexPet \u542f\u52a8\u811a\u672c\uff1a"
}
'@ | ConvertFrom-Json

$scriptPath = Join-Path $PSScriptRoot "scripts\start_codex_pet.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "$($messages.scriptMissing)$scriptPath"
}

& $scriptPath @PSBoundParameters
