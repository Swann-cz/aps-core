"""T-12：使用算例原始输入、参考计划和两份反例核对期初排空。"""
import json
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel


def run_initial_drain_cases():
    case = Path(__file__).resolve().parents[2] / "cases" / "1d-initial-drain"
    inp = InputModel(json.loads((case / "input.json").read_text(encoding="utf-8")))
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    scenarios = [("_reference-plan.json", expected["judge_on_engine"])]
    scenarios += [(c["file"], c["judge"]) for c in expected["counter_plans"]]
    failed = 0
    for filename, want in scenarios:
        plan = json.loads((case / filename).read_text(encoding="utf-8"))
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        verdict = "REJECT" if j.hard_errors else "ACCEPT"
        rules = sorted({e.rule for e in j.hard_errors})
        ok = verdict == want["verdict"] and rules == sorted(want.get("rules", []))
        if "phases" in want:
            # expected.json（cases/，不可改）未含 L6；T-17 起 objective 带 L6，比对时补
            # L6=0（本期初排空计划所有节点 EOD 都在目标，L6 应为 0）。
            want_obj = dict(want["objective"])
            want_obj.setdefault("L6", 0)
            ok = ok and j.phases == want["phases"] and j.objective == want_obj
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-12 {filename}")
        print(f"   预期判定: {want}")
        print(f"   实得判定: {verdict}；rules={rules}")
        print(f"   phases={j.phases}")
        print(f"   objective={j.objective}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
    return len(scenarios), failed
