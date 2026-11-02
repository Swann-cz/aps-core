"""生成 1c 短停算例文件（Claude 维护）。手算过程见 README.md。

python cases/1c-short-stop/build.py
产出：input.json、expected.json、counter/*.plan.json
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

START, END = dt.date(2026, 3, 30), dt.date(2026, 4, 10)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
HOLIDAYS = {dt.date(2026, 4, 2), dt.date(2026, 4, 3)}
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
TARGET = {"BS1": 69, "BS2": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
INV0 = {"BS1": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
PRE_STOP, STOP_START, STOP_END, REFILL = (dt.date(2026, 4, 1), dt.date(2026, 4, 2),
                                          dt.date(2026, 4, 5), dt.date(2026, 4, 6))
PR = 624


def working(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


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
        "demand": {"PR": {"A": {"2026-03": 160, "2026-04": PR - 160}},
                   "WS_daily": {"A": {"2026-03-31": 160, END.isoformat(): PR - 160}}},
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
            if d == PRE_STOP:  # PS 只在这天从 147 降到 131：少进 16，照常出 80
                f["BS1"], f["PS"] = (64, 64), (64, 80)
            if d == REFILL:  # 复工正常日 PS 须回到 147：进 80、出 64，下游跟着 64（C15 镜像）
                f["PS"] = (80, 64)
                f["AS_MAIN"] = f["AS_FIN"] = (64, 64)
        flows[d] = f
    return flows


def build_plan(flows: dict) -> dict:
    inv = dict(INV0)
    inv.setdefault("BS2", 0)
    net, days = 0, []
    ws_by_day = {dt.date.fromisoformat(k): v for k, v in build_input()["demand"]["WS_daily"]["A"].items()}
    for d in DAYS:
        f = flows[d]
        bod = dict(inv)
        for w in WORKSHOPS:
            inv[w] += f[w][0] - f[w][1]
        inv["WBS"] += f["BS1"][1] + f["BS2"][1] - f["PS"][0]
        inv["PBS"] += f["PS"][1] - f["AS_MAIN"][0]
        assert f["AS_FIN"][0] == f["AS_MAIN"][1], d
        fok = f["AS_FIN"][1]
        net += fok - ws_by_day.get(d, 0)
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
            "stop_list": [], "objective": {"levels": []}, "findings": []}


def phase_of(d: dt.date) -> str:
    if d == PRE_STOP:
        return "PS_PRE_STOP"
    if STOP_START <= d <= STOP_END:
        return "STOP"
    return "NORMAL"  # 短停不补线：复工日 04-06 即为正常日（2026-10-24 按业务答复）


ZERO = {"L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0}
STOP_LIST = [{"start": STOP_START.isoformat(), "end": STOP_END.isoformat(), "length": 4,
              "pre_stop_date": PRE_STOP.isoformat(), "target": 131, "source": "DEFAULT"}]


def main() -> None:
    flows = optimal_flows()
    plan = build_plan(flows)
    plan["stop_list"] = STOP_LIST

    # 反例 1：PS 提前一天开始降（03-31 就降到 139，04-01 再降到 131）→ C8（03-31 是 3 月最后生产日，BS1 少投按 C14 例外合法；PS 少进因 WBS 在目标属 C15 镜像）
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[dt.date(2026, 3, 31)].update({"BS1": (72, 72), "PS": (72, 80)})
    f1[PRE_STOP].update({"BS1": (72, 72), "PS": (72, 80)})
    early = build_plan(f1)
    early["stop_list"] = STOP_LIST
    early["findings"] = ["反例：PS 在 03-31 就降到 139，停前日前低于正常下限"]

    # 反例 2：复工日 PS 停在 131 照常供 80，次日才补回 → 正常日 PS 低于目标（C8）
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[REFILL].update({"PS": (80, 80), "AS_MAIN": (80, 80), "AS_FIN": (80, 80)})
    f2[dt.date(2026, 4, 7)].update({"PS": (80, 64), "AS_MAIN": (64, 64), "AS_FIN": (64, 64)})
    leak = build_plan(f2)
    leak["stop_list"] = STOP_LIST
    leak["findings"] = ["反例：04-06 PS 日末 131 < 147，复工正常日低于下限"]

    phases = {d.isoformat(): phase_of(d) for d in DAYS}
    keys = ("date", "workshops", "eod", "fok", "fin", "bl")
    expected = {
        "case": "1c-short-stop",
        "spec": "CORE_MODEL §8 1c；§5 PS 停前日、停线（短停不补线，rev 153）",
        "engine": {"status": "FEASIBLE", "objective": ZERO, "stop_list": STOP_LIST,
                   "days": [{k: day[k] for k in keys} for day in plan["days"]]},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": ZERO, "phases": phases},
        "counter_plans": [
            {"file": "counter/ps-early-drop.plan.json",
             "why": "PS 在停前日之前就低于正常下限",
             "judge": {"verdict": "REJECT", "rules": ["C8"]}, "engine_must_differ": True},
            {"file": "counter/ps-not-restored.plan.json",
             "why": "短停复工即正常日，PS 当天须回到目标",
             "judge": {"verdict": "REJECT", "rules": ["C8"]}, "engine_must_differ": True},
        ],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "ps-early-drop.plan.json", early)
    dump(HERE / "counter" / "ps-not-restored.plan.json", leak)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
