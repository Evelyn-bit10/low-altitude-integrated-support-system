# =============================================================================
#  挺中航空 · 低空综合保障系统 —— 一键启动
#  由根目录「启动一体化门户.bat」调用（双击即用）。
#
#  本脚本是【全系统总入口】，会拉起：
#    1. 飞控后端            flight\flycontrol  (端口 8080)
#    2. 门户数据桥          platform\portal\ground-bridge.py (端口 8090)
#    3. 管理平台门户        platform\portal     (端口 5500)
#    4. 飞手端 App          pilot-app\flyer-app (端口 5502)
#    5. 通讯态势            comms\communication (浏览器打开)
#    6. 地面站桌面端        device\groundstation（若存在虚拟环境）
#
#  服务统一绑定 0.0.0.0，同一 Wi-Fi 下手机可直接访问。
# =============================================================================
$ErrorActionPreference = "SilentlyContinue"

$root      = $PSScriptRoot
$portalDir = Join-Path $root "platform\portal"
$bridgePy  = Join-Path $portalDir "ground-bridge.py"
$apiDir    = Join-Path $root "flight\flycontrol\low-altitude-demo\backend"
$apiPy     = Join-Path $apiDir ".venv\Scripts\python.exe"
$commHtml  = Join-Path $root "comms\communication\index.html"
$pilotDir  = Join-Path $root "pilot-app\flyer-app"
$groundDir = Join-Path $root "device\groundstation\wrjtksf\drone_ground_station"
$groundPy  = Join-Path $groundDir "venv\Scripts\python.exe"

$portalUrl    = "http://127.0.0.1:5500/index.html"
$pilotUrl     = "http://127.0.0.1:5502/index.html"
$apiHealth    = "http://127.0.0.1:8080/api/health"
$bridgeHealth = "http://127.0.0.1:8090/api/health"

function Test-Url([string]$Url, [int]$TimeoutSec = 1) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec).StatusCode -eq 200 }
    catch { return $false }
}
function Test-Flycontrol {
    try { return (Invoke-RestMethod -Uri $apiHealth -TimeoutSec 1).status -eq "ok" }
    catch { return $false }
}
function Find-Python {
    if (Test-Path -LiteralPath $apiPy) { return $apiPy }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    if (Test-Path -LiteralPath $groundPy) { return $groundPy }
    return $null
}
function Get-LanIp {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
               Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
               Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    }
    catch { }
    return $null
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  挺中航空 · 低空综合保障系统" -ForegroundColor Cyan
Write-Host "  一键启动（管理平台 + 飞控 + 通讯态势 + 地面站 + 飞手端）" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$python = Find-Python
if (-not $python) {
    Write-Host "[错误] 未找到 Python 运行环境。" -ForegroundColor Red
    Write-Host "       请确认 flight\flycontrol\low-altitude-demo\backend\.venv 存在，"
    Write-Host "       或已安装 Python 并加入 PATH。"
    Read-Host "按回车退出"
    exit 1
}
Write-Host ("  工程根目录 : " + $root)
Write-Host ("  Python     : " + $python)
Write-Host ""

# ---------------------------------------------------------------- 1 飞控后端
Write-Host "[1/6] 飞控后端       端口 8080" -NoNewline
if (Test-Flycontrol) { Write-Host "   已在运行，复用" -ForegroundColor Green }
elseif (Test-Path -LiteralPath $apiPy) {
    Start-Process -FilePath $apiPy `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080") `
        -WorkingDirectory $apiDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}
else { Write-Host "   跳过（无虚拟环境，门户将回退演示数据）" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 2 数据桥
Write-Host "[2/6] 门户数据桥     端口 8090" -NoNewline
if (Test-Url $bridgeHealth) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    Start-Process -FilePath $python `
        -ArgumentList @($bridgePy, "--host", "0.0.0.0", "--port", "8090") `
        -WorkingDirectory $portalDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}

# ---------------------------------------------------------------- 3 门户
Write-Host "[3/6] 管理平台门户   端口 5500" -NoNewline
if (Test-Url $portalUrl) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "http.server", "5500", "--bind", "0.0.0.0") `
        -WorkingDirectory $portalDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}

# ---------------------------------------------------------------- 4 飞手端
Write-Host "[4/6] 飞手端 App     端口 5502" -NoNewline
if (Test-Url $pilotUrl) { Write-Host "   已在运行，复用" -ForegroundColor Green }
else {
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "http.server", "5502", "--bind", "0.0.0.0") `
        -WorkingDirectory $pilotDir -WindowStyle Hidden
    Write-Host "   已启动" -ForegroundColor Green
}

# ---------------------------------------------------------------- 5 通讯态势
Write-Host "[5/6] 通讯态势       (communication)" -NoNewline
if (Test-Path -LiteralPath $commHtml) {
    Start-Process $commHtml
    Write-Host "   已在浏览器打开" -ForegroundColor Green
}
else { Write-Host "   跳过（未找到 comms\communication\index.html）" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 6 地面站桌面端
Write-Host "[6/6] 地面站桌面端   (groundstation)" -NoNewline
if (Test-Path -LiteralPath $groundPy) {
    Start-Process -FilePath $groundPy -ArgumentList @("main.py") -WorkingDirectory $groundDir
    Write-Host "   已启动（独立窗口）" -ForegroundColor Green
}
else { Write-Host "   跳过（未找到地面站虚拟环境）" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 就绪 & 打开
Write-Host ""
Write-Host "等待门户就绪..." -NoNewline
for ($i = 0; $i -lt 20; $i++) {
    if (Test-Url $portalUrl) { break }
    Start-Sleep -Milliseconds 400
    Write-Host "." -NoNewline
}
Write-Host " 完成"

$lan = Get-LanIp

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  系统已就绪" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ("  管理平台门户    " + $portalUrl)
Write-Host ("  飞手端 App      " + $pilotUrl)
Write-Host ("  飞控接口文档    http://127.0.0.1:8080/docs")
if ($lan) {
    Write-Host ""
    Write-Host ("  手机访问（同一 Wi-Fi）  http://" + $lan + ":5502/index.html") -ForegroundColor Yellow
    Write-Host ("  手机端首次打开需在「我的 → 设置」填 http://" + $lan + ":8080") -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  停止服务：把启动时新开的最小化窗口关掉即可。"
Write-Host ""

Start-Process $portalUrl
