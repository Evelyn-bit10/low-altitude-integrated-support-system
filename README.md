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
| 2 | 门户数据桥（ground-bridge） | 8090 | 机位 / RID900 / 传感器数据 |
| 3 | 管理平台门户 | 5500 | 浏览器自动打开 |
| 4 | 飞手端 App（PWA） | 5502 | 手机同 Wi-Fi 可直接访问 |
| 5 | 通讯态势（communication） | — | 浏览器自动打开 |
| 6 | 地面站桌面端（groundstation） | — | 独立窗口，若虚拟环境存在 |

服务统一绑定 `0.0.0.0`，手机在同一 Wi-Fi 下可直接访问（启动完成时会打印手机地址）。
已在运行的服务会自动复用，不会重复启动。

> 关闭服务：把启动时新开的几个最小化窗口关掉即可。

---

## 一·补、功能演示台（对外演示用）

如果目的是**给别人演示这三项能力**，直接双击根目录 **`启动演示.bat`**：

| 页面 | 地址 | 内容 |
| --- | --- | --- |
| 功能演示台 | http://127.0.0.1:5500/demo.html | ① 进出场程序　② 多设备去重　③ 对外数据推送 |

它会额外拉起「模拟 UOM 接收端」(8099)，并把后端切到 `PUSH_MODE=http`。
演示脚本与讲解词见 `flight/flycontrol/low-altitude-demo/backend/docs/DEMO.md`。

## 二、目录结构

```
yth/
├── 启动一体化门户.bat        ★ 全系统一键启动（双击）
├── start-system.ps1          启动逻辑（被上面那个 bat 调用）
├── README.md                 本说明
│
├── 需求/                      需求文档与功能分解
│   ├── 低空综合保障设备-软件及管理平台需求说明书-整合版.docx
│   ├── 系统功能分解思维导图.html        ← 三大系统分解，交互式可折叠
│   └── README.md                        ← 需求文档索引（含各项目内 SRS 位置）
│
├── platform/                  【二、后台管理平台（B/S）】
│   ├── portal/                一体化门户（我方可控的网页端）
│   └── prototype/             同事做的管理平台原型（龙兴机场示例，只读参考）
│
├── device/                    【一、设备端嵌入式软件（节点层）】
│   └── groundstation/         地面站：机位调度 + RID900 探测 + Modbus 传感器 + 桌面端
│
├── flight/                    【二、5.3 飞行程序管理】
│   └── flycontrol/            动态起降飞行程序实时调整（FastAPI 后端 + 前端）
│
├── comms/                     【二、5.2 监视 / 通讯】
│   └── communication/         低空起降点—飞行器实时通讯与态势系统
│
├── pilot-app/                 【三、终端 APP】
│   └── flyer-app/             C 端飞手 App（PWA + Android APK 打包工程）
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
   设备端           │  groundstation       │
   device/          │  机位 / RID / 传感器  │
                    └──────────┬───────────┘
                               │ ground-bridge.py (8090) 转 REST
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

---

## 四、端口约定

| 端口 | 用途 |
| --- | --- |
| 8080 | 飞控后端 / 机场 UTM 服务 |
| 8090 | 门户数据桥（地面站数据） |
| 5500 | 管理平台门户 |
| 5502 | 飞手端 App |
| 8081 | 地面站本地 DSM 瓦片服务（由地面站桌面端自行启动） |

---

## 五、各子系统单独运行

| 子系统 | 入口 |
| --- | --- |
| 管理平台门户 | `platform\portal\` — 直接打开 `index.html`，或起静态服务 |
| 地面站 | `device\groundstation\wrjtksf\drone_ground_station\` — `python main.py` |
| 飞控 | `flight\flycontrol\low-altitude-demo\启动后端.bat` |
| 通讯态势 | `comms\communication\启动.bat` |
| 飞手端 App | `pilot-app\flyer-app\启动.bat`（本机）/ `真机测试.bat`（手机联调）/ `打包APK.bat`（打安卓包） |

---

## 六、维护说明

- **`shared/` 不要移动层级**：它被 `flight/flycontrol` 的 Python 后端与 `comms/communication` 前端引用。
  飞控后端已改为**向上逐层查找** `shared/interface.py`，只要它还在工程根下就不会断；
  通讯态势前端用的是相对路径 `../../shared/interface.js`，移动 `comms/` 需同步调整。
- **启动器里的路径是相对的**（基于 `start-system.ps1` 所在目录），整个 `yth/` 文件夹可以整体搬走或改名，不受影响。
- **各子项目的虚拟环境**（`.venv` / `venv` / `.conda`）已随目录移动验证可用；
  它们内部记录的是系统 Python 路径（`C:\Python314`），不依赖工程所在位置。
