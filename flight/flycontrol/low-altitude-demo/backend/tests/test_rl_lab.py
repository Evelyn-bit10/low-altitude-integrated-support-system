# -*- coding: utf-8 -*-
"""RL 实验室接口测试：权重能正确暴露给可视化页面。"""
from __future__ import annotations

from app.routers import rl_lab


def test_model_payload():
    d = rl_lab.rl_model()
    assert len(d["features"]) == 19
    assert len(d["mean"]) == 19 and len(d["std"]) == 19
    w = d["weights"]
    assert len(w["enc0_w"]) == 19 and len(w["enc0_w"][0]) == 64     # [in, out]
    assert len(w["enc2_w"]) == 64 and len(w["actor_w"]) == 64
    assert 0.0 < d["threshold"] < 1.0
    assert len(d["history"]) >= 1
    assert d["model_info"]["params"] == 5505


def test_health():
    d = rl_lab.rl_health()
    assert d["ok"] is True and d["features"] == 19


def test_weights_reproduce_known_scores():
    """用暴露的权重手算一次，结果应与标定时一致（防止导出/加载错位）。"""
    import math
    d = rl_lab.rl_model()
    # 第 13 维（索引 12）现在是"航迹存活时长/60"，不再是命中次数
    feats = [.30, .10, .10, .05, 1, 0, 0, 1, 0, 0, .10, 0, 0.5, .80, .50, 0, 2.0, .07, 1.0]
    x = [(v - m) / s for v, m, s in zip(feats, d["mean"], d["std"])]
    w = d["weights"]
    h = [math.tanh(sum(x[i] * w["enc0_w"][i][j] for i in range(19)) + w["enc0_b"][j])
         for j in range(64)]
    h = [math.tanh(sum(h[i] * w["enc2_w"][i][j] for i in range(64)) + w["enc2_b"][j])
         for j in range(64)]
    z = sum(h[i] * w["actor_w"][i][0] for i in range(64)) + w["actor_b"][0]
    p = 1 / (1 + math.exp(-z))
    assert p > 0.8           # 「同一架」样本必须明显偏向合并（阈值 0.80）
    assert p > 0.5


# ---------------------------------------------------------------- 场景对比

def test_compare_single_scenario_fast():
    """单场景对比：规则 vs PPO，用真值打分（小帧数跑得快）。"""
    from app.services import replay
    d = replay.compare("dense", frames=8)
    assert d["scenario"] == "dense"
    for side in ("rule", "policy"):
        m = d[side]
        assert set(m) >= {"reward", "wrong", "miss", "frags", "split"}
        assert m["wrong"] >= 0 and m["miss"] >= 0
        assert 1.0 <= m["frags"] <= 40.0
    assert 0 < d["threshold"] < 1


def test_compare_unknown_scenario():
    from app.services import replay
    import pytest as _pytest
    with _pytest.raises(ValueError):
        replay.compare("no-such-scenario")


def test_compare_scenarios_registered():
    from app.services import replay
    assert set(replay.SCENARIOS) >= {"sparse", "dense", "hard_dense", "swarm"}
