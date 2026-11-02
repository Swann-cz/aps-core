"""算例构建的共用部分（Claude 维护）：单车型 A 的输入骨架和“逐日流量 → 计划”。

各算例的 build.py 用 sys.path 引入本文件。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
TARGET_1D = {"BS1": 70, "BS2": 130, "WBS": 35, "PS": 150, "PBS": 45, "AS_MAIN": 100, "AS_FIN": 80}
RULES = {"ps_stop_min_days": 3, "ps_long_stop_days": 15, "ps_pre_stop_target_short": 131,
         "ps_pre_stop_target_long": 91, "monthly_band_ratio": 0.1}
ZERO = {"L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0}


def days_between(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(n) for n in range((end - start).days + 1)]


def single_model_input(days: list[dt.date], working, targets: dict, inv0: dict, pr: dict,
                       ws: dict, glue: int = 15, extra_calendar: list | None = None) -> dict:
    calendar = [{"date": d.isoformat(), "is_working_capable": working(d)} for d in days]
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": days[0].isoformat(), "end": days[-1].isoformat()},
        "calendar": calendar + (extra_calendar or []),
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8}, "PS": {"jph": 10},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 69}, "PBS": {"cap_max": 70}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": glue}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {"A": pr}, "WS_daily": {"A": {d.isoformat(): q for d, q in ws.items()}}},
        "initial": {"wip": {n: {"A": q} for n, q in inv0.items() if q}, "fin": {"A": 0}},
        "wip_targets": targets,
        "wbs_hi": None,
        "conditions": [],
        "rules": RULES,
    }


def full_flows(days, working, rate: int = 80) -> dict:
    """每个可生产日 BS1、PS、总装都 rate/rate，其余为 0；算例再按日覆盖。"""
    flows = {}
    for d in days:
        f = {w: (0, 0) for w in WORKSHOPS}
        if working(d):
            f.update({w: (rate, rate) for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")})
        flows[d] = f
    return flows


def build_plan(days, flows: dict, inv0: dict, ws: dict, stop_list: list) -> dict:
    inv = {n: inv0.get(n, 0) for n in ("BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")}
    net, out = 0, []
    for d in days:
        f = flows[d]
        bod = dict(inv)
        for w in WORKSHOPS:
            inv[w] += f[w][0] - f[w][1]
        inv["WBS"] += f["BS1"][1] + f["BS2"][1] - f["PS"][0]
        inv["PBS"] += f["PS"][1] - f["AS_MAIN"][0]
        assert f["AS_FIN"][0] == f["AS_MAIN"][1], d
        assert all(v >= 0 for v in inv.values()), (d, inv)
        fok = f["AS_FIN"][1]
        net += fok - ws.get(d, 0)
        row = {}
        for w in WORKSHOPS:
            active = bool(f[w][0] or f[w][1])
            row[w] = {"mode": "SINGLE_8H" if active else "OFF", "hours": 8 if active else 0,
                      "in": {"A": f[w][0]} if f[w][0] else {},
                      "out": {"A": f[w][1]} if f[w][1] else {}}
        out.append({"date": d.isoformat(), "workshops": row,
                    "bod": {n: {"A": q} for n, q in bod.items() if q},
                    "eod": {n: {"A": q} for n, q in inv.items() if q},
                    "fok": {"A": fok} if fok else {}, "fin": {"A": net} if net > 0 else {},
                    "bl": {"A": -net} if net < 0 else {}, "phase": "NORMAL"})
    return {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": out,
            "stop_list": stop_list, "objective": {"levels": []}, "findings": []}


def engine_days(plan: dict) -> list[dict]:
    keys = ("date", "workshops", "eod", "fok", "fin", "bl")
    return [{k: day[k] for k in keys} for day in plan["days"]]


def dump(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
