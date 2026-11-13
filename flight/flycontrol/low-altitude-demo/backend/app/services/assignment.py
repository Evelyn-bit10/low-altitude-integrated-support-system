# -*- coding: utf-8 -*-
"""最小代价 / 最大收益二分指派（匈牙利算法）。

为什么需要它
------------
去重时的分配问题：本帧 N 条观测、M 条候选航迹，要求"每条观测最多配给一条航迹"、
"同一条航迹对同一来源最多收一条观测"，并且总分最大。
全局贪心（按分数从高到低占用）在密集场景会给次优解：一条高分边占掉了别人唯一的候选。

实现
----
经典的 O(n³) 匈牙利算法（e-maxx 版），支持 n ≤ m 的矩形矩阵；求**最大值**时取负。
纯标准库，不引入 scipy。
"""
from __future__ import annotations

from typing import List, Optional, Sequence


def _hungarian_min(cost: Sequence[Sequence[float]]) -> List[int]:
    """返回每行匹配到的列号（行数 ≤ 列数）。"""
    n, m = len(cost), len(cost[0])
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)          # p[j] = 匹配到列 j 的行（1-based）
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            row = cost[i0 - 1]
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = row[j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    res = [-1] * n
    for j in range(1, m + 1):
        if p[j] > 0:
            res[p[j] - 1] = j - 1
    return res


def max_weight_matching(weights: Sequence[Sequence[float]],
                        min_weight: float = 0.0) -> List[Optional[int]]:
    """最大权二分匹配。

    weights[i][j] 为权重（>=0），返回每行匹配的列号；不匹配返回 None。
    低于 min_weight 的边不会被采用。
    """
    n = len(weights)
    if n == 0:
        return []
    m = len(weights[0])
    if m == 0:
        return [None] * n

    neg = [[-w for w in row] for row in weights]
    if n <= m:
        idx = _hungarian_min(neg)
        out: List[Optional[int]] = []
        for i in range(n):
            j = idx[i]
            out.append(j if j >= 0 and weights[i][j] >= min_weight else None)
        return out

    # 行多于列：转置后求解，再映射回来
    trans = [[weights[i][j] for i in range(n)] for j in range(m)]
    idx_t = _hungarian_min([[-w for w in row] for row in trans])
    out = [None] * n
    for j in range(m):
        i = idx_t[j]
        if i >= 0 and weights[i][j] >= min_weight:
            out[i] = j
    return out
