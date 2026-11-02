"""生成 1c 长停算例文件（Claude 维护）。手算过程见 README.md。

python cases/1c-long-stop/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

START, END = dt.date(2026, 2, 2), dt.date(2026, 3, 6)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
HOLIDAY = (dt.date(2026, 2, 14), dt.date(2026, 3, 1))  # 含周末共 16 天
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
TARGET = {"BS1": 67, "BS2": 67, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
INV0 = {"BS1": 67, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
CLEAR1, CLEAR2 = dt.date(2026, 2, 12), dt.date(2026, 2, 13)  # CLEAR2 同时是 PS 停前日
REFILL1, REFILL2 = dt.date(2026, 3, 2), dt.date(2026, 3, 3)
WS = {dt.date(2026, 2, 13): 800, dt.date(2026, 3, 6): 240}


def working(d: dt.date) -> bool:
    return d.weekday() < 5 and not (HOLIDAY[0] <= d <= HOLIDAY[1])


def build_input() -> dict:
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": START.isoformat(), "end": END.isoformat()},
        "calendar": [{"date": d.isoformat(), "is_working_capable": working(d)} for d in DAYS],
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8}, "PS": {"jph": 10},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 69}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": 14}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {"A": {"2026-02": 800, "2026-03": 240}},
                   "WS_daily": {"A": {d.isoformat(): q for d, q in WS.items()}}},
        "initial": {"wip": {n: {"A": q} for n, q in INV0.items()}, "fin": {"A": 0}},
        "wip_targets": TARGET,
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def optimal_flows() -> dict:
    """手算的唯一最优 {日期: {车间: (IN, OUT)}}，见 README。"""
    flows = {}
    for d in DAYS:
        f = {w: (0, 0) for w in WORKSHOPS}
        if working(d):
            f.update({w: (80, 80) for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")})
        if d == CLEAR1:
            f["BS1"] = (0, 67)
        if d == CLEAR2:
            f["BS1"], f["PS"] = (0, 0), (24, 80)
        if d == REFILL1:
            f.update({"BS1": (80, 13), "PS": (0, 0), "AS_MAIN": (0, 0), "AS_FIN": (0, 0)})
        if d == REFILL2:
            f.update({"BS1": (80, 80), "PS": (56, 0), "AS_MAIN": (0, 0), "AS_FIN": (0, 0)})
        flows[d] = f
    return flows


def build_plan(flows: dict) -> dict:
    inv = dict(INV0)
    inv.setdefault("BS2", 0)
    net, days = 0, []
    for d in DAYS:
        f = flows[d]
        bod = dict(inv)
        for w in WORKSHOPS:
            inv[w] += f[w][0] - f[w][1]
        inv["WBS"] += f["BS1"][1] + f["BS2"][1] - f["PS"][0]
        inv["PBS"] += f["PS"][1] - f["AS_MAIN"][0]
        assert f["AS_FIN"][0] == f["AS_MAIN"][1], d
        assert all(v >= 0 for v in inv.values()), (d, inv)
        fok = f["AS_FIN"][1]
        net += fok - WS.get(d, 0)
        ws = {}
        for w in WORKSHOPS:
            active = bool(f[w][0] or f[w][1])
            ws[w] = {"mode": "SINGLE_8H" if active else "OFF", "hours": 8 if active else 0,
                     "in": {"A": f[w][0]} if f[w][0] else {},
                     "out": {"A": f[w][1]} if f[w][1] else {}}
        days.append({"date": d.isoformat(), "workshops": ws,
                     "bod": {n: {"A": q} for n, q in bod.items() if q},
                     "eod": {n: {"A": q} for n, q in inv.items() if q},
                     "fok": {"A": fok} if fok else {}, "fin": {"A": net} if net > 0 else {},
                     "bl": {"A": -net} if net < 0 else {}, "phase": "NORMAL"})
    return {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": STOP_LIST, "objective": {"levels": []}, "findings": []}


def phase_of(d: dt.date) -> str:
    if d == CLEAR1:
        return "PS_PRE_STOP+BS_CLEAR"  # rev 185 起首个 BS 清线日即进入 PS 停前降库
    if d == CLEAR2:
        return "PS_PRE_STOP+BS_CLEAR"
    if HOLIDAY[0] <= d <= HOLIDAY[1]:
        return "STOP"
    if d in (REFILL1, REFILL2):
        return "REFILL"
    return "NORMAL"


ZERO = {"L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0}
STOP_LIST = [{"start": HOLIDAY[0].isoformat(), "end": HOLIDAY[1].isoformat(), "length": 16,
              "pre_stop_date": CLEAR2.isoformat(), "target": 91, "source": "DEFAULT"}]


def main() -> None:
    flows = optimal_flows()
    plan = build_plan(flows)

    # 反例 1：WBS 没清空（02-13 PS 只出不进，WBS 留 24 台过长假）→ BS_CLEAR + C7（胶龄 19 天 > 14）
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[CLEAR2].update({"PS": (0, 56), "AS_MAIN": (56, 56), "AS_FIN": (56, 56)})
    f1[REFILL1].update({"BS1": (80, 13)})
    f1[REFILL2].update({"PS": (80, 24), "AS_MAIN": (24, 24), "AS_FIN": (24, 24)})
    dirty = build_plan(f1)
    dirty["findings"] = ["反例：长停前 WBS 留 24 台未清"]

    # 反例 2：复工首日 BS1 没补到 67 就向 WBS 出车 80 → REFILL
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[REFILL1].update({"BS1": (80, 80), "PS": (43, 0)})
    f2[REFILL2].update({"BS1": (80, 13), "PS": (13, 0)})
    leak = build_plan(f2)
    leak["findings"] = ["反例：03-02 BS1 日末 0 < 67 仍向 WBS 出车"]

    phases = {d.isoformat(): phase_of(d) for d in DAYS}
    keys = ("date", "workshops", "eod", "fok", "fin", "bl")
    expected = {
        "case": "1c-long-stop",
        "spec": "CORE_MODEL §8 1c；§5 BS 清线、PS 停前日（长停 91）、停线、补线、阶段重叠（rev 153）",
        "engine": {"status": "FEASIBLE", "compare": "none", "objective": {**ZERO, "L2": 1},
                   "stop_list": STOP_LIST},  # 02-12/02-13 BS1 出车怎么分不唯一，见 README 末节
        "judge_on_engine": {"verdict": "ACCEPT", "objective": {**ZERO, "L2": 1}, "phases": phases},
        "counter_plans": [
            {"file": "counter/wbs-not-cleared.plan.json",
             "why": "长停前 WBS 没清到 0，24 台车在 WBS 里过了 16 天假",
             "judge": {"verdict": "REJECT", "rules": ["BS_CLEAR", "C7", "PS_PRE_STOP"]}, "engine_must_differ": True},
            {"file": "counter/refill-bs-leak.plan.json",
             "why": "补线首日 BS1 没补到目标就向下游出车",
             "judge": {"verdict": "REJECT", "rules": ["REFILL"]}, "engine_must_differ": True},
        ],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "wbs-not-cleared.plan.json", dirty)
    dump(HERE / "counter" / "refill-bs-leak.plan.json", leak)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
