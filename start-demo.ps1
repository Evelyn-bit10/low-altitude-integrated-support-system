# =============================================================================
#  低空综合保障系统 —— 演示模式一键启动
#  由根目录「启动演示.bat」调用。
#
#  与「启动一体化门户.bat」的区别：
#    - 不打开门户与飞手端，而是打开【功能演示台】 demo.html
#    - 额外拉起「模拟 UOM 接收端」(8099)，用于第三个功能的现场演示
# =============================================================================
$ErrorActionPreference = "SilentlyContinue"

$root      = $PSScriptRoot
$portalDir = Join-Path $root "platform\portal"
$apiDir    = Join-Path $root "flight\flycontrol\low-altitude-demo\backend"
$apiPy     = Join-Path $apiDir ".venv\Scripts\python.exe"
$mockPy    = Join-Path $apiDir "tools\mock_uom_server.py"

$demoUrl   = "http://127.0.0.1:5500/demo.html"
$apiHealth = "http://127.0.0.1:8080/api/health"
$uomHealth = "http://127.0.0.1:8099/health"
$portalUrl = "http://127.0.0.1:5500/index.html"

function Test-Url([string]$Url, [int]$TimeoutSec = 1) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec).StatusCode -eq 200 }
    catch { return $false }
}
function Find-Python {
    if (Test-Path -LiteralPath $apiPy) { return $apiPy }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  低空综合保障系统 · 功能演示台" -ForegroundColor Cyan
Write-Host "  ① 进出场程序   ② 多设备去重   ③ 对外数据推送" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$python = Find-Python
if (-not $python) {
    Write-Host "[错误] 未找到 Python 运行环境。" -ForegroundColor Red
    Write-Host "       请先按 README 修复 backend\.venv，或安装 Python 并加入 PATH。"
    Read-Host "按回车退出"
    exit 1
}
Write-Host ("  Python : " + $python)
Write-Host ""

# ---------------------------------------------------------------- 1 后端
Write-Host "[1/4] 后端 8080" -NoNewline
if (Test-Url $apiHealth) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    $env:PUSH_MODE = "http"
    $env:PUSH_ENDPOINT = "http://127.0.0.1:8099/uom/v1/messages"
    $env:PUSH_TRACK_INTERVAL = "5"
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080") `
        -WorkingDirectory $apiDir -WindowStyle Hidden
    Write-Host "   已启动（推送模式 http）" -ForegroundColor Green
}

# ---------------------------------------------------------------- 2 模拟 UOM
Write-Host "[2/4] 模拟 UOM 8099" -NoNewline
if (Test-Url $uomHealth) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    Start-Process -FilePath $python `
        -ArgumentList @($mockPy, "--port", "8099") `
        -WorkingDirectory $apiDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}

# ---------------------------------------------------------------- 3 静态服务
Write-Host "[3/4] 演示页面 5500" -NoNewline
if (Test-Url $portalUrl) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "http.server", "5500", "--bind", "127.0.0.1") `
        -WorkingDirectory $portalDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}

# ---------------------------------------------------------------- 4 等待并打开
Write-Host "[4/4] 等待就绪" -NoNewline
for ($i = 0; $i -lt 25; $i++) {
    if ((Test-Url $apiHealth) -and (Test-Url $portalUrl)) { break }
    Start-Sleep -Milliseconds 400
    Write-Host "." -NoNewline
}
Write-Host " 完成" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  演示台已就绪" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ("  功能演示台   " + $demoUrl)
Write-Host ("  管理门户     " + $portalUrl) -ForegroundColor DarkGray
Write-Host ("  接口文档     http://127.0.0.1:8080/docs") -ForegroundColor DarkGray
Write-Host ""
Write-Host "  建议演示顺序：① 进出场程序 → ② 多设备去重 → ③ 对外推送"
Write-Host "  关闭服务：把启动时新开的最小化窗口关掉即可。"
Write-Host ""

Start-Process $demoUrl
