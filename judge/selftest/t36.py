"""T-36（36-J）：合并长停里的自建空闲不算清线空档（CORE_MODEL rev 200 §5 BS 清线行）。

判定器改动（judge/constraints.py check_bs_clear 第 3 项）：清空日后到零流窗口结束，本线
空着的工作日，只有当天 PS 仍在生产（IN 或 OUT > 0）才报「空档」BS_CLEAR；零流窗口由
日历假期与自建空闲合并而成时，窗口内全厂都停（PS 也无流）的工作日算停线、不算清空后
空档。

自检场景（合成单车型 A、绑定 BS1、胶龄 14）：清线后进入 15 天合并长停 = 10 天日历假期
（02-13..02-22，is_working_capable=false）+ 5 天自建空闲工作日（02-23..02-27，
is_working_capable=true、全厂 OFF）。清空日 02-12（BS1 EOD=0、WBS A EOD=0）紧贴停线。
自建空闲工作日全厂停 → 不报 BS_CLEAR 空档（rev 200）；改动前这些工作日会被判为空档。

注：「清空后 PS 仍生产、本线空着仍报 BS_CLEAR」由 selftest/__main__.py 的
_run_s1c_long_cases 第 2 份用例（02-12 清空、02-13 空档工作日、PS 仍 OUT=80）继续覆盖。
"""
from __future__ import annotations

import datetime
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel

ROOT = Path(__file__).resolve().parents[2]

WS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")

# 正常生产日 02-02..02-10（9 天）
NORM_DAYS = tuple(
    (datetime.date(2026, 2, 2) + datetime.timedelta(days=i)).isoformat()
    for i in range(9)
)
CLEAR_D1 = "2026-02-11"  # 清线第 1 天：BS1(0,67)、PS 80、AS 80
CLEAR_D2 = "2026-02-12"  # 清线第 2 天 = PS 停前日：BS1(0,0)、PS(24,80)、AS 80 → PS EOD 91
HOLIDAY = tuple(
    (datetime.date(2026, 2, 13) + datetime.timedelta(days=i)).isoformat()
    for i in range(10)
)  # 02-13..02-22 日历假期
SELF_IDLE = tuple(
    (datetime.date(2026, 2, 23) + datetime.timedelta(days=i)).isoformat()
    for i in range(5)
)  # 02-23..02-27 自建空闲工作日（全厂 OFF，与假期合并成 15 天长停）


def _make_input() -> dict:
    """合成输入：单车型 A、绑定 BS1、胶龄 14；各车间产能 80；PS 物理上限放宽到 200。

    停线窗口 = 02-13..02-27（10 天假期 + 5 天自建空闲，全厂 PS 零流合并）≥ 15（长停，
    停前目标 91）且 ≥ 胶龄 14（BS 清线）。horizon 收尾到自建空闲末日 02-27，避开复工补线，
    聚焦「清空后空档」判定。
    """
    cal = []
    for ds in NORM_DAYS + (CLEAR_D1, CLEAR_D2):
        cal.append({"date": ds, "is_working_capable": True})
    for ds in HOLIDAY:
        cal.append({"date": ds, "is_working_capable": False})
    for ds in SELF_IDLE:
        cal.append({"date": ds, "is_working_capable": True})
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": "2026-02-02", "end": SELF_IDLE[-1]},
        "calendar": cal,
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8},
                          "PS": {"jph": 10, "cap_max": 200},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 120}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": 14}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {"A": {"2026-02": 2000}},
                   "WS_daily": {"A": {CLEAR_D2: 2000}}},
        "initial": {"wip": {"BS1": {"A": 67}, "WBS": {"A": 37}, "PS": {"A": 147},
                            "PBS": {"A": 80}, "AS_MAIN": {"A": 100}, "AS_FIN": {"A": 40}},
                    "fin": {"A": 0}},
        "wip_targets": {"BS1": 67, "BS2": 67, "WBS": 37, "PS": 147,
                        "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40},
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def _make_day(ds: str, flows: dict) -> dict:
    workshops = {}
    for w in WS:
        spec = flows.get(w, 0)
        inn, out = spec if isinstance(spec, tuple) else (spec, spec)
        active = inn > 0 or out > 0
        workshops[w] = {"mode": "SINGLE_8H" if active else "OFF",
                        "hours": 8 if active else 0,
                        "in": {"A": inn} if inn else {},
                        "out": {"A": out} if out else {}}
    return {"date": ds, "workshops": workshops}


def _build(inp: InputModel, flows: dict) -> dict:
    days = [_make_day(d.isoformat(), flows.get(d.isoformat(), {})) for d in inp.dates]
    plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}
    j = Judge(inp, plan)
    j.recompute_inventory()
    for d in plan["days"]:
        ds = d["date"]
        for key in ("bod", "eod"):
            d[key] = {n: {m: v for m, v in per.items() if v}
                      for n, per in getattr(j, key)[ds].items() if any(per.values())}
        for key in ("fok", "fin", "bl"):
            d[key] = {m: v for m, v in getattr(j, key)[ds].items() if v}
    return plan


def _judge(inp: InputModel, plan: dict) -> Judge:
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


def run_t36_cases() -> tuple[int, int]:
    failures: list[str] = []

    inp = InputModel(_make_input())
    flows: dict[str, dict] = {}
    for ds in NORM_DAYS:
        flows[ds] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    flows[CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    flows[CLEAR_D2] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": 80}
    # 02-13..02-27 全厂零流（假期 + 自建空闲工作日），无逐日 flow。

    j = _judge(inp, _build(inp, flows))
    got = sorted({e.rule for e in j.hard_errors})
    bs_clear_gap = [e for e in j.hard_errors
                    if e.rule == "BS_CLEAR" and e.date in SELF_IDLE]
    ok = not j.hard_errors and not bs_clear_gap and len(j.bs_clear_events) == 1
    if not ok:
        failures.append("T-36 合并长停内自建空闲误报 BS_CLEAR 空档")
    print(f"[{'PASS' if ok else 'FAIL'}] T-36 合并长停内自建空闲全厂停（不报 BS_CLEAR）")
    print("   预期条款      : 无（ACCEPT），02-23..02-27 无 BS_CLEAR 空档")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print(f"   清线事件      : {len(j.bs_clear_events)} 次")
    print()

    total = 1
    print(f"== T-36 结果：{total - len(failures)}/{total} ==")
    return total, len(failures)


if __name__ == "__main__":
    total, failed = run_t36_cases()
    raise SystemExit(bool(failed))
