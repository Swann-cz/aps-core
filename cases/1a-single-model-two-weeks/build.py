"""生成 1a 算例文件（Claude 维护）。手算过程见 README.md。

python cases/1a-single-model-two-weeks/build.py
产出：input.json、expected.json、counter/bs-overfeed-40.plan.json
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

START, END = dt.date(2026, 3, 2), dt.date(2026, 3, 11)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
TARGET = {"BS1": 69, "BS2": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
INV0 = {"BS1": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}


def working(d: dt.date) -> bool:
    return d.weekday() < 5


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
        "demand": {"PR": {"A": {"2026-03": 600}}, "WS_daily": {"A": {"2026-03-11": 600}}},
        "initial": {"wip": {n: {"A": q} for n, q in INV0.items()}, "fin": {"A": 0}},
        "wip_targets": TARGET,
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def flow_of(d: dt.date) -> int:
    """手算的唯一最优：工作日满产 80，最后一天 03-11 尾差 40，周末 0。"""
    if not working(d):
        return 0
    return 40 if d == END else 80


def build_plan(bs1_in_override: dict[dt.date, int] | None = None) -> dict:
    """按 IO_CONTRACT §3 写出完整计划；bs1_in_override 用于构造反例。"""
    override = bs1_in_override or {}
    inv = {n: INV0.get(n, 0) for n in NODES}
    fin = 0
    days = []
    for d in DAYS:
        f = flow_of(d)
        ins = {w: f for w in WORKSHOPS}
        outs = {w: f for w in WORKSHOPS}
        ins["BS2"] = outs["BS2"] = 0
        ins["BS1"] = override.get(d, ins["BS1"])
        bod = dict(inv)
        # 车间：EOD = BOD + IN − OUT；缓冲：IN = 上游车间 OUT，OUT = 下游车间 IN
        for w in WORKSHOPS:
            inv[w] += ins[w] - outs[w]
        inv["WBS"] += outs["BS1"] + outs["BS2"] - ins["PS"]
        inv["PBS"] += outs["PS"] - ins["AS_MAIN"]
        fok = outs["AS_FIN"]
        fin += fok - (600 if d == END else 0)
        mode = "SINGLE_8H" if working(d) else "OFF"
        ws = {}
        for w in WORKSHOPS:
            m = "OFF" if w == "BS2" else mode
            ws[w] = {"mode": m, "hours": 8 if m == "SINGLE_8H" else 0,
                     "in": {"A": ins[w]} if ins[w] else {},
                     "out": {"A": outs[w]} if outs[w] else {}}
        days.append({
            "date": d.isoformat(),
            "workshops": ws,
            "bod": {n: {"A": q} for n, q in bod.items() if q},
            "eod": {n: {"A": q} for n, q in inv.items() if q},
            "fok": {"A": fok},
            "fin": {"A": fin},
            "bl": {},
            "phase": "NORMAL",
        })
    return {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}


ZERO = {"L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0}


def main() -> None:
    inp = build_input()
    plan = build_plan()
    counter = build_plan({END: 80})  # 03-11 焊装照常投 80、只出 40：BS1 多留 40 台
    counter["findings"] = ["反例：焊装 8 天全部满产 640 台，多出的 40 台留在 BS1"]

    expected = {
        "case": "1a-single-model-two-weeks",
        "spec": "CORE_MODEL §8 1a",
        "engine": {
            "status": "FEASIBLE",
            "objective": ZERO,
            "stop_list": [],
            "days": [{k: day[k] for k in ("date", "workshops", "eod", "fok", "fin", "bl")}
                     for day in plan["days"]],
        },
        "judge_on_engine": {
            "verdict": "ACCEPT",
            "objective": ZERO,
            "phases": {day["date"]: "NORMAL" for day in plan["days"]},
        },
        "counter_plans": [{
            "file": "counter/bs-overfeed-40.plan.json",
            "why": "03-11 BS1 日末 109 超过车间物理上限（暂取目标 69，rev 173）",
            "judge": {"verdict": "REJECT", "rules": ["C6"]},
            "engine_must_differ": True,
        }],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", inp)
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "bs-overfeed-40.plan.json", counter)


if __name__ == "__main__":
    main()
