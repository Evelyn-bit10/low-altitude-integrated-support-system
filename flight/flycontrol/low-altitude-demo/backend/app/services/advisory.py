"""Read-only candidate calculations for advisory use."""
from __future__ import annotations

import os

from ..engines import compliance, planner, simulate
from ..plans_library import DIRECTIONS, find_plans, plan_to_program
from . import recommend


def _program_score(program, comp, sim, env):
    from types import SimpleNamespace

    checks = [{"name": item.name, "margin": item.margin} for item in comp.checks]
    return recommend.program_score(program, SimpleNamespace(is_pass=comp.is_pass, checks=checks), sim, env)


def calculate_candidate(env, rules, plans_lib, program_type, direction):
    """Calculate and check one candidate without accessing or changing a Store."""
    def dynamic():
        program = (planner.replan_departure(env, rules, direction=direction)
                   if program_type == "departure"
                   else planner.replan_arrival(env, rules, direction=direction))
        return (program, compliance.check_full(program, env, rules, env.limits),
                simulate.simulate_check(program, env))

    plans = find_plans(plans_lib, program_type, direction)
    if not plans:
        program, comp, sim = dynamic()
        return program, comp, sim, {"mode": "dynamic", "fallback": True,
                                    "reason": "no_plan_for_direction"}

    plan = plans[0]
    program = plan_to_program(plan, program_type, env=env)
    comp = compliance.check_full(program, env, rules, env.limits)
    sim = simulate.simulate_check(program, env)
    if comp.is_pass and sim.is_pass:
        if os.environ.get("TRACK_SELECT", "1") == "1":
            template_score = _program_score(program, comp, sim, env)
            if template_score["available"] and template_score["base"] < 0.72:
                candidate, candidate_comp, candidate_sim = dynamic()
                dynamic_score = _program_score(candidate, candidate_comp, candidate_sim, env)
                winner, why = recommend.pick_better(template_score, dynamic_score)
                if winner is dynamic_score:
                    candidate.std_name = (plan.get("std_name") or "") + "+DYN"
                    return candidate, candidate_comp, candidate_sim, {
                        "mode": "dynamic", "fallback": True, "reason": why}
        return program, comp, sim, {"mode": "template", "fallback": False, "reason": ""}

    reason = comp.err_msg() or sim.err_msg() or "模板校验未通过"
    program, comp, sim = dynamic()
    program.std_name = (plan.get("std_name") or "") + "+DYN"
    return program, comp, sim, {"mode": "dynamic", "fallback": True, "reason": reason}


def rank_candidates(env, rules, plans_lib, program_type):
    rows = []
    for direction, bearing in DIRECTIONS.items():
        program, comp, sim, meta = calculate_candidate(
            env, rules, plans_lib, program_type, direction)
        heading = (float(bearing) + 180.0) % 360.0 if program_type == "arrival" else float(bearing)
        row = recommend.score_one(direction, float(bearing), program, comp, sim, env.meteo, heading)
        row["entry_heading"] = heading
        row["mode"] = meta["mode"]
        row["fallback"] = meta["fallback"]
        rows.append(row)
    ranked = recommend.rank(rows)
    return [{key: row[key] for key in ("direction", "score", "available", "metrics", "reasons", "mode", "fallback")}
            for row in ranked]
