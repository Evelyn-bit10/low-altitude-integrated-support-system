# HANDOFF · 会话接手说明

> 用途：上下文压缩或新开会话时，读这一页即可恢复状态。
> 更新时间：2026-11-15

---

## 1. 项目

`D:\低空综合保障系统\低空综合保障系统-全量工程` —— 挺中航空 · 低空综合保障系统（三大系统 + 两个独立子系统）。
详细说明见仓库根目录 `README.md`、`ONBOARDING.md`。

> 整个工程目录可以整体搬走或改名：启动器内部全用相对路径。下面示例里的绝对路径
> 按你本地实际位置替换即可。

## 2. 已完成的工作

### 功能一：8 方向进出场程序
- 方案库 `backend/app/plans_library.py`：8 方向 × 2 类型 = 16 套
- 接口：`GET /api/plans`、`POST /api/program/generate`
- 模板不合格自动回退 A*+Dubins，`meta.available=false` 表示不可用
- 演示：`python tools/sim_procedures.py` → `docs/procedures_8dir.png`
- 文档：`backend/docs/PROCEDURES.md`

### 功能二：多设备去重
- 引擎 `backend/app/services/dedup.py`（同一性判定 + 融合）
- 接入 `backend/app/routers/traffic.py`：`/api/traffic`、`/api/traffic/stats`
- 关键参数：`gate_k=3.44`、σ 按源查表（下限 8）、时钟自动对齐、网格索引（>50 目标）
- 演示：`python tools/sim_two_devices.py`（10 条 → 7 条）
- 文档：`backend/docs/DEDUP.md`（含 v1.1 改进记录）

### 功能三：对外推送（UOM）
- `backend/app/integrations/`（adapter / outbox / client）+ `services/push_service.py`
- 接口：`/api/push/status|flush|test|requeue`
- 演示：`python tools/mock_uom_server.py --port 8099` + `PUSH_MODE=http`
- 文档：`backend/docs/PUSH.md`

### 演示台
- `platform/portal/demo.html` + `启动演示.bat` / `start-demo.ps1`
- 三幕：① 进出场程序 ② 多设备去重（俯视图 + 双源连线）③ 推送
- 快捷参数：`?tab=p1|p2|p3`、`?dir=NE`、`?gen=arrival`、`?run=1`

### 强化学习（飞桨）
- `backend/experiments/rl_dedup/`：`env.py`（MDP）、`train_ppo.py`（PPO + 规则热启动）
- 一条命令（用任意装了 PaddlePaddle 的 Python 环境）：`python experiments\rl_dedup\run_all.py`
- 参数：`policy_weights.json`（115 KB）+ `rl_params.json`（阈值 0.80）
- 结果（验证集）：规则 −1247/错配 909/碎片 2.60 → PPO −959/错配 753/碎片 2.10
- 文档：`backend/docs/RL_DEDUP.md`

### 影子模式（RL 上线前验证）
- `app/services/shadow.py`：策略跟跑、只记录不生效，`DEDUP_SHADOW=1` 打开
- `GET /api/traffic/shadow` 实时统计；`tools/report_shadow.py` 出日报
- 实测：390 条观测、2737 条边，一致率 **100%**
- 文档：`backend/docs/SHADOW.md`

### RL 可视化实验室
- `platform/portal/rl_lab.html`：19 维特征滑杆 + 网络动画 + 判定结果 + 训练曲线
- `GET /api/rl/model`：暴露权重（mtime 缓存，重训自动刷新）
- 6 个预设（含 2 个"分歧样本"），`?preset=extra` 可直达
- 一键打开：`低空系统.bat rl`
- 文档：`backend/docs/RL_LAB.md`

### 实时可视化
- `rl_lab.html` 底部「实时影子流」：拉 `/api/rl/live`，点行可把该帧特征灌进模型
- 演示台「多设备去重」俯视图：飞线 + 拖尾 + 脉冲环，可视化合并过程
- 文档：`backend/docs/RL_LAB.md`（4.1 节）、`backend/docs/DEMO.md`（合并动画）

### 演示台集成 RL
- 第二幕新增「RL 策略在场（影子模式）」面板：一致率/多并/少并 + 最近 8 条判定
- 勾选即开启（`POST /api/traffic/shadow`，运行时加载，无需重启）
- 「开始上报」自动开启；面板有「打开 RL 实验室 →」入口

### 演示台第四幕（RL 影子模式）
- 对比屏：`GET /api/rl/compare/all`（带真值，规则 vs PPO）
- 关键结论：困难密集 错配 103 → 1，漏配 4 → 0
- 实时影子流大表 + 场景对比柱状图 + 结论条
- 文档：`backend/docs/DEMO.md`（第四幕）

### 运维 / 权限 / 台账（v1.6）
- `GET /api/metrics`：帧耗时 p50/p99、候选边、计数、卡尔曼 σ 分布
- RBAC：viewer/operator/admin 三级，`AUTH_ENABLED=1` 开启，`X-Token` 传入
- `GET/POST/PUT/DELETE /api/devices`：设备台账（source_key 唯一，落盘 data/devices.json）
- `GET/POST/PUT/DELETE /api/routes`：路线管理（落盘 data/routes.json）
- 航迹快照：每 5 秒写 `data/tracks.json`，`DEDUP_RESTORE=1` 启动恢复
- 文档：`backend/docs/ADMIN.md`

### 方向推荐（v1.7）
- `GET /api/program/recommend`：8 方向自动评分排序（侧风/顺风/航程/梯度/航向）
- 演示台第一幕新增「自动推荐」按钮，自动选中并生成，讲解词区显示理由
- 实测：风 5 m/s @ 0° → 推荐 S（逆风、侧风 0）1.000；N 顺风扣分 0.922
- 文档：`backend/docs/PROCEDURES.md`

### RL 机动目标实验（负结果，已回退）
- 实现了 `KalmanIMM`（双模型 2/8 m/s²），接口与 `KalmanCV` 一致，**未启用**
- 加过 `orbit` 仿真场景（turn 6~18°/s）并重训三次，均导致漏配/碎片暴涨
- 结论：瓶颈在"30° 硬航向门限"，不在滤波器；需改为软证据才可能解决
- 现状：回退到 CV + 4 直飞场景（奖励 −1003 / 错配 760 / 漏配 29 / 影子 100%）

### 自动切换方向（v1.7b）
- 调度周期内自动评估 8 个方向，得分优势 ≥0.05 才切换（滞回）
- 开关 `AUTO_RECOMMEND=1`；决策见 `/api/metrics` 的 `recommend` 字段
- 实测：风 5m/s@0° 时程序 S；改成 9m/s@180° 后自动切到 N（1.000 vs 0.645）

### 环境现状（2026-11-15 核对）
- `.venv` / `venv` **不入库**（`.gitignore` 已忽略），克隆后按需重建：
  `cd flight\flycontrol\low-altitude-demo\backend` → `python -m venv .venv` →
  `.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`
- 启动器已支持回退：有 `.venv` 就用它，没有就用系统 Python
  （后端只依赖 fastapi / uvicorn / pydantic / sqlalchemy）
- `python -m pytest tests -q` → **87 passed**（约 2 分钟，系统 Python 3.13 实测）
- RL 训练另需 PaddlePaddle（CPU 版即可），装在哪个环境都行，不要求固定路径

## 3. 常用命令

```powershell
# 跑测试（在工程根目录下执行；有 .venv 自动用 .venv，没有就用系统 Python）
cd flight\flycontrol\low-altitude-demo\backend
python -m pytest tests -q

# 启动全系统
双击工程根目录的 启动一体化门户.bat

# 演示台
双击工程根目录的 启动演示.bat

# 去重基准 / 前后对比
python experiments\dedup_ml\bench_engine.py
python experiments\dedup_ml\bench_compare.py
```

## 4. 未完成 / 待定

| 项 | 状态 |
|---|---|
| ~~RL 影子模式~~ | ✅ 已完成（`app/services/shadow.py` + `docs/SHADOW.md`） |
| ~~去重航迹级事后合并~~ | ✅ 已做（`DEDUP_POSTMERGE=1` 默认开，稀疏/密集输出=真值） |
| ~~门限写进 RL 特征（19 维）~~ | ✅ 已做并重训（阈值 0.80，影子一致率 100%） |
| ~~卡尔曼滤波（预测+门限）~~ | ✅ 已做（`DEDUP_KALMAN=1` 默认开，与 numpy 参考实现偏差 2e-13） |
| ~~Hungarian 最优分配~~ | ✅ 已做（`DEDUP_ASSIGN=hungarian`，实测暂无增益，默认贪心） |
| 演示台可视化增强（去重开关、左右分屏、飞线动画） | 已给方案，未实施 |
| ~~RL 可视化界面~~ | ✅ 已完成（`rl_lab.html`） |
| ~~RBAC / 设备管理台账 / 路线管理~~ | ✅ 已做（v1.6，见 docs/ADMIN.md） |
| 真实 UOM 规范对接 | 待对方文档 |

## 5. 关键文件速查

```
backend/app/services/dedup.py          去重引擎（~800 行）
backend/app/routers/traffic.py         交通接口 + 去重接入
backend/app/services/push_service.py   推送调度
backend/app/plans_library.py           8 方向方案库
platform/portal/demo.html              演示台（单文件）
experiments/dedup_ml/                  规则 vs 监督学习实验
experiments/rl_dedup/                  强化学习实验
docs/                                  PROCEDURES / DEDUP / PUSH / RL_DEDUP / DEMO
```

## 6. 桌面上的交付物

- `低空综合保障系统-必知手册.md`
- `低空综合保障系统-必知手册.docx`
- `低空综合保障系统-需求核对表.xlsx`
- `低空综合保障系统-需求差距分析.docx`
- `三项新增功能-验收说明.docx`
- `去重精度改进-记录.docx`
- `8方向进出场轨迹.png`
