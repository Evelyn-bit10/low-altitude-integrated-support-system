# -*- coding: utf-8 -*-
"""实验：用监督学习替代手工门限，做「同一架」判定。

对照：现有规则引擎（距离/高差/航向 + ua_id 硬规则）
关注：**误配率**（两架并成一条）与**漏配率**（同一架拆成两条）

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python experiments\\dedup_ml\\run.py
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sim  # noqa: E402

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

EASY = ["sparse", "dense", "cross", "formation"]
HARD = ["hard_dense", "hard_formation", "cross"]
EXTREME = ["extreme_dense", "hard_formation"]
RNG = np.random.default_rng(7)


# ------------------------------------------------------------------ 数据
def frame_matrix(fr):
    """一帧 -> (X, meta, rule, label, srcs)，meta=(obs_idx, track_idx)。"""
    t, obs, tracks = fr["t"], fr["obs"], fr["tracks"]
    rows, meta, rules, labels, srcs = [], [], [], [], [o.src for o in obs]
    for oi, o in enumerate(obs):
        order = sorted(range(len(tracks)),
                       key=lambda ti: (o.x - tracks[ti].x) ** 2 + (o.y - tracks[ti].y) ** 2)
        for rank, ti in enumerate(order):
            f, lbl, r = sim.pair_features(o, tracks[ti], t, rank)
            rows.append(f); meta.append((oi, ti)); rules.append(r); labels.append(lbl)
    return (np.asarray(rows, dtype=np.float64), meta,
            np.asarray(rules, dtype=np.float64), np.asarray(labels, dtype=np.int8), srcs)


def build_frames(scenarios, seed, frames=50, level="easy"):
    out = []
    for sc in scenarios:
        out.extend(sim.generate(sc, n_planes=12, frames=frames, seed=seed, level=level))
    return out


def build_train(frames, subsample_neg=6):
    X, y = [], []
    for fr in frames:
        Xf, meta, rule, lab, _ = frame_matrix(fr)
        pos = np.flatnonzero(lab == 1)
        neg = np.flatnonzero(lab == 0)
        keep = list(pos)
        if len(neg):
            keep += list(RNG.choice(neg, size=min(len(neg), subsample_neg * max(1, len(pos))),
                                    replace=False))
        if keep:
            X.append(Xf[keep]); y.append(lab[keep])
    return np.vstack(X), np.concatenate(y)


# ------------------------------------------------------------------ 评估
def assignment_eval(mats, score_vec_fn, threshold):
    """逐帧一对一匹配；同一条航迹允许被「不同来源」的观测同时更新（与线上引擎一致）。"""
    correct = wrong = missed = 0
    for X, meta, rule, lab, srcs in mats:
        if len(X) == 0:
            continue
        s = score_vec_fn(X, rule)
        idx = np.flatnonzero(s >= threshold)
        used_o, used_t = set(), set()
        if len(idx):
            for k in idx[np.argsort(-s[idx])]:
                oi, ti = meta[k]
                key = (srcs[oi], ti)
                if oi in used_o or key in used_t:
                    continue
                used_o.add(oi); used_t.add(key)
                if lab[k] == 1:
                    correct += 1
                else:
                    wrong += 1
        missed += len(srcs) - len(used_o)
    total = correct + wrong + missed
    return {"correct": correct, "wrong": wrong, "missed": missed,
            "wrong_rate": wrong / max(1, total), "miss_rate": missed / max(1, total)}


def loose_rule_score(X, rule=None):
    """对照组：把规则的固定门限放宽（航向/高差 45，距离 1.6 倍），看是否就能追上学习。"""
    dgate, dalt, dhdg = X[:, 0], X[:, 2] * 30.0, X[:, 3] * 30.0
    ua_conf, reg_conf, slow = X[:, 6], X[:, 9], X[:, 15]
    ok = ((ua_conf < 0.5) & (reg_conf < 0.5) & (dgate <= 1.6) &
          (dalt <= 45.0) & ((slow > 0.5) | (dhdg <= 45.0)))
    return np.where(ok, 1.0 - dgate / 1.6, 0.0)


def ambiguity(mats):
    """真值航迹不是最近候选的比例：越高说明场景越难。"""
    wrong_nearest = total = 0
    for X, meta, rule, lab, srcs in mats:
        best = {}
        for k, (oi, ti) in enumerate(meta):
            if oi not in best or X[k, 0] < X[best[oi], 0]:
                best[oi] = k
        for oi, k in best.items():
            total += 1
            if lab[k] != 1:
                wrong_nearest += 1
    return wrong_nearest / max(1, total)


def prf(pred, y):
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    p = tp / max(1, tp + fp); r = tp / max(1, tp + fn)
    return p, r, 2 * p * r / max(1e-9, p + r)


def pick_threshold(proba, y, rule_pred, allow_extra=1.0):
    """在误配数不超过规则基线的前提下，选召回最高的阈值（安全优先）。"""
    rule_fp = int(((rule_pred == 1) & (y == 0)).sum())
    best_thr, best_recall = 0.5, -1.0
    for thr in np.arange(0.05, 0.96, 0.01):
        pred = proba >= thr
        if int((pred & (y == 0)).sum()) > rule_fp * allow_extra:
            continue
        tp = int((pred & (y == 1)).sum()); fn = int((~pred & (y == 1)).sum())
        rec = tp / max(1, tp + fn)
        if rec > best_recall:
            best_recall, best_thr = rec, float(thr)
    return best_thr if best_recall >= 0 else 0.5


# ------------------------------------------------------------------ 主流程
def main() -> int:
    t0 = time.time()
    print("=" * 78)
    print(" 去重关联：规则 vs 监督学习（仿真数据 + 真值）")
    print("=" * 78)

    print("\n[1/4] 训练数据 …")
    tr_frames = (build_frames(EASY, seed=1, frames=50)
                 + build_frames(HARD, seed=2, frames=45, level="hard")
                 + build_frames(EXTREME, seed=3, frames=45, level="extreme"))
    Xtr, ytr = build_train(tr_frames)
    print("      帧 %d / 样本 %d（正样本 %d）" % (len(tr_frames), len(ytr), int(ytr.sum())))

    print("[2/4] 验证集（选阈值）与测试集 …")
    va_frames = (build_frames(EASY, seed=21, frames=35)
                 + build_frames(HARD, seed=22, frames=30, level="hard")
                 + build_frames(EXTREME, seed=23, frames=30, level="extreme"))
    te_easy = build_frames(EASY, seed=11, frames=45)
    te_hard = build_frames(HARD, seed=12, frames=45, level="hard")
    te_ext = build_frames(EXTREME, seed=13, frames=45, level="extreme")
    mats_va = [frame_matrix(f) for f in va_frames]
    mats_easy = [frame_matrix(f) for f in te_easy]
    mats_hard = [frame_matrix(f) for f in te_hard]
    mats_ext = [frame_matrix(f) for f in te_ext]
    for tag, mats in (("验证", mats_va), ("测试-常规", mats_easy),
                      ("测试-困难", mats_hard), ("测试-极端", mats_ext)):
        y = np.concatenate([m[3] for m in mats])
        print("      %-10s 帧 %4d / 对 %6d / 正样本 %5d"
              % (tag, len(mats), len(y), int(y.sum())))

    print("[3/4] 训练 …")
    scaler = StandardScaler().fit(Xtr)
    models = {
        "逻辑回归": LogisticRegression(max_iter=3000, class_weight="balanced"),
        "随机森林": RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                          n_jobs=-1, class_weight="balanced_subsample",
                                          random_state=0),
        "梯度提升": HistGradientBoostingClassifier(max_iter=250, learning_rate=0.08,
                                                max_depth=6, random_state=0),
    }
    for name, m in models.items():
        X = scaler.transform(Xtr) if name == "逻辑回归" else Xtr
        m.fit(X, ytr)
        print("      %s ✓" % name)

    print("[4/4] 评估\n")

    def predict(m, name, X):
        return m.predict_proba(scaler.transform(X) if name == "逻辑回归" else X)[:, 1]

    # 阈值在验证集上选（误配不超过规则基线）
    Xva = np.vstack([m[0] for m in mats_va])
    yva = np.concatenate([m[3] for m in mats_va])
    rva = np.concatenate([m[2] for m in mats_va])
    thrs = {}
    for name, m in models.items():
        p = predict(m, name, Xva)
        thrs[name] = pick_threshold(p, yva, rva > 0)
        print("  %-8s 验证集 AUC=%.4f  选定阈值=%.2f"
              % (name, roc_auc_score(yva, p), thrs[name]))

    for tag, mats in (("常规场景（间距 >> 噪声）", mats_easy),
                      ("困难场景（大噪声 + 系统偏差 + 密集）", mats_hard),
                      ("极端场景（间距 ≈ 噪声）", mats_ext)):
        X = np.vstack([m[0] for m in mats])
        y = np.concatenate([m[3] for m in mats])
        rule = np.concatenate([m[2] for m in mats])

        print("\n" + "-" * 78)
        print(" %s" % tag)
        print("-" * 78)
        amb = ambiguity(mats)
        print("  歧义度：真值航迹不是最近候选的比例 = %.1f%%" % (amb * 100))
        print("%-10s %8s %8s %8s %9s %9s" % ("方法", "正确", "误配", "漏配", "误配率", "漏配率"))

        base = assignment_eval(mats, lambda X_, rule_: rule_, 1e-9)
        print("%-10s %8d %8d %8d %8.3f%% %8.2f%%"
              % ("规则(现状)", base["correct"], base["wrong"], base["missed"],
                 base["wrong_rate"] * 100, base["miss_rate"] * 100))
        loose = assignment_eval(mats, loose_rule_score, 1e-9)
        print("%-10s %8d %8d %8d %8.3f%% %8.2f%%"
              % ("规则(放宽)", loose["correct"], loose["wrong"], loose["missed"],
                 loose["wrong_rate"] * 100, loose["miss_rate"] * 100))

        for name, m in models.items():
            thr = thrs[name]

            def score(X_, rule_, m=m, name=name):
                return predict(m, name, X_)

            ev = assignment_eval(mats, score, thr)
            print("%-10s %8d %8d %8d %8.3f%% %8.2f%%"
                  % (name, ev["correct"], ev["wrong"], ev["missed"],
                     ev["wrong_rate"] * 100, ev["miss_rate"] * 100))

        print("  （成对分类：规则(现状) P=%.4f R=%.4f F1=%.4f）" % prf(rule > 0, y))
        print("            规则(放宽) P=%.4f R=%.4f F1=%.4f" % prf(loose_rule_score(X) > 0, y))
        for name, m in models.items():
            p = predict(m, name, X)
            print("             %-6s P=%.4f R=%.4f F1=%.4f  AUC=%.4f"
                  % (name, *prf(p >= thrs[name], y), roc_auc_score(y, p)))

    rf = models["随机森林"]
    print("\n特征重要度（随机森林）")
    print("-" * 78)
    for k, v in sorted(zip(sim.FEATURE_NAMES, rf.feature_importances_), key=lambda x: -x[1])[:10]:
        print("  %-16s %5.1f%%  %s" % (k, v * 100, "█" * int(round(v * 55))))

    print("\n耗时 %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
