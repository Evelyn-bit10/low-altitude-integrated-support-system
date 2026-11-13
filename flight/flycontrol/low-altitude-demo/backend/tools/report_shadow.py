# -*- coding: utf-8 -*-
"""影子模式日报：把 logs/shadow.jsonl 聚合成"规则 vs 策略"对比表。

用法::

    python tools/report_shadow.py                     # 默认读 logs/shadow.jsonl
    python tools/report_shadow.py --log other.jsonl
    python tools/report_shadow.py --samples 5          # 打印分歧样本
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict


def load(path: str):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join("logs", "shadow.jsonl"))
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print("没有影子日志：%s" % args.log)
        print("先以 DEDUP_SHADOW=1 启动服务跑一段时间。")
        return 1

    rows = load(args.log)
    if not rows:
        print("日志为空")
        return 1

    total = len(rows)
    agree = sum(1 for r in rows if r.get("agree"))
    extra = sum(1 for r in rows if not r.get("agree") and r.get("policy_gid")
                and not r.get("rule_gid"))
    missed = sum(1 for r in rows if not r.get("agree") and r.get("rule_gid")
                 and not r.get("policy_gid"))
    differ = total - agree - extra - missed
    frames = len({r.get("frame") for r in rows})

    print("=" * 66)
    print(" 影子模式报告  %s" % args.log)
    print("=" * 66)
    print("  帧数 %d ｜ 观测 %d ｜ 策略日均推理 %d 次" % (frames, total, total))
    print("-" * 66)
    print("  %-24s %8s %8s" % ("指标", "数量", "占比"))
    print("  %-24s %8d %7.1f%%" % ("一致（判断相同）", agree, 100.0 * agree / total))
    print("  %-24s %8d %7.1f%%" % ("策略多并（规则没合）", extra, 100.0 * extra / total))
    print("  %-24s %8d %7.1f%%" % ("策略少并（规则合了）", missed, 100.0 * missed / total))
    print("  %-24s %8d %7.1f%%" % ("两边都改判到别的航迹", differ, 100.0 * differ / total))
    print("-" * 66)

    rate = 100.0 * agree / total
    verdict = "✅ 可以进入灰度" if rate >= 95 else ("⚠️  继续观察" if rate >= 85 else "❌ 不建议上线")
    print("  一致率 %.1f%%  →  %s" % (rate, verdict))

    # 按来源
    by_src = defaultdict(lambda: [0, 0])
    for r in rows:
        k = r.get("src") or "?"
        by_src[k][0] += 1
        by_src[k][1] += 1 if r.get("agree") else 0
    if len(by_src) > 1:
        print("\n  按来源：")
        for k, (n, a) in sorted(by_src.items()):
            print("    %-10s %6d 次  一致 %5.1f%%" % (k, n, 100.0 * a / n))

    # 分歧样本
    bad = [r for r in rows if not r.get("agree")]
    if bad and args.samples:
        print("\n  分歧样本（前 %d 条）：" % min(args.samples, len(bad)))
        print("    %-6s %-10s %-8s %-10s %-10s %s"
              % ("帧", "来源", "本地ID", "规则→", "策略→", "p_max"))
        for r in bad[:args.samples]:
            print("    %-6s %-10s %-8s %-10s %-10s %.3f"
                  % (r.get("frame"), r.get("src"), r.get("lid"),
                     r.get("rule_gid") or "新建", r.get("policy_gid") or "新建",
                     r.get("p_max") or 0.0))

    # p 分布（看策略是否"过度自信"）
    ps = sorted(r.get("p_max") or 0.0 for r in rows)
    if ps:
        print("\n  p_max 分布：中位数 %.2f ｜ 90 分位 %.2f ｜ <0.5 占比 %.1f%%"
              % (ps[len(ps) // 2], ps[int(len(ps) * 0.9)],
                 100.0 * sum(1 for p in ps if p < 0.5) / len(ps)))
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
