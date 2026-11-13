# 挺中航空科技有限公司 · 一体化门户

这是根目录下重新实现的独立 Web 门户，用于「低空起降点一体化系统」的演示与运行展示。

门户有两种数据源模式：

- **演示数据（默认）**：完整使用内置演示数据（`mock-data.js`），六个页面全部有内容、全页坐标统一，不依赖任何后端，适合对外演示；
- **实时数据**：接入三个子系统（flycontrol / communication / groundstation），每 5 秒轮询刷新，适合现场联调与后期真实机场对接。

顶栏右上角的状态胶囊可一键切换两种模式；也可用 URL 参数 `?mode=live` 或 `window.LAV_CONFIG.dataMode = 'live'` 指定默认模式。

## 一键运行

双击 `index.bat` 或 `启动一体化门户.bat`。

启动器会：

1. 启动 flycontrol FastAPI（`127.0.0.1:8080`，态势 / 程序数据源）；
2. 启动地面站数据桥（`127.0.0.1:8090`，机位 / RID900 / 传感器数据源）；
3. 启动门户静态服务（`127.0.0.1:5500`）；
4. 打开 communication 通讯态势（浏览器中运行，其飞行器态势会回传 flycontrol）；
5. 启动 groundstation 地面站桌面程序（独立窗口，若虚拟环境存在）；
6. 打开一体化门户。

切到「实时数据」后，门户每 5 秒轮询一次，同时拉取 flycontrol（统一快照 + 当前程序）与地面站数据桥（机位 / 传感器），三个子系统的数据实时汇入一体化界面。任一数据源未就绪时，对应模块自动回退内置演示数据。

默认的「演示数据」模式不发起任何请求，页面立即渲染，不会等待或白屏；直接双击 `index.html` 也一样。

## 文件职责

```text
index.html             门户页面壳与统一导航
styles.css             深色科技风、响应式布局与组件样式
mock-data.js           canonical、groundstation、业务与图表演示数据
api.js                 flycontrol REST 统一出口；唯一 baseUrl 配置点
visuals.js             Canvas 态势图、程序图、剖面与 ECharts 降级
app.js                 路由、状态、六个页面、详情抽屉和交互
portal-launcher.ps1    Windows 一键启动核心（拉起三个子系统 + 数据桥 + 门户）
ground-bridge.py       地面站数据桥（REST: /api/ground，端口 8090，仅标准库）
start-all.bat          启动器兼容入口
index.bat              双击入口
启动一体化门户.bat     中文双击入口
```

## 页面路由

```text
#/home        运行总览
#/situation   实时态势
#/program     飞行程序
#/ground      地面站机位
#/dashboard   数据看板
#/business    业务管理
```

## 预留接口：后期接入真实机场

统一接口层全部保留，对接真实机场**不需要改动页面渲染逻辑**，只需把数据源指向真实服务。

**1）接口出口（唯一改动点）** — `api.js` 顶部：

```js
var defaults = {
  baseUrl:   'http://127.0.0.1:8080',   // flycontrol / 真实机场 UTM 服务
  groundUrl: 'http://127.0.0.1:8090',   // 地面站数据服务
  timeoutMs: 2200
};
```

**2）已预留的接口方法**（`window.LAVApi`）：

| 方法 | 接口 | 数据 |
| --- | --- | --- |
| `snapshot()` | `GET /api/sync/snapshot` | 统一快照：机场 / 障碍物 / 空域 / 气象 / 程序 / 态势 |
| `program()` | `GET /api/program/current` | 当前程序、风险、合规、仿真 |
| `traffic()` | `GET /api/traffic` | 实时飞行器态势（已去重，一架一条） |
| `trafficStats()` | `GET /api/traffic/stats` | 去重统计（原始/唯一/融合/来源分布） |
| `ground()` | `GET /api/ground` | 机位 / RID900 / 传感器 / 停靠调度 |
| `replan()` | `POST /api/program/replan` | 程序重规划 |
| `setMeteo()` | `POST /api/env/meteo` | 写入气象 |
| `toggleObstacle()` | `POST /api/env/obstacle/toggle` | 切换障碍物状态 |

**3）接入步骤**：把 `baseUrl` / `groundUrl` 指向真实机场服务（或把 `ground-bridge.py` 换成真实地面站 REST），再切到「实时数据」模式即可。字段一律遵循 canonical 约定（WGS84 经纬度 + 海拔 MSL + snake_case），契约见 `..\..\shared\contract.md`。

> 设计取舍：演示阶段各页展示数据统一取自 `mock-data.js`（含飞行程序），保证演示完整、坐标一致；真实数据接入时由上述接口提供，页面按 canonical 字段读取即可，渲染逻辑无需改动。


## RL 关联实验室（rl_lab.html）

强化学习航迹去重的可视化页面：拖动 19 维特征，实时看策略网络输出概率、
与规则基线对比、查看训练曲线与特征重要性。

- 打开：双击 `G:\yth\启动RL实验室.bat`，或直接打开 `rl_lab.html`
- 依赖后端 `GET /api/rl/model`（8080）
- 文档：`flight/flycontrol/low-altitude-demo/backend/docs/RL_LAB.md`
