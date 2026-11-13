# 核心算法与理论支撑

本 Demo 的核心算法均有可靠文献/规范支撑。下表说明每个引擎使用了哪项理论、
对应实现位置, 以及哪些部分是面向演示的简化。

## 1. 4D 航迹动态规划引擎(`app/engines/planner.py`)

| 理论/算法 | 出处 | 实现 |
| --- | --- | --- |
| A* 启发式图搜索 | Hart, P. E., Nilsson, N. J., & Raphael, B. (1968). *A Formal Basis for the Heuristic Determination of Minimum Cost Paths*. IEEE Trans. Systems Science and Cybernetics, 4(2), 100–107. | `plan_astar()`: 3D 网格 + 欧氏启发式 + 障碍物占据 + 梯度约束 |
| RRT 快速扩展随机树 | LaValle, S. M. (1998). *Rapidly-exploring Random Trees: A New Tool for Path Planning*. TR 98-11, Iowa State Univ. | `plan_rrtstar()` 的基础框架 |
| RRT* 渐近最优 | Karaman, S., & Frazzoli, E. (2011). *Sampling-based Algorithms for Optimal Motion Planning*. IJRR, 30(7), 846–894. | `plan_rrtstar()`: 重连(rewiring)与目标偏置 |
| Dubins 曲率约束(最小转弯半径) | Dubins, L. E. (1957). *On Curves of Minimal Length with a Constraint on Average Curvature...*. Amer. J. Math., 79(3), 497–516. | `smooth_shortcut()` 以三点定圆半径(`geometry.turn_radius_from_points`)约束航迹曲率 ≥ 最小转弯半径 |
| 4D 航迹(t + 速度剖面) | 沿航迹积分得到 `(x,y,z,t)` 四维剖面 | `build_4d_profile()` |

> 说明: 网格分辨率(XY 50m / Z 5m)与梯度离散化导致实际可实现的梯度略低于
> 标称限制, 属保守近似; 生产可换用连续空间 A*/LazyPRM/模型预测控制(MPC)。

## 2. 民航合规校验引擎(`app/engines/compliance.py`)

| 概念 | 出处 | 实现 |
| --- | --- | --- |
| OAS 障碍物评价面 | ICAO Doc 8168 *PANS-OPS*, Vol. II (以及国内 CCAR-97FS 对标) | `check_oas()`: 与跑道固连的最终进近面, 横向线性漏斗 + 下滑道斜面 |
| MOC 超障余度 | 同上(PANS-OPS 超障余度) | `check_moc()`: 航迹点 vs 障碍物圆柱的垂直净空 |
| MSA 最低安全高度 | CCAR-97 / PANS-OPS | `calc_msa()`: 最高障碍物 + 附加余度 |
| 航段爬升/下降梯度 | 机型性能包线 | `check_gradients()` |

> 说明: 真实 OAS 是一组三维曲面方程(进近/离场/复飞各自定义), 且需按
> 精密/非精密进近区分。本 Demo 以"横向扩展漏斗 + 下滑道斜面"作结构化近似,
> 计算结构与规范一致, 便于验证; 生产必须替换为完整曲面方程组并引入审定数据。

## 3. 环境风险评估引擎(`app/engines/risk.py`)

| 方法 | 出处 | 实现 |
| --- | --- | --- |
| 特定运行风险评估(SORA) | JARUS, *SORA: Specific Operations Risk Assessment* | 障碍物/气象/空域多因子打分与分级思路 |
| 风险矩阵与权重模型 | ICAO Doc 9859 *Safety Management Manual* | `assess()`: 加权求和 + 阈值分级(低/中/高/禁飞) |

> 说明: 权重(`RISK_W_*`)与阈值(`RISK_TH_*`)存放在规则库, 可运行时调整。
> 演示使用透明加权模型; 生产可采用贝叶斯网络/模糊推理/深度风险模型并做审定。

## 4. 仿真验证引擎(`app/engines/simulate.py`)

- 障碍物碰撞: 线段-圆柱采样检测(`geometry.segment_free`)。
- 气象适配/空域冲突: 点-多边形(射线法)与高度层判定。
> 这是面向演示的工程级校验, 非空气动力学/飞行仿真; 生产应接入六自由度动力学
> 仿真与气象场插值。

## 5. 标准与规范清单(系统对标)

- 《民用机场飞行程序和运行最低标准管理规定》CCAR-97FS-R3
- MH/T 4055.2-2022《低空飞行服务系统技术规范》
- ICAO Doc 8168 PANS-OPS Vol. II(飞行程序设计/障碍物评价)
- ICAO Doc 9859(安全管理)
- JARUS SORA(无人/低空运行特定风险评估)

> 重要声明: 本 Demo 用于展示系统架构、闭环调度与算法可行性, 不构成可发布的
> 民航飞行程序设计成果。任何正式运行程序须由具备资质的设计单位按 CCAR-97
> 与 PANS-OPS 完整计算并报民航审定/备案。
