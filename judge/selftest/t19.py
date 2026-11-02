"""T-19：标准清线计划的焊装分批出车与一次出清。"""
import json
from datetime import timedelta

from judge.model import InputModel, parse_date
from .t18 import ROOT, _build, _judge


def run_t19_cases():
    case = ROOT / "cases" / "1c-standard-clear"
    inp = InputModel(json.loads((case / "input.json").read_text(encoding="utf-8")))
    ref = json.loads((case / "_reference-plan.json").read_text(encoding="utf-8"))
    baseline = _judge(inp, ref)
    event = baseline.bs_clear_events[0]
    line, model = event["line"], event["model"]
    first = event["start"]
    second = (parse_date(first) + timedelta(days=1)).isoformat()
    amount = baseline.bod[first][line][model]
    unit = len(inp.models)
    flows = {
        day["date"]: {
            w: (row["in"].get(model, 0), row["out"].get(model, 0))
            for w, row in day["workshops"].items()
        }
        for day in ref["days"]
    }
    flows[first][line] = (0, unit)
    flows[second][line] = (0, amount - unit)
    wbs = sum(baseline.bod[first]["WBS"].values())
    for ds in (first, second):
        supplied = wbs + flows[ds][line][1]
        ps_in = min(inp.cap_for_mode("PS", inp.default_mode, parse_date(ds)), supplied)
        flows[ds]["PS"] = (ps_in, flows[ds]["PS"][1])
        wbs = supplied - ps_in
    split = _judge(inp, _build(inp, flows))
    results = [
        (f"清线首日出 {unit}、次日出 {amount - unit}", split,
         any(e.rule == "BS_CLEAR" and e.date == first and e.node == line
             for e in split.hard_errors)),
        (f"清线首日一次出完 {amount}", baseline, not baseline.hard_errors),
    ]
    failures = 0
    for name, judge, ok in results:
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-19 {name}")
        print(f"   实得条款: {sorted({e.rule for e in judge.hard_errors})}")
        print(f"   判定: {'REJECT' if judge.hard_errors else 'ACCEPT'}")
        for error in judge.hard_errors:
            print(f"     - {error.rule} {error.date} {error.node} {error.model} {error.detail}")
        print()
    return len(results), failures
