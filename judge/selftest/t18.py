"""T-18：停线前出清 + 清线零头放在清线前一天。

四份自检：
  ① 停前日 PBS 46 / AS_FIN 82（期初多出未清掉）→ 只有 PS_PRE_STOP；
  ② 同一停线出清后 PBS 45 / AS_FIN 80 → 不报；
  ③ 零头放在清线后（PS、总装最后一天只出 4）→ 只有 BS_CLEAR；
  ④ 标准写法（清线前一天焊装投 76 出 80，清线 2 天 PS、总装出 80，停前日 PS 到 91）→ ACCEPT。

合成输入基于 1c-long-stop（长停 16 天、停前目标 91），把 BS1 目标/期初改为 71、
PBS 目标 45、AS_FIN 目标 80，使「清线需流出 164 台 = 71(焊装)+37(WBS)+56(PS 降库)」
在零头 = 4 时正好被 2 个满产日（160）+ 清线前一天减量 4 消化。horizon 收尾到 03-01，
避开复工补线噪声，只保留清线段。
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


def _input(excess_pbs_fin=False):
    """合成输入：1c-long-stop 基础上 BS1 目标/期初 71、PBS 45、AS_FIN 80；长停 16 天。

    excess_pbs_fin=True 时把期初 PBS / AS_FIN 各加 1 / 2（46 / 82），模拟「期初多出」。
    """
    raw = json.loads((ROOT / "cases" / "1c-long-stop" / "input.json").read_text(encoding="utf-8"))
    raw["horizon"]["end"] = "2026-03-01"
    raw["wip_targets"]["BS1"] = 71
    raw["wip_targets"]["PBS"] = 45
    raw["wip_targets"]["AS_FIN"] = 80
    raw["initial"]["wip"]["BS1"] = {"A": 71}
    raw["initial"]["wip"]["PBS"] = {"A": 45 + (1 if excess_pbs_fin else 0)}
    raw["initial"]["wip"]["AS_FIN"] = {"A": 80 + (2 if excess_pbs_fin else 0)}
    # 去掉 3 月需求（horizon 已不含 3 月生产）。
    raw["demand"]["PR"] = {"A": {"2026-02": 800}}
    raw["demand"]["WS_daily"] = {"A": {"2026-02-13": 800}}
    return raw


_NORM = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}


def _normal_base_flows():
    flows = {}
    for ds in ("2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06",
               "2026-02-09", "2026-02-10"):
        flows[ds] = dict(_NORM)
    return flows


def _standard_flows():
    """④ 标准写法：清线前一天（02-11）焊装投 76 出 80，清线 2 天（02-12/13）PS、总装出 80，
    停前日（02-13）PS 到 91。"""
    f = _normal_base_flows()
    f["2026-02-11"] = {"BS1": (76, 80), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    f["2026-02-12"] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    f["2026-02-13"] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": 80}
    return f


def _remainder_after_flows():
    """③ 零头放在清线后：清线前一天（02-10）不减量、清线 3 天（02-11/12/13），
    停前日（02-13）PS、总装只出 4。"""
    f = {}
    for ds in ("2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06",
               "2026-02-09"):
        f[ds] = dict(_NORM)
    f["2026-02-10"] = dict(_NORM)  # 清线前一天：不减量投入
    f["2026-02-11"] = {"BS1": (0, 71), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    f["2026-02-12"] = {"PS": (28, 80), "AS_MAIN": 80, "AS_FIN": 80}
    f["2026-02-13"] = {"PS": (0, 4), "AS_MAIN": 4, "AS_FIN": 4}
    return f


def _report(name, exp, got, j, failures):
    ok = exp is None and not j.hard_errors or exp is not None and all(e in got for e in exp)
    mark = "PASS" if ok else "FAIL"
    if not ok:
        failures.append(name)
    print(f"[{mark}] {name}")
    print(f"   预期条款      : {exp if exp is not None else '无'}")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()
    return failures


def run_t18_cases():
    failures = []

    # ---- ① / ②：停前日 PBS / AS_FIN 出清（期初多出 46/82 未清 vs 干净 45/80） ----
    # ① 期初多出未清掉：整份标准写法流量下，PBS 停在 46、AS_FIN 停在 82 → 只有 PS_PRE_STOP。
    raw_excess = _input(excess_pbs_fin=True)
    inp_excess = InputModel(raw_excess)
    j1 = _judge(inp_excess, _build(inp_excess, _standard_flows()))
    got1 = sorted({e.rule for e in j1.hard_errors})
    ok1 = got1 == ["PS_PRE_STOP"]
    if not ok1:
        failures.append("① 停前日 PBS 46 / AS_FIN 82 只有 PS_PRE_STOP")
    print(f"[{'PASS' if ok1 else 'FAIL'}] T-18 ① 停前日 PBS 46 / AS_FIN 82（期初多出未清）→ 只有 PS_PRE_STOP")
    print("   预期条款      : ['PS_PRE_STOP']")
    print(f"   实得条款      : {got1}")
    print(f"   判定     : {'REJECT' if j1.hard_errors else 'ACCEPT'}")
    for e in j1.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # ② 出清后干净：期初 PBS 45 / AS_FIN 80，标准写法 → 不报（ACCEPT）。
    raw_clean = _input(excess_pbs_fin=False)
    inp_clean = InputModel(raw_clean)
    j2 = _judge(inp_clean, _build(inp_clean, _standard_flows()))
    got2 = sorted({e.rule for e in j2.hard_errors})
    ok2 = not j2.hard_errors
    if not ok2:
        failures.append("② 停前日 PBS 45 / AS_FIN 80 不报")
    print(f"[{'PASS' if ok2 else 'FAIL'}] T-18 ② 出清后停前日 PBS 45 / AS_FIN 80 → 不报")
    print(f"   预期条款      : 无")
    print(f"   实得条款      : {got2}")
    print(f"   判定     : {'REJECT' if j2.hard_errors else 'ACCEPT'}")
    for e in j2.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # ---- ③ / ④：清线零头（清线后 vs 清线前一天） ----
    # ③ 零头放在清线后：清线前一天不减量、清线 3 天，停前日 PS、总装只出 4 → 触发 BS_CLEAR。
    #    注：零头放在清线后（而非清线前一天）会连带使 WBS 在清线倒数第二天就被 T-17「能做尽做」
    #    吃空，停前日 BS1/WBS 空档（紧贴停线失败 → BS_CLEAR），并连带 C8/C13，故此处按
    #    「BS_CLEAR 必须命中」断言。
    j3 = _judge(inp_clean, _build(inp_clean, _remainder_after_flows()))
    got3 = sorted({e.rule for e in j3.hard_errors})
    ok3 = "BS_CLEAR" in got3
    if not ok3:
        failures.append("③ 零头放在清线后命中 BS_CLEAR")
    print(f"[{'PASS' if ok3 else 'FAIL'}] T-18 ③ 零头放在清线后（PS、总装最后一天只出 4）→ BS_CLEAR")
    print("   预期条款      : 含 BS_CLEAR")
    print(f"   实得条款      : {got3}")
    print(f"   判定     : {'REJECT' if j3.hard_errors else 'ACCEPT'}")
    for e in j3.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # ④ 标准写法：清线前一天焊装投 76 出 80，清线 2 天 PS、总装出 80，停前日 PS 到 91 → ACCEPT。
    j4 = _judge(inp_clean, _build(inp_clean, _standard_flows()))
    got4 = sorted({e.rule for e in j4.hard_errors})
    ok4 = not j4.hard_errors
    if not ok4:
        failures.append("④ 标准写法 ACCEPT")
    print(f"[{'PASS' if ok4 else 'FAIL'}] T-18 ④ 标准写法（清线前一天投 76 出 80、清线 2 天出 80、停前日 PS 91）→ ACCEPT")
    print(f"   预期条款      : 无")
    print(f"   实得条款      : {got4}")
    print(f"   判定     : {'REJECT' if j4.hard_errors else 'ACCEPT'}")
    for e in j4.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    return 4, len(failures)
