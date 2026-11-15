# 低空动态起降飞行程序实时调整系统 · Demo

将 SRS 需求与核心代码框架落地为**可直接部署的最小可运行 Demo**:

- 统一数据库技术栈为 **PostgreSQL 15 + PostGIS 3.3**(修复原文档 MySQL/PostGIS 混用),
  时序气象数据从 InfluxDB 收敛到 Postgres(`lp_meteo_log`), 消除版本冲突。
- 四大引擎由伪代码落地为**真实可运行代码**, 核心算法以论文/规范支撑:
  - 合规校验引擎: 简化 OAS + MOC + MSA + 航段梯度
  - 风险评估引擎: 多因子加权(障碍物/气象/空域)
  - 4D 航迹规划引擎: **A*** + **RRT*** + **Dubins** 曲率约束平滑 + 4D 剖面
  - 仿真验证引擎: 碰撞/气象/空域校验
- FastAPI 后端 + 纯 Canvas 前端(零外部依赖) + **1~2 秒闭环调度**。

详见 `docs/REFERENCES.md` 的算法出处与简化说明。

## 目录结构

```
low-altitude-demo/
├── docker-compose.yml          # 一键部署(PostGIS + 后端)
├── .env
├── db/init/                    # 统一 PostgreSQL+PostGIS 建表 + 种子数据
│   ├── 01_schema.sql
│   └── 02_seed.sql
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── config.py / db.py / models.py / store.py / schemas.py
│   │   ├── demo_data.py        # 演示场景(与 SQL 种子一致)
│   │   ├── domain.py           # 领域数据类(ENU 坐标)
│   │   ├── engines/            # 四大引擎
│   │   │   ├── geometry.py     # 坐标/碰撞/射线法
│   │   │   ├── compliance.py   # 引擎1 合规校验
│   │   │   ├── risk.py         # 引擎2 风险评估
│   │   │   ├── planner.py      # 引擎3 A*/RRT*/Dubins 规划
│   │   │   └── simulate.py     # 引擎4 仿真验证
│   │   ├── services/dispatch.py # 闭环调度
│   │   └── routers/program.py   # API
│   └── tests/test_engines.py    # 单元测试
└── frontend/                   # 静态可视化(平面 + 高度剖面)
```

## 快速开始

### 方式 A: 双击启动(最简单, Windows)

双击工程根目录的 **`低空系统.bat`** 并选 `[6] Backend + built-in frontend page`（或执行 `低空系统.bat apidev`）即可:

1. 首次运行会自动创建虚拟环境 `backend\.venv` 并安装依赖(需本机已装 Python 3.10+)。
2. 随后自动启动服务并打开浏览器 http://127.0.0.1:8080 。
3. 关闭弹出的命令行窗口即停止服务。

> 若需手动运行, 虚拟环境已内置, 可直接:
> `backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8080`
> (在 `backend` 目录下执行)。

### 方式 B: 纯 Python(本机无 Docker 也可演示)

需要 Python 3.10+。在 `backend` 目录:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

> 首次运行默认使用 `sqlite:///./flight_demo.db`(无需数据库服务), 自动建表 +
> 内置演示数据。浏览器打开 http://127.0.0.1:8080 即可看到平面/剖面视图与
> 控制面板。交互式 API 文档在 http://127.0.0.1:8080/docs 。

### 方式 C: Docker Compose(生产形态, 统一 PostGIS)

```bash
docker-compose up -d --build
```

启动后: 前端 http://localhost:8080, 数据库 PostgreSQL/PostGIS(5432)。
首次启动自动执行 `db/init/*.sql` 建表并写入种子数据。

## 演示流程(闭环)

1. 系统启动后自动生成初始**进近程序**(塔吊默认关闭, 航径直线)。
2. 点击 **"激活动态塔吊"** —— 塔吊出现在进场航路上, 风险评估升至"高风险",
   闭环调度自动触发 **A\* + Dubins 平滑** 实时重规划, 航迹绕开塔吊后发布新版本。
3. 可点击 **"恶劣气象"**(大风/低能见/风切变)观察风险分级与程序状态变化。
4. 可手动触发 **进近/离场重规划**, 实时查看平面图、高度剖面与合规/仿真校验结果。

## 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/program/current` | 当前程序 + 风险 + 合规/仿真校验 + 告警 |
| GET | `/api/plans` | 方案库查询（`program_type` / `direction`） |
| POST | `/api/program/generate` | 按方向生成 `{program_type, direction, mode}` |
| POST | `/api/program/replan` | 手动重规划 `{program_type, direction?}` |
| POST | `/api/env/meteo` | 更新气象 |
| POST | `/api/env/obstacle/toggle` | 激活/关闭障碍物 `{id, active}` |
| GET | `/api/traffic` | 实时态势（**已去重**：一架一条） |
| GET | `/api/traffic/stats` | 去重统计（原始/唯一/融合/来源分布） |
| POST | `/api/traffic/ingest` | 接收设备态势，服务端去重后入库 |
| GET | `/api/push/status` | 对外推送状态（队列/成功率/延迟） |
| POST | `/api/push/flush` `/api/push/test` | 立即推送 / 发测试报文 |
| GET | `/api/obstacles` `/api/airspaces` `/api/rules` `/api/airport` | 数据查询 |

## 8 方向进出场程序

选择 N/NE/E/SE/S/SW/W/NW 中任一方向，从方案库生成进近 / 离场程序；
模板不合规时自动动态重规划。详见 [`docs/PROCEDURES.md`](docs/PROCEDURES.md)。

演示：`python tools\sim_procedures.py`（16 条轨迹 + `docs/procedures_8dir.png`）。

## 对外数据推送（UOM / 地方平台）

态势、飞行程序、气象按配置推送到外部平台；发件箱落库保证断网不丢、指数退避重试、
HMAC-SHA256 签名。详见 [`docs/PUSH.md`](docs/PUSH.md)。

本地联调：`python tools\mock_uom_server.py`（模拟对端）+ `PUSH_MODE=http` 启动后端。

## 多设备去重

同一架无人机被多个设备看到时只输出一条，详见 [`docs/DEDUP.md`](docs/DEDUP.md)。

演示：`python tools\sim_two_devices.py`（双设备上报 10 条 → 去重后 7 条）。

## 运行单元测试

```bash
cd backend
python tests/test_engines.py        # 或 pytest tests -q
```

## 已知边界与生产化提示

- **OAS 为简化近似**(横向漏斗 + 下滑道斜面), 非完整 PANS-OPS 曲面方程组; 生产须替换并引入审定数据。
- **风险模型为透明加权**, 权重/阈值存于 `lp_avi_rule`, 可运行时调整; 生产可升级为 SORA 完整评估。
- **A\* 网格分辨率**(50m/5m)带来的梯度离散化略保守; 生产可换连续空间规划或 MPC。
- **鉴权未启用**(`AUTH_ENABLED=false`), RBAC 表已建好, 供后续接入。
- 本 Demo 不构成可发布的民航飞行程序设计成果, 正式运行须经有资质单位设计并报民航审定/备案。
