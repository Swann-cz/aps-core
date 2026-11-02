"""生成 1d 期初补线算例文件（Claude 维护）。手算过程见 README.md。

python cases/1d-initial-refill/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from casegen import TARGET_1D, ZERO, build_plan, days_between, dump, engine_days, full_flows, single_model_input  # noqa: E402

DAYS = days_between(dt.date(2026, 1, 1), dt.date(2026, 1, 9))
HOLIDAY = (dt.date(2026, 1, 1), dt.date(2026, 1, 4))  # 01-03、01-04 是周末
DAY1, DAY2 = dt.date(2026, 1, 5), dt.date(2026, 1, 6)
INV0 = {"BS1": 69, "WBS": 30, "PS": 140, "PBS": 50, "AS_MAIN": 100, "AS_FIN": 100}  # 9-15 输入的真实期初
WS = {dt.date(2026, 1, 9): 400}
STOP_LIST = [{"start": "2026-01-01", "end": "2026-01-04", "length": 4,
              "pre_stop_date": None, "target": None, "source": "DEFAULT"}]


def working(d: dt.date) -> bool:
    return d.weekday() < 5 and not (HOLIDAY[0] <= d <= HOLIDAY[1])


def main() -> None:
    flows = full_flows(DAYS, working)
    flows[DAY1].update({"BS1": (80, 79), "PS": (74, 64), "AS_MAIN": (68, 68), "AS_FIN": (68, 80)})
    flows[DAY2].update({"AS_MAIN": (72, 72), "AS_FIN": (72, 80)})
    flows[DAYS[-1]].update({"BS1": (71, 71), "PS": (71, 71)})  # 段末尾差日（C14）
    plan = build_plan(DAYS, flows, INV0, WS, STOP_LIST)

    # 反例（rev 182 前的标准答案）：01-05 BS1 只投 71 → 补线日焊装未满产（C14）
    f0 = {d: dict(v) for d, v in flows.items()}
    f0[DAY1].update({"BS1": (71, 70), "PS": (65, 55), "AS_MAIN": (60, 60), "AS_FIN": (60, 80)})
    f0[DAY2].update({"AS_MAIN": (80, 80), "AS_FIN": (80, 80)})
    f0[DAYS[-1]].update({"BS1": (80, 80), "PS": (80, 80)})
    under = build_plan(DAYS, f0, INV0, WS, STOP_LIST)
    under["findings"] = ["反例：期初补线首日 BS1 未满产投入"]

    # 反例：01-05 PS 日末 144 < 150 仍向 PBS 出车 70 → REFILL；01-06 补回
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[DAY1].update({"PS": (74, 70)})
    f1[DAY2].update({"PS": (80, 74)})
    leak = build_plan(DAYS, f1, INV0, WS, STOP_LIST)
    leak["findings"] = ["反例：期初补线首日 PS 未达目标就向 PBS 供车"]

    phases = {d.isoformat(): ("STOP" if HOLIDAY[0] <= d <= HOLIDAY[1] else
                              "REFILL" if d == DAY1 else "NORMAL") for d in DAYS}
    objective = {**ZERO, "L5": 136}
    expected = {
        "case": "1d-initial-refill",
        "spec": "CORE_MODEL §5 补线行（期初低于目标，rev 159；补线按满产推进，rev 182）、停线行（计划期首日在停线，rev 159）、C14",
        "engine": {"status": "FEASIBLE", "compare": "none", "objective": objective, "stop_list": STOP_LIST,
                   "days": engine_days(plan)},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": objective, "phases": phases},
        "counter_plans": [
            {"file": "counter/refill-ps-leak.plan.json",
             "why": "期初补线首日 PS 日末 144 未到 150 就向 PBS 出车",
             "judge": {"verdict": "REJECT", "rules": ["REFILL"]}, "engine_must_differ": True},
            {"file": "counter/refill-underfeed.plan.json",
             "why": "期初补线首日 BS1 只投 71，未满产（rev 182 前的标准答案）",
             "judge": {"verdict": "REJECT", "rules": ["C14"]}, "engine_must_differ": True},
        ],
    }
    targets = dict(TARGET_1D)
    dump(HERE / "input.json", single_model_input(DAYS, working, targets, INV0, {"2026-01": 400}, WS))
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "refill-ps-leak.plan.json", leak)
    dump(HERE / "counter" / "refill-underfeed.plan.json", under)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
