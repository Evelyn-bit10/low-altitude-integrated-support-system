# RL 航迹关联（飞桨）

一条命令生成全部参数：

```powershell
python experiments\rl_dedup\run_all.py
# 只重做导出+标定（训练已完成）：
... run_all.py --skip-train
```

## 参数是怎么来的（四层）

| 层 | 参数 | 来源 | 文件 |
| --- | --- | --- | --- |
| ① 超参 | lr 1e-3 / clip 0.2 / 熵 0.01 / 隐层 64 | 手工设定（见 docs/RL_DEDUP.md） | `train_ppo.py` |
| ② 权重 | 10 个张量 | **训练** | `ppo_policy.pdparams` → `policy_weights.json` |
| ③ 归一化 | 19 维 mean/std | 训练样本统计 | 同上 |
| ④ 阈值 | 0.30 | **标定**（误配 ≤ 规则约束下取奖励最优） | `rl_params.json` |

## 文件

| 文件 | 说明 |
| --- | --- |
| `env.py` | MDP 环境（状态/动作/奖励/转移） |
| `train_ppo.py` | 飞桨 PPO（规则热启动 + 逐边优势） |
| `export_policy.py` | 权重 → JSON，并校验与飞桨一致（<2e-6） |
| `policy_runtime.py` | **纯 numpy 推理**，线上不装 Paddle 也能用 |
| `calibrate_threshold.py` | 阈值标定 |
| `run_all.py` | 流水线：训练→导出→标定 |
| `train.py` | CEM 参数搜索（无依赖对照） |
| `rl_params.json` | 上线参数（阈值 + 预期指标 + 约束） |

## 当前结果（验证集）

| | 奖励 | 错配 | 漏配 | 碎片 |
| --- | --- | --- | --- | --- |
| 规则 | −1247 | 909 | 38 | 2.60 |
| PPO(0.30) | **−959** | **753** | **13** | **2.10** |

## 上线步骤

1. 影子模式：规则与策略并行，只记录不生效；
2. 比对一周指标，不劣于规则再切；
3. 换设备/换场景 → 重跑 `run_all.py` 重新生成参数。
