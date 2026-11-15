# Low-Altitude Integrated Support System

> Tingzhong Aviation Technology Co., Ltd. · 低空综合保障系统

> 以《低空综合保障设备-软件及管理平台需求说明书》与《系统功能分解思维导图》为依据，
> 按 **三大系统** 组织的一体化工程仓库。

---

## 一、一键启动（演示 / 展示用）

**双击根目录的 `启动一体化门户.bat`** —— 这是**全系统总入口**，会自动拉起：

| # | 子系统 | 端口 | 说明 |
| --- | --- | --- | --- |
| 1 | 飞控后端（flycontrol API） | 8080 | 统一快照 / 飞行程序 / 风险合规 |
| 2 | 门户数据桥（ground-bridge） | 8090 | 机位 / RID900 / 传感器数据（**模拟值**，见第三节） |
| 3 | 管理平台门户 | 5500 | 浏览器自动打开 |
| 4 | 飞手端 App（PWA） | 5502 | 手机同 Wi-Fi 可直接访问 |
| 5 | 通讯态势（communication） | — | 浏览器自动打开 |
| 6 | 地面站桌面端（groundstation） | 8081 | 独立窗口；需 `drone_ground_station\venv`（含 PyQt5），缺失则跳过 |

服务统一绑定 `0.0.0.0`，手机在同一 Wi-Fi 下可直接访问（启动完成时会打印本机局域网地址）。
已在运行的服务会自动复用，不会重复启动。

**停止服务**：双击根目录的 **`停止服务.bat`** —— 它按端口（8080 / 8081 / 8090 / 8099 / 5500 / 5502）
把本项目启动的 Python 进程连子进程一起结束，并逐条打印停掉了什么、哪些端口本来空闲。

> 第 1~4 项是**隐藏窗口**，任务栏里看不到，不能靠"关窗口"停；地面站（第 6 项）虽是独立窗口，
> `停止服务.bat` 也一并处理。端口若被非本项目的程序占着，脚本打印 `[SKIP]` 而不会误杀。

> 其余子系统入口都收在根目录的 **`低空系统.bat`** 里：双击弹菜单，也可带子命令直连，
> 例如 `低空系统.bat rl`、`低空系统.bat mobile`（完整列表见 `低空系统.bat help`）。

---

## 一·补、功能演示台（对外演示用）

如果目的是**给别人演示这三项能力**，直接双击根目录 **`启动演示.bat`**：

| 页面 | 地址 | 内容 |
| --- | --- | --- |
| 功能演示台 | http://127.0.0.1:5500/demo.html | ① 进出场程序　② 多设备去重　③ 对外数据推送 |

它会额外拉起「模拟 UOM 接收端」(8099)，并把后端切到 `PUSH_MODE=http`。
演示脚本与讲解词见 `flight/flycontrol/low-altitude-demo/backend/docs/DEMO.md`。

> 演示台的后端与页面都只绑定 `127.0.0.1`，**手机打不开**；要用手机演示请走 `低空系统.bat mobile`
> 或 `启动一体化门户.bat`（那两个会绑 `0.0.0.0`）。

## 一·补二、其它常用入口

| 入口 | 用途 |
| --- | --- |
| `低空系统.bat` | **其余入口的统一调度器**：双击弹菜单，或带子命令直连 —— `portal` / `demo` / `rl` / `api` / `pages` / `apidev` / `app` / `mobile` / `comms` / `decision` / `apk` / `check` / `lanip` / `help` |
| `自检.bat` | 单元测试（87 项）+ 网页冒烟 + 接口探活，改完代码先跑这个（等同 `低空系统.bat check`） |
| `停止服务.bat` | 一键停掉全部服务（6 个端口，含地面站），逐条打印结果 |

---

## 二、目录结构

```
low-altitude/
├── 启动一体化门户.bat        ★ 全系统一键启动（双击，总入口）
├── start-system.ps1          启动逻辑（被上面那个 bat 调用；-LanIpOnly 只打印局域网 IP）
├── 启动演示.bat              功能演示台（三项能力 + 模拟 UOM 8099）
├── start-demo.ps1            演示台启动逻辑（被上面那个 bat 调用）
├── 低空系统.bat              统一调度器：双击弹菜单 / 带子命令直连其余入口
├── 自检.bat                  单元测试 + 网页冒烟 + 接口探活
├── 停止服务.bat              一键停止所有服务（按端口结束 Python 进程，含子进程）
├── README.md                 本说明
├── ONBOARDING.md             上手必读（架构 / 接口 / 排障 / 已知局限）
├── HANDOFF.md                接手说明（做到哪 / 关键文件 / 常用命令）
├── 使用说明.md               面向使用者的操作说明
│
├── 需求/                      需求文档与功能分解
│   ├── 低空综合保障设备-软件及管理平台需求说明书-整合版.docx
│   ├── 系统功能分解思维导图.html        ← 三大系统分解，交互式可折叠
│   └── README.md                        ← 需求文档索引（含各项目内 SRS 位置）
│
├── platform/                  【二、后台管理平台（B/S）】
│   ├── portal/                一体化门户（我方可控的网页端）
│   │   ├── index.html         门户本体（演示数据 / 实时数据双模式）
│   │   ├── demo.html          功能演示台（三项能力 + RL 影子模式）
│   │   ├── demo_p1.html       演示台第一幕的独立版（进出场程序）
│   │   ├── demo_p1_place.html 演示台第一幕点位投放版
│   │   ├── rl_lab.html        RL 关联实验室（19 维特征可视化）
│   │   └── ground-bridge.py   门户数据桥（8090，模拟数据生成器）
│   └── prototype/             同事做的管理平台原型（龙兴机场示例，只读参考）
│
├── device/                    【一、设备端嵌入式软件（节点层）】
│   └── groundstation/
│       └── wrjtksf/
│           ├── drone_ground_station/  PyQt5 真机版地面站（工程默认入口，瓦片服务 8081）
│           ├── src/                   仿真版地面站（PySide6，独立入口）
│           └── rid/ sensor/ scripts/ config/ tests/   同级辅助目录（RID / 传感器 / 脚本 / 配置 / 测试）
│
├── flight/                    【二、5.3 飞行程序管理】
│   └── flycontrol/
│       └── low-altitude-demo/ 动态起降飞行程序实时调整（FastAPI 后端 + 前端）
│
├── comms/                     【二、5.2 监视 / 通讯】
│   └── communication/         低空起降点—飞行器实时通讯与态势系统
│
├── pilot-app/                 【三、终端 APP】
│   └── flyer-app/             C 端飞手 App（PWA + Android APK 打包工程）
│
├── tools_docs/                文档与生成脚本（gen_opt_doc.py → 优化说明 docx；model-training-notes.docx 模型训练说明）
│
└── shared/                    统一接口契约（跨系统，被多个项目引用）
    ├── contract.md            统一数据契约（WGS84 + MSL + snake_case）
    ├── schema.json            机器可读 schema
    ├── interface.js           JS 适配层
    └── interface.py           Python 适配层
```

---

## 三、数据流

```
                    ┌──────────────────────┐
   设备端           │  groundstation       │   PyQt5 桌面端（机位 / RID / 传感器）
   device/          │  机位 / RID / 传感器  │
                    └──────────┬───────────┘
                               ┊  ✗ 尚未接通：桌面站没有把数据交给门户的通道
                               ▼
                    ┌──────────────────────┐
   门户数据桥       │  ground-bridge.py    │   ⚠ 独立的模拟数据生成器
   platform/portal  │  GET /api/ground     │      数值来自 sin 波形，不读地面站进程
                    └──────────┬───────────┘
                               │ REST (8090)
                               ▼
                    ┌──────────────────────┐
   管理平台         │  platform/portal     │◀── 统一快照 /api/sync/snapshot
   platform/        │  一体化门户 (5500)    │
                    └──────────▲───────────┘
                               │
                    ┌──────────┴───────────┐
   飞控             │  flight/flycontrol   │
   flight/          │  FastAPI (8080)      │
                    └──────────▲───────────┘
                               │ 飞行器态势回传 /api/traffic/ingest
                    ┌──────────┴───────────┐
   通讯态势         │  comms/communication │
   comms/           │  C2 / RID / 气象      │
                    └──────────────────────┘
                               │
   终端 APP         ┌──────────┴───────────┐
   pilot-app/       │  pilot-app/flyer-app │  同一套后端，手机可直连
                    └──────────────────────┘
```

所有跨系统数据都走 `shared/` 里的统一契约（`contract.md`），字段一律 canonical：
**WGS84 经纬度 + 海拔 MSL + snake_case**。

> 现状说明：上图里「设备端 → 门户数据桥」这一段**在实现上还不存在**——`ground-bridge.py`
> 是一份自带波浪的模拟数据生成器（`ONBOARDING.md` 的「已知局限」里也注明了"演示占位"）。
> 门户的「地面站」页面拿到的是这组模拟值，不是真机数据。飞控、通讯态势、飞手端三条链路是真的。

---

## 四、端口约定

| 端口 | 用途 |
| --- | --- |
| 8080 | 飞控后端 / 机场 UTM 服务（`/docs` 为 Swagger） |
| 8081 | 地面站本地 DSM 瓦片服务（由地面站桌面端自行启动） |
| 8090 | 门户数据桥（地面站**模拟**数据） |
| 8099 | 模拟 UOM 接收端（仅 `启动演示.bat` 拉起） |
| 5500 | 管理平台门户 |
| 5502 | 飞手端 App |

---

## 五、各子系统单独运行

| 子系统 | 入口 |
| --- | --- |
| 管理平台门户 | `platform\portal\` — 直接打开 `index.html`（默认演示数据模式，不发任何请求），或起静态服务 |
| 地面站（真机版） | `低空系统.bat device`（或双击 `低空系统.bat` 选 `[7]`）。**需先建 venv**：`python -m venv venv` → `venv\Scripts\pip install -r requirements.txt`（PyQt5 / PyQtWebEngine / pymavlink / pyserial / aiohttp / rs1090 …）。**工程路径含中文时**启动器会自动建一个纯 ASCII 的 junction（`%LOCALAPPDATA%\gs-venv`）绕过 Qt 5.15 的 8-bit 路径限制，否则会报 `Could not find the Qt platform plugin "windows"` / `Couldn't mmap icu data file` |
| 地面站（仿真版） | `device\groundstation\wrjtksf\src\` — `python main.py`，需 PySide6（见 `wrjtksf\requirements.txt`） |
| 飞控 | `低空系统.bat api`（前台起 8080，看日志）或 `低空系统.bat apidev`（连带打开后端自带前端页） |
| 通讯态势 | `低空系统.bat comms`（打开页面）；决策引擎原型：`低空系统.bat decision` |
| 飞手端 App | `低空系统.bat app`（本机 5502）/ `低空系统.bat mobile`（手机联调）/ `低空系统.bat apk`（打安卓包） |

---

## 六、维护说明

- **`shared/` 不要移动层级**：它被 `flight/flycontrol` 的 Python 后端与 `comms/communication` 前端引用。
  飞控后端已改为**向上逐层查找** `shared/interface.py`，只要它还在工程根下就不会断；
  通讯态势前端用的是相对路径 `../../shared/interface.js`，移动 `comms/` 需同步调整。
- **启动器里的路径是相对的**（基于 `start-system.ps1` 所在目录），整个工程文件夹可以整体搬走或改名，不受影响。
- **虚拟环境不入库**（`.gitignore` 已忽略 `.venv/` / `venv/` / `.conda/`）。启动器会先用各子项目的
  `.venv`，找不到就回退到系统 Python（`start-system.ps1` 的 `Find-Python`）。
  需要重建后端环境时：`cd flight\flycontrol\low-altitude-demo\backend` →
  `python -m venv .venv` → `.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`。
