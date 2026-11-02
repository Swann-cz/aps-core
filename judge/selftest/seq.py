"""T-09：从算例输入取日期、数量，单独验证 SEQ 判据与同日清空许可。"""
import copy
import json
from pathlib import Path

from judge.constraints import check_seq
from judge.core import Judge
from judge.model import InputModel


def run_seq_cases():
    source = Path(__file__).resolve().parents[2] / "cases" / "1b-two-models-changeover" / "input.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    base = InputModel(raw)
    a, b = base.models
    la, lb = base.line_of[a], base.line_of[b]
    dates = [d.isoformat() for d in base.dates if base.is_working(d)]
    first, second, third = dates[:3]
    shared = ("WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")
    qty = min(base.node_target(n) for n in shared)
    scenarios = [
        ("换型后 PS 旧车型未出完", "PS", second, b, False, True),
        ("同日 PS 先出完旧车型再出新车型", "PS", second, b, True, False),
        ("A→B→A 第二次换型 AS_FIN 的 B 未出完", "AS_FIN", third, a, False, True),
        ("换型后 WBS 旧车型未出完", "WBS", second, b, False, True),
    ]
    failed = 0
    for name, node, day, new, clear_old, reject in scenarios:
        inp_raw = copy.deepcopy(raw)
        inp_raw["initial"]["wip"] = {
            la: {a: base.node_target(la)},
            **{n: {a: base.node_target(n), b: base.node_target(n)} for n in shared},
        }
        inp = InputModel(inp_raw)
        plan = {"days": [{"date": d.isoformat(), "workshops": {}} for d in inp.dates]}
        days = {d["date"]: d for d in plan["days"]}
        for ds, line, model in ((first, la, a), (second, lb, b), (third, la, a)):
            days[ds]["workshops"][line] = {"in": {model: qty}, "out": {}}
        old = b if new == a else a
        out = {new: qty}
        if clear_old:
            out[old] = inp.inv0[node][old]
        workshop = inp.downstream[node] if node in inp.buffers else node
        key = "in" if node in inp.buffers else "out"
        days[day]["workshops"][workshop] = {key: out}
        j = Judge(inp, plan)
        j.recompute_inventory()
        check_seq(j)
        expected = [(day, node, new)] if reject else []
        got = [(e.date, e.node, e.model) for e in j.hard_errors]
        ok = got == expected
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] SEQ {name}")
        print(f"   预期 SEQ 日期/节点/新车型: {expected}")
        print(f"   实得 SEQ 日期/节点/新车型: {got}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.detail}")
        print()
    for reject in (True, False):
        inp = InputModel(copy.deepcopy(raw))
        plan = {"days": [{"date": d.isoformat(), "workshops": {}} for d in inp.dates]}
        days = {d["date"]: d for d in plan["days"]}
        # 直接使用 1b 的期初 PBS 两车型数量和 AS_MAIN 期初数量。
        days[first]["workshops"] = {
            la: {"in": {a: qty}},
            "AS_MAIN": {"in": {a: inp.inv0["PBS"][a]},
                        "out": {a: inp.inv0["AS_MAIN"][a]}},
            "AS_FIN": {"in": {a: inp.inv0["AS_MAIN"][a]}},
        }
        if reject:
            # 累计 PBS 出车超过含焊装线、缓冲的全部上游期初 A。
            extra = sum(inp.inv0.get(n, {}).get(a, 0)
                        for n in (la, lb, "WBS", "PS")) + qty
            days[second]["workshops"] = {
                la: {"in": {a: extra}, "out": {a: extra}},
                "PS": {"in": {a: extra}, "out": {a: extra}},
                "AS_MAIN": {"in": {a: extra}},
            }
        days[third]["workshops"] = {
            "AS_MAIN": {"in": {b: inp.inv0["PBS"][b]},
                        "out": {b: inp.inv0["PBS"][b]}},
            "AS_FIN": {"in": {b: inp.inv0["PBS"][b]}},
        }
        j = Judge(inp, plan)
        j.recompute_inventory()
        check_seq(j)
        expected = [(second, "PBS", a)] if reject else []
        got = [(e.date, e.node, e.model) for e in j.hard_errors]
        ok = got == expected
        failed += not ok
        name = ("计划期内焊出的 A 出 PBS 时期初 B 仍在" if reject else
                "1b 期初 AS_MAIN 先出 A、PBS 先出 A、B 随后出")
        print(f"[{'PASS' if ok else 'FAIL'}] SEQ {name}")
        print(f"   预期 SEQ 日期/节点/新车型: {expected}")
        print(f"   实得 SEQ 日期/节点/新车型: {got}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.detail}")
        print()
    return len(scenarios) + len((True, False)), failed
