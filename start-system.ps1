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
#
#  参数：
#    -LanIpOnly   只打印本机局域网 IP 后退出（供 低空系统.bat 复用探测逻辑）
# =============================================================================
param([switch]$LanIpOnly)

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
        # 排除回环、链路本地与各类虚拟网卡（VPN / 虚拟机 / TUN 等），避免把手机地址给成 VPN 的 IP
        $cands = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                 Where-Object {
                     $_.IPAddress -notlike '127.*' -and
                     $_.IPAddress -notlike '169.254.*' -and
                     $_.InterfaceAlias -notmatch 'Loopback|vEthernet|VMware|VirtualBox|Hyper-V|Radmin|Tailscale|ZeroTier|TAP|TUN|Bluetooth|蓝牙'
                 }
        if (-not $cands) { return $null }
        $private = $cands | Where-Object { $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)' }
        $pool = if ($private) { $private } else { $cands }
        $pick = $pool | Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-?Fi|以太网|Ethernet' } | Select-Object -First 1
        if (-not $pick) { $pick = $pool | Select-Object -First 1 }
        if ($pick) { return $pick.IPAddress }
    }
    catch { }
    return $null
}

# 只输出局域网 IP 就退出：让 低空系统.bat 等调用方复用同一份探测逻辑，
# 避免每个启动脚本各写一遍、选出 VPN 网卡地址。
if ($LanIpOnly) {
    $ip = Get-LanIp
    if ($ip) { Write-Output $ip }
    exit 0
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
else {
    # 有 .venv 就用 .venv，没有就用系统 Python（$python 由 Find-Python 回退得到）
    $pyLabel = if ($python -eq $apiPy) { "venv" } else { "系统 Python" }
    Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080") `
        -WorkingDirectory $apiDir -WindowStyle Hidden
    Write-Host ("   已启动 · " + $pyLabel) -ForegroundColor Green
}

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
else { Write-Host "   跳过（需 drone_ground_station\venv，内含 PyQt5/PyQtWebEngine）" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 就绪 & 打开
Write-Host ""
Write-Host "等待服务就绪..." -NoNewline
for ($i = 0; $i -lt 25; $i++) {
    if ((Test-Url $portalUrl) -and (Test-Flycontrol)) { break }
    Start-Sleep -Milliseconds 400
    Write-Host "." -NoNewline
}
Write-Host " 完成"

$lan = Get-LanIp

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  系统已就绪" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
if (Test-Flycontrol) {
    Write-Host "  飞控后端        已就绪" -ForegroundColor Green
} else {
    Write-Host "  飞控后端        未就绪（再等几秒刷新；仍失败请手动执行 backend 下的 uvicorn 看报错）" -ForegroundColor Yellow
}
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
