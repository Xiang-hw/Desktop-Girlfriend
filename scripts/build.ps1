$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    throw "尚未安装构建环境，请先运行 scripts\setup_environment.ps1。"
}

Set-Location $projectRoot
if (-not (Test-Path ".\user_assets\workflow.json")) {
    throw "没有私有制作流程状态，不能打包。"
}
if (-not (Test-Path ".\user_assets\pet\manifest.json")) {
    throw "没有私有宠物素材，不能打包。"
}

& ".venv\Scripts\python.exe" ".\tools\onepic_workflow.py" check-package
if ($LASTEXITCODE -ne 0) {
    throw "私有角色或走路尚未验收，已停止打包。"
}

& $pyinstaller --noconfirm --clean OnePicDesktopPet.spec
exit $LASTEXITCODE
