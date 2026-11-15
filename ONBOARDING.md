# 低空综合保障系统 · 新人上手指南（ONBOARDING）

> 面向第一次接触本仓库的同学。目标：**30 分钟内能跑起来、说得清架构、找得到代码**。
> 本文基于仓库当前代码梳理，随代码演进请同步更新。
>
> 最后核对：以 `README.md` + 各子系统 README 为准；有冲突时以代码实际行为为准。

---

## 0. 一分钟版本

- 这是一个**低空起降点（无人机 / eVTOL 起降场）综合保障系统**的工程原型仓库。
- 按需求文档分为 **三大系统**：设备端（地面站）、后台管理平台（B/S）、终端 App。
- 另有 **两个独立算法/业务子系统**：飞行程序实时调整（flycontrol）、通讯与态势（communication）。
- 所有跨系统数据走 **`shared/` 统一契约**：`WGS84 经纬度 + 海拔 MSL + snake_case`。
- 一键启动：双击根目录 **`启动一体化门户.bat`**。

---

## 1. 项目定位与边界

| 维度 | 说明 |
| --- | --- |
| 性质 | 工程原型 / 演示系统（Demo），**不是生产系统** |
| 依据 | 《低空综合保障设备-软件及管理平台需求说明书》+《系统功能分解思维导图》 |
| 明确不做 | **不做飞行控制** |
| 人机边界 | 智能输出 = **建议 + 人工确认**，不自动执行 |
| 二期预留 | 雷达 / 频谱侦测 / 光电红外 —— 插件化、可插拔 |
| 鉴权 | `AUTH_ENABLED=false`，CORS `*`，仅演示 |
| 数据 | 演示数据与真实数据双轨，前端均有 mock 回退 |

---

## 2. 5 分钟跑起来

### 2.1 一键启动（推荐）

双击根目录：

```
启动一体化门户.bat
```

它调用 `start-system.ps1`，按顺序拉起 6 个组件（已在运行的服务自动复用）：

| # | 组件 | 端口 | 启动方式 |
| --- | --- | --- | --- |
| 1 | 飞控后端 flycontrol | 8080 | `backend\.venv\Scripts\python.exe -m uvicorn app.main:app` |
| 2 | 门户数据桥 ground-bridge | 8090 | `python ground-bridge.py`（仅标准库） |
| 3 | 管理平台门户 | 5500 | `python -m http.server 5500 --bind 0.0.0.0` |
| 4 | 飞手端 App | 5502 | `python -m http.server 5502 --bind 0.0.0.0` |
| 5 | 通讯态势 | — | 浏览器打开 `comms\communication\index.html` |
| 6 | 地面站桌面端 | — | `wrjtksf\drone_ground_station\venv\Scripts\python.exe main.py`（若 venv 存在） |

启动完成会打印局域网地址，手机同 Wi-Fi 可直接访问。

**停止**：关掉启动时新开的那几个最小化窗口。

### 2.2 冷启动验证清单

启动后按顺序验证，全部通过说明环境正常：

```powershell
# 1) 飞控后端健康检查
Invoke-RestMethod http://127.0.0.1:8080/api/health

# 2) 统一快照（机场/障碍物/空域/气象/程序/态势）
Invoke-RestMethod http://127.0.0.1:8080/api/sync/snapshot | ConvertTo-Json -Depth 4

# 3) 地面站数据桥
Invoke-RestMethod http://127.0.0.1:8090/api/ground | ConvertTo-Json -Depth 4

# 4) 门户与 App 能打开
Start-Process http://127.0.0.1:5500/index.html
Start-Process http://127.0.0.1:5502/index.html
```

浏览器侧检查：

- 门户顶栏右上角状态胶囊显示 **实时**（非「演示」）；
- 飞手端 App 顶栏胶囊同样显示 **实时**；
- `http://127.0.0.1:8080/docs` 能打开 Swagger，且 `/api/sync/snapshot` 有数据。

### 2.3 各子系统单独启动

| 子系统 | 命令 / 入口 |
| --- | --- |
| 门户 | `platform\portal\` 直接开 `index.html`，或 `python -m http.server 5500` |
| 飞控 | `flight\flycontrol\low-altitude-demo\启动后端.bat`（已有 venv）或 `启动Demo.bat`（首次自动建 venv） |
| 通讯态势 | `comms\communication\启动.bat` → 选 1（网页）或 2（跑 Python 决策引擎） |
| 飞手端 | `pilot-app\flyer-app\启动.bat`（本机）/ `真机测试.bat`（局域网联调）/ `打包APK.bat` |
| 地面站（真机版） | `device\groundstation\wrjtksf\drone_ground_station\` → `python main.py` |
| 地面站（仿真版） | `device\groundstation\wrjtksf\` → `python -m src.main` |

---

## 3. 全局架构

```
┌──────────────────────── 设备端 device/ ────────────────────────┐
│  drone_ground_station (PyQt5+高德)      wrjtksf/src (PySide6 仿真)│
│  MAVLink 遥测 / 天气 / 机位分配           A* 路径 / 调度 / 告警    │
└───────────────────────────────┬────────────────────────────────┘
                                │ ground-bridge.py :8090 (REST)
                                ▼
┌──────────────────── 管理平台 platform/portal :5500 ────────────┐
│  6 个页面：总览 / 态势 / 飞行程序 / 地面站 / 看板 / 业务          │
│  演示数据（默认）  ⇄  实时数据（每 5s 轮询 8080 + 8090）          │
└───────────────▲──────────────────────────────▲─────────────────┘
                │ /api/sync/snapshot           │ /api/program/current
                │                              │ /api/traffic
┌───────────────┴──────────── 飞控 flight/ ─────┴─────────────────┐
│  flycontrol :8080  FastAPI + 4 引擎 + 2s 闭环调度               │
│  合规校验 / 风险评估 / A*+RRT*+Dubins 规划 / 仿真验证             │
└───────────────▲────────────────────────────────────────────────┘
                │ POST /api/traffic/ingest
┌───────────────┴────── 通讯态势 comms/ (纯前端) ──────────────────┐
│  C2 报文 / RID 广播 / 气象 / 障碍物冲突 / 决策引擎                │
└──────────────────────────────┬─────────────────────────────────┘
                               │ 同一套后端
┌──────────────────────────────▼─────────────────────────────────┐
│  终端 App pilot-app/flyer-app :5502 （PWA / Android APK）        │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. 三大系统 ↔ 代码位置

| 需求文档中的系统 | 代码位置 | 说明 |
| --- | --- | --- |
| 一、设备端嵌入式软件（节点层） | `device/groundstation/` | 桌面端 + 串口/传感器，**内含两套实现** |
| 二、后台管理平台（B/S） | `platform/portal/`（自研）<br>`platform/prototype/`（同事原型，只读参考） | Web 门户 |
| 三、终端 APP | `pilot-app/flyer-app/` | PWA + Capacitor Android |
| 跨系统统一接口 | `shared/` | 契约 + JS/Python 双适配层 |
| （平台层独立子系统）飞行程序 | `flight/flycontrol/low-altitude-demo/` | FastAPI + 算法引擎 |
| （平台层独立子系统）通讯态势 | `comms/communication/` | 纯前端 Demo |

需求索引见 `需求/README.md`；交互式功能分解见 `需求/系统功能分解思维导图.html`。

---

## 5. 必读：`shared/` 统一契约

**这是理解全仓库的钥匙。** 主文档 `shared/contract.md`，机器可读 `shared/schema.json`。

### 5.1 四条铁律

1. **坐标**：跨系统传输一律 `WGS84 经纬度 + 海拔 MSL（米）`。
   内部可用本地 ENU（x 东 / y 北 / z 相对起降点 AGL），**边界必须转换**。
2. **命名**：字段一律 `snake_case`，SI 单位（米、米/秒、度、hPa、℃）。
3. **报文信封**：`{ protocol, messageHeader, payload }`，如 `CAAC-UTM-C2/1.0`。
4. **单一数据源**：
   - 起降点 / 障碍物 / 空域 / 气象 / 飞行程序 → **flycontrol 说了算**；
   - 实时飞行器态势 / C2 / RID → **communication 说了算**。

### 5.2 坐标换算（两边实现必须一致）

```text
M_PER_DEG_LAT = 111320.0
mpdl(lat)     = M_PER_DEG_LAT * cos(lat * π/180)

ENU -> 经纬度：
  lon = ref_lon + x / mpdl(ref_lat)
  lat = ref_lat + y / M_PER_DEG_LAT
  alt(MSL) = ref_alt + z

经纬度 -> ENU：
  x = (lon - ref_lon) * mpdl(ref_lat)
  y = (lat - ref_lat) * M_PER_DEG_LAT
  z = alt(MSL) - ref_alt
```

参考点 = 起降点 `(lat, lon, elevation)`。实现在：
`flight/.../engines/geometry.py`、`shared/interface.js`、`shared/interface.py`。

### 5.3 canonical 实体

| 实体 | 关键字段 |
| --- | --- |
| `Airport` | `code, name, lat, lon, elevation, safe_radius, runway_heading` |
| `Obstacle` | `id, name, type(fixed/dynamic), lat, lon, base_msl, top_msl, radius, buffer, active` |
| `Airspace` | `id, name, polygon[[lat,lon]], floor_msl, ceiling_msl, active` |
| `Meteo` | `timestamp, wind_speed, wind_dir, gust, visibility, cloud_base_agl, turbulence, wind_shear, temperature, dew_point, pressure` |
| `Traffic` | `id, model, reg_no, ua_id, phase, lat, lon, alt_msl, speed, heading, vertical_speed, battery_pct, link_quality, emergency, rid_lost, route` |
| `Program` | `type(arrival/departure/missed), version, source, plan_id, waypoints[], miss_approach[]` |
| `Snapshot` | `schema_version, frame, altitude_ref, generated_at, airport, obstacles, airspaces, meteo, program, traffic` |

### 5.4 两条核心接口

```text
flycontrol  →  communication/portal/app ：GET  /api/sync/snapshot
communication →  flycontrol            ：POST /api/traffic/ingest
```

`/api/traffic/ingest` 同时接受 **裸数组 / 单个对象 / 带信封对象** 三种形式。

### 5.5 字段映射（旧 → canonical）

- communication：`height`(顶高 AGL) → `top_msl`；`x,y`(ENU) → `lat,lon`；`wind`→`wind_speed`；`ceiling`→`cloud_base_agl`；`alt`(AGL)→`alt_msl`；`regNo/uaId/vs` → snake_case。
- flycontrol：`obs_type` 1→fixed / 2→dynamic；`top_agl`→`top_msl`；`cloud_base`→`cloud_base_agl`；`floor_agl/ceiling_agl`→`*_msl`；`Waypoint{x,y,z}` → `{lat,lon,alt_msl}`。

⚠️ **`shared/` 不能挪层级**：
- Python 侧从 `routers/traffic.py` **逐层向上查找** `shared/interface.py`；
- JS 侧（communication）用相对路径 `../../shared/interface.js`。

---

## 6. 模块详解

### 6.1 flycontrol —— 飞行程序实时调整（算法含量最高）

**位置**：`flight/flycontrol/low-altitude-demo/`
**技术栈**：FastAPI + SQLAlchemy +（PostgreSQL 15/PostGIS 3.3，可回退 SQLite）
**规模**：后端约 1100 行 Python

```
backend/app/
├── main.py             # FastAPI 入口，lifespan 启动闭环调度
├── config.py           # 环境变量配置（DATABASE_URL / DISPATCH_INTERVAL / AUTH_ENABLED）
├── store.py            # 运行态存储 + DB 读写；DB 不可用时静默回退内存演示数据
├── demo_data.py        # 演示场景种子（机场 LAC-DEMO / 5 障碍物 / 1 限飞区 / 1 进近预案）
├── domain.py           # 领域数据类（ENU 坐标）
├── models.py           # SQLAlchemy 表模型（lp_*）
├── schemas.py          # 请求体 Pydantic 模型
├── engines/
│   ├── geometry.py     # 坐标换算 / 碰撞 / 射线法（134 行）
│   ├── compliance.py   # 引擎1 合规校验：简化 OAS + MOC + MSA + 航段梯度（146 行）
│   ├── risk.py         # 引擎2 风险评估：障碍物/气象/空域加权（203 行）
│   ├── planner.py      # 引擎3 4D 航迹：A* + RRT* + Dubins（384 行，最重）
│   └── simulate.py     # 引擎4 仿真验证（67 行）
├── services/dispatch.py # 闭环调度：风险超阈值 → 自动重规划 → 发布新版本（115 行）
└── routers/
    ├── program.py      # /api/health /airport /obstacles /airspaces /rules
    │                   # /program/current /program/replan /env/meteo /env/obstacle/toggle
    └── traffic.py      # /api/sync/snapshot /traffic /traffic/ingest
```

**演示逻辑（重要）**：

- 启动后自动生成初始进近程序，**动态塔吊（id=1）默认关闭**，航径为直线；
- 激活塔吊（`POST /api/env/obstacle/toggle {"id":1,"active":true}`）→ 塔吊出现在进场航路上 → 风险升为高风险 → 闭环调度自动触发 A*+Dubins 重规划 → 发布新版本；
- 注入恶劣气象（`POST /api/env/meteo`）观察风险分级与程序状态变化。

**已知简化**（README 已声明）：OAS 为近似、风险为透明加权、A* 网格离散（50m/5m）、未启用鉴权。

---

### 6.2 communication —— 通讯与态势（纯前端 Demo）

**位置**：`comms/communication/`（约 1100 行 `app.js`）

- 单页 `index.html`，直接浏览器打开即可（`file://` 也能跑）。
- 模拟：RID 广播（1s）/ 心跳（3s）/ 位置报告（2s）/ 起飞降落申请 / 许可 / 等待 / 复飞 / 气象广播 / 障碍物告警 / 链路检查。
- 决策引擎 `autoDecision()` 输出 `APPROVE / DENY / ADVISE_HOLD / WARNING`，指令带 `validUntil`。
- 有 `decision_engine_demo.py`（Python 版决策引擎原型，可独立运行）。
- 启动时拉 `flycontrol` 快照做对齐，此后约每秒回传飞行器态势。
- 未启动 flycontrol 时保持**本地演示模式**，功能不受影响。

**设计依据**（README 有详述）：《无人驾驶航空器飞行管理暂行条例》、CCAR-92 部、MH/T 系列接口规范、ASTM F3411（RID）。

---

### 6.3 portal —— 一体化门户（自研 B/S）

**位置**：`platform/portal/`（约 48 KB `app.js`，压缩风格单行较多）

| 文件 | 职责 |
| --- | --- |
| `index.html` | 页面壳 + 顶部导航 |
| `styles.css` | 深色科技风 / 响应式 |
| `app.js` | 路由 + 状态 + 6 个页面渲染 + 详情抽屉 + 事件 |
| `api.js` | **唯一 baseUrl 配置点**（8080 / 8090） |
| `mock-data.js` | 演示数据（canonical 字段） |
| `visuals.js` | Canvas 态势图 / 程序图 / 高度剖面 / ECharts 降级 |
| `ground-bridge.py` | 地面站数据桥（8090，仅标准库） |

**路由**：`#/home` `#/situation` `#/program` `#/ground` `#/dashboard` `#/business`

**两种数据模式**：

- **演示数据（默认）**：不发请求、不白屏；
- **实时数据**：每 5 秒轮询 flycontrol（快照 + 当前程序）与 ground-bridge（机位/传感器）；
  任一源未就绪时该模块回退演示数据。

切换方式：顶栏状态胶囊 / URL `?mode=live` / `window.LAV_CONFIG.dataMode`。

**接入真实机场**：只改 `api.js` 顶部 `baseUrl` / `groundUrl`，渲染逻辑无需改动。

⚠️ **注意**：`ground-bridge.py` 当前是**模拟数据生成器**（正弦波造波动），
并非真正读取地面站进程。文件头注释已说明「后期接入地面站真实 REST 后可直接替换本桥」。

---

### 6.4 groundstation —— 设备端（⚠️ 有两套实现，别搞混）

**位置**：`device/groundstation/`

| 目录 | 技术栈 | 定位 | 入口 |
| --- | --- | --- | --- |
| `wrjtksf/drone_ground_station/` | **PyQt5 + PyQtWebEngine + 高德地图 + pymavlink** | **真机地面站**：多机遥测、天气 API、智能机位分配、邮件通知 | `python main.py`（**一键启动脚本用的是这个**，用其自带 `venv`） |
| `wrjtksf/src/` | **PySide6** | **停靠调度仿真 Demo**（v1.3.0）：A* + Catmull-Rom + 最小转弯半径、Best-Fit 机位分配、偏航告警、Modbus 三路传感器、ADS-B 雷达 | `python -m src.main`，配置 `config/demo_config.yaml` |
| `wrjtksf/rid/` | PySide6 | RID 模块 GUI 监视器 | — |
| `wrjtksf/sensor/` | 脚本 | 传感器串口调试脚本 | — |

**仿真版关键模块**（`wrjtksf/src/`）：

```
src/main.py                     # 入口：加载配置 → 组装引擎 → 主窗口
src/engine/simulation_engine.py # 仿真步进（592 行，最重）
src/engine/dock_scheduler.py    # 机位 9 步分配算法 + 「为何预约该机位」文案
src/engine/path_planner.py      # A* + 平滑 + 最小转弯半径
src/engine/deviation_monitor.py # 到规划路径距离 / 最近点 / 脱离方向
src/engine/slot_policy.py       # 机位策略
src/ui/main_window.py           # 主界面（114 KB，最大的单文件）
src/ui/gcs_*_card.py            # 无人机 / 机位 / 天气 / 传感器卡片
src/services/                   # GPS / 气象 / 邮件 / 告警 / ADS-B 串口
config/demo_config.yaml         # 仿真 / 地图 / 偏航 / gcs / 告警参数
```

**机位分配顺序**（README 与代码一致）：
机型支持 → 尺寸匹配 → 功率匹配（≥ 需求 × 50%）→ 空闲 → 优先级降序 → 停靠时长升序 → Best-Fit 尺寸升序。

**真机版关键点**：

- 默认地图中心重庆 `(29.5689, 106.5577)`；
- `AUTO_CONNECT_ON_START = False`，需手动连接；
- 天气走 WeatherAPI（5 分钟刷新，带缓存）；
- 支持自定义机位增删并持久化。

---

### 6.5 flyer-app —— C 端飞手 App

**位置**：`pilot-app/flyer-app/`（约 967 行 `app.js`）

| 文件 | 职责 |
| --- | --- |
| `index.html` | HUD 顶栏 + 内容区 + 底部 TabBar + PWA 元信息 |
| `app.js` | 5 个 Tab、决策预判、许可倒计时、弹层 |
| `map.js` | Canvas 态势图：缩放 / 拖动 / 惯性 / 双击放大 |
| `api.js` | 数据出口 + mock 回退；**按 `PAGE_HOST` 自动推导后端** |
| `mock.js` | 内置演示数据（canonical） |
| `sw.js` / `manifest.webmanifest` | PWA 离线缓存 / 可安装 |
| `selftest.js` | Node 自测（34 项断言） |
| `build-apk.ps1` | Capacitor → Gradle 出安卓包 |

**5 个 Tab**：首页 / 周边 / 起降申请 / 消息 / 我的

**两个核心交互**：

1. **自动决策预判 `evaluate(uav, action)`**（`app.js:230`）
   - `DENY`：RID 丢失 / 紧急状态 / 缺实名登记号或识别码 / 电量 < 25% / 链路 ≤ 2 / 气象低于标准 / 在限制空域内 / 与障碍物净空冲突
   - `HOLD`：电量 25–45% / 链路 = 3 / 阵风接近限制 / 降落无空闲机位
   - `APPROVE`：全部通过
2. **许可 60s 倒计时**：生成 `CLR-XXXXXX` + 状态时间线，剩 ≤10s 变红，到期置「已过期」。

**关键设计**：`api.js` 用 `PAGE_HOST` 从当前页面主机推导后端地址 ——
电脑打开指向 `127.0.0.1`，手机打开指向电脑局域网 IP，因此两端访问的是同一套后端。
（不做这个推导，手机会连自己的 `127.0.0.1`，永远看演示数据。）

**`www/` 目录**是 `build-apk.ps1` 生成的打包副本，**改代码请改根目录文件**，不要改 `www/`。

---

## 7. 端口 / 环境变量 / 配置速查

### 7.1 端口

| 端口 | 服务 |
| --- | --- |
| 8080 | 飞控后端 / 机场 UTM 服务（`/docs` 为 Swagger） |
| 8090 | 门户数据桥（地面站数据） |
| 5500 | 管理平台门户 |
| 5502 | 飞手端 App |
| 8081 | 地面站本地 DSM 瓦片服务（由地面站自行启动） |
| 5432 | PostgreSQL/PostGIS（Docker 形态） |

### 7.2 flycontrol 环境变量（`config.py`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./flight_demo.db` | 生产改为 PostgreSQL+PostGIS |
| `DISPATCH_INTERVAL` | `2` | 闭环调度周期（秒） |
| `AUTH_ENABLED` | `false` | 演示关闭 |
| `FRONTEND_DIR` | `../frontend` | 前端静态目录 |

### 7.3 地面站仿真配置（`wrjtksf/config/demo_config.yaml`）

常用项：`simulation.spawn_count` / `max_concurrent_inbound` / `inbound_dispatch_interval_seconds` /
`charging_acceleration`、`deviation.distance_threshold` / `duration_threshold_seconds`、
`map.background_image`、`path.min_turn_radius`、`gcs.pilot_smtp_*`、`alert.mode`。

### 7.4 前端接口地址

| 位置 | 变量 |
| --- | --- |
| 门户 | `platform/portal/api.js` → `defaults.baseUrl` / `groundUrl` |
| 飞手端 | `pilot-app/flyer-app/api.js` → `defaults.baseUrl` / `groundUrl`（支持 `?api=` / `?ground=` 与本地设置） |
| 通讯态势 | `comms/communication/app.js` → 顶部 `SYNC` 配置 |

---

## 8. 常用调试命令

```powershell
# 查看当前程序 + 风险 + 合规 + 仿真
Invoke-RestMethod http://127.0.0.1:8080/api/program/current | ConvertTo-Json -Depth 6

# 激活动态塔吊（id=1），触发自动重规划
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/env/obstacle/toggle `
  -ContentType 'application/json' -Body '{"id":1,"active":true}'

# 手动重规划
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/program/replan `
  -ContentType 'application/json' -Body '{"program_type":"arrival"}'

# 注入恶劣气象
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/env/meteo `
  -ContentType 'application/json' `
  -Body '{"wind_speed":12,"wind_dir":90,"gust":18,"visibility":1200,"cloud_base":90,"turbulence":3,"wind_shear":3,"temperature":15,"pressure":1002}'

# 模拟 communication 回传态势
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/traffic/ingest `
  -ContentType 'application/json' `
  -Body '[{"id":"UAS-TEST-1","lat":30.001,"lon":120.002,"alt_msl":120,"phase":"APPROACH"}]'

# 查看态势
Invoke-RestMethod http://127.0.0.1:8080/api/traffic
```

飞控后端单元测试：

```powershell
cd flight\flycontrol\low-altitude-demo\backend
.\.venv\Scripts\python.exe tests\test_engines.py   # 或 pytest tests -q
```

地面站仿真测试：

```powershell
cd device\groundstation\wrjtksf
pytest -q
```

飞手端自测：

```powershell
cd pilot-app\flyer-app
node selftest.js
```

---

## 9. 常见坑（踩过的）

1. **地面站有两套**：PyQt5 真机版 vs PySide6 仿真版，入口/依赖/配置完全不同。先确认看哪套。
2. **数据库是可选的**：flycontrol 连不上 Postgres 时**静默回退** SQLite/内存，界面照常。排查「重启后数据没了」先看日志里 `数据库不可用, 回退内存演示模式` 与 `store.db_ok`。
3. **`shared/` 位置是硬约束**，移动会断（Python 向上查找、JS 相对路径）。
4. **虚拟环境不入库**（`.gitignore` 已忽略 `.venv` / `venv` / `.conda` / `__pycache__`）。启动器优先用各子项目的
   `.venv`，没有就回退系统 Python；需要重建后端环境见 `HANDOFF.md` §2 的「环境现状」。
5. **「有内容」≠「连上了」**：门户和 App 都有 mock 回退，必须看顶栏 `实时 / 演示` 胶囊。
6. **手机连不上**：常见原因是手机开了 VPN/流量、电脑防火墙未放行 5500/5502/8080/8090，或路由器 AP 隔离。
7. **PWA 安装需要安全上下文**：`http://192.168.x.x` 下 Android Chrome 不出安装按钮，需用 `adb reverse` 或 `chrome://flags` 白名单。
8. **`www/` 是打包产物**，改了不生效是改错文件了。
9. **`start-system.ps1` 里地面站路径**指向 `wrjtksf\drone_ground_station`，不是 `wrjtksf\src`。
10. **仓库已上 GitHub**：`github.com/Evelyn-bit10/low-altitude-integrated-support-system`（分支 `main`）。
    `.gitignore` 已排除 `.env` / `*.db` / 运行时 json / 虚拟环境；提交前 `git status` 确认没有夹带本地配置。

---

## 10. 推荐阅读路线

### 第 1 天：建立全局印象

1. 根 `README.md` → 本文 → `需求/README.md`
2. 双击一键启动，把 6 个界面都点一遍
3. 浏览器打开 `需求/系统功能分解思维导图.html`（三层可折叠）

### 第 2 天：吃透契约

4. 精读 `shared/contract.md`（8.7 KB，必读）
5. 对照看 `shared/interface.py` / `interface.js`，理解 ENU ↔ WGS84 怎么转
6. 用第 8 节的 `curl` 命令看真实返回长什么样

### 第 3–4 天：按方向深入

| 方向 | 阅读顺序 |
| --- | --- |
| **算法 / 后端** | `main.py` → `store.py` → `domain.py` → `engines/geometry.py` → `planner.py` → `risk.py` → `compliance.py` → `dispatch.py` |
| **前端门户** | `index.html` → `api.js` → `app.js`（`parseRoute` / `render*` / `normalize*`）→ `visuals.js` |
| **设备端（仿真）** | `src/main.py` → `engine/dock_scheduler.py` → `engine/path_planner.py` → `engine/simulation_engine.py` → `ui/main_window.py`（按需跳读） |
| **设备端（真机）** | `main.py` → `config.py` → `ui/main_window.py` → `workers/drone_worker.py` → `utils/*` |
| **移动端** | `api.js`（`PAGE_HOST`）→ `app.js`（`evaluate` / `submitApply` / `tickCountdown`）→ `map.js` → `selftest.js` |
| **通讯态势** | `app.js` 的 `SYNC` / `runScriptedComms` / `autoDecision` / `applySnapshot` → `decision_engine_demo.py` |

### 第 5 天：做一次需求覆盖检查

对照思维导图逐条打勾，产出「需求有、代码未做」清单（见 `device/groundstation/wrjtksf/开发清单.md` 的清单格式可复用）。

---

## 11. 已知技术债 / 待改进（按风险排序）

| 级别 | 项 | 位置 / 说明 |
| --- | --- | --- |
| 🔴 高 | **SMTP 账号与授权码硬编码在源码** | `device/groundstation/wrjtksf/drone_ground_station/config.py` 的 `SMTP_*`；建议改为纯环境变量注入并轮换凭据 |
| 🟠 中 | `ground-bridge.py` 是模拟数据生成器 | 未真正读取地面站进程，属演示占位 |
| 🟠 中 | 交通态势仅内存存储，TTL 6s | `routers/traffic.py` 的 `TrafficStore`；生产需落库 `lp_traffic` |
| 🟠 中 | 鉴权关闭 + CORS `*` | `main.py`、`AUTH_ENABLED=false` |
| 🟡 低 | 已清理的历史重复文件 | `wrjtksf/src/main_window.py`、`温度风速雨量/` 已删除；当前仿真入口为 `wrjtksf/src/ui/main_window.py`，传感器调试脚本在 `wrjtksf/sensor/` |
| 🟡 低 | 超大单文件难维护 | `wrjtksf/src/ui/main_window.py`（114 KB）、`comms/communication/app.js`（1102 行） |
| 🟡 低 | OAS / 风险模型为简化近似 | 生产须替换为完整 PANS-OPS 曲面与 SORA 评估 |

需求文档里也留了后续项（见 `shared/contract.md` §7）：
`lp_traffic` 落库、真实气象站/RID 接收器、TLS+签名+防重放、北斗短报文备份、契约代码生成。

---

## 12. 术语表

| 术语 | 含义 |
| --- | --- |
| MSL | Mean Sea Level，海拔高（米） |
| AGL | Above Ground Level，离地高（米） |
| ENU | 东-北-天本地平面坐标系（x 东 / y 北 / z 上） |
| canonical | 统一契约中的标准字段形态 |
| RID | Remote ID，无人机远程识别广播 |
| C2 | Command & Control，指挥控制链路 |
| OAS | Obstacle Assessment Surface，障碍物评估面 |
| MOC | Minimum Obstacle Clearance，最小超障余度 |
| MSA | Minimum Safe Altitude，最低安全高度 |
| Best-Fit | 机位分配策略：选能满足需求的最小资源，减少浪费 |
| PWA | Progressive Web App，可安装的网页应用 |
| 闭环调度 | flycontrol 每 2s 检查风险 → 超阈值自动重规划 → 发布新版本 |
| 演示 / 实时 | 前端两种数据源模式，顶栏胶囊可切换 |

---

## 附：文件规模速查（帮助判断从哪读起）

```
comms/communication/app.js                          1102 行
pilot-app/flyer-app/app.js                           967 行
pilot-app/flyer-app/map.js                           469 行
platform/portal/app.js                               330 行（48 KB，长行）
platform/portal/visuals.js                           195 行
platform/portal/ground-bridge.py                     126 行
flight/.../engines/planner.py                        384 行
flight/.../store.py                                  234 行
flight/.../engines/risk.py                           203 行
flight/.../engines/compliance.py                     146 行
flight/.../services/dispatch.py                      115 行
shared/interface.py                                  233 行
shared/interface.js                                  215 行
device/.../src/engine/simulation_engine.py           592 行
device/.../src/engine/path_planner.py                212 行
device/.../src/engine/dock_scheduler.py              140 行
device/.../src/ui/main_window.py                     114 KB（最大单文件）
```

小文件（<150 行）适合通读；大文件建议先看 `function xxx` 索引再跳读。
