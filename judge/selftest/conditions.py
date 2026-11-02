"""T-11 条件正反例；数量、日期与模式从阶段算例输入取得。"""
from copy import deepcopy
import json
from pathlib import Path

from judge.model import InputModel
from judge.core import Judge
from judge.constraints import check_all

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "cases" / "1a-single-model-two-weeks"


def evaluate(raw, plan):
    inp = InputModel(raw)
    j = Judge(inp, plan)
    if inp.condition_errors:
        for detail in inp.condition_errors:
            j._err("INPUT", None, None, None, detail)
        return j
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


def reconcile_plan(raw, plan):
    """只填库存对账字段；条件、模式、流量和预期结果由用例明确给出。"""
    j = Judge(InputModel(raw), plan)
    j.recompute_inventory()
    for day in plan["days"]:
        ds = day["date"]
        for key in ("bod", "eod", "fok", "fin", "bl"):
            day[key] = deepcopy(getattr(j, key)[ds])
    return plan


def run_condition_cases():
    from .__main__ import build_plan

    raw = json.loads((CASE / "input.json").read_text(encoding="utf-8"))
    inp = InputModel(raw)
    model = next(iter(inp.models))
    line = inp.line_of[model]
    active = (line, "PS", "AS_MAIN", "AS_FIN")
    working = [d.isoformat() for d in inp.dates if inp.is_working(d)]
    weekend = next(d.isoformat() for d in inp.dates if not inp.is_working(d))
    day = working[1]
    mode = inp.default_mode
    overtime = next(k for k in inp.modes if k not in ("OFF", mode))
    capacity = inp.cap_for_mode(line, mode)
    remaining = sum(inp.pr[model].values())
    flows = {}
    for ds in working:
        q = min(capacity, remaining)
        flows[ds] = {w: q for w in active}
        remaining -= q
    base = build_plan(inp, flows)
    total = failed = 0

    def check(name, data, plan, rules=(), extra=lambda j: True):
        nonlocal total, failed
        total += 1
        j = evaluate(data, plan)
        got = sorted({e.rule for e in j.hard_errors})
        ok = (set(rules).issubset(got) if rules else not got) and extra(j)
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] T-11 {name}")
        print(f"   预期条款: {list(rules)}；实得条款: {got}")
        print(f"   判定: {'REJECT' if got else 'ACCEPT'}；objective={j.objective}")
        if j.stop_windows:
            print("   停线清单: " + json.dumps(j.stop_windows, ensure_ascii=False))
        for report in j.reports:
            if report["rule"] == "PS_PRE_STOP":
                print("   报告: " + report["detail"])
        for e in j.hard_errors:
            print(f"   {e.rule} {e.date} {e.node}: {e.detail}")
        return j

    def condition(kind, **fields):
        return {"id": kind, "type": kind, **fields}

    def with_conditions(*conditions):
        data = deepcopy(raw)
        data["conditions"] = list(conditions)
        return data

    def set_flow(plan, ds, qty, selected_mode=mode):
        row = next(d for d in plan["days"] if d["date"] == ds)
        for w in active:
            row["workshops"][w] = {
                "mode": selected_mode, "hours": inp.modes[selected_mode],
                "in": {model: qty}, "out": {model: qty},
            }

    def add_pr(data, delta):
        month = day[:7]
        data["demand"]["PR"][model][month] += delta

    sat = condition("SATURDAY_AUTH", date=weekend)
    data = with_conditions(sat)
    add_pr(data, capacity)
    plan = deepcopy(base)
    set_flow(plan, weekend, capacity)
    reconcile_plan(data, plan)
    check("周六授权正例 / L3a", data, plan,
          extra=lambda j: j.objective["L3a"] == len(active))
    no_auth = deepcopy(data)
    no_auth["conditions"] = []
    check("周六无授权反例", no_auth, plan, ("C3",))

    auth = condition("MODE_AUTH", start=day, end=day, workshops=list(active), mode=overtime)
    data = with_conditions(auth)
    extra_qty = inp.cap_for_mode(line, overtime) - capacity
    add_pr(data, extra_qty)
    plan = deepcopy(base)
    set_flow(plan, day, capacity + extra_qty, overtime)
    reconcile_plan(data, plan)
    check("模式授权正例 / L3b", data, plan,
          extra=lambda j: j.objective["L3b"] == len(active))
    no_auth = deepcopy(data)
    no_auth["conditions"] = []
    check("模式无授权反例", no_auth, plan, ("C3",))

    data = with_conditions(sat)
    add_pr(data, capacity + extra_qty)
    plan = deepcopy(base)
    set_flow(plan, weekend, capacity + extra_qty, overtime)
    reconcile_plan(data, plan)
    check("周六加班缺 MODE_AUTH", data, plan, ("C3",))
    data["conditions"].append({**auth, "start": weekend, "end": weekend})
    check("周六加班双授权", data, plan,
          extra=lambda j: j.objective["L3a"] == len(active)
          and j.objective["L3b"] == len(active))

    shut = condition("SHUTDOWN", start=day, end=day, workshops=["PS"])
    check("部分停线有流且覆盖授权", with_conditions(shut, auth), base, ("C3",))
    short = ROOT / "cases" / "1c-short-stop"
    stop_raw = json.loads((short / "input.json").read_text(encoding="utf-8"))
    stop_plan = json.loads((short / "_reference-plan.json").read_text(encoding="utf-8"))
    stop_j = evaluate(stop_raw, stop_plan)
    window = stop_j.stop_windows[0]
    stop_raw["conditions"] = [condition("SHUTDOWN", start=window["start"], end=window["start"])]
    next(c for c in stop_raw["calendar"] if c["date"] == window["start"])["is_working_capable"] = True
    check("停线与相邻日历零流合并正例", stop_raw, stop_plan,
          extra=lambda j: j.stop_windows == stop_j.stop_windows)
    partial = deepcopy(stop_raw)
    partial["conditions"][0]["workshops"] = ["PS"]
    partial["conditions"].append(condition(
        "WIP_TARGET", node="AS_MAIN", start=window["start"], end=window["start"],
        target=partial["wip_targets"]["AS_MAIN"] + 1))
    check("部分停线不豁免其他车间 C8/C13", partial, stop_plan, ("C8", "C13"))
    bad_stop = deepcopy(stop_plan)
    pre = window["pre_stop_date"]
    pre_row = next(d for d in bad_stop["days"] if d["date"] == pre)
    pre_row["workshops"]["PS"]["out"][model] -= (
        stop_raw["wip_targets"]["PS"] - window["target"])
    reconcile_plan(stop_raw, bad_stop)
    check("停线形成窗口未执行停前目标", stop_raw, bad_stop, ("PS_PRE_STOP",))

    hours = inp.modes[mode] - 1
    loss = condition("CAPACITY_LOSS", start=day, end=day,
                     workshops=list(active), hours_max=hours)
    data = with_conditions(loss)
    check("产能损失超限反例", data, base, ("C2",))
    plan = deepcopy(base)
    lowered = hours * inp.workshops[line]
    set_flow(plan, day, lowered)
    add_pr(data, lowered - capacity)
    reconcile_plan(data, plan)
    check("产能损失满产正例 / C14", data, plan)
    no_loss = deepcopy(data)
    no_loss["conditions"] = []
    check("移除产能损失后段中不满产", no_loss, plan, ("C14",))

    target = condition("WIP_TARGET", node="PS", start=day, end=day,
                       target=inp.node_target("PS") + 1)
    check("人工目标下限反例", with_conditions(target), base, ("C8",))
    target["target"] = inp.node_target("PS") - 1
    check("人工车间目标上限反例", with_conditions(target), base, ("C6",))
    target.update(start=raw["horizon"]["start"], end=raw["horizon"]["end"])
    data = with_conditions(target)
    data["initial"]["wip"]["PS"][model] = target["target"]
    plan = reconcile_plan(data, deepcopy(base))
    check("人工车间目标覆盖正例 / L5", data, plan,
          extra=lambda j: j.objective["L5"] == 0)
    target = condition("WIP_TARGET", node="WBS", start=day, end=day,
                       target=inp.node_target("WBS") - 1)
    check("缓冲人工目标保留物理上限", with_conditions(target), base,
          extra=lambda j: j.objective["L5"] == 1)

    manual = condition("PRE_STOP_TARGET", pre_stop_date=pre, target=window["target"])
    data = deepcopy(stop_raw)
    data["conditions"].append(manual)
    data["rules"]["ps_pre_stop_target_short"] = data["wip_targets"]["PS"]
    check("人工停前目标覆盖默认正例", data, stop_plan,
          extra=lambda j: j.stop_windows[0]["source"] == "MANUAL:PRE_STOP_TARGET"
          and j.stop_windows[0]["target"] == manual["target"])
    data["conditions"][-1] = {**manual, "target": manual["target"] - 1}
    check("人工停前目标未执行反例", data, stop_plan, ("PS_PRE_STOP",))
    unmatched = condition("PRE_STOP_TARGET", pre_stop_date=day, target=0)
    check("未匹配人工停前目标只报告", with_conditions(unmatched), base,
          extra=lambda j: any("PRE_STOP_TARGET" in r["detail"] for r in j.reports))

    fixed = condition("FIXED_OUTPUT", workshop=line, date=day, out=capacity)
    check("指定产量正例", with_conditions(fixed), base)
    check("指定产量反例", with_conditions({**fixed, "out": capacity - 1}), base, ("FIXED",))

    invalid = [
        ("未知类型", [condition("UNKNOWN")]),
        ("缺字段", [condition("CAPACITY_LOSS")]),
        ("重复 id", [sat, sat]),
        ("越界日期", [{**sat, "date": (inp.end.replace(year=inp.end.year + 1)).isoformat()}]),
        ("反向范围", [{**auth, "start": working[-1], "end": working[0]}]),
        ("不存在车间", [{**auth, "workshops": ["UNKNOWN"]}]),
        ("不存在节点", [{**target, "node": "UNKNOWN"}]),
        ("不存在模式", [{**auth, "mode": "UNKNOWN"}]),
        ("目标冲突", [target, {**target, "id": "OTHER", "target": target["target"] + 1}]),
        ("指定产量冲突", [fixed, {**fixed, "id": "OTHER", "out": fixed["out"] + 1}]),
        ("停线指定正产量", [shut, {**fixed, "workshop": "PS"}]),
        ("负值", [{**loss, "hours_max": -1}]),
        ("日期格式", [{**sat, "date": "not-a-date"}]),
    ]
    for name, conditions in invalid:
        check("INPUT " + name, with_conditions(*conditions), base, ("INPUT",),
              extra=lambda j: all("条件" in e.detail for e in j.hard_errors))
    return total, failed
