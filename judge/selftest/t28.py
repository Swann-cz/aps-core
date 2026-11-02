"""T-28：显式车间物理上限与目标分离。"""
from copy import deepcopy
import json

from judge.model import InputModel
from .conditions import CASE, evaluate


def fixture():
    from .__main__ import build_plan

    raw = json.loads((CASE / "input.json").read_text(encoding="utf-8"))
    base = InputModel(raw)
    dates = [d.isoformat() for d in base.dates if base.is_working(d)][:3]
    raw["horizon"] = {"start": dates[0], "end": dates[-1]}
    cap = base.cap_for_mode("AS_FIN", base.default_mode)
    raw["demand"] = {"PR": {"A": {dates[0][:7]: cap * len(dates)}}, "WS_daily": {}}
    flows = {ds: {w: cap for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in dates}
    return raw, flows, dates, cap, build_plan


def run_t28_cases():
    raw, flows, dates, cap, build_plan = fixture()
    target = raw["wip_targets"]["AS_FIN"]
    results = []

    def record(name, data, flow, expected, objective=None):
        plan = build_plan(InputModel(data), flow)
        j = evaluate(data, plan)
        got = sorted({e.rule for e in j.hard_errors})
        ok = got == expected
        if objective is not None:
            ok = ok and (j.objective["L5"], j.objective["L6"]) == objective
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] T-28 {name}")
        print(f"   预期条款: {expected}；实得条款: {got}")
        print(f"   判定: {'REJECT' if j.hard_errors else 'ACCEPT'}")
        if objective is not None:
            print(f"   L5={j.objective['L5']} L6={j.objective['L6']}；预期={objective}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.detail}")

    data = deepcopy(raw)
    data["factory"]["workshops"]["AS_FIN"]["cap_max"] = target + 2
    data["initial"]["wip"]["AS_FIN"]["A"] = target + 1
    record("EOD 在目标与上限之间，计入 L5/L6", data, flows, [], (len(dates), len(dates)))
    over = deepcopy(flows)
    over[dates[0]]["AS_FIN"] = (cap, cap - 2)
    record("EOD 超显式上限", data, over, ["C6"])

    for full in (False, True):
        data = deepcopy(raw)
        data["factory"]["workshops"]["AS_FIN"]["cap_max"] = target + 2
        data["initial"]["wip"]["PBS"]["A"] += 1
        data["initial"]["wip"]["AS_FIN"]["A"] = target + 2 if full else target
        reduced = deepcopy(flows)
        for ds in dates:
            reduced[ds]["AS_MAIN"] = cap - 1
            reduced[ds]["AS_FIN"] = cap - 1
        record("下游到上限 C15 豁免" if full else "下游只到目标，报 C14", data, reduced,
               [] if full else ["C14"])

    record("未填上限，原目标水位合法", raw, flows, [])
    record("未填上限，EOD 超目标报 C6", raw, over, ["C6"])
    data = deepcopy(raw)
    data["factory"]["workshops"]["AS_FIN"]["cap_max"] = target - 1
    record("车间上限小于基础目标", data, flows, ["INPUT"])
    for node in ("AS_FIN", "PBS"):
        data = deepcopy(raw)
        data["factory"]["workshops"]["AS_FIN"]["cap_max"] = target + 2
        limit = target + 2 if node == "AS_FIN" else data["factory"]["buffers"][node]["cap_max"]
        data["conditions"] = [{"id": "T28", "type": "WIP_TARGET", "node": node,
                               "start": dates[0], "end": dates[-1], "target": limit + 1}]
        record(f"{node} 人工目标大于显式上限", data, flows, ["INPUT"])

    data = deepcopy(raw)
    data["factory"]["workshops"]["AS_FIN"]["cap_max"] = target + 2
    data["conditions"] = [{"id": "T28", "type": "WIP_TARGET", "node": "AS_FIN",
                           "start": dates[0], "end": dates[-1], "target": target - 1}]
    record("人工目标降低不改变显式上限", data, flows, [], (len(dates), len(dates)))
    data["initial"]["wip"]["AS_FIN"]["A"] = target + 4
    drain = deepcopy(flows)
    for ds in dates:
        drain[ds]["AS_MAIN"] = (cap - 1, cap - 1)
        drain[ds]["AS_FIN"] = (cap - 1, cap)
    record("期初高于显式上限只减不增", data, drain, [])
    print(f"== T-28 结果：{sum(results)}/{len(results)} ==")
    return len(results), len(results) - sum(results)


if __name__ == "__main__":
    total, failed = run_t28_cases()
    raise SystemExit(bool(failed))
