"""T-31（31-J）：胶龄逼清的短停按长停判（CORE_MODEL rev 196 §5 BS 清线行）。

判定器改动：零流窗口长度 W 虽短于 Lg，但 W + k > Lg(m)（k = ⌈WBS 当日目标 ÷
该线停前最后生产日的焊装产能⌉）时，这次停线按长停处理——照 BS 清线行清线、WBS 清空，
PS 按停前日行停前降库，停后按补线 / 复线补满，并切分 C14 生产段。

自检场景（合成单车型 B，绑定 BS2，胶龄 7；WBS 目标 60、BS2 产能 48 → k = 2）：
  ① 停 6 天（W+k=8>7）且计划按长停清线、复线 → ACCEPT（含 BS_CLEAR / PS_PRE_STOP / REFILL）；
  ② 停 6 天但计划保留 WBS 过停线 → BS_CLEAR（rev 196 胶龄逼清，按长停）；
  ③ 停 5 天（W+k=7=Lg）按短停、保留在制 → ACCEPT（不触发清线）。
规格例子（车型 B 胶龄 7、WBS 目标 60、产能 48，k=⌈60/48⌉=2）：停 6 天按长停、停 5 天按短停，
对应 ② / ③。
"""
from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel

ROOT = Path(__file__).resolve().parents[2]

WS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")


def _make_input(stop_days: int, end_at_stop: bool = False) -> dict:
    """合成输入：单车型 B 绑定 BS2、胶龄 7；WBS 目标 60；BS2 jph=6（产能 48）、
    PS jph=10（产能 80）。日历除连续 stop_days 天停线外均为工作日（无周末，简化）。

    k = ⌈60 / 48⌉ = 2；停 6 天时 W+k=8>7 按长停，停 5 天时 W+k=7 不超、按短停。
    end_at_stop=True 时 horizon 收尾到停线末日，只保留清线段（避开复工复线）。
    """
    start = datetime.date(2026, 3, 2)
    work1 = [start + datetime.timedelta(days=i) for i in range(5)]          # 03-02..06
    stop = [work1[-1] + datetime.timedelta(days=i + 1) for i in range(stop_days)]
    work2 = ([] if end_at_stop
             else [stop[-1] + datetime.timedelta(days=i + 1) for i in range(3)])
    all_days = work1 + stop + work2
    horizon_end = all_days[-1]
    calendar = [{"date": d.isoformat(), "is_working_capable": d not in stop}
                for d in all_days]
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": start.isoformat(), "end": horizon_end.isoformat()},
        "calendar": calendar,
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 6}, "PS": {"jph": 10},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 120}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"B": {"line": "BS2", "glue_age_max": 7}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {
            "PR": {"B": {"2026-03": 400}},
            "WS_daily": {"B": {horizon_end.isoformat(): 400}},
        },
        "initial": {
            "wip": {"BS2": {"B": 20}, "WBS": {"B": 60}, "PS": {"B": 131},
                    "PBS": {"B": 80}, "AS_MAIN": {"B": 100}, "AS_FIN": {"B": 40}},
            "fin": {"B": 0},
        },
        "wip_targets": {"BS1": 69, "BS2": 20, "WBS": 60, "PS": 131,
                        "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40},
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def _make_day(ds: str, flows: dict) -> dict:
    workshops = {}
    for w in WS:
        spec = flows.get(w, 0)
        inn, out = spec if isinstance(spec, tuple) else (spec, spec)
        active = inn > 0 or out > 0
        workshops[w] = {"mode": "SINGLE_8H" if active else "OFF",
                        "hours": 8 if active else 0,
                        "in": {"B": inn} if inn else {},
                        "out": {"B": out} if out else {}}
    return {"date": ds, "workshops": workshops}


def _build(inp: InputModel, flows: dict) -> dict:
    days = [_make_day(d.isoformat(), flows.get(d.isoformat(), {})) for d in inp.dates]
    plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}
    j = Judge(inp, plan)
    j.recompute_inventory()
    for d in plan["days"]:
        ds = d["date"]
        for key in ("bod", "eod"):
            d[key] = {n: {m: v for m, v in per.items() if v}
                      for n, per in getattr(j, key)[ds].items() if any(per.values())}
        for key in ("fok", "fin", "bl"):
            d[key] = {m: v for m, v in getattr(j, key)[ds].items() if v}
    return plan


def _judge(inp: InputModel, plan: dict) -> Judge:
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


def _workdays(stop_days: int) -> tuple[list[str], list[str]]:
    start = datetime.date(2026, 3, 2)
    work1 = [start + datetime.timedelta(days=i) for i in range(5)]
    stop = [work1[-1] + datetime.timedelta(days=i + 1) for i in range(stop_days)]
    work2 = [stop[-1] + datetime.timedelta(days=i + 1) for i in range(3)]
    return [d.isoformat() for d in work1], [d.isoformat() for d in work2]


def run_t31_cases() -> tuple[int, int]:
    failures: list[str] = []

    def report(name, exp, j, extra=lambda jj: True):
        got = sorted({e.rule for e in j.hard_errors})
        ok = (exp is None and not j.hard_errors) \
            or (exp is not None and all(e in got for e in exp))
        ok = ok and extra(j)
        if not ok:
            failures.append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] T-31 {name}")
        print(f"   预期条款      : {exp if exp is not None else '无'}")
        print(f"   实得条款      : {got}")
        print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()

    # ---- ① 停 6 天（W+k=8>7）按长停清线、复线 → ACCEPT ----
    raw = _make_input(6, end_at_stop=False)
    inp = InputModel(raw)
    work1, work2 = _workdays(6)
    flows: dict[str, dict] = {}
    for ds in work1[:4]:  # 03-02..05 正常生产
        flows[ds] = {"BS2": 48, "PS": 48, "AS_MAIN": 48, "AS_FIN": 48}
    # 03-06 清线日 + 停前日：BS2 出清 20、PS/WBS/下游出清
    flows[work1[4]] = {"BS2": (0, 20), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    # 停 6 天后复工复线：BS2 补到 20、WBS 补到 60、全链逐级补满
    flows[work2[0]] = {"BS2": (48, 28)}
    flows[work2[1]] = {"BS2": 48, "PS": 16, "AS_MAIN": 16, "AS_FIN": 16}
    flows[work2[2]] = {"BS2": 48, "PS": 48, "AS_MAIN": 48, "AS_FIN": 48}
    j1 = _judge(inp, _build(inp, flows))
    report("① 停 6 天按长停清线、复线（合法）", None, j1,
           extra=lambda j: j.stop_windows
           and j.stop_windows[0]["length"] == 6
           and len(j.bs_clear_events) == 1
           and bool(j.refill_periods))

    # ---- ② 停 6 天但保留 WBS 过停线 → BS_CLEAR（rev 196 胶龄逼清） ----
    raw = _make_input(6, end_at_stop=True)
    inp = InputModel(raw)
    work1, _ = _workdays(6)
    flows = {ds: {"BS2": 48, "PS": 48, "AS_MAIN": 48, "AS_FIN": 48} for ds in work1}
    j2 = _judge(inp, _build(inp, flows))
    report("② 停 6 天保留 WBS 过停线 → BS_CLEAR", ["BS_CLEAR"], j2)

    # ---- ③ 停 5 天（W+k=7=Lg）按短停、保留在制 → ACCEPT ----
    raw = _make_input(5, end_at_stop=True)
    inp = InputModel(raw)
    work1, _ = _workdays(5)
    flows = {ds: {"BS2": 48, "PS": 48, "AS_MAIN": 48, "AS_FIN": 48} for ds in work1}
    j3 = _judge(inp, _build(inp, flows))
    report("③ 停 5 天按短停保留在制（合法）", None, j3,
           extra=lambda j: not j.bs_clear_events)

    total = 3
    print(f"== T-31 结果：{total - len(failures)}/{total} ==")
    return total, len(failures)


# ==================== 31-J2：清线期「能做尽做」（CORE_MODEL rev 197） ====================

J2_WS = WS
J2_NORM_DAYS = tuple(
    (datetime.date(2026, 2, 2) + datetime.timedelta(days=i)).isoformat()
    for i in range(9)  # 02-02 .. 02-10 正常生产
)
J2_CLEAR_D1 = "2026-02-11"  # 清线第 1 天
J2_CLEAR_D2 = "2026-02-12"  # 清线第 2 天 = 停前日


def _j2_input(wbs_init: int) -> dict:
    """合成输入（31-J2）：单车型 A，BS1，胶龄 14；各车间产能 80；长停 16 天、停前目标 91。

    正常生产 02-02..02-10，清线段 02-11、02-12（02-12 为 PS 停前日），02-13 起停线 16 天。
    期初各节点都在目标；WBS 期初由 wbs_init 控制，用于在清线期制造「上游供得上 / 供不上」。
    PS 物理上限放宽到 200，避免「少产堆积超目标」连带的 C6 噪声，聚焦「能做尽做」判定。
    """
    start = datetime.date(2026, 2, 2)
    cal = []
    for i in range(11):
        cal.append({"date": (start + datetime.timedelta(days=i)).isoformat(),
                    "is_working_capable": True})
    for i in range(16):
        cal.append({"date": (start + datetime.timedelta(days=11 + i)).isoformat(),
                    "is_working_capable": False})
    end = start + datetime.timedelta(days=26)
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": "2026-02-02", "end": end.isoformat()},
        "calendar": cal,
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8},
                          "PS": {"jph": 10, "cap_max": 200},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 120}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": 14}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {"A": {"2026-02": 2000}},
                   "WS_daily": {"A": {"2026-02-12": 2000}}},
        "initial": {"wip": {"BS1": {"A": 67}, "WBS": {"A": wbs_init}, "PS": {"A": 147},
                            "PBS": {"A": 80}, "AS_MAIN": {"A": 100}, "AS_FIN": {"A": 40}},
                    "fin": {"A": 0}},
        "wip_targets": {"BS1": 67, "BS2": 67, "WBS": wbs_init, "PS": 147,
                        "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40},
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def _j2_make_day(ds: str, flows: dict) -> dict:
    workshops = {}
    for w in J2_WS:
        spec = flows.get(w, 0)
        inn, out = spec if isinstance(spec, tuple) else (spec, spec)
        active = inn > 0 or out > 0
        workshops[w] = {"mode": "SINGLE_8H" if active else "OFF",
                        "hours": 8 if active else 0,
                        "in": {"A": inn} if inn else {},
                        "out": {"A": out} if out else {}}
    return {"date": ds, "workshops": workshops}


def _j2_build(inp: InputModel, flows: dict) -> dict:
    days = [_j2_make_day(d.isoformat(), flows.get(d.isoformat(), {})) for d in inp.dates]
    plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}
    j = Judge(inp, plan)
    j.recompute_inventory()
    for d in plan["days"]:
        ds = d["date"]
        for key in ("bod", "eod"):
            d[key] = {n: {m: v for m, v in per.items() if v}
                      for n, per in getattr(j, key)[ds].items() if any(per.values())}
        for key in ("fok", "fin", "bl"):
            d[key] = {m: v for m, v in getattr(j, key)[ds].items() if v}
    return plan


def _j2_judge(inp: InputModel, plan: dict) -> Judge:
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


def _j2_report(name, expect, j, detail_hint=None, failures=None):
    """J2 断言：expect=None 时要求 ACCEPT；expect 为 rule 列表时要求含这些 rule；
    detail_hint 非空时额外要求某条硬错误 detail 包含该片段（用于区分「能做尽做」与「不满落最后」）。"""
    got = sorted({e.rule for e in j.hard_errors})
    ok = (expect is None and not j.hard_errors) \
        or (expect is not None and all(e in got for e in expect))
    if detail_hint is not None:
        ok = ok and any(detail_hint in e.detail for e in j.hard_errors)
    if not ok:
        failures.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] T-31-J2 {name}")
    print(f"   预期条款      : {expect if expect is not None else '无'}"
          + (f"，且 detail 含「{detail_hint}」" if detail_hint else ""))
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
    print()
    return failures


def run_t31_j2_cases() -> tuple[int, int]:
    """31-J2 三份自检（rev 197 清线期「能做尽做」）：
      ① 清线期上游供不上、少产且不满的那天在最后 → ACCEPT；
      ② 清线期供得上却少产（有车却不满产）→ BS_CLEAR（detail 含「能做尽做」）；
      ③ 不满的那天不在最后 → BS_CLEAR（detail 含「不满应落在」）。
    """
    failures: list[str] = []
    normal = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
              for ds in J2_NORM_DAYS}

    # ① 供不上、少产、不满在最后（WBS 期初 20：清线第 2 天 PS 供不上，出 63 不满、落在最后）
    inp = InputModel(_j2_input(wbs_init=20))
    flows = dict(copy.deepcopy(normal))
    flows[J2_CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    flows[J2_CLEAR_D2] = {"PS": (7, 63), "AS_MAIN": 63, "AS_FIN": 63}
    j1 = _j2_judge(inp, _j2_build(inp, flows))
    _j2_report("① 供不上少产且不满在最后（合法）", None, j1, failures=failures)

    # ② 供得上却少产（WBS 期初 80：清线第 2 天 PS 供得上应出满 80，却出 40）
    inp = InputModel(_j2_input(wbs_init=80))
    flows = dict(copy.deepcopy(normal))
    flows[J2_CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    flows[J2_CLEAR_D2] = {"PS": (67, 40), "AS_MAIN": 40, "AS_FIN": 40}
    j2 = _j2_judge(inp, _j2_build(inp, flows))
    _j2_report("② 供得上却少产（清线第 2 天 PS 出 40 而非 80）", ["BS_CLEAR"], j2,
               detail_hint="能做尽做", failures=failures)

    # ③ 不满的那天不在最后（WBS 期初 80：AS_FIN 清线第 1 天出 40 不满、第 2 天出 80 满）
    inp = InputModel(_j2_input(wbs_init=80))
    flows = dict(copy.deepcopy(normal))
    flows[J2_CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 40}
    flows[J2_CLEAR_D2] = {"PS": (67, 80), "AS_MAIN": 80, "AS_FIN": 80}
    j3 = _j2_judge(inp, _j2_build(inp, flows))
    _j2_report("③ 不满的那天不在最后（AS_FIN 先少出后满出）", ["BS_CLEAR"], j3,
               detail_hint="不满应落在", failures=failures)

    total = 3
    print(f"== T-31-J2 结果：{total - len(failures)}/{total} ==")
    return total, len(failures)


if __name__ == "__main__":
    total, failed = run_t31_cases()
    raise SystemExit(bool(failed))
