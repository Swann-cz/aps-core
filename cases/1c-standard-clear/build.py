"""生成 1c 标准清线算例文件（Claude 维护，rev 187）。手算见 README.md。

python cases/1c-standard-clear/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from casegen import TARGET_1D, ZERO, build_plan, days_between, dump, full_flows, single_model_input  # noqa: E402

DAYS = days_between(dt.date(2026, 3, 2), dt.date(2026, 3, 8))  # 周一至周日；03-07 起停线，计划期包住停线开头
D_RED, D_CLR1, D_PRE = dt.date(2026, 3, 4), dt.date(2026, 3, 5), dt.date(2026, 3, 6)
INV0 = dict(TARGET_1D, BS2=0)  # 标准摆线：各节点都在目标
WS = {D_PRE: 400}
# 03-07 至 03-22 停 16 天（≥ 15，停前目标 91；焊装零流 ≥ 胶龄 15，触发清线），03-23 复工；计划期后的日历只用来推算停线长度
EXTRA = [{"date": d.isoformat(), "is_working_capable": d == dt.date(2026, 3, 23)}
         for d in days_between(dt.date(2026, 3, 9), dt.date(2026, 3, 23))]
STOP_LIST = [{"start": "2026-03-07", "end": "2026-03-22", "length": 16,
              "pre_stop_date": "2026-03-06", "target": 91, "source": "DEFAULT"}]


def working(d: dt.date) -> bool:
    return d.weekday() < 5 and d < dt.date(2026, 3, 7)


def main() -> None:
    flows = full_flows(DAYS, working)
    flows[D_RED].update({"BS1": (76, 80)})                       # 清线前一天：少投 4（零头），出车满产，BS1 降到 66
    flows[D_CLR1].update({"BS1": (0, 66)})                       # 清线第 1 天：BS1 出清
    flows[D_PRE].update({"BS1": (0, 0), "PS": (21, 80)})          # 停前日：WBS 余 21 进 PS，PS 出 80 降到 91
    plan = build_plan(DAYS, flows, INV0, WS, STOP_LIST)

    # 反例 1：零头放在清线后（焊装满产到清线，最后一天 PS、总装只出 4）——需要多一天，这里用旧的“80、24、60”式写法
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[D_RED].update({"BS1": (80, 80)})
    f1[D_CLR1].update({"BS1": (0, 70), "PS": (80, 80)})
    f1[D_PRE].update({"BS1": (0, 0), "PS": (25, 84 - 4), "AS_MAIN": (80, 80), "AS_FIN": (80, 80)})
    tail = build_plan(DAYS, f1, INV0, {D_PRE: 400}, STOP_LIST)
    tail["findings"] = ["反例：零头没放在清线前一天，停线时 PS 多 4 台"]

    # 反例 2：清线前一天焊装少投又少出（全线做 76），停线时线上多 4 台没出清
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[D_RED].update({w: (76, 76) for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")})
    f2[D_CLR1].update({"BS1": (0, 70)})
    f2[D_PRE].update({"BS1": (0, 0), "PS": (25, 80)})
    hold = build_plan(DAYS, f2, INV0, WS, STOP_LIST)
    hold["findings"] = ["反例：清线前一天全线降到 76，PS 停前日末 95，未出清"]

    phases = {D_RED.isoformat(): "NORMAL", D_CLR1.isoformat(): "PS_PRE_STOP+BS_CLEAR",
              D_PRE.isoformat(): "PS_PRE_STOP+BS_CLEAR",
              "2026-03-07": "STOP", "2026-03-08": "STOP"}
    objective = {**ZERO, "L2": 1}
    expected = {
        "case": "1c-standard-clear",
        "spec": "CORE_MODEL §5 BS 清线行（停线前出清、清线零头放在清线前一天，rev 186–187）、PS 停前日行（停前降库，rev 185）",
        "engine": {"status": "FEASIBLE", "compare": "none", "objective": objective,
                   "stop_list": STOP_LIST, "days": []},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": objective, "phases": phases},
        "counter_plans": [
            {"file": "counter/tail-after-clear.plan.json",
             "why": "焊装满产到清线，零头没放在清线前一天，停前日 PS 日末 95 未到 91",
             "judge": {"verdict": "REJECT", "rules": ["PS_PRE_STOP"]}, "engine_must_differ": True},
            {"file": "counter/hold-at-stop.plan.json",
             "why": "清线前一天全线降到 76，停线时线上多 4 台未出清",
             "judge": {"verdict": "REJECT", "rules": ["BS_CLEAR", "PS_PRE_STOP"]}, "engine_must_differ": True},
        ],
    }
    dump(HERE / "input.json", single_model_input(DAYS, working, dict(TARGET_1D), INV0, {"2026-03": 400}, WS,
                                                 glue=15, extra_calendar=EXTRA))
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "tail-after-clear.plan.json", tail)
    dump(HERE / "counter" / "hold-at-stop.plan.json", hold)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
