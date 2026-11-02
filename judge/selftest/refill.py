"""T-14：补线满产、无投入出车及新参考计划。"""
import json
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel


def run_refill_cases():
    root = Path(__file__).resolve().parents[2] / "cases"
    case = root / "1d-initial-refill"
    raw = json.loads((case / "input.json").read_text(encoding="utf-8"))
    expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    checks = [
        ("补线少投", raw,
         json.loads((case / "counter/refill-underfeed.plan.json").read_text(encoding="utf-8")),
         ["C14"], None),
        ("新参考计划", raw,
         json.loads((case / "_reference-plan.json").read_text(encoding="utf-8")),
         [], expected["judge_on_engine"]["objective"]["L5"]),
    ]

    # 由现有输入构造：PBS 期初低于目标，首日完成线无来车却消化超目标在制。
    data = json.loads((root / "1a-single-model-two-weeks/input.json").read_text(encoding="utf-8"))
    base = InputModel(data)
    model = next(iter(base.models))
    dates = [d for d in base.dates if base.is_working(d)][:3]
    data["horizon"] = {"start": dates[0].isoformat(), "end": dates[-1].isoformat()}
    cap = base.cap_for_mode("AS_FIN", base.default_mode)
    excess = cap - base.node_target("AS_FIN")
    data["initial"]["wip"]["PBS"] = {model: base.node_target("PBS") - cap}
    data["initial"]["wip"]["AS_FIN"] = {model: base.node_target("AS_FIN") + excess}
    inp = InputModel(data)
    days = []
    for d in dates:
        workshops = {}
        for w in inp.workshops:
            inn = out = cap if w != "BS2" else 0
            if d == dates[0] and w in ("AS_MAIN", "AS_FIN"):
                inn = 0
                out = excess if w == "AS_FIN" else 0
            mode = inp.default_mode if inn or out else "OFF"
            workshops[w] = {"mode": mode, "hours": inp.modes[mode],
                            "in": {model: inn}, "out": {model: out}}
        days.append({"date": d.isoformat(), "workshops": workshops})
    plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days}
    inventory = Judge(inp, plan)
    inventory.recompute_inventory()
    for day in days:
        ds = day["date"]
        for key in ("bod", "eod", "fok", "fin", "bl"):
            day[key] = getattr(inventory, key)[ds]
    checks.append(("补线首日 AS_FIN 无投入出车", data, plan, ["C17"], None))

    failures = 0
    for name, data, plan, rules, l5 in checks:
        j = Judge(InputModel(data), plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        got = sorted({e.rule for e in j.hard_errors})
        ok = got == rules and (l5 is None or j.objective["L5"] == l5)
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-14 {name}")
        print(f"   预期条款: {rules}；实得条款: {got}")
        print(f"   判定: {'REJECT' if got else 'ACCEPT'}；L5={j.objective['L5']}；预期 L5={l5}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
        print()
    return len(checks), failures
