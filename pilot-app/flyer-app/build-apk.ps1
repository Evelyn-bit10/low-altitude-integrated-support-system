# =============================================================================
#  挺中航空 · 飞手端 —— Android APK 一键打包
#  由 低空系统.bat 的 apk 子命令调用（菜单 [11]）。首次运行会自动下载依赖与 Gradle，请耐心等待。
# =============================================================================
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

function Say($m) { Write-Host $m }
function Step($m) { Write-Host ""; Write-Host $m -ForegroundColor Cyan }
function Fail($m) {
    Write-Host ""
    Write-Host ("[失败] " + $m) -ForegroundColor Red
    Write-Host ""
    Read-Host "按回车退出"
    exit 1
}
function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "============================================================"
Write-Host "  挺中航空 · 飞手端 —— Android APK 打包"
Write-Host "============================================================"

# ------------------------------------------------------------------ 1 环境检查
Step "[1/7] 检查打包环境"

if (-not (Have node)) { Fail "未找到 Node.js。请先安装：https://nodejs.org/（装 LTS 版即可）" }
Say ("      Node   " + (& node --version))

if (-not (Have npm)) { Fail "未找到 npm（通常随 Node.js 一起安装）" }
Say ("      npm    " + (& npm --version))

if (-not (Have java)) {
    Fail @"
未找到 JDK。Android 打包需要 JDK 17：
  下载 Eclipse Temurin 17（Windows x64 .msi）：https://adoptium.net/temurin/releases/?version=17
  安装时勾选 "Set JAVA_HOME variable"，装完重新打开本窗口再运行一次。
"@
}
$javaLine = (& java -version 2>&1 | Select-Object -First 1)
Say ("      Java   " + $javaLine)

if (-not $env:ANDROID_HOME -and -not $env:ANDROID_SDK_ROOT) {
    $guess = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $guess) {
        $env:ANDROID_HOME = $guess
        Say ("      SDK    自动识别 " + $guess)
    }
    else {
        Fail @"
未找到 Android SDK。二选一：
  A) 安装 Android Studio（推荐，图形化最省事）：https://developer.android.com/studio
     安装向导里勾选 Android SDK，装好后重新运行本脚本。
  B) 只装命令行工具，然后：
     sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
     并设置环境变量 ANDROID_HOME 指向 SDK 目录。
"@
    }
}
Say ("      SDK    " + $env:ANDROID_HOME)

# ------------------------------------------------------------------ 2 组装 www
Step "[2/7] 组装静态资源到 www/"
$www = Join-Path $root "www"
if (Test-Path $www) { Remove-Item $www -Recurse -Force }
New-Item -ItemType Directory -Path $www -Force | Out-Null

$assets = @("index.html", "styles.css", "app.js", "decision.js", "api.js", "map.js", "mock.js", "manifest.webmanifest", "sw.js")
foreach ($f in $assets) {
    $src = Join-Path $root $f
    if (-not (Test-Path $src)) { Fail ("缺少文件：" + $f) }
    Copy-Item $src $www -Force
}
Copy-Item (Join-Path $root "icons") $www -Recurse -Force
Say ("      已复制 " + (Get-ChildItem $www -Recurse -File).Count + " 个文件")

# ------------------------------------------------------------------ 3 依赖
Step "[3/7] 安装 Capacitor 依赖（首次约 1-3 分钟）"
if (-not (Test-Path (Join-Path $root "node_modules\@capacitor\cli"))) {
    & npm install --no-audit --no-fund "@capacitor/core@6" "@capacitor/cli@6" "@capacitor/android@6"
    if ($LASTEXITCODE -ne 0) { Fail "npm install 失败，请检查网络（必要时配置 npm 镜像）" }
}
else { Say "      依赖已存在，跳过" }

# ------------------------------------------------------------------ 4 生成工程
Step "[4/7] 生成 / 更新 Android 工程"
if (-not (Test-Path (Join-Path $root "android"))) {
    & npx cap add android
    if ($LASTEXITCODE -ne 0) { Fail "npx cap add android 失败" }
}
else { Say "      android/ 已存在，跳过生成" }

# ------------------------------------------------------------------ 5 明文 HTTP
Step "[5/7] 允许明文 HTTP（连接内网后端 http://192.168.x.x:8082 必需）"
$manifest = Join-Path $root "android\app\src\main\AndroidManifest.xml"
if (-not (Test-Path $manifest)) { Fail "未找到 AndroidManifest.xml，Android 工程可能生成失败" }
$t = Get-Content $manifest -Raw -Encoding UTF8
if ($t -notmatch 'usesCleartextTraffic') {
    # 注意：Capacitor 生成的 <application 后面是换行而非空格，必须用 \s+ 匹配任意空白（用空格会静默失败）
    $t = $t -replace '<application(\s+)', '<application android:usesCleartextTraffic="true"$1'
    if ($t -notmatch 'usesCleartextTraffic="true"') { Fail "写明文 HTTP 配置失败：AndroidManifest.xml 结构不符合预期" }
    # 用 WriteAllText 无 BOM 写出；PowerShell 的 Set-Content -Encoding UTF8 会加 BOM
    [System.IO.File]::WriteAllText($manifest, $t, (New-Object System.Text.UTF8Encoding($false)))
    Say '      已写入 android:usesCleartextTraffic="true"'
}
else { Say "      已配置，跳过" }

# 复核：这一项错了会导致 App 连不上内网后端，且现象是"连不上也不报错"
$verify = [System.IO.File]::ReadAllText($manifest, [System.Text.Encoding]::UTF8)
if ($verify -notmatch 'usesCleartextTraffic="true"') { Fail "复核失败：AndroidManifest.xml 未开启明文 HTTP" }
Say "      复核通过：明文 HTTP 已开启"

# ------------------------------------------------------------------ 6 同步
Step "[6/7] 同步资源到 Android 工程"
& npx cap sync android
if ($LASTEXITCODE -ne 0) { Fail "npx cap sync 失败" }

# ------------------------------------------------------------------ 7 打包
Step "[7/7] Gradle 打包（首次会下载 Gradle，约 3-10 分钟，请勿关闭窗口）"
Push-Location (Join-Path $root "android")
& .\gradlew.bat assembleDebug
$gradleCode = $LASTEXITCODE
Pop-Location

if ($gradleCode -ne 0) {
    Fail @"
Gradle 打包失败。常见原因：
  1) 缺少 SDK 组件 —— 打开 Android Studio 的 SDK Manager，安装
     "Android SDK Platform 34" 与 "Android SDK Build-Tools 34.0.0"
     或命令行执行：sdkmanager "platforms;android-34" "build-tools;34.0.0"
  2) JDK 版本不对 —— 需要 JDK 17（不是 8，也不是 11）
  3) 首次下载依赖超时 —— 重跑一次本脚本即可
"@
}

$apk = Join-Path $root "android\app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { Fail "Gradle 结束但没找到 APK，请检查上面输出" }

$out = Join-Path $root "挺中航空飞手端.apk"
Copy-Item $apk $out -Force
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  打包成功" -ForegroundColor Green
Write-Host ("  APK: " + $out + "  (" + $mb + " MB)") -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  安装到手机："
Write-Host "    1) 把 APK 传到手机（数据线 / 微信 / 网盘）后点击安装，需允许「未知来源」；"
Write-Host "    2) 或手机开 USB 调试后执行："
Write-Host ("       adb install -r `"" + $out + "`"")
Write-Host ""
Write-Host "  首次打开后：" -ForegroundColor Yellow
Write-Host "    进入「我的 → 设置」，填写后端地址（电脑/机场服务器局域网 IP），例如" -ForegroundColor Yellow
Write-Host "      机场服务     http://192.168.1.20:8082" -ForegroundColor Yellow
Write-Host "      地面站服务   http://192.168.1.20:8090" -ForegroundColor Yellow
Write-Host "    点「测试连接」确认通了，再「保存并同步」。" -ForegroundColor Yellow
Write-Host ""

Start-Process explorer.exe -ArgumentList ("/select,`"" + $out + "`"")
Read-Host "按回车退出"
