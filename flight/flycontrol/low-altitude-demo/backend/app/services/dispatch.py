"""闭环调度服务: 对应原伪代码 FlightProgramDispatchService.loopDispatch。

流程: 采集环境 -> 风险评估 -> 程序可用性判定 -> (预案切换 | 实时重规划)
      -> 民航合规校验 -> 仿真校验 -> 审核发布, 循环执行。
"""
from __future__ import annotations

import asyncio
import os
import logging
from typing import Tuple

from ..domain import FlightProgram, Waypoint
from ..plans_library import find_plans, plan_to_program
from ..engines import compliance, planner, risk, simulate
from ..store import Store
from .history import record_event

log = logging.getLogger("lowalt.dispatch")


class DispatchService:
    def __init__(self, store: Store):
        self.store = store
        self.running = False
        self._task = None

    # ------------------------------------------------------------------ 核心
    def run_cycle(self):
        store = self.store
        env = store.snapshot()
        rules = store.rules

        # 1) 尚无程序: 生成初始程序并直接发布
        if store.current_program is None:
            prog = planner.replan_arrival(env, rules)
            self._verify_and_publish(prog, 1)
            return

        # 2) 环境风险评估 & 程序可用性判定
        rr = risk.assess(env, store.current_program, store.plans, rules)
        store.risk_result = rr
        if rr.program_status == "STATIC_VALID":
            # 2.5) 自动方向推荐：程序本身没问题，但环境变了可能有更优方向。
            #      放在风险评估之后，risk_result 才不会被跳过。
            if os.environ.get("AUTO_RECOMMEND", "1") == "1":
                try:
                    info = auto_recommend(self, "arrival")
                    store.last_recommend = info
                    hist = getattr(store, "recommend_history", None)
                    if hist is None:
                        hist = store.recommend_history = []
                    if info.get("switched"):
                        import time as _t
                        hist.append({"t": _t.time(), "from": info.get("from"),
                                     "to": info.get("to"), "score": info.get("score"),
                                     "prev_score": info.get("prev_score"),
                                     "reason": info.get("reason", "")})
                        del hist[:-20]
                    if info.get("switched"):
                        log.info("自动切换方向 %s → %s（%.2f vs %.2f）",
                                 info.get("from"), info.get("to"),
                                 info["score"], info["prev_score"])
                        return
                except Exception as exc:      # 推荐失败不影响主调度
                    log.debug("自动推荐失败: %s", exc)
            store.last_alarm = None
            return
        if rr.program_status == "INVALID":
            store.last_alarm = f"禁飞级风险({rr.level_name}), 无可用程序"
            return

        # 3) 需要调整: 优先预案切换(仅当预案合规), 否则实时重规划
        prog = None
        if rr.matched_plan_id is not None:
            cand = self._plan_program(rr.matched_plan_id)
            if compliance.check_full(cand, env, rules, store.limits).is_pass:
                prog = cand
        if prog is None:
            prog = planner.replan_arrival(env, rules)
            record_event(store, "procedure", "auto_replan", "warn",
                         "风险 %s，自动重规划进近程序" % rr.level_name)

        self._verify_and_publish(prog, rr.level)

    def _verify_and_publish(self, prog: FlightProgram, risk_level: int):
        store = self.store
        env = store.snapshot()
        comp = compliance.check_full(prog, env, store.rules, store.limits)
        store.compliance = comp
        if not comp.is_pass:
            store.last_alarm = "合规校验未通过: " + comp.err_msg()
            record_event(store, "procedure", "publish_failed", "error", store.last_alarm)
            return
        sim = simulate.simulate_check(prog, env)
        store.simulate = sim
        if not sim.is_pass:
            store.last_alarm = "仿真校验未通过: " + sim.err_msg()
            record_event(store, "procedure", "publish_failed", "error", store.last_alarm)
            return
        store.publish(prog, risk_level)
        record_event(store, "procedure", "published", "info",
                     "%s %s v%s（风险 %s）" % (prog.program_type, prog.plan_id,
                                               prog.version, risk_level))
        store.last_alarm = None

    def _plan_program(self, plan_id: int) -> FlightProgram:
        plan = next((p for p in self.store.plans if p["id"] == plan_id), None)
        if plan is None:
            return planner.replan_arrival(self.store.snapshot(), self.store.rules)
        wps = [Waypoint(w["x"], w["y"], w["z"]) for w in plan["waypoints"]]
        return FlightProgram("arrival", wps, source="plan", plan_id=plan_id)

    def run_manual_replan(self, program_type: str, direction: str | None = None,
                          publish: bool = True):
        """人工干预: 强制重规划(不经过风险门)，可指定进出场方向。"""
        store = self.store
        env = store.snapshot()
        prog = (planner.replan_departure(env, store.rules, direction=direction)
                if program_type == "departure"
                else planner.replan_arrival(env, store.rules, direction=direction))
        comp = compliance.check_full(prog, env, store.rules, store.limits)
        sim = simulate.simulate_check(prog, env)
        store.compliance = comp
        store.simulate = sim
        lvl = store.risk_result.level if store.risk_result else risk.SAFE
        if publish:
            store.publish(prog, lvl)
            record_event(store, "procedure", "manual_replan", "info",
                         "人工重规划 %s（方向 %s）" % (program_type, direction or "auto"))
        return prog, comp, sim

    def run_generate(self, program_type: str, direction: str,
                     mode: str = "template"):
        """按方向生成程序: template=方案库直出, dynamic=动态重规划。

        模板方案若未通过合规/仿真（例如该方向有障碍物侵入），自动退回动态重规划，
        保证每个方向都能给出可用程序。
        """
        store = self.store
        if mode == "dynamic":
            prog, comp, sim = self.run_manual_replan(program_type, direction)
            ok = comp.is_pass and sim.is_pass
            return prog, comp, sim, {"mode": "dynamic", "fallback": False,
                                     "reason": "", "available": ok}

        plans = find_plans(store.plans_lib, program_type, direction)
        if not plans:
            prog, comp, sim = self.run_manual_replan(program_type, direction)
            ok = comp.is_pass and sim.is_pass
            return prog, comp, sim, {"mode": "dynamic", "fallback": True,
                                     "reason": "no_plan_for_direction", "available": ok}

        plan = plans[0]
        env = store.snapshot()
        prog = plan_to_program(plan, program_type, env=env)
        comp = compliance.check_full(prog, env, store.rules, store.limits)
        sim = simulate.simulate_check(prog, env)

        if comp.is_pass and sim.is_pass:
            # 航迹选择：模板可用，但若它本身"质量一般"（转弯多/余度小），
            # 就再生成一条动态航迹比一比，而不是无条件优先模板。
            if os.environ.get("TRACK_SELECT", "1") == "1":
                try:
                    from app.services import recommend as rec
                    s_tpl = rec.program_score(prog, comp, sim, env)
                    if s_tpl["available"] and s_tpl["base"] < 0.72:
                        p2, c2, m2 = self.run_manual_replan(program_type, direction, publish=False)
                        s_dyn = rec.program_score(p2, c2, m2, env)
                        win, why = rec.pick_better(s_tpl, s_dyn)
                        store.last_track_pick = {
                            "chosen": "template" if win is s_tpl else "dynamic",
                            "why": why,
                            "candidates": {"template": s_tpl, "dynamic": s_dyn}}
                        if win is s_dyn:
                            p2.std_name = (plan.get("std_name") or "") + "+DYN"
                            lvl0 = store.risk_result.level if store.risk_result else risk.SAFE
                            store.compliance = c2
                            store.simulate = m2
                            store.publish(p2, lvl0)
                            return p2, c2, m2, {"mode": "dynamic", "fallback": True,
                                                "reason": "模板可用但航迹更优: " + why,
                                                "template_reason": "", "available": True,
                                                "track_pick": "dynamic", "why": why}
                except Exception:
                    pass
            store.compliance = comp
            store.simulate = sim
            lvl = store.risk_result.level if store.risk_result else risk.SAFE
            store.publish(prog, lvl)
            tp = getattr(store, "last_track_pick", None) or {}
            return prog, comp, sim, {"mode": "template", "fallback": False,
                                     "reason": "", "available": True,
                                     "track_pick": "template",
                                     "why": tp.get("why", "")}

        # 模板不合格 -> 动态重规划
        reason = comp.err_msg() or sim.err_msg() or "模板校验未通过"
        prog2, comp2, sim2 = self.run_manual_replan(program_type, direction, publish=False)
        prog2.std_name = (plan.get("std_name") or "") + "+DYN"

        # 航迹选择：即使模板可用，也比一比"哪条航迹本身更好"
        # （航程更短 / 超障余度更大 / 转弯更少），而不是无条件优先模板
        if os.environ.get("TRACK_SELECT", "1") == "1":
            try:
                from app.services import recommend as rec
                s_tpl = rec.program_score(prog, comp, sim, env)
                s_dyn = rec.program_score(prog2, comp2, sim2, env)
                win, why = rec.pick_better(s_tpl, s_dyn)
                if win is s_tpl:
                    store.last_track_pick = {"chosen": "template", "why": why,
                                             "candidates": {"template": s_tpl, "dynamic": s_dyn}}
                    store.compliance = comp
                    store.simulate = sim
                    lvl0 = store.risk_result.level if store.risk_result else risk.SAFE
                    store.publish(prog, lvl0)
                    return prog, comp, sim, {"mode": "template", "fallback": False,
                                             "reason": "", "available": True,
                                             "track_pick": "template", "why": why}
                store.last_track_pick = {"chosen": "dynamic", "why": why,
                                         "candidates": {"template": s_tpl, "dynamic": s_dyn}}
            except Exception:
                pass

        ok = comp2.is_pass and sim2.is_pass
        if ok:
            # 动态方案可用才发布，避免把不可飞的方向写进"当前程序"
            lvl = store.risk_result.level if store.risk_result else risk.SAFE
            store.publish(prog2, lvl)
            # 原因只说明"模板为什么被替换"，不再当成最终结论
            note = "模板被替换: " + reason
        else:
            store.compliance = comp2
            store.simulate = sim2
            # 最终不可用的原因必须来自**重规划之后**的方案，而不是模板阶段
            note = comp2.err_msg() or sim2.err_msg() or reason
            store.last_alarm = "该方向不可用: " + note
        return prog2, comp2, sim2, {"mode": "dynamic", "fallback": True,
                                    "reason": note if not ok else "",
                                    "template_reason": reason,
                                    "plan_id": plan.get("id"),
                                    "available": ok}

    # ------------------------------------------------------------------ 循环
    async def loop(self):
        while self.running:
            try:
                await asyncio.to_thread(self.run_cycle)
            except Exception:  # noqa: BLE001
                log.exception("调度周期异常")
            await asyncio.sleep(self.store.settings.dispatch_interval)

    def start(self):
        self.running = True
        self._task = asyncio.create_task(self.loop())

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


# ------------------------------------------------------------------ 自动方向推荐
def auto_recommend(service, program_type: str = "arrival", margin: float = 0.05) -> dict:
    """按推荐结果自动切方向：推荐方向明显更优时才切换并推送。

    为什么要有它
    ------------
    现在的流程是"人点方向 → 生成 → 发布"。环境一变（风向转了、限飞区更新），
    人来不及反应。这里每周期算一次推荐，只有**明显更优**才自动切，
    避免在两个同分方向之间来回跳（滞回）。
    """
    from app.plans_library import DIRECTIONS
    from app.services import recommend as rec

    store = service.store
    env = store.snapshot()
    rows = []
    for d, bearing in DIRECTIONS.items():
        prog, comp, sim, meta = service.run_generate(program_type, d, "template")
        hdg = (float(bearing) + 180.0) % 360.0 if program_type != "departure" else float(bearing)
        row = rec.score_one(d, float(bearing), prog, comp, sim, env.meteo, hdg)
        row["entry_heading"] = hdg
        row["program"] = prog
        rows.append(row)

    ranked = rec.rank(rows, None)
    best = ranked[0] if ranked else None
    if not best or not best.get("available"):
        return {"switched": False, "reason": "无可用方向"}

    # "当前方向"以引擎自己记住的为准：publish 之后 current_program.direction
    # 未必被写回（动态重规划的返回体里没有这个字段），否则会每个周期重复切换
    cur_dir = getattr(store, "last_auto_dir", None)
    if not cur_dir and store.current_program is not None:
        cur_dir = getattr(store.current_program, "direction", None)
    cur = next((r for r in ranked if r["direction"] == cur_dir), None)
    cur_score = cur["score"] if cur and cur.get("available") else 0.0

    if cur_dir == best["direction"]:
        return {"switched": False, "recommend": best["direction"], "score": best["score"],
                "reason": "当前方向已是最优"}

    if best["score"] - cur_score < margin:
        return {"switched": False, "recommend": best["direction"], "score": best["score"],
                "current": cur_dir, "current_score": cur_score,
                "reason": "优势不足 %.2f，保持当前方向（滞回）" % margin}

    # 切换并发布（走正常发布链路，推送服务会自动带上新程序）
    prog = best["program"]
    try:
        prog.direction = best["direction"]
    except Exception:
        pass
    store.last_auto_dir = best["direction"]
    lvl = store.risk_result.level if store.risk_result else risk.SAFE
    store.publish(prog, lvl)
    store.last_alarm = None
    return {"switched": True, "from": cur_dir, "to": best["direction"],
            "score": best["score"], "prev_score": cur_score,
            "reason": "；".join(best["reasons"])}
