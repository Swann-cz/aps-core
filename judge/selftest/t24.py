"""T-24：未使用的周六授权按车间视同休息日。"""
from copy import deepcopy
import json

from judge.model import InputModel
from .conditions import CASE, evaluate


def run_t24_cases():
    from .__main__ import build_plan

    raw = json.loads((CASE / "input.json").read_text(encoding="utf-8"))
    base = InputModel(raw)
    model = next(iter(base.models))
    line = base.line_of[model]
    active = (line, "PS", "AS_MAIN", "AS_FIN")
    saturday = next(d for d in base.dates if not base.is_working(d))
    flows = {}
    remaining = sum(base.pr[model].values())
    for d in base.dates:
        if base.is_working(d):
            qty = min(base.cap_for_mode(line, base.default_mode, d), remaining)
            flows[d.isoformat()] = {w: qty for w in active}
            remaining -= qty
    raw["conditions"] = [{"id": "T-24-SAT", "type": "SATURDAY_AUTH",
                          "date": saturday.isoformat()}]
    inp = InputModel(raw)
    all_off = evaluate(raw, build_plan(inp, flows))

    weld_flows = deepcopy(flows)
    # 焊装把 WBS 补至物理上限，下游保持 OFF；下周继续正常生产。
    qty = base.buffers["WBS"] - base.node_target("WBS")
    weld_flows[saturday.isoformat()] = {line: qty}
    weld_only = evaluate(raw, build_plan(inp, weld_flows))
    results = [
        ("授权周六全线 OFF，周五周一正常生产", all_off,
         not all_off.hard_errors and not all_off.stop_windows
         and all_off.objective["L3a"] == 0),
        ("授权周六只焊装生产，下游 OFF", weld_only,
         not weld_only.hard_errors and not weld_only.stop_windows
         and weld_only.objective["L3a"] == 1),
    ]
    failures = 0
    for name, judge, ok in results:
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-24 {name}")
        print(f"   实得条款: {sorted({e.rule for e in judge.hard_errors})}")
        print(f"   判定: {'REJECT' if judge.hard_errors else 'ACCEPT'}")
        print(f"   停线清单: {judge.stop_windows}；L3a={judge.objective['L3a']}")
        for error in judge.hard_errors:
            print(f"     - {error.rule} {error.date} {error.node} {error.model} {error.detail}")
        print()
    return len(results), failures
