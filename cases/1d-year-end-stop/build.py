"""生成 1d 年末停线两个算例（Claude 维护）。手算过程见各自 README.md。

python cases/1d-year-end-stop/build.py
产出：本目录与 ../1d-year-end-stop-calendar/ 的 input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAL = HERE.parent / "1d-year-end-stop-calendar"
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from casegen import TARGET_1D, ZERO, build_plan, days_between, dump, engine_days, full_flows, single_model_input  # noqa: E402

DAYS = days_between(dt.date(2026, 12, 14), dt.date(2026, 12, 31))
HOLIDAY = (dt.date(2026, 12, 29), dt.date(2026, 12, 31))
CLEAR1, PRE = dt.date(2026, 12, 25), dt.date(2026, 12, 28)
TARGET = {**TARGET_1D, "BS1": 66}  # BS1 66 + WBS 35 = 101 = 80 + 21，长停清线正好两天（见 calendar 版 README）
INV0 = {n: q for n, q in TARGET.items() if n != "BS2"}
WS = {PRE: 880}
PR = {"2026-12": 880}
# 下一年日历：2027-01-01 至 01-12 不可生产，01-13 可生产
NEXT_YEAR = [{"date": (dt.date(2027, 1, 1) + dt.timedelta(n)).isoformat(), "is_working_capable": n >= 12}
             for n in range(13)]
SHORT = [{"start": "2026-12-29", "end": "2027-01-03", "length": 6,
          "pre_stop_date": PRE.isoformat(), "target": 131, "source": "DEFAULT"}]
LONG = [{"start": "2026-12-29", "end": "2027-01-12", "length": 15,
         "pre_stop_date": PRE.isoformat(), "target": 91, "source": "DEFAULT"}]


def working(d: dt.date) -> bool:
    return d.weekday() < 5 and not (HOLIDAY[0] <= d <= HOLIDAY[1])


def short_flows() -> dict:
    flows = full_flows(DAYS, working)
    flows[PRE].update({"BS1": (61, 61), "PS": (61, 80)})
    return flows


def long_flows() -> dict:
    flows = full_flows(DAYS, working)
    flows[CLEAR1].update({"BS1": (0, 66)})
    flows[PRE].update({"BS1": (0, 0), "PS": (21, 80)})
    return flows


def main() -> None:
    # 不带下一年日历：推算到 2027-01-03，6 天短停，停前 131
    short = build_plan(DAYS, short_flows(), INV0, WS, SHORT)
    f1 = short_flows()
    f1[PRE].update({"BS1": (21, 21), "PS": (21, 80)})
    wrong = build_plan(DAYS, f1, INV0, WS, LONG)
    wrong["findings"] = ["反例：没带下一年日历却按长停取 91"]
    phases = {d.isoformat(): ("STOP" if d >= HOLIDAY[0] else "PS_PRE_STOP" if d == PRE else "NORMAL")
              for d in DAYS}
    dump(HERE / "input.json", single_model_input(DAYS, working, TARGET, INV0, PR, WS))
    dump(HERE / "expected.json", {
        "case": "1d-year-end-stop",
        "spec": "CORE_MODEL §5 停线行（年末尾停长度：元旦放假、遇周末顺延，rev 159）、PS 停前日",
        "engine": {"status": "FEASIBLE", "objective": dict(ZERO), "stop_list": SHORT,
                   "days": engine_days(short)},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": dict(ZERO), "phases": phases},
        "counter_plans": [
            {"file": "counter/ps-long-target.plan.json",
             "why": "停线推算是 6 天短停，停前却把 PS 降到长停目标 91",
             "judge": {"verdict": "REJECT", "rules": ["PS_PRE_STOP"]}, "engine_must_differ": True},
        ],
    })
    dump(HERE / "counter" / "ps-long-target.plan.json", wrong)
    dump(HERE / "_reference-plan.json", short)

    # 带下一年日历：停到 2027-01-12，15 天长停，停前 91，焊装要清线
    long = build_plan(DAYS, long_flows(), INV0, WS, LONG)
    ignored = build_plan(DAYS, short_flows(), INV0, WS, SHORT)
    ignored["findings"] = ["反例：没看下一年日历，按 6 天短停排"]
    # rev 185 起：首个 BS 清线日到停前日都是 PS 停前降库（中间的非生产日也算降库期）
    phases = {d.isoformat(): ("STOP" if d >= HOLIDAY[0] else "PS_PRE_STOP+BS_CLEAR" if d in (CLEAR1, PRE)
                              else "PS_PRE_STOP" if CLEAR1 < d < PRE else "NORMAL") for d in DAYS}
    objective = {**ZERO, "L2": 1}
    dump(CAL / "input.json", single_model_input(DAYS, working, TARGET, INV0, PR, WS, extra_calendar=NEXT_YEAR))
    dump(CAL / "expected.json", {
        "case": "1d-year-end-stop-calendar",
        "spec": "CORE_MODEL §5 停线行（带下一年日历时以日历为准，rev 159）、PS 停前日（长停 91）、BS 清线",
        "engine": {"status": "FEASIBLE", "compare": "none", "objective": objective, "stop_list": LONG},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": objective, "phases": phases},
        "counter_plans": [
            {"file": "counter/calendar-ignored.plan.json",
             "why": "没看下一年日历：停前 PS 取 131，焊装没清线就进了 15 天长停",
             "judge": {"verdict": "REJECT", "rules": ["BS_CLEAR", "PS_PRE_STOP"]}, "engine_must_differ": True},
        ],
    })
    dump(CAL / "counter" / "calendar-ignored.plan.json", ignored)
    dump(CAL / "_reference-plan.json", long)


if __name__ == "__main__":
    main()
