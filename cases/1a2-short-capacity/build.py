"""生成 1a2 缺产算例文件（Claude 维护）。手算过程见 README.md。

python cases/1a2-short-capacity/build.py
产出：input.json、expected.json、counter/short-tail-40.plan.json
设定沿用 1a（工厂、日历、期初、目标），只改需求：PR 750 > 产能 640。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "case1a", HERE.parent / "1a-single-model-two-weeks" / "build.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

PR = 750
WS = {dt.date(2026, 3, 5): 400, dt.date(2026, 3, 11): 350}


def build_input() -> dict:
    inp = base.build_input()
    inp["demand"] = {"PR": {"A": {"2026-03": PR}},
                     "WS_daily": {"A": {d.isoformat(): q for d, q in WS.items()}}}
    return inp


def build_plan(last_day_flow: int) -> dict:
    """工作日满产 80（03-11 为 last_day_flow），周末 0；fin/bl 按 CORE_MODEL C11 逐日推出。"""
    def flow(d: dt.date) -> int:
        if not base.working(d):
            return 0
        return last_day_flow if d == base.END else 80

    base.flow_of = flow
    plan = base.build_plan()
    net = 0  # fin − bl
    for day in plan["days"]:
        d = dt.date.fromisoformat(day["date"])
        net += day["fok"]["A"] - WS.get(d, 0)
        day["fin"] = {"A": max(net, 0)}
        day["bl"] = {"A": max(-net, 0)} if net < 0 else {}
    return plan


def objective(plan: dict) -> dict:
    fok = sum(day["fok"]["A"] for day in plan["days"])
    band = PR - round(0.1 * PR)
    return {**base.ZERO,
            "L1a": max(0, PR - fok),
            "L1b": sum(day["bl"].get("A", 0) for day in plan["days"]),
            "L1c": max(0, band - fok)}


def main() -> None:
    plan = build_plan(80)
    counter = build_plan(40)
    counter["findings"] = ["反例：03-11 只做 40 台（段末尾差），产能没用满"]
    keys = ("date", "workshops", "eod", "fok", "fin", "bl")
    expected = {
        "case": "1a2-short-capacity",
        "spec": "CORE_MODEL C10/C11/C12 缺产放宽（2026-10-24 裁决），§6 L1a/L1b/L1c",
        "engine": {
            "status": "FEASIBLE",
            "objective": objective(plan),
            "stop_list": [],
            "days": [{k: day[k] for k in keys} for day in plan["days"]],
        },
        "judge_on_engine": {
            "verdict": "ACCEPT",
            "objective": objective(plan),
            "phases": {day["date"]: "NORMAL" for day in plan["days"]},
        },
        "counter_plans": [{
            "file": "counter/short-tail-40.plan.json",
            "why": "放宽后仍满足全部硬约束（段末尾差合法），只有 L1a 把它排除",
            "judge": {"verdict": "ACCEPT", "objective": objective(counter)},
            "engine_must_differ": True,
        }],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "short-tail-40.plan.json", counter)


if __name__ == "__main__":
    main()
