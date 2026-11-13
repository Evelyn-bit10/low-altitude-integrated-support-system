# -*- coding: utf-8 -*-
"""一条命令跑完 RL 参数生成流水线：训练 → 导出 → 标定 → 打印参数。

用法：
    C:/Users/Lenovo/rl-venv/Scripts/python.exe experiments/rl_dedup/run_all.py
    ... --skip-train      # 跳过训练，只重做导出 + 标定（调阈值时用）
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def run(script: str, title: str):
    print("\n" + "=" * 78)
    print(" %s" % title)
    print("=" * 78)
    r = subprocess.run([sys.executable, os.path.join(_HERE, script)], cwd=_HERE)
    if r.returncode != 0:
        raise SystemExit("%s 失败（exit %d）" % (script, r.returncode))


def main() -> int:
    skip_train = "--skip-train" in sys.argv
    if not skip_train:
        run("train_ppo.py", "① 训练 PPO（飞桨）")
    run("export_policy.py", "② 导出权重为纯 JSON")
    run("calibrate_threshold.py", "③ 标定决策阈值")

    params = json.load(open(os.path.join(_HERE, "rl_params.json"), encoding="utf-8"))
    print("\n" + "=" * 78)
    print(" 最终参数")
    print("=" * 78)
    print("  阈值        : %.2f" % params["threshold"])
    print("  特征维度    : %d" % len(params["features"]))
    print("  预期（验证）: 奖励 %.1f 错配 %.0f 漏配 %.0f 碎片 %.2f"
          % (params["expected"]["reward"], params["expected"]["wrong"],
             params["expected"]["miss"], params["expected"]["frags"]))
    print("  规则基线    : 奖励 %.1f 错配 %.0f 漏配 %.0f 碎片 %.2f"
          % (params["rule_baseline"]["reward"], params["rule_baseline"]["wrong"],
             params["rule_baseline"]["miss"], params["rule_baseline"]["frags"]))
    print("\n  产物：policy_weights.json（权重+归一化）、rl_params.json（阈值+指标）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
