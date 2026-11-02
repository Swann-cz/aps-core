"""T-17：PS 停前降库（清线起满产降）+ 第 6 级目标（超目标在制靠下游）。

三份自检：
 ① 旧写法（降库期 PS 出 80/24/58，不满产落在中间）→ 只有 PS_PRE_STOP；
 ② 同一停线按新写法（80/80/余数，做尽）→ 不报 PS_PRE_STOP；
 ③ 两份只差超额在制位置（PBS 多 1 台 vs AS_FIN 多 1 台）→ L5 相同、L6 不同且差值按权重
    （PBS 权重 3、AS_FIN 权重 1）算对。
"""
import copy
import json
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel

ROOT = Path(__file__).resolve().parents[2]

WS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")


def _make_day(ds, flows):
    workshops = {}
    for w in WS:
        spec = flows.get(w, 0)
        inn, out = spec if isinstance(spec, tuple) else (spec, spec)
        active = inn > 0 or out > 0
        workshops[w] = {"mode": "SINGLE_8H" if active else "OFF",
                        "hours": 8 if active else 0,
                        "in": {"A": inn} if inn else {},
                        "out": {"A": out} if out else {}}
    return {"date": ds, "workshops": workshops}


def _build(inp, flows):
    days = [_make_day(d.isoformat(), flows.get(d.isoformat(), {})) for d in inp.dates]
    plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}
    j = Judge(inp, plan)
    j.recompute_inventory()
    for d in plan["days"]:
        ds = d["date"]
        d["bod"] = {n: {m: v for m, v in per.items() if v}
                    for n, per in j.bod[ds].items() if any(per.values())}
        d["eod"] = {n: {m: v for m, v in per.items() if v}
                    for n, per in j.eod[ds].items() if any(per.values())}
        d["fok"] = {m: v for m, v in j.fok[ds].items() if v}
        d["fin"] = {m: v for m, v in j.fin[ds].items() if v}
        d["bl"] = {m: v for m, v in j.bl[ds].items() if v}
    return plan


def _judge(inp, plan):
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


# ①/② 的合成输入：在 1c-long-stop 基础上把 BS1 目标/期初改为 69（spec §5 阶段重叠示例，
# 需清 3 天），并把 horizon 收尾到停线内（03-01），避开复工补线的额外噪声，只保留降库段。
def _clear_down_input():
    raw = json.loads((ROOT / "cases" / "1c-long-stop" / "input.json").read_text(encoding="utf-8"))
    raw["horizon"]["end"] = "2026-03-01"
    raw["wip_targets"]["BS1"] = 69
    raw["initial"]["wip"]["BS1"] = {"A": 69}
    # 去掉 3 月需求（horizon 已不含 3 月生产）。
    raw["demand"]["PR"] = {"A": {"2026-02": 800}}
    raw["demand"]["WS_daily"] = {"A": {"2026-02-13": 800}}
    return raw


_NORM = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}


def _clear_down_base_flows():
    flows = {}
    for ds in ("2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06",
               "2026-02-09", "2026-02-10"):
        flows[ds] = dict(_NORM)
    return flows


def run_t17_cases():
    failures = []

    # ---- ① / ②：同一停线（BS1=69，清 3 天：02-11、02-12、02-13，停前日 02-13） ----
    raw = _clear_down_input()
    inp = InputModel(raw)

    old_f = _clear_down_base_flows()
    old_f["2026-02-11"] = {"BS1": (0, 69), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    old_f["2026-02-12"] = {"PS": (24, 24), "AS_MAIN": 24, "AS_FIN": 24}
    old_f["2026-02-13"] = {"PS": (2, 58), "AS_MAIN": 58, "AS_FIN": 58}

    new_f = _clear_down_base_flows()
    new_f["2026-02-11"] = {"BS1": (0, 69), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    new_f["2026-02-12"] = {"PS": (26, 80), "AS_MAIN": 80, "AS_FIN": 80}
    new_f["2026-02-13"] = {"PS": (0, 2), "AS_MAIN": 2, "AS_FIN": 2}

    j_old = _judge(inp, _build(inp, old_f))
    got_old = sorted({e.rule for e in j_old.hard_errors})
    # T-18 起「清线段 PS/总装必须满产」：旧写法（PS 出 80/24/58，中间不满产）除 PS_PRE_STOP
    # （能做尽做公式不符）外，还触发 BS_CLEAR（清线段不满产）。
    ok1 = got_old == ["BS_CLEAR", "PS_PRE_STOP"]
    if not ok1:
        failures.append("① 降库期旧写法只报 PS_PRE_STOP")
    print(f"[{'PASS' if ok1 else 'FAIL'}] T-17 ① 降库期旧写法（PS 出 80/24/58）→ PS_PRE_STOP + BS_CLEAR")
    print("   预期条款      : ['BS_CLEAR', 'PS_PRE_STOP']")
    print(f"   实得条款      : {got_old}")
    for e in j_old.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
    print()

    # ② 新写法做尽：不报 PS_PRE_STOP（做满到最后自然落余数；此场景 WBS 提前清空、停前日
    #    BS1 空档，属降库「做尽」与 BS 清线「紧贴停线」的张力的边界，见回报规格疑问）。
    j_new = _judge(inp, _build(inp, new_f))
    got_new = sorted({e.rule for e in j_new.hard_errors})
    ok2 = "PS_PRE_STOP" not in got_new
    if not ok2:
        failures.append("② 降库期新写法不报 PS_PRE_STOP")
    print(f"[{'PASS' if ok2 else 'FAIL'}] T-17 ② 降库期新写法（PS 出 80/80/余数）→ 不报 PS_PRE_STOP")
    print(f"   预期条款      : 不含 PS_PRE_STOP")
    print(f"   实得条款      : {got_new}")
    for e in j_new.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
    print()

    # ---- ③ L6：只差超额在制位置（PBS 多 1 台 vs AS_FIN 多 1 台） ----
    raw_1a = json.loads((ROOT / "cases" / "1a-single-model-two-weeks" / "input.json").read_text(encoding="utf-8"))
    base = InputModel(raw_1a)
    model = next(iter(base.models))
    flows = {}
    for ds in ("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
               "2026-03-09", "2026-03-10"):
        flows[ds] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    flows["2026-03-11"] = {w: 40 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}

    def plus_one(node):
        r = copy.deepcopy(raw_1a)
        r["initial"]["wip"] = copy.deepcopy(r["initial"]["wip"])
        r["initial"]["wip"][node][model] = base.node_target(node) + 1
        return r

    inp_pbs = InputModel(plus_one("PBS"))
    inp_fin = InputModel(plus_one("AS_FIN"))
    j_pbs = _judge(inp_pbs, _build(inp_pbs, flows))
    j_fin = _judge(inp_fin, _build(inp_fin, flows))

    l5_p, l6_p = j_pbs.objective["L5"], j_pbs.objective["L6"]
    l5_f, l6_f = j_fin.objective["L5"], j_fin.objective["L6"]
    ok3 = (l5_p == l5_f) and (l6_p - l6_f == 2 * l5_p)  # PBS 权重 3 - AS_FIN 权重 1 = 2
    if not ok3:
        failures.append("③ L6 权重差值")
    print(f"[{'PASS' if ok3 else 'FAIL'}] T-17 ③ L6：PBS 多 1 台 vs AS_FIN 多 1 台（L5 相同、L6 差按权重）")
    print(f"   PBS+1  : L5={l5_p} L6={l6_p}")
    print(f"   AS_FIN+1: L5={l5_f} L6={l6_f}")
    print(f"   预期: L5 相同；L6 差 = 2 × L5 = {2 * l5_p}")
    print()

    return 3, len(failures)
