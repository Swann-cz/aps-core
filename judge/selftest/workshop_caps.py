"""T-10：由输入数量构造车间上限与直接下游车间满载自检。"""
import copy
import json
from pathlib import Path

from judge.constraints import check_all, check_c14
from judge.core import Judge
from judge.model import InputModel


def run_workshop_cap_cases():
    root = Path(__file__).resolve().parents[2] / "cases"
    raw = json.loads((root / "1a-single-model-two-weeks/input.json").read_text(encoding="utf-8"))
    annual_path = root / "1d-annual-feedback/feedback-gap.input.json"
    base = InputModel(raw)
    model = next(iter(base.models))
    dates = [d.isoformat() for d in base.dates if base.is_working(d)][:3]
    cap = base.cap_for_mode("AS_FIN", base.default_mode)
    failed = 0
    skipped = 0
    scenarios = ("正常日 AS_MAIN 超上限", "期初 AS_FIN 超限逐日下降", "AS_FIN 达标后回升")
    for name in scenarios:
        if name != scenarios[0] and not annual_path.exists():
            print(f"跳过（无真实数据）：T-10 {name}")
            skipped += 1
            continue
        data = copy.deepcopy(raw)
        data["horizon"] = {"start": dates[0], "end": dates[-1]}
        flows = [{w: (cap, cap) for w in (base.line_of[model], "PS", "AS_MAIN", "AS_FIN")}
                 for ds in dates]
        node = "AS_MAIN" if name == scenarios[0] else "AS_FIN"
        if node == "AS_MAIN":
            flows[0][node] = (cap, cap - 1)
            flows[0]["AS_FIN"] = (cap - 1, cap - 1)
            expected = [(ds, node) for ds in dates]
        else:
            annual = json.loads(annual_path.read_text(encoding="utf-8"))
            initial = sum(annual["initial"]["wip"][node].values())
            target = annual["wip_targets"][node]
            data["initial"]["wip"][node] = {model: initial}
            data["wip_targets"][node] = target
            step = (initial - target) // (len(dates) - 1)
            for flow in flows[:-1]:
                flow["AS_MAIN"] = (cap - step, cap - step)
                flow[node] = (cap - step, cap)
            if name == scenarios[-1]:
                flows[-1][node] = (cap, cap - 1)
                expected = [(dates[-1], node)]
            else:
                expected = []
        inp = InputModel(data)
        plan = {"days": [{"date": ds, "workshops": {
            w: {"mode": inp.default_mode, "in": {model: inn}, "out": {model: out}}
            for w, (inn, out) in flow.items()}} for ds, flow in zip(dates, flows)]}
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.compute_phases()
        check_all(j)
        got = [(e.date, e.node) for e in j.hard_errors if e.rule == "C6"]
        ok = got == expected
        if node == "AS_MAIN":
            ok = ok and all(j.phases[ds] == "NORMAL" for ds in dates)
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-10 {name}")
        print(f"   期初={sum(inp.inv0[node].values())} 上限={inp.node_target(node)} "
              f"EOD={[j.node_eod_total(ds, node) for ds in dates]}")
        print(f"   预期 C6 日期/节点: {expected}")
        print(f"   实得 C6 日期/节点: {got}")
        for e in j.hard_errors:
            if e.rule == "C6":
                print(f"     - {e.rule} {e.detail}")
        print()

    # 上游 PBS 高于目标，排除 C15 镜像；只改变下游 AS_FIN 是否到上限。
    for full in (True, False):
        data = copy.deepcopy(raw)
        data["horizon"] = {"start": dates[0], "end": dates[-1]}
        data["initial"]["wip"]["PBS"][model] = base.node_target("PBS") + 1
        if full:  # rev 202：完成线须填了物理上限，才算下游到上限
            data["factory"]["workshops"]["AS_FIN"]["cap_max"] = base.node_target("AS_FIN")
        inp = InputModel(data)
        plan = {"days": [{"date": ds, "workshops": {
            "AS_MAIN": {"mode": inp.default_mode, "in": {model: cap - 1}, "out": {model: cap - 1}},
            "AS_FIN": {"mode": inp.default_mode, "in": {model: cap - 1}, "out": {model: cap - 1}},
            "PS": {"mode": inp.default_mode, "in": {model: cap - 1}, "out": {model: cap - 1}},
        }} for ds in dates]}
        if not full:
            plan["days"][0]["workshops"]["AS_FIN"]["out"][model] = cap
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.compute_phases()
        check_c14(j)
        got = [(e.date, e.node) for e in j.hard_errors if e.node == "AS_MAIN"]
        expected = [] if full else [(ds, "AS_MAIN") for ds in dates[:-1]]
        ok = got == expected
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-10 下游 AS_FIN {'到' if full else '未到'}上限时 AS_MAIN 不满产")
        print(f"   预期 C14 日期/节点: {expected}")
        print(f"   实得 C14 日期/节点: {got}")
        print()
    return len(scenarios) + len((True, False)) - skipped, failed, skipped
