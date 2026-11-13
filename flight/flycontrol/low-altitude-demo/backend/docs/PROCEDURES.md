# 8 方向进出场程序设计

> 需求：选择进出场方向，通过给定方案库规划轨迹。
> 实现：`app/plans_library.py`（方案库） + `engines/planner.py`（方向化规划） + `routers/program.py`（接口）。

---

## 1. 方向定义

`direction` 表示**从哪个方向来 / 往哪个方向去**，取 8 方位：

| 名称 | 中文 | 方位角（真北 0°，顺时针） |
| --- | --- | --- |
| N | 北 | 0 |
| NE | 东北 | 45 |
| E | 东 | 90 |
| SE | 东南 | 135 |
| S | 南 | 180 |
| SW | 西南 | 225 |
| W | 西 | 270 |
| NW | 西北 | 315 |

- **进近**：从该方向的 2500 m 处进入，反向着陆（着陆航向 = 方位角 + 180°）。
- **离场**：起飞后朝该方向爬升，3000 m 处到达 300 m。
- 接口同时接受方位角数字（如 `90` 等价于 `E`）。

不传 `direction` 时保持旧行为：使用机场跑道方向（`airport.runway_heading`）。

---

## 2. 方案库

`build_library(point_code)` 生成 **8 方向 × 2 类型 = 16 条方案**：

| 字段 | 说明 |
| --- | --- |
| `std_name` | 标准程序名，如 `ARR-S` / `DEP-NE` |
| `direction` | 方位名 |
| `entry_bearing` / `exit_bearing` | 入口 / 出口方位角 |
| `waypoints` | 本地 ENU（x 东 / y 北 / z 相对标高），4 个点 |
| `length_m` | 三维长度 |
| `min_vis` / `max_wind` | 适用气象门槛 |
| `is_default` | 跑道方向对应的默认方案 |

模板剖面统一 10% 梯度（在机型包线 12% 内）：

```
进近  2500m/250m → 1500m/150m → 800m/80m → 0m/0m
离场  0m/0m → 600m/60m → 1500m/150m → 3000m/300m
```

> 方案库在代码里内置，不写 DB，避免演示库表结构迁移；后续接真实机场时换成
> `lp_program_plan` 的 `direction/entry_bearing` 字段即可。

---

## 3. 生成策略（模板优先，动态兜底）

```
按方向取模板
   ├─ 合规 + 仿真通过 → 直接发布（source=plan）
   └─ 不通过（障碍物/限飞区/梯度）
        └─ 动态重规划（A* + Dubins，source=dynamic）
             ├─ 通过 → 发布，std_name 加 “+DYN”
             └─ 不通过 → 标记该方向不可用（available=false），不覆盖当前程序
```

这样每个方向都有明确结论：要么可飞（模板或动态），要么不可飞并给出原因。

---

## 4. 接口

```http
GET  /api/plans?program_type=arrival&direction=S
POST /api/program/generate   {"program_type":"arrival","direction":"NE","mode":"template"}
POST /api/program/replan     {"program_type":"departure","direction":"W"}
```

`generate` 响应额外带 `meta`：

```json
{"mode":"dynamic","fallback":true,"reason":"障碍物[山地(固定)]超障余度不足","available":true}
```

---

## 5. 轨迹模拟

```powershell
cd flight\flycontrol\low-altitude-demo\backend
python tools\sim_procedures.py
```

输出 16 条程序的统计表（点数 / 长度 / 时长 / 最大梯度 / 合规 / 仿真），并生成
`docs/procedures_8dir.png`：

- 实线 = 进近，虚线 = 离场（为区分各偏 70 m）；
- 阴影圆 = 障碍物，紫色虚线框 = 临时限飞区；
- 红色 × = 该方向不可用。

当前演示数据下的结果：

| 方向 | 进近 | 离场 |
| --- | --- | --- |
| N / E / SE / S / SW | 模板直出 | 模板直出 |
| NE / W | 动态重规划（绕障） | 动态重规划 |
| NW | **不可用**（侵入临时限飞区） | **不可用** |

---

## 6. 测试

```powershell
pytest tests\test_procedures.py -q
```

覆盖：方案库数量、模板梯度、8 方向入口/出口方位、方位角与名称等价、
无遮挡方向的模板合规、未指定方向时沿用跑道方向。


---

## 复飞段避障（v1.3 修复）

### 现象

SE 方向进场程序的复飞段（橙色虚线）从跑道直冲西北，**斜穿"临时限飞区-NW"**，
而界面仍显示"合规 ✓ / 仿真 ✓"——检查根本没看复飞段。

### 根因（三处）

| # | 位置 | 问题 |
| --- | --- | --- |
| 1 | `plans_library._missed_approach` | 模板方案的复飞是**硬编码直线 2.8 km**，完全不看障碍/限飞区 |
| 2 | `simulate.check_*` | 只检查 `program.waypoints`，**复飞段压根没被检查过** |
| 3 | `simulate.check_airspace_conflict` | 只看航路点是否落在多边形内；4~5 个点的情况下，整段切进限飞区也可能一个点都不中 |

### 修复

| 位置 | 改动 |
| --- | --- |
| `plans_library.plan_to_program` | 增加 `env` 参数，模板复飞改用规划器的避障版本 |
| `planner.build_missed_approach` | 重写：直线段限长 1200 m；沿线探测障碍/限飞区，冲突则**提前 320 m 转向**，左右转自动挑安全侧；避障余量 15 m（大于仿真的 10 m）；最后自检，不通过退化成长 300 m 的短爬升 |
| `simulate._paths` | 主航迹与复飞**分开检查**（拼成一个列表会凭空多出"末点→复飞起点"的假航段，把所有方向都判成撞障碍） |
| `simulate.check_airspace_conflict` | 改为沿航段每 50 m 采样 |

### 结果

| | 修复前 | 修复后 |
| --- | --- | --- |
| SE 进场复飞 | 穿限飞区，却报"合规 ✓" | 提前转向绕开，**合规 ✓ / 仿真 ✓** |
| 8 方向 × 2 类型 | 15/16 可用（且检查不覆盖复飞） | **16/16 可用，且复飞也纳入检查** |


---

## 自动推荐进出场方向（v1.7）

`GET /api/program/recommend?program_type=arrival[&heading=120]`

把 8 个方向全生成一遍，按**可解释规则**打分排序。为什么不用强化学习：

| RL 适用条件 | 选方向的实际情况 |
| --- | --- |
| 动作多到无法枚举 | 只有 8 方向 × 2 类型 = 16 个候选 |
| 代价延迟出现 | 生成即知（合规/仿真/航程/侧风） |
| 缺评价函数 | 评价维度明确 |

用神经网络替代 16 次循环只会更慢、更不可解释。

### 评分（0~1）

```
0.40            基础分（合规 ✓ 且仿真 ✓），否则直接淘汰
+0.25 × 风分    侧风越小越好；顺风额外扣分（起降都希望逆风）
+0.20 × 航程分  同类型里最短得满分
+0.10 × 梯度余量
+0.05 × 航向契合（避免大转弯）
```

### 实测（风 5 m/s @ 0°）

| 方向 | 得分 | 理由 |
| --- | --- | --- |
| **S** | **1.000** | 逆风 5.0 m/s、侧风 0.0（最优），航程 2.5 km |
| N | 0.922 | 顺风 5.0 m/s（不利） |
| SE | 0.889 | 侧风 3.5 m/s（可接受） |

演示台第一幕新增「自动推荐」按钮，点击后自动选中推荐方向并生成程序，
讲解词区会显示推荐理由。


---

## 自动切换方向（v1.7b）

调度周期里会跑一次推荐，满足条件就**自动切向并发布**（推送服务随之带上新程序）：

| 条件 | 说明 |
| --- | --- |
| 当前程序 `STATIC_VALID` | 程序本身没问题，才考虑"换个更好的方向" |
| 推荐方向可用 | 合规 ✓ 且仿真 ✓ |
| 得分优势 ≥ 0.05 | **滞回**，防止两个同分方向来回跳 |

开关：`AUTO_RECOMMEND=1`（默认开）。决策结果可以通过 `GET /api/metrics` 的
`recommend` 字段查看（`switched / from / to / score / prev_score / reason`）。

### 实测

```
初始（风 5 m/s @ 0°）：程序 S
把风改成 9 m/s @ 180°：一个周期内自动切到 N
   决策：{"switched": true, "from": "NW", "to": "N", "score": 1.0, "prev_score": 0.645}
```

> 踩坑：第一版把这段放在**风险评估之前**并且 `return`，导致 `risk_result`
> 永远是 None，`test_dispatch_full_loop` 直接挂。必须放在 `risk.assess()` 之后。
