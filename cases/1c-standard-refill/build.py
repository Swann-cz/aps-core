"""生成 1c 标准复线算例文件（Claude 维护，rev 182–187）。手算见 README.md。

python cases/1c-standard-refill/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from casegen import TARGET_1D, ZERO, build_plan, days_between, dump, engine_days, full_flows, single_model_input  # noqa: E402

DAYS = days_between(dt.date(2026, 3, 23), dt.date(2026, 3, 27))  # 周一至周五
D1, D2, D3 = DAYS[0], DAYS[1], DAYS[2]
# 标准停线水位（= 1c-standard-clear 停线时的日末）：焊装、WBS 空，PS 停前目标 91，PBS、总装在目标
INV0 = {"BS1": 0, "BS2": 0, "WBS": 0, "PS": 91, "PBS": 45, "AS_MAIN": 100, "AS_FIN": 80}
WS = {DAYS[-1]: 236}


def working(d: dt.date) -> bool:
    return d.weekday() < 5


def main() -> None:
    flows = full_flows(DAYS, working)
    off = (0, 0)
    flows[D1].update({"BS1": (80, 10), "PS": off, "AS_MAIN": off, "AS_FIN": off})   # BS1 补满 70，多的 10 给 WBS
    flows[D2].update({"PS": (55, 0), "AS_MAIN": off, "AS_FIN": off})               # WBS 补满 35，多的 55 给 PS；PS 146 未满不出车
    flows[D3].update({"PS": (80, 76), "AS_MAIN": (76, 76), "AS_FIN": (76, 76)})   # PS 补满 150，多的 76 往下流
    plan = build_plan(DAYS, flows, INV0, WS, [])

    # 反例 1：首日焊装只投 48、不出车（复线未满产，C14）
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[D1].update({"BS1": (48, 0)})
    f1[D2].update({"BS1": (80, 58), "PS": (23, 0)})
    f1[D3].update({"PS": (80, 44), "AS_MAIN": (44, 44), "AS_FIN": (44, 44)})
    under = build_plan(DAYS, f1, INV0, {DAYS[-1]: 204}, [])
    under["findings"] = ["反例：复线首日焊装只投 48、不出车"]

    # 反例 2：首日完成线没有来车，单独出 3 台（C17）
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[D1].update({"AS_FIN": (0, 3)})
    f2[D3].update({"AS_FIN": (76, 73)})
    lone = build_plan(DAYS, f2, INV0, WS, [])
    lone["findings"] = ["反例：复线首日完成线无投入出 3 台"]

    phases = {D1.isoformat(): "REFILL", D2.isoformat(): "REFILL", D3.isoformat(): "REFILL",
              DAYS[3].isoformat(): "NORMAL", DAYS[4].isoformat(): "NORMAL"}
    expected = {
        "case": "1c-standard-refill",
        "spec": "CORE_MODEL §5 补线行（期初低于目标、逐级补满，B13；补线按满产推进，rev 182）、C14、C17",
        "engine": {"status": "FEASIBLE", "objective": ZERO, "stop_list": [], "days": engine_days(plan)},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": ZERO, "phases": phases},
        "counter_plans": [
            {"file": "counter/refill-underfeed.plan.json", "why": "复线首日焊装只投 48、不出车",
             "judge": {"verdict": "REJECT", "rules": ["C11", "C14"]}, "engine_must_differ": True},
            {"file": "counter/lone-output.plan.json", "why": "复线首日完成线无投入单独出 3 台",
             "judge": {"verdict": "REJECT", "rules": ["C17", "REFILL"]}, "engine_must_differ": True},
        ],
    }
    dump(HERE / "input.json", single_model_input(DAYS, working, dict(TARGET_1D), INV0, {"2026-03": 236}, WS))
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "refill-underfeed.plan.json", under)
    dump(HERE / "counter" / "lone-output.plan.json", lone)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
