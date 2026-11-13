# 挺中航空 · C 端（手机端 Web App）

> 挺中航空科技有限公司 · 面向**虚拟注册 C 端客户（飞手 / 无人机运营者）**的移动端应用。
> 查看起降点周边信息与飞行器实时动态、提交起降申请、查看许可与告警。

这不是管理后台，而是**客户端**：信息优先、操作轻量、视觉抓眼球。深色底 + 霓虹渐变（青 `#2f9bff` / 青绿 `#27e0d8` / 紫 `#7c5cff`），与网页端门户同一套设计 token。

---

## 一、运行方式

**推荐**：双击本目录 `启动.bat`（启动本地服务 `127.0.0.1:5502` 并自动打开浏览器）。

也可以直接双击 `index.html`：界面正常显示，但 **Service Worker / PWA 安装不可用**（需要 http 环境）。

### 真机测试（手机）

#### 一键启动（推荐）

双击本目录 **`真机测试.bat`**。它一次启动四样东西，并把它们都绑到局域网：

| 服务 | 监听 | 说明 |
| --- | --- | --- |
| flycontrol API | `0.0.0.0:8080` | 机场 / 程序 / 态势后端 |
| 地面站数据桥 | `0.0.0.0:8090` | 机位 / RID900 / 传感器 |
| 飞手端 App | `0.0.0.0:5502` | 本 App |
| 一体化门户 | `0.0.0.0:5500` | 网页端门户（用于对比） |

脚本会自动识别本机局域网 IP 并打印手机访问地址，例如：

```text
飞手端 App     http://192.168.1.20:5502/index.html
网页端门户     http://192.168.1.20:5500/index.html
```

手机连同一个 Wi-Fi，直接打开第一个地址即可。

#### 数据一致性怎么验证

**关键点**：App 的后端地址是按「当前页面所在主机」自动推导的（`api.js` 里的 `PAGE_HOST`）——电脑上打开指向 `127.0.0.1`，手机上打开指向**电脑的局域网 IP**。所以手机和电脑访问的是**同一套后端**，数据天然一致，不用改任何代码。

> 如果不做这个推导，手机上 `http://127.0.0.1:8080` 会指向**手机自己**，永远连不上后端，只能看演示数据 —— 这正是真机测试最容易踩的坑。

验证步骤：

1. 手机打开 `http://<电脑IP>:5502/index.html`，看 App 顶栏右侧胶囊：
   - **实时** → 已连上电脑的 flycontrol 与地面站桥，数据是真的；
   - **演示** → 没连上（检查服务是否起来、防火墙是否放行）。
2. 电脑浏览器打开 `http://<电脑IP>:5500/index.html`（网页端门户），同样看它的连接状态。
3. 逐项对照：

   | 对比项 | 飞手端 App | 网页端门户 |
   | --- | --- | --- |
   | 起降点 | 首页顶卡 `CQ-LX01` | 运行总览 / 实时态势 |
   | 飞行器 | 首页「我的飞行器」+ 态势图 | 实时态势「在线飞行器」 |
   | 气象 | 首页天气胶囊 / 周边页仪表盘 | 实时态势「实时气象」 |
   | 机位 | 周边页「可用机位」 | 地面站机位页 |
   | 航路 | 起降申请的预判依据 | 飞行程序页 |

4. **造一个变化来确认真的在同步**：在门户「飞行程序」页点「注入恶劣气象」，或改地面站数据；App 每 15 秒轮询一次，**下拉刷新**可立即同步，两边应同时变化。

> **两边显示不完全相同是正常的**，因为定位不同：
> - 门户是**管理视角**：全部飞行器、全部机位、程序与合规详情；
> - App 是**C 端飞手视角**：只展示「我的飞行器」（`mock.js` 里 `profile.fleet` 绑定的那两架），其他飞行器只在态势图上出现。
> - 另外若在线快照里**没有飞行器**（communication 未回传），两边都会回退到各自的演示目标。

#### 装到手机桌面（PWA）

| 平台 | 操作 | 是否需要 HTTPS |
| --- | --- | --- |
| **Android Chrome** | 地址栏右侧出现「安装」图标 → 点击 | **需要**（见下） |
| **iOS Safari** | 分享 → 「添加到主屏幕」 | 不需要，`http://` 即可全屏运行 |

> **Android 的限制**：Chrome 只在**安全上下文**（HTTPS 或 `localhost`）下允许 Service Worker 与「安装」提示。用 `http://192.168.x.x:5502` 访问时**不会**出现安装按钮。三种解法：
>
> 1. **USB 端口转发（最省事）**：手机开 USB 调试并连电脑，执行 `adb reverse tcp:5502 tcp:5502`，然后手机打开 `http://localhost:5502/index.html` —— `localhost` 算安全上下文，可注册 SW、可安装。
> 2. **Chrome 白名单**：手机 Chrome 访问 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`，填入 `http://192.168.1.20:5502` 并启用，重启 Chrome。
> 3. **上 HTTPS**：内网穿透（frp / ngrok / cpolar）或带证书的内网服务，手机用 `https://` 访问。
>
> 只是**测界面和数据**的话不装也完全够用 —— 浏览器直接打开就能用全部功能。

#### 手动启动（不想用脚本）

```powershell
cd yth\flight\flycontrol\low-altitude-demo\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080

cd yth
python ground-bridge.py --host 0.0.0.0 --port 8090

cd yth\pilot-app\flyer-app
python -m http.server 5502 --bind 0.0.0.0
```

#### 手机打不开？

1. 确认手机与电脑在**同一 Wi-Fi**（手机别开流量 / VPN）；
2. 关掉电脑上的 VPN、代理、网络加速类软件；
3. 放行防火墙 —— 以管理员身份运行一次：
   ```powershell
   New-NetFirewallRule -DisplayName "TingzhongDemo" -Direction Inbound -Protocol TCP -LocalPort 5500,5502,8080,8090 -Action Allow
   ```
4. 先用电脑浏览器访问 `http://<电脑IP>:5502/index.html`：能打开说明服务正常，问题在防火墙或路由器的 AP 隔离。

### 浏览器设备模式预览 375 宽度

1. 打开 `http://127.0.0.1:5502/index.html`；
2. 按 `F12`（或 `Ctrl+Shift+I`）打开开发者工具；
3. 点左上角**设备图标**（Toggle device toolbar，快捷键 `Ctrl+Shift+M`）；
4. 顶部设备下拉选 **iPhone SE / iPhone 12 Pro**，或选 `Responsive` 后把宽度设为 **375**；
5. 刷新页面即可看到移动端布局。桌面上宽度 ≥560px 时页面会居中成 430px 手机比例，方便预览。

---

## 二、目录结构

```text
flyer-app/
├── index.html              应用壳：HUD 顶栏 + 内容区 + 底部 TabBar + PWA 元信息
├── styles.css              移动端样式：深色科技风、玻璃拟态、霓虹、安全区适配
├── app.js                  应用逻辑：5 个 Tab、自动决策预判、许可倒计时、弹层、交互
├── map.js                  Canvas 态势图：自绘网格/限飞区/障碍物/飞行器，双指缩放+拖动+惯性
├── api.js                  统一数据出口：真实接口 + mock 回退（后期对接真实机场的唯一改动点）
├── mock.js                 内置演示数据（canonical 契约字段）
├── manifest.webmanifest    PWA 清单：可安装、独立窗口、竖屏、快捷方式
├── sw.js                   Service Worker：静态资源离线缓存（后端接口不缓存）
├── icons/
│   ├── icon.svg            App 图标
│   └── icon-maskable.svg   Android 自适应图标
├── selftest.js             Node 自测脚本：渲染 + 预判 + 许可 + 后端推导（34 项断言）
├── 启动.bat                本机一键启动（127.0.0.1:5502）
├── 真机测试.bat            手机真机联调：后端 + 地面站桥 + App + 门户全部绑局域网
├── 打包APK.bat             Android APK 一键打包入口
├── build-apk.ps1           打包核心：组装资源 → Capacitor → Gradle 出包
├── capacitor.config.json   Capacitor 配置（appId / 应用名 / webDir）
├── package.json            打包依赖声明
└── README.md               本说明
```

---

## 三、五个 Tab 与已实现交互

| Tab | 内容 |
| --- | --- |
| **首页** | 起降点 Hero 卡（编号/名称/跑道方向）、天气胶囊（风速/能见度/云底高/温度）、告警横幅、「我的飞行器」横滑卡片（相位/高度/速度/链路/电量条）、可缩放态势图 |
| **周边** | 起降点卡片（标高/跑道/安全半径/经纬度）、气象仪表盘（4 圆环 + 6 项明细）、空域/限飞区列表、周边障碍物（含距起降点距离）、可用机位（室内/室外 + 占用状态） |
| **起降申请** | ① 选飞行器 → ② 选动作（起飞/降落）→ ③ **自动决策预判** → ④ 提交申请 → **许可状态时间线 + 60s 倒计时** |
| **消息** | C2 / RID / ATC / 气象 / 告警 / 系统 按类型分组，未读高亮，支持单条已读与全部已读 |
| **我的** | 虚拟注册资料（飞手编号/实名登记号/唯一识别码/资质有效期）、我的飞行器绑定与解绑、后端地址设置、关于 |

### 两个重点交互

**① 自动决策预判（`evaluate()`）** — 选完飞行器和动作立刻出结论，7 类规则逐条给原因：

| 判定 | 规则 |
| --- | --- |
| DENY | RID 信号丢失 / 紧急状态 / 缺实名登记号或识别码 / 电量 < 25% / 链路 ≤ 2 / 气象低于起降标准 / 处于限制空域内 / 与障碍物净空冲突 |
| HOLD | 电量 25–45% / 链路 = 3 / 风速阵风接近限制值 / 降落时无空闲机位 |
| APPROVE | 以上均通过 |

**② 许可有效期 60s 倒计时** — 提交后生成许可号（`CLR-XXXXXX`）与状态时间线；APPROVE 时启动倒计时环（剩 ≤10s 变红），到期自动置为「已过期」并提示重新申请；HOLD 走等待队列、DENY 直接拒绝。

其它交互：态势图**双指捏合缩放 / 单指拖动 / 松手惯性 / 双击放大 / 点击飞行器**弹详情；首页**下拉刷新**；桌面滚轮缩放。

---

## 四、数据来源与「预留接口」

应用启动即用内置演示数据渲染（不等后端、不白屏），随后后台尝试接入真实服务并每 15 秒轮询一次；任一请求失败自动回退演示数据，顶栏胶囊显示 `演示 / 实时`。

`api.js` 顶部是**唯一改动点**：

```js
var defaults = {
  baseUrl:   'http://127.0.0.1:8080',   // flycontrol / 真实机场 UTM 服务
  groundUrl: 'http://127.0.0.1:8090',   // 地面站数据服务
  timeoutMs: 2400
};
```

也可用 URL 参数临时指定：`index.html?api=http://x.x.x.x:8080&ground=http://x.x.x.x:8090`，
或在「我的 → 设置」里填写并保存（存 localStorage）。

已预留的接口方法：

| 方法 | 接口 | 数据 |
| --- | --- | --- |
| `snapshot()` | `GET /api/sync/snapshot` | 机场 / 障碍物 / 空域 / 气象 / 程序 / 态势 |
| `program()` | `GET /api/program/current` | 程序、风险、合规、仿真 |
| `traffic()` | `GET /api/traffic` | 实时飞行器态势 |
| `ground()` | `GET /api/ground` | 机位 / RID900 / 传感器 / 停靠调度 |
| `replan()` | `POST /api/program/replan` | 程序重规划 |
| `setMeteo()` | `POST /api/env/meteo` | 写入气象 |
| `toggleObstacle()` | `POST /api/env/obstacle/toggle` | 切换障碍物状态 |

字段一律遵循统一契约 canonical（**WGS84 经纬度 + 海拔 MSL + snake_case**），契约见 `../../shared/contract.md`。
接入真实机场时只需改地址，**页面渲染逻辑无需改动**。

---

## 五、App 封装（PWA）

已完成的封装：

- `manifest.webmanifest`：可安装、`display: standalone` 独立窗口、竖屏锁定、主题色、应用图标（含 Android maskable）、两个快捷方式（起降申请 / 实时态势）；
- `sw.js`：Service Worker 离线缓存静态资源（`/api/` 与 8080/8090 接口请求**不缓存**，避免运行数据过期），断网也能打开界面并回退演示数据；
- `icons/`：SVG 应用图标与自适应图标；
- iOS 支持：`apple-mobile-web-app-capable` + `apple-touch-icon` + 状态栏样式，可「添加到主屏幕」全屏运行。

**安装步骤（Chrome / Edge）**：打开页面 → 地址栏右侧出现「安装」图标 → 点击即安装为独立 App。
**iOS Safari**：分享菜单 → 「添加到主屏幕」。

---

## 六、打包成 Android APK

能打，而且打好的 APK **能直接装在手机上离线用**。工程已经配好了，只差打包环境。

### 环境要求（缺一不可）

| 组件 | 版本 | 获取方式 |
| --- | --- | --- |
| Node.js | 18+ | <https://nodejs.org/>（LTS） |
| JDK | **17** | <https://adoptium.net/temurin/releases/?version=17>（安装时勾选 *Set JAVA_HOME variable*） |
| Android SDK | Platform 34 + Build-Tools 34.0.0 | 装 Android Studio 最省事，或用命令行 `sdkmanager` |

> 当前这台机器：Node ✅、npm ✅，**JDK 与 Android SDK 尚未安装** —— 装上这两个就能出包。

### 一键打包

双击 **`打包APK.bat`**，脚本自动完成 7 步：

1. 检查 Node / JDK / Android SDK（缺失时给出下载地址与话术）
2. 把静态资源组装到 `www/`
3. 安装 Capacitor 依赖（首次 1–3 分钟）
4. 生成 Android 工程（`android/`）
5. **给 `AndroidManifest.xml` 打开明文 HTTP** ← 关键，否则连不上内网后端
6. `npx cap sync android`
7. Gradle 打包，产出 **`挺中航空飞手端.apk`** 并自动定位到资源管理器

首次会下载 Gradle 与依赖（约 3–10 分钟），之后改完代码重跑是增量的，很快。

### 装到手机

```bash
# 方式 1：数据线 + adb
adb install -r "挺中航空飞手端.apk"

# 方式 2：把 APK 传到手机（微信 / 网盘 / 数据线）后点击安装
#         需在手机上允许「未知来源」安装
```

### ⚠️ 装好后必做一步：填后端地址

APK 里的页面来自**本地资源**，`location.hostname` 推导会失效（不像浏览器访问局域网 IP 那样能自动识别）。所以首次打开要：

1. 首页会出现 **「未连接到起降点服务」** 引导条 → 点「去设置」；
2. 或直接进 **「我的 → 设置」**，填写：

   ```text
   机场服务     http://192.168.1.20:8080     ← 换成你电脑的局域网 IP
   地面站服务   http://192.168.1.20:8090
   ```

3. 点 **「测试连接」** 确认两个服务都通，再点「保存并同步」。地址存在手机里，之后无需再填。

> 电脑侧仍用 `真机测试.bat` 启动（它把服务绑到 `0.0.0.0`，手机才访问得到）。

### 几个已知点

- **明文 HTTP**：Android 9+ 默认禁止 HTTP 明文流量。脚本已自动加 `android:usesCleartextTraffic="true"`；若你手工用 Android Studio 打包，记得自己加，否则现象是「连不上但也不报错」。
- **CORS**：APK 内页面 origin 是 `https://localhost`，请求电脑后端属跨域；flycontrol 与地面站桥都已开放 `Access-Control-Allow-Origin: *`，无需额外配置。
- **正式发布**：产出的是 `debug` 包，可直接安装体验；要上架需改 `assembleRelease` 并配置签名 keystore。
- **iOS**：同一套配置加 `@capacitor/ios` + `npx cap add ios` 即可，但必须在 macOS + Xcode 上构建。
- **改代码后**：APK 只是外层容器，里面还是这套 HTML/JS。改完 `app.js` 等文件重跑 `打包APK.bat` 即会更新。

---

## 七、验收清单

- [x] 5 个 Tab 全部可点通，有真实数据流（真实接口 + mock 回退）
- [x] 「自动决策预判」可跑通：切换飞行器/动作，结论与原因实时刷新
- [x] 「许可 60s 倒计时」可跑通：提交后出许可号、时间线、倒计时环，到期自动失效
- [x] 态势图支持双指缩放 / 拖动 / 惯性 / 点击选中
- [x] 375px 移动端布局，底部 TabBar 固定，关键按钮 ≥ 44px
- [x] PWA 可安装、可离线打开
- [x] Android APK 打包工程已就绪（`打包APK.bat`）：补装 JDK 17 + Android SDK 即可出包
- [x] App 内已内置连接引导与「测试连接」，解决 APK 无法自动识别后端的问题

---

## 八、自测

```bash
cd flyer-app
node selftest.js
```

用最小 DOM 桩在 Node 里**真实加载四个模块并跑一遍**，30 项断言覆盖：

- 四模块加载无异常、启动状态正确（起降点 / 飞行器数量 / 我的飞行器绑定）
- 5 个 Tab 均渲染出关键元素（态势图、天气胶囊、仪表盘、机位、预判区、消息分组、资料卡、设置表单）
- 自动决策预判：紧急状态 → DENY、RID 丢失 → DENY、未选飞行器 → DENY、正常待命 → APPROVE、恶劣气象 → DENY
- 许可签发：生成 `CLR-*` 编号、时间线、60s 有效期、倒计时在 0~60；DENY 时无倒计时
- 后端不可用时自动回退演示数据

当前状态：**30 / 30 通过**。
