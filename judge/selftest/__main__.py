"""判定器自检入口：python -m judge.selftest

从 compact 描述构造若干份「故意违规」的计划，逐份跑判定器，
打印每份的预期条款与判定器实得条款。只用标准库。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE_INPUT = ROOT / "cases" / "1a-single-model-two-weeks" / "input.json"

# 五个车间；BS2 全期闲置（1a 单车型 A 绑定 BS1）
WS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")
_EMPTY = {}


def _day(date: str, flows: dict) -> dict:
    """构造某天的 workshops 描述。

    flows 给出每个车间当日 in/out 的台数（车型 A）；缺省 0。
    值可为 int（in==out）或 (in, out) 二元组（in 与 out 不同）。
    模式：有流用 SINGLE_8H，否则 OFF。
    """
    workshops = {}
    for w in WS:
        spec = flows.get(w, 0)
        if isinstance(spec, tuple):
            inn, out = spec
        else:
            inn = out = spec
        active = inn > 0 or out > 0
        mode = "SINGLE_8H" if active else "OFF"
        hours = 8 if active else 0
        d = {"mode": mode, "hours": hours}
        d["in"] = {"A": inn} if inn else {}
        d["out"] = {"A": out} if out else {}
        workshops[w] = d
    return {"date": date, "workshops": workshops}


class Case:
    """一份自检计划：名字、逐日每车间流量、预期违规条款与预期报告条款。"""

    def __init__(self, name: str, expected_rules: list[str], flows: dict[str, dict[str, int]],
                 expected_reports: list[str] | None = None,
                 bl_override: dict[str, dict[str, int]] | None = None):
        self.name = name
        self.expected_rules = expected_rules
        self.flows = flows  # {date: {workshop: qty}} in==out；缺省 0
        self.expected_reports = expected_reports or []
        self.bl_override = bl_override


def _all_dates():
    from judge.model import InputModel
    import json
    inp = InputModel(json.loads(CASE_INPUT.read_text(encoding="utf-8")))
    return inp, [d.isoformat() for d in inp.dates]


def build_plan(inp, flows: dict[str, dict[str, int]], bl_override: dict[str, dict[str, int]] | None = None) -> dict:
    """从 compact 逐日流量构造一份完整计划，并用判定器自身的库存重算补全
    bod/eod/fok/fin/bl，保证对账一致（如此只暴露「故意」的违规条款）。

    bl_override：把计划自报的 bl 覆盖为给定值（故意填错，用于触发 C11 对账）。
    """
    import json
    from judge.core import Judge

    days = []
    for ds in [d.isoformat() for d in inp.dates]:
        f = flows.get(ds, {})
        days.append(_day(ds, f))

    plan = {
        "schema": "aps-core/plan/v1",
        "status": "FEASIBLE",
        "days": days,
        "stop_list": [],
        "objective": {"levels": []},
        "findings": [],
    }

    j = Judge(inp, plan)
    j.recompute_inventory()
    # 用重算结果回填，使 plan 的 eod 与判定器重算一致（对账通过）
    for d in plan["days"]:
        ds = d["date"]
        d["bod"] = {n: {m: v for m, v in per.items() if v}
                    for n, per in j.bod[ds].items() if any(per.values())}
        d["eod"] = {n: {m: v for m, v in per.items() if v}
                    for n, per in j.eod[ds].items() if any(per.values())}
        d["fok"] = {m: v for m, v in j.fok[ds].items() if v}
        d["fin"] = {m: v for m, v in j.fin[ds].items() if v}
        ov = (bl_override or {}).get(ds)
        if ov is not None:
            d["bl"] = {m: v for m, v in ov.items() if v}
        else:
            d["bl"] = {m: v for m, v in j.bl[ds].items() if v}
        d["phase"] = "NORMAL"
    return plan


def run_case(inp, case: Case, bl_override: dict[str, dict[str, int]] | None = None):
    from judge.core import Judge
    from judge.constraints import check_all
    import json

    plan = build_plan(inp, case.flows, bl_override=bl_override)
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()

    got_rules = sorted({e.rule for e in j.hard_errors})
    got_reports = sorted({r.get("rule") for r in j.reports})
    verdict = "ACCEPT" if not j.hard_errors else "REJECT"
    return verdict, got_rules, j.hard_errors, j.objective, got_reports


def main() -> int:
    import json
    from judge.model import InputModel

    # cp1252 控制台打印中文会 UnicodeEncodeError，入口统一改成 UTF-8（T-02 B 部分第 3 条）
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    inp = InputModel(json.loads(CASE_INPUT.read_text(encoding="utf-8")))

    # ---- 三个故意违规的算例，均基于 1a 最优计划的流量做单点改动 ----
    # 最优流量：03-02..06 / 03-09..10 各车间 80，03-11 各车间 40，周末 0
    opt = {
        "2026-03-02": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-03": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-04": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-05": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-06": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-09": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-10": {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
        "2026-03-11": {w: 40 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")},
    }

    def copy(f):
        return {k: dict(v) for k, v in f.items()}

    cases: list[Case] = []

    # 1) C6：03-11 焊装照常 in=out=80（向 WBS 送 80），下游 PS 只 in=out=40
    #    → WBS EOD = 37 + 80 - 40 = 77 > 69（物理上限）
    f = copy(opt)
    f["2026-03-11"] = {"BS1": 80, "PS": 40, "AS_MAIN": 40, "AS_FIN": 40}
    cases.append(Case("C6 WBS 超上限（03-11 WBS=77）", ["C6"], f))

    # 2) C13：03-05 工作日无故空闲（需求 600 尚未排完）→ C13，且 C10 FOK≠PR 一并触发。
    #    用 03-05（周中）而非 03-06（周五）：03-06 空闲会与周末 03-07/08 连成 ≥3 天
    #    PS 零流窗口，触发停线检测（PS_PRE_STOP），不再只报 C13。
    f = copy(opt)
    f["2026-03-05"] = {}
    cases.append(Case("C13 工作日无故空闲（03-05 空闲）", ["C13"], f))

    # 3) C14：03-10 只产 40、03-11 产 80 → 尾差不在段末（段中不满产）
    f = copy(opt)
    f["2026-03-10"] = {w: 40 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    f["2026-03-11"] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    cases.append(Case("C14 尾差日不在段末（03-10 不满产）", ["C14"], f))

    # 4) C14：PS 段中不满产（仅 03-10 PS=40，其余车间满产）
    f = copy(opt)
    f["2026-03-10"]["PS"] = 40
    cases.append(Case("C14 PS 段中不满产（03-10 PS=40）", ["C14"], f))

    # 5) C14：AS_FIN 段中不满产（守恒写法：AS_MAIN 满投只出 40，AS_FIN 收 40 出 40）
    #    AS_MAIN 日末 140 高于目标，AS_FIN 直接上游 AS_MAIN EOD != tgt，镜像不成立 → C14。
    f = copy(opt)
    f["2026-03-10"]["AS_MAIN"] = (80, 40)
    f["2026-03-10"]["AS_FIN"] = 40
    cases.append(Case("C14 AS_FIN 段中不满产（03-10 AS_MAIN 满投只出 40）", ["C14"], f))

    # 5b) C1：拓扑守恒 AS_MAIN 出 80、AS_FIN 只收 40（AS_FIN.in != AS_MAIN.out）
    f = copy(opt)
    f["2026-03-10"]["AS_FIN"] = 40
    cases.append(Case("C1 拓扑守恒 AS_MAIN 出 80 / AS_FIN 只收 40（03-10）", ["C1"], f))

    # 6) C13：PS 工作日无故空闲（仅 03-10 PS=0，需求未排完）
    f = copy(opt)
    f["2026-03-10"]["PS"] = 0
    cases.append(Case("C13 PS 工作日无故空闲（03-10 PS=0）", ["C13"], f))

    # 7) PS 在工作日自建空闲 ≥3 天（03-04..06 全厂零流，连周末 03-07/08 合并 5 天）→
    #    按实际流量识别为停线窗口，停前日 03-03 PS 未降到 131 → PS_PRE_STOP。
    #    rev 163：停线窗口须全厂零流（任一焊装线复工当天窗口即结束），故 BS1 也停。
    f = copy(opt)
    for ds in ("2026-03-04", "2026-03-05", "2026-03-06"):
        f[ds]["BS1"] = 0
        f[ds]["PS"] = 0
        f[ds]["AS_MAIN"] = 0
        f[ds]["AS_FIN"] = 0
    cases.append(Case("PS_PRE_STOP PS 自建空闲 3 天停前未降（03-04..06）", ["PS_PRE_STOP"], f))

    # ---- T-01b 增补 3 份 ----
    # 8) C13 日初口径：03-11 BS1 空闲，日初 cumFOK=560 < cumPR=600，日末 AS_FIN 出 40 后
    #    cumFOK=600 ≥ 600。旧「当月累计 FOK 当日末已达当月 PR」会放行，新「截至前一日日初」应报 C13。
    #    （BS1 空闲连带 WBS 负库存 → C8，属预期，自检只要求 C13 出现。）
    f = copy(opt)
    f["2026-03-11"]["BS1"] = 0
    cases.append(Case("C13 日初口径（03-11 BS1 空闲，日初 560<600、日末 600）", ["C13"], f))

    # 9) C11 计划 bl 填错：产能够时 bl 恒 0，把 03-11 自报 bl 改成 5 → 与递推重算不一致
    cases.append(Case("C11 计划 bl 填错（03-11 自报 5）", ["C11"], opt,
                      bl_override={"2026-03-11": {"A": 5}}))

    # 10) C10 超产：8 个工作日全 80 → FOK 合计 640 > PR 600（连带 C12 末月超上限，属预期）
    f = copy(opt)
    f["2026-03-11"] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    cases.append(Case("C10 超产（FOK 640 > PR 600）", ["C10"], f))

    print("== judge selftest：故意违规计划 ==\n")
    fail = 0
    for c in cases:
        verdict, got, errs, obj, got_reports = run_case(inp, c, bl_override=c.bl_override)
        exp = sorted(c.expected_rules)
        exp_reports = sorted(c.expected_reports)
        ok = (all(e in got for e in exp)
              and all(r in got_reports for r in exp_reports))
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fail += 1
        print(f"[{mark}] {c.name}")
        print(f"   预期条款      : {exp}")
        print(f"   实得条款      : {got}")
        if exp_reports:
            print(f"   预期报告      : {exp_reports}")
            print(f"   实得报告      : {got_reports}")
        print(f"   判定     : {verdict}  L1a={obj['L1a']} L1b={obj['L1b']} L1c={obj['L1c']} "
              f"L2={obj['L2']} L3a={obj['L3a']} L3b={obj['L3b']} L4={obj['L4']} L5={obj['L5']}")
        for e in errs:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()

    # 8) INPUT：rules 缺 monthly_band_ratio（不应写死 0.1 兜底，应报 INPUT 硬错误）
    from judge.core import Judge
    from judge.constraints import check_all

    raw_in = json.loads(CASE_INPUT.read_text(encoding="utf-8"))
    del raw_in["rules"]["monthly_band_ratio"]
    inp2 = InputModel(raw_in)
    plan2 = build_plan(inp2, opt)
    j2 = Judge(inp2, plan2)
    j2.recompute_inventory()
    j2.reconcile()
    j2.compute_phases()
    check_all(j2)
    j2.compute_objective()
    got2 = sorted({e.rule for e in j2.hard_errors})
    ok2 = "INPUT" in got2
    mark2 = "PASS" if ok2 else "FAIL"
    if not ok2:
        fail += 1
    print(f"[{mark2}] INPUT 缺 monthly_band_ratio")
    print(f"   预期条款 : ['INPUT']")
    print(f"   实得条款 : {got2}")
    for e in j2.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # ---- T-02 增补 6 份（基于 1b 两车型换型） ----
    total_s1b, fail_s1b = _run_s1b_cases()
    fail += fail_s1b

    # ---- T-04 增补 3 份（基于 1c 单车型短停） ----
    total_s1c, fail_s1c = _run_s1c_cases()
    fail += fail_s1c

    # ---- T-05 增补 4 份（基于 1c 单车型长停：BS 清线 / 补线） ----
    total_s1c_long, fail_s1c_long = _run_s1c_long_cases()
    fail += fail_s1c_long

    # ---- T-06 增补 5 份（期初补线 / 首次启动 / 多次换型 / 首尾停线推算） ----
    total_s1d, fail_s1d = _run_s1d_cases()
    fail += fail_s1d

    # ---- T-06 第二轮增补 1 份（需求排完后月末自建空闲 → PS_PRE_STOP） ----
    total_self_idle, fail_self_idle = _run_self_idle_case()
    fail += fail_self_idle

    # ---- T-06 第三轮增补 3 份（多日清线 / 补线放宽 / 补线首日不计入停线） ----
    total_round3, fail_round3, skipped_round3 = _run_round3_cases()
    fail += fail_round3

    # ---- T-06 第四轮增补 1 份（焊装线 C13 只判绑定车型） ----
    total_round4, fail_round4, skipped_round4 = _run_round4_case()
    fail += fail_round4

    # ---- T-06 第五轮增补 2 份（CLR-07 清线前一天可减量投入） ----
    total_round5, fail_round5 = _run_round5_cases()
    fail += fail_round5

    from .seq import run_seq_cases
    total_seq, fail_seq = run_seq_cases()
    fail += fail_seq

    from .workshop_caps import run_workshop_cap_cases
    total_caps, fail_caps, skipped_caps = run_workshop_cap_cases()
    fail += fail_caps

    from .conditions import run_condition_cases
    total_conditions, fail_conditions = run_condition_cases()
    fail += fail_conditions

    from .initial_drain import run_initial_drain_cases
    total_drain, fail_drain = run_initial_drain_cases()
    fail += fail_drain

    from .refill import run_refill_cases
    total_refill, fail_refill = run_refill_cases()
    fail += fail_refill

    from .t17 import run_t17_cases
    total_t17, fail_t17 = run_t17_cases()
    fail += fail_t17

    from .t18 import run_t18_cases
    total_t18, fail_t18 = run_t18_cases()
    fail += fail_t18

    from .t19 import run_t19_cases
    total_t19, fail_t19 = run_t19_cases()
    fail += fail_t19

    from .t24 import run_t24_cases
    total_t24, fail_t24 = run_t24_cases()
    fail += fail_t24

    from .t28 import run_t28_cases
    total_t28, fail_t28 = run_t28_cases()
    fail += fail_t28

    from .t31 import run_t31_cases, run_t31_j2_cases
    total_t31, fail_t31 = run_t31_cases()
    fail += fail_t31

    total_t31j2, fail_t31j2 = run_t31_j2_cases()
    fail += fail_t31j2

    from .t34 import run_t34_cases
    total_t34, fail_t34 = run_t34_cases()
    fail += fail_t34

    from .t36 import run_t36_cases
    total_t36, fail_t36 = run_t36_cases()
    fail += fail_t36

    from .t37 import run_t37_cases
    total_t37, fail_t37 = run_t37_cases()
    fail += fail_t37
    from .t38 import run_t38_cases
    total_t38, fail_t38, skipped_t38 = run_t38_cases()
    fail += fail_t38
    from .t39 import run_t39_cases
    total_t39, fail_t39 = run_t39_cases()
    fail += fail_t39

    total = (len(cases) + 1 + total_s1b + total_s1c + total_s1c_long + total_s1d
             + total_self_idle + total_round3 + total_round4 + total_round5 + total_seq + total_caps + total_conditions + total_drain + total_refill + total_t17 + total_t18 + total_t19 + total_t24 + total_t28 + total_t31 + total_t31j2 + total_t34 + total_t36 + total_t37 + total_t38 + total_t39)
    skipped = skipped_round3 + skipped_round4 + skipped_caps + skipped_t38
    if skipped:
        print(f"== 结果：{total - fail}/{total} 份计划的预期条款被命中（跳过 {skipped} 份：无真实数据）==")
    else:
        print(f"== 结果：{total - fail}/{total} 份计划的预期条款被命中 ==")
    return 0 if fail == 0 else 1


def _run_s1b_cases() -> tuple[int, int]:
    """构造 6 份 1b 两车型换型的故意违规计划，确认判定器命中 C4/C8/CHANGEOVER/C14。

    直接从 _reference-plan.json 深拷贝后做单点改动，用判定器自身库存重算回填，保证
    对账一致，只暴露「故意」的违规条款。返回 (份数, 失败数)。
    """
    import copy as _copy
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    S1B = ROOT / "cases" / "1b-two-models-changeover"
    raw_in = json.loads((S1B / "input.json").read_text(encoding="utf-8"))
    ref = json.loads((S1B / "_reference-plan.json").read_text(encoding="utf-8"))
    inp = InputModel(raw_in)

    # 从逐日流量重建一份与判定器重算一致的计划（bod/eod/fok/fin/bl 全部回填）
    def _rebuld(plan_days):
        plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE",
                "days": plan_days, "stop_list": [],
                "objective": {"levels": []}, "findings": []}
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

    def _judge(plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        got = sorted({e.rule for e in j.hard_errors})
        return j, got

    def _report(name, exp, got, j, fails):
        ok = all(e in got for e in exp)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails.append(name)
        print(f"[{mark}] {name}")
        print(f"   预期条款      : {exp}")
        print(f"   实得条款      : {got}")
        print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
              f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
              f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
              f"L4={j.objective['L4']} L5={j.objective['L5']}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
        return fails

    fails: list[str] = []

    # 1) C4：同一天 BS1、BS2 都有正流量。挑一个换型前的正常日 03-05，让闲置线 BS2 也产 8 台 B。
    days = _copy.deepcopy(ref["days"])
    d5 = next(d for d in days if d["date"] == "2026-03-05")
    d5["workshops"]["BS2"]["mode"] = "SINGLE_8H"
    d5["workshops"]["BS2"]["hours"] = 8
    d5["workshops"]["BS2"]["in"] = {"B": 8}
    d5["workshops"]["BS2"]["out"] = {"B": 8}
    j, got = _judge(_rebuld(days))
    fails = _report("C4 同一天 BS1/BS2 都有流量（03-05）", ["C4"], got, j, fails)

    # 2) C8：闲置线有在制。给期初 BS2 一份在制（B 5 台），换型前 BS2 一直闲置却持有在制，
    #    触发「闲置线保持 0」的 C8。
    raw_in2 = _copy.deepcopy(raw_in)
    raw_in2["initial"]["wip"] = _copy.deepcopy(raw_in2["initial"].get("wip", {}))
    raw_in2["initial"]["wip"].setdefault("BS2", {})["B"] = 5
    inp2 = InputModel(raw_in2)
    j2 = Judge(inp2, _rebuld(_copy.deepcopy(ref["days"])))
    j2.recompute_inventory()
    j2.reconcile()
    j2.compute_phases()
    check_all(j2)
    j2.compute_objective()
    got2 = sorted({e.rule for e in j2.hard_errors})
    ok2 = "C8" in got2
    if not ok2:
        fails.append("C8 闲置线有在制")
    print(f"[{'PASS' if ok2 else 'FAIL'}] C8 闲置线有在制（期初 BS2 有在制 5）")
    print(f"   预期条款      : ['C8']")
    print(f"   实得条款      : {got2}")
    print(f"   判定     : {'REJECT' if j2.hard_errors else 'ACCEPT'}  L2={j2.objective['L2']}")
    for e in j2.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # 3) CHANGEOVER：换型期内旧线还在投入。03-18 仍在换型期内，旧线 BS1 又投入 5 台 A。
    days = _copy.deepcopy(ref["days"])
    d18 = next(d for d in days if d["date"] == "2026-03-18")
    d18["workshops"]["BS1"]["mode"] = "SINGLE_8H"
    d18["workshops"]["BS1"]["hours"] = 8
    d18["workshops"]["BS1"]["in"] = {"A": 5}
    d18["workshops"]["BS1"]["out"] = {}
    j, got = _judge(_rebuld(days))
    fails = _report("CHANGEOVER 换型期旧线仍投入（03-18 BS1 IN=5）", ["CHANGEOVER"], got, j, fails)

    # 4) CHANGEOVER：新线未到目标就向 WBS 出车（逐级补满）。03-18 新线 BS2 未达 69，
    #    却产出向 WBS 送车（OUT>0），触发其在 WBS / PS 的逐级补满违规。
    days = _copy.deepcopy(ref["days"])
    d18 = next(d for d in days if d["date"] == "2026-03-18")
    d18["workshops"]["BS2"]["out"] = {"B": 5}
    j, got = _judge(_rebuld(days))
    fails = _report("CHANGEOVER 新线未到 69 就出车（03-18 BS2 OUT=5）", ["CHANGEOVER"], got, j, fails)

    # 5) C14：换型期外 PS 不满产而 WBS 高于目标（镜像不成立）。03-20 是换型结束后的正常日，
    #    让 BS2 满产 64，但 PS 只吃 32（留 32 在 WBS，使 WBS=69>37），PS 投入 32<80 不满产，
    #    WBS 高于目标 → 镜像不成立 → C14。
    days = _copy.deepcopy(ref["days"])
    d20 = next(d for d in days if d["date"] == "2026-03-20")
    d20["workshops"]["PS"]["in"] = {"B": 32}
    d20["workshops"]["PS"]["out"] = {"B": 32}
    d20["workshops"]["AS_MAIN"]["in"] = {"B": 32}
    d20["workshops"]["AS_MAIN"]["out"] = {"B": 32}
    d20["workshops"]["AS_FIN"]["in"] = {"B": 32}
    d20["workshops"]["AS_FIN"]["out"] = {"B": 32}
    j, got = _judge(_rebuld(days))
    fails = _report("C14 换型期外 PS 不满产且 WBS 高于目标（03-20）", ["C14"], got, j, fails)

    # 6) CHANGEOVER：清线日旧线仍在投入。03-17 是旧线 BS1 的清线日（OUT=69），
    #    又给它投入 10 台 A（旧线未清到 0、清线日仍在投入）→ 记 CHANGEOVER。
    days = _copy.deepcopy(ref["days"])
    d17 = next(d for d in days if d["date"] == "2026-03-17")
    d17["workshops"]["BS1"]["in"] = {"A": 10}
    j, got = _judge(_rebuld(days))
    fails = _report("CHANGEOVER 清线日旧线仍投入（03-17 BS1 IN=10）", ["CHANGEOVER"], got, j, fails)

    return 6, len(fails)


def _run_s1c_cases() -> tuple[int, int]:
    """构造 3 份 1c 单车型短停的故意违规计划，确认判定器命中
    PS_PRE_STOP / C3(停线日流量) / C8(短停复工日硬下限)。

    rev 153 短停不补线：复工首日 04-06 即为 NORMAL，不再有 REFILL；原 T-04 第 3 份
    自测依赖「短停后补线」，已改为新口径（见下方第 3 份）。

    直接从 _reference-plan.json 深拷贝后做单点改动，用判定器自身库存重算回填，
    保证对账一致，只暴露「故意」的违规条款。返回 (份数, 失败数)。
    """
    import copy as _copy
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    S1C = ROOT / "cases" / "1c-short-stop"
    raw_in = json.loads((S1C / "input.json").read_text(encoding="utf-8"))
    ref = json.loads((S1C / "_reference-plan.json").read_text(encoding="utf-8"))
    inp = InputModel(raw_in)

    def _rebuld(plan_days):
        plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE",
                "days": plan_days, "stop_list": ref.get("stop_list", []),
                "objective": {"levels": []}, "findings": []}
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

    def _judge(plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        got = sorted({e.rule for e in j.hard_errors})
        return j, got

    def _report(name, exp, got, j, fails):
        ok = all(e in got for e in exp)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails.append(name)
        print(f"[{mark}] {name}")
        print(f"   预期条款      : {exp}")
        print(f"   实得条款      : {got}")
        print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
              f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
              f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
              f"L4={j.objective['L4']} L5={j.objective['L5']}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
        return fails

    fails: list[str] = []

    # 1) PS_PRE_STOP：停前日 04-01 PS 日末 132 ≠ 131。把 PS out 由 80 改为 79，
    #    并把 AS_MAIN/AS_FIN 同步改为 79，使下游守恒、其余节点仍达目标，
    #    只暴露 PS_PRE_STOP（EOD=147+64-79=132）。
    days = _copy.deepcopy(ref["days"])
    d01 = next(d for d in days if d["date"] == "2026-04-01")
    d01["workshops"]["PS"]["out"] = {"A": 79}
    d01["workshops"]["AS_MAIN"]["in"] = {"A": 79}
    d01["workshops"]["AS_MAIN"]["out"] = {"A": 79}
    d01["workshops"]["AS_FIN"]["in"] = {"A": 79}
    d01["workshops"]["AS_FIN"]["out"] = {"A": 79}
    j, got = _judge(_rebuld(days))
    fails = _report("PS_PRE_STOP 停前日 PS 132 ≠ 131（04-01）", ["PS_PRE_STOP"], got, j, fails)

    # 2) 停线日有流量：04-02 是停线窗口首个自然日（不可生产假日），给 BS1 加正流量
    #    → 违反不可生产日只能 OFF（C3）。对应条款 = C3。
    days = _copy.deepcopy(ref["days"])
    d02 = next(d for d in days if d["date"] == "2026-04-02")
    d02["workshops"]["BS1"]["mode"] = "SINGLE_8H"
    d02["workshops"]["BS1"]["hours"] = 8
    d02["workshops"]["BS1"]["in"] = {"A": 8}
    d02["workshops"]["BS1"]["out"] = {"A": 8}
    j, got = _judge(_rebuld(days))
    fails = _report("停线日 04-02 BS1 有流量 → C3", ["C3"], got, j, fails)

    # 3) C8：短停复工日 04-06 为 NORMAL（rev 153 短停不补线，不再有 REFILL 放宽），
    #    让 BS1 只供 16 台（WBS 入 16）、PS 仍从 WBS 取 32 台（WBS 出 32），
    #    WBS 日末 37+16-32=21 < 37 → NORMAL 日 C8 七节点硬下限报 C8。
    #    PS 进 32 出 16，日末 131+32-16=147 达标，不触发 PS 违规。
    #    （改自 T-04 旧用例「REFILL 补线日 WBS 未达目标仍向 PS 供车」：旧口径补线期
    #    不查 C8、由 REFILL 逐级补满报 REFILL；新口径短停不触发补线，04-06 复工即
    #    NORMAL，同一工况改报 C8。）
    days = _copy.deepcopy(ref["days"])
    d06 = next(d for d in days if d["date"] == "2026-04-06")
    d06["workshops"]["BS1"]["in"] = {"A": 16}
    d06["workshops"]["BS1"]["out"] = {"A": 16}
    d06["workshops"]["PS"]["in"] = {"A": 32}
    d06["workshops"]["PS"]["out"] = {"A": 16}
    d06["workshops"]["AS_MAIN"]["in"] = {"A": 16}
    d06["workshops"]["AS_MAIN"]["out"] = {"A": 16}
    d06["workshops"]["AS_FIN"]["in"] = {"A": 16}
    d06["workshops"]["AS_FIN"]["out"] = {"A": 16}
    j, got = _judge(_rebuld(days))
    fails = _report("C8 短停复工日 WBS 未达目标（04-06 NORMAL，rev 153）", ["C8"], got, j, fails)

    return 3, len(fails)


def _run_s1c_long_cases() -> tuple[int, int]:
    """构造 5 份 1c 长停（BS 清线 / 补线）的故意违规计划，确认判定器命中
    BS_CLEAR / C8，以及 C15 镜像扩展（上游 WBS 清线时 PS 不满产不报 C14）。

    直接从 _reference-plan.json 深拷贝后做单点改动，用判定器自身库存重算回填，
    保证对账一致，只暴露「故意」的违规条款。返回 (份数, 失败数)。

    关键日（reference 手算，见 cases/1c-long-stop/README.md）：
    - 02-12 清线日：BS1(0,67)、PS(80,80) → BS1 EOD 0、WBS 24、PS 147
    - 02-13 清线日+停前日：BS1(0,0)、PS(24,80) → WBS 0、PS 91
    - 03-02 补线首日：BS1(80,13)、PS(0,0)
    """
    import copy as _copy
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    S1C = ROOT / "cases" / "1c-long-stop"
    raw_in = json.loads((S1C / "input.json").read_text(encoding="utf-8"))
    ref = json.loads((S1C / "_reference-plan.json").read_text(encoding="utf-8"))
    inp = InputModel(raw_in)

    def _rebuld(plan_days):
        plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE",
                "days": plan_days, "stop_list": ref.get("stop_list", []),
                "objective": {"levels": []}, "findings": []}
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

    def _judge(plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        got = sorted({e.rule for e in j.hard_errors})
        return j, got

    def _report(name, exp, got, j, fails):
        ok = all(e in got for e in exp)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails.append(name)
        print(f"[{mark}] {name}")
        print(f"   预期条款      : {exp}")
        print(f"   实得条款      : {got}")
        print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
              f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
              f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
              f"L4={j.objective['L4']} L5={j.objective['L5']}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
        return fails

    fails: list[str] = []

    # 1) 清线期仍投入：02-13 是清线期（02-12 清线日 IN=0 起、WBS 尚未清空），BS1 又投入
    #    10 台 → BS_CLEAR（清线期仍投入）。
    days = _copy.deepcopy(ref["days"])
    d13 = next(d for d in days if d["date"] == "2026-02-13")
    d13["workshops"]["BS1"]["in"] = {"A": 10}
    d13["workshops"]["BS1"]["mode"] = "SINGLE_8H"
    d13["workshops"]["BS1"]["hours"] = 8
    j, got = _judge(_rebuld(days))
    fails = _report("BS_CLEAR 清线期仍投入（02-13 BS1 IN=10）", ["BS_CLEAR"], got, j, fails)

    # 2) 清空后留空档：把清空日提前到 02-12（PS 02-12 吃 104 清空 WBS，超能力 C2），
    #    02-13 BS1 空档（工作日未紧贴停线）→ BS_CLEAR。
    #    rev 203：02-13 PS 不投入、出 80 降库，尾巴 80 > 清线前一天可少投的 67，按躲不掉的
    #    清线尾日不再报空档；这份计划仍因 PS 超能力投入被 C2 / PS_PRE_STOP 拒收。
    #    可躲的尾巴仍报 BS_CLEAR，由 T-18 ③（零头放在清线后）覆盖。
    days = _copy.deepcopy(ref["days"])
    d12 = next(d for d in days if d["date"] == "2026-02-12")
    d12["workshops"]["PS"]["in"] = {"A": 104}
    d13 = next(d for d in days if d["date"] == "2026-02-13")
    d13["workshops"]["PS"]["in"] = {}
    j, got = _judge(_rebuld(days))
    fails = _report("清空后 PS 只降库（02-12 超能力清空、02-13 降库尾日）", ["C2", "PS_PRE_STOP"], got, j, fails)

    # 3) 降库期 PS 少投（T-17 起）：02-12 是首个 BS 清线日（降库期首日，非停前日），PS 少进
    #    40 台 → 不再按 C8 判（降库期 PS 不查 C8），改由「能做尽做」公式记 PS_PRE_STOP
    #    （投入 40 ≠ min(80, WBS 日初 37 + 焊装出车 67) = 80）。
    days = _copy.deepcopy(ref["days"])
    d12 = next(d for d in days if d["date"] == "2026-02-12")
    d12["workshops"]["PS"]["in"] = {"A": 40}
    j, got = _judge(_rebuld(days))
    fails = _report("PS_PRE_STOP 降库期 PS 少投（02-12 PS 进 40 而非 80，原先判 C8）", ["PS_PRE_STOP"], got, j, fails)

    # 4) 降库期 PS 少投少出（T-17 起）：02-12 上游 WBS 正在清线，PS 进 40/出 40（不满产）。
    #    rev 185 撤销了降库期 PS 的 C15 镜像「上游清线可少产」豁免，且「能做尽做」公式要求
    #    出车 = min(80, PS 日初 147 + 投入 40 − 停前目标 91) = 80，故记 PS_PRE_STOP。
    days = _copy.deepcopy(ref["days"])
    d12 = next(d for d in days if d["date"] == "2026-02-12")
    d12["workshops"]["PS"]["in"] = {"A": 40}
    d12["workshops"]["PS"]["out"] = {"A": 40}
    d12["workshops"]["AS_MAIN"]["in"] = {"A": 40}
    d12["workshops"]["AS_MAIN"]["out"] = {"A": 40}
    d12["workshops"]["AS_FIN"]["in"] = {"A": 40}
    d12["workshops"]["AS_FIN"]["out"] = {"A": 40}
    j, got = _judge(_rebuld(days))
    ok4 = "PS_PRE_STOP" in got
    mark4 = "PASS" if ok4 else "FAIL"
    if not ok4:
        fails.append("降库期 PS 少投少出")
    print(f"[{mark4}] PS_PRE_STOP 降库期 PS 少投少出（02-12 进 40/出 40，原先 C15 镜像豁免）")
    print(f"   预期条款      : ['PS_PRE_STOP']")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
          f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
          f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
          f"L4={j.objective['L4']} L5={j.objective['L5']}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # 5) 长停未清线（评审退回）：02-12 BS1 仍投入 10，BS1 带 10 台进入长停（不再有
    #    IN=0;OUT>0 的清线日）。长停识别须按零流窗口长度（≥ Lg）而非清线日，窗口前
    #    最后一天该线 EOD≠0 → BS_CLEAR。_rebuld 用重算 EOD 回填，C1 对账不报。
    days = _copy.deepcopy(ref["days"])
    d12 = next(d for d in days if d["date"] == "2026-02-12")
    d12["workshops"]["BS1"]["in"] = {"A": 10}
    j, got = _judge(_rebuld(days))
    fails = _report("BS_CLEAR 长停未清线（02-12 BS1 仍投入 10，带 10 台进入长停）", ["BS_CLEAR"], got, j, fails)

    return 5, len(fails)


def _run_s1d_cases() -> tuple[int, int]:
    """构造 5 份 1d 的故意违规计划，确认判定器命中 REFILL / FIRST_START / CHANGEOVER /
    PS_PRE_STOP / C14（验收条件 3）。

    直接从新算例的 _reference-plan.json / counter/*.plan.json 深拷贝后做单点改动，
    用判定器自身库存重算回填，保证对账一致，只暴露「故意」的违规条款。返回 (份数, 失败数)。
    """
    import copy as _copy
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    fails: list[str] = []

    def _load(case: str, plan_file: str):
        raw_in = json.loads((ROOT / "cases" / case / "input.json").read_text(encoding="utf-8"))
        plan = json.loads((ROOT / "cases" / case / plan_file).read_text(encoding="utf-8"))
        return InputModel(raw_in), plan

    def _judge(inp, plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        return j, sorted({e.rule for e in j.hard_errors})

    def _report(name, exp, got, j, fails):
        ok = all(e in got for e in exp)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails.append(name)
        print(f"[{mark}] {name}")
        print(f"   预期条款      : {exp}")
        print(f"   实得条款      : {got}")
        print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
              f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
              f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
              f"L4={j.objective['L4']} L5={j.objective['L5']}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
        return fails

    # 1) REFILL：期初补线首日 PS 未达标就向 PBS 供车（1d-initial-refill 反例）
    inp, plan = _load("1d-initial-refill", "counter/refill-ps-leak.plan.json")
    j, got = _judge(inp, plan)
    fails = _report("REFILL 期初补线 PS 未达标即向 PBS 供车", ["REFILL"], got, j, fails)

    # 2) FIRST_START：B 首次出车当天 BS2 日末低于目标（1d-first-start-changeover 反例）
    inp, plan = _load("1d-first-start-changeover", "counter/first-start-early.plan.json")
    j, got = _judge(inp, plan)
    fails = _report("FIRST_START B 首次出车当天 BS2 日末低于目标", ["FIRST_START"], got, j, fails)

    # 3) CHANGEOVER：第二次换型旧线 BS2 未清空就开 BS1（1d-first-start-changeover 反例）
    inp, plan = _load("1d-first-start-changeover", "counter/second-change-dirty.plan.json")
    j, got = _judge(inp, plan)
    fails = _report("CHANGEOVER 第二次换型旧线 BS2 未清空就开 BS1", ["CHANGEOVER"], got, j, fails)

    # 4) PS_PRE_STOP：日历把停线拉到 15 天长停，停前却按短停目标 131
    #    （1d-year-end-stop-calendar 反例 calendar-ignored）
    inp, plan = _load("1d-year-end-stop-calendar", "counter/calendar-ignored.plan.json")
    j, got = _judge(inp, plan)
    fails = _report("PS_PRE_STOP 日历拉到长停却仍用 131", ["PS_PRE_STOP"], got, j, fails)

    # 4b) 不报错：年末停线按 6 天短停推算、停前目标 131（结果相同，应为 ACCEPT）
    inp, plan = _load("1d-year-end-stop", "_reference-plan.json")
    j, got = _judge(inp, plan)
    ok = "PS_PRE_STOP" not in got and j.hard_errors == []
    mark = "PASS" if ok else "FAIL"
    if not ok:
        fails.append("PS_PRE_STOP 6 天短停不误报")
    print(f"[{mark}] PS_PRE_STOP 6 天短停取 131 不误报（尾停推算长度正确）")
    print(f"   预期条款      : 无")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
    print()

    # 5) C14：计划期首日在停线、期初已达标 → 复工首日应为 NORMAL，PS 不满产记 C14
    #    （不应误判为 REFILL 而放宽）。构造：1d-initial-refill 输入改期初为达标，
    #    复工 01-05 PS 只进 40（< 80 满产），且上游 WBS 期初在目标之上（无镜像）。
    raw_in = json.loads((ROOT / "cases" / "1d-initial-refill" / "input.json").read_text(encoding="utf-8"))
    # 期初全部改为等于目标，使期初不触发补线
    raw_in["initial"]["wip"] = {
        "BS1": {"A": 70}, "WBS": {"A": 35}, "PS": {"A": 150},
        "PBS": {"A": 45}, "AS_MAIN": {"A": 100}, "AS_FIN": {"A": 80},
    }
    inp5 = InputModel(raw_in)
    ref5 = json.loads((ROOT / "cases" / "1d-initial-refill" / "_reference-plan.json").read_text(encoding="utf-8"))
    days5 = _copy.deepcopy(ref5["days"])
    d05 = next(d for d in days5 if d["date"] == "2026-01-05")
    # 复工 01-05：PS 少进（40 而不是 65），其余照常；PS 日末 150+40-55=135 < 150 会先触发 C8。
    # 这里让 PS 少出也少进，只改 PS 投入为 40、产出 40，使 PS 日末保持 150（不低于目标），
    # 从而暴露「段中不满产」的 C14（上游 WBS 期初已在目标，镜像不成立）。
    d05["workshops"]["PS"]["in"] = {"A": 40}
    d05["workshops"]["PS"]["out"] = {"A": 40}
    d05["workshops"]["AS_MAIN"]["in"] = {"A": 40}
    d05["workshops"]["AS_MAIN"]["out"] = {"A": 40}
    d05["workshops"]["AS_FIN"]["in"] = {"A": 40}
    d05["workshops"]["AS_FIN"]["out"] = {"A": 40}
    plan5 = {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days5,
             "stop_list": ref5.get("stop_list", []), "objective": {"levels": []}, "findings": []}
    j5 = Judge(inp5, plan5)
    j5.recompute_inventory()
    for d in plan5["days"]:
        ds = d["date"]
        d["bod"] = {n: {m: v for m, v in per.items() if v} for n, per in j5.bod[ds].items() if any(per.values())}
        d["eod"] = {n: {m: v for m, v in per.items() if v} for n, per in j5.eod[ds].items() if any(per.values())}
        d["fok"] = {m: v for m, v in j5.fok[ds].items() if v}
        d["fin"] = {m: v for m, v in j5.fin[ds].items() if v}
        d["bl"] = {m: v for m, v in j5.bl[ds].items() if v}
    j5 = Judge(inp5, plan5)
    j5.recompute_inventory()
    j5.reconcile()
    j5.compute_phases()
    check_all(j5)
    j5.compute_objective()
    got5 = sorted({e.rule for e in j5.hard_errors})
    ok5 = "C14" in got5 and "REFILL" not in got5
    mark5 = "PASS" if ok5 else "FAIL"
    if not ok5:
        fails.append("C14 期初达标复工日 PS 不满产")
    print(f"[{mark5}] C14 期初达标复工日 PS 不满产（不应误判 REFILL 放宽）")
    print(f"   预期条款      : 含 C14、不含 REFILL")
    print(f"   实得条款      : {got5}")
    print(f"   判定     : {'REJECT' if j5.hard_errors else 'ACCEPT'}")
    for e in j5.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    return 5, len(fails)


def _run_self_idle_case() -> tuple[int, int]:
    """构造 1 份「需求排完后月末自建空闲 ≥3 天（不碰计划期末）」的故意违规计划，
    确认停前日 PS 未降到停前目标时判定器命中 PS_PRE_STOP（§9 待你决定：需求排完后的
    自建空闲 ≥3 天与假期一样触发停前目标）。

    用一份跨两个月的自建输入（03-30..04-10）：3 月 PR 只有 80，03-30 产 80 即排完，
    03-31..04-03 自建空闲（连周末 04-04/05 合并 6 天零流窗口），04-06 起产 4 月需求。
    窗口不碰计划期末（04-10），停前日 03-30 PS 停在 147 未降到 131 → PS_PRE_STOP。
    返回 (份数, 失败数)。
    """
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    raw_in = json.loads(CASE_INPUT.read_text(encoding="utf-8"))
    # 换一份跨两个月（03-30..04-10）的自建输入；factory/initial/targets/rules 沿用 1a。
    raw_in["horizon"] = {"start": "2026-03-30", "end": "2026-04-10"}
    working = ("2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03",
               "2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10")
    raw_in["calendar"] = [
        {"date": d, "is_working_capable": d in working}
        for d in ("2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03",
                  "2026-04-04", "2026-04-05", "2026-04-06", "2026-04-07", "2026-04-08",
                  "2026-04-09", "2026-04-10")
    ]
    raw_in["demand"] = {
        "PR": {"A": {"2026-03": 80, "2026-04": 400}},
        "WS_daily": {"A": {"2026-04-10": 480}},
    }
    inp = InputModel(raw_in)

    # 03-30 产 80（3 月排完，PS 未降到 131）；03-31..04-03 自建空闲；04-06..04-10 产 4 月。
    flows: dict[str, dict[str, int]] = {}
    flows["2026-03-30"] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    for d in ("2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"):
        flows[d] = {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")}
    # 03-31..04-03 全车间零流（自建空闲），04-04/05 周末零流
    for d in ("2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03"):
        flows[d] = {}

    plan = build_plan(inp, flows)
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    got = sorted({e.rule for e in j.hard_errors})
    ok = "PS_PRE_STOP" in got
    mark = "PASS" if ok else "FAIL"
    fail = 0 if ok else 1
    print(f"[{mark}] PS_PRE_STOP 需求排完后月末自建空闲 3 天停前未降（03-31..04-03）")
    print(f"   预期条款      : ['PS_PRE_STOP']")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()
    return 1, fail


def _run_round3_cases() -> tuple[int, int, int]:
    """构造 3 份第三轮（rev 163 修补）自检，用真实全年计划（1d-annual-feedback pass）与
    1c-long-stop 参考计划验证：多日清线（线先空、WBS 后空）不报 C8/C14；补线中 PS 低于
    目标且不供车不报 C8/C13；补线首日 PS 等车不计入停线（停线清单长度不变）。

    返回 (运行份数, 失败数, 跳过份数)。
    """
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    ANN = ROOT / "cases" / "1d-annual-feedback"
    fails: list[str] = []

    def _errs_by_date(j):
        # {date: [rule,...]}，便于按日断言「某天不报某条款」
        out = {}
        for e in j.hard_errors:
            out.setdefault(e.date, []).append(e.rule)
        return out

    def _judge(inp, plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        return j

    skipped = 0
    if all(p.exists() for p in (ANN / "feedback-pass.input.json",
                               ANN / "_out" / "T-07-feedback-pass-1.plan.json")):
        # ---- 1) 多日清线（线先空、WBS 后空）不报 C8/C14 ----
        raw_in = json.loads((ANN / "feedback-pass.input.json").read_text(encoding="utf-8"))
        plan = json.loads((ANN / "_out" / "T-07-feedback-pass-1.plan.json").read_text(encoding="utf-8"))
        inp = InputModel(raw_in)
        j = _judge(inp, plan)
        by_date = _errs_by_date(j)
        clear_ok = True
        for day in ("2026-02-12", "2026-02-13", "2026-02-14", "2026-07-22", "2026-07-23", "2026-07-24"):
            ph = j.phases.get(day, "")
            if "BS_CLEAR" not in ph.split("+"):
                clear_ok = False
                fails.append(f"多日清线：{day} 阶段 {ph} 缺 BS_CLEAR")
            for bad in ("C8", "C14"):
                if bad in by_date.get(day, []):
                    clear_ok = False
                    fails.append(f"多日清线：{day} 误报 {bad}")
        mark = "PASS" if clear_ok else "FAIL"
        print(f"[{mark}] 多日清线（线先空、WBS 后空）不报 C8/C14（全年 pass 02-12..14、07-22..24）")
        print("   预期条款      : 02-12..14 / 07-22..24 均为 BS_CLEAR，且不报 C8/C14")
        print("   实得条款      : " + json.dumps({d: j.phases.get(d) for d in
              ("2026-02-12", "2026-02-13", "2026-02-14", "2026-07-22", "2026-07-23", "2026-07-24")}, ensure_ascii=False))
        for e in j.hard_errors:
            if e.date in ("2026-02-12", "2026-02-13", "2026-02-14", "2026-07-22", "2026-07-23", "2026-07-24"):
                print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
        print()

        # ---- 2) 补线中 PS 低于目标且不供车不报 C8/C13 ----
        refill_ok = True
        for day, ps_eod in (("2026-03-12", 146), ("2026-08-11", 146)):
            ph = j.phases.get(day, "")
            if "REFILL" not in ph.split("+"):
                refill_ok = False
                fails.append(f"补线：{day} 阶段 {ph} 缺 REFILL")
            for bad in ("C8", "C13"):
                if bad in by_date.get(day, []):
                    refill_ok = False
                    fails.append(f"补线：{day}（PS EOD {ps_eod} < 150）误报 {bad}")
        mark2 = "PASS" if refill_ok else "FAIL"
        print(f"[{mark2}] 补线中 PS 低于目标且不供车不报 C8/C13（全年 pass 03-12、08-11）")
        print("   预期条款      : 03-12 / 08-11 均为 REFILL，PS 146<150 不报 C8、总装空闲不报 C13")
        print("   实得条款      : " + json.dumps({d: j.phases.get(d) for d in
              ("2026-03-11", "2026-03-12", "2026-03-13", "2026-08-10", "2026-08-11", "2026-08-12")}, ensure_ascii=False))
        for e in j.hard_errors:
            if e.date in ("2026-03-11", "2026-03-12", "2026-03-13", "2026-08-10", "2026-08-11", "2026-08-12"):
                print(f"     - {e.rule} {e.date} {e.node} {e.detail}")
        print()
    else:
        print("跳过（无真实数据）：多日清线（线先空、WBS 后空）不报 C8/C14（全年 pass 02-12..14、07-22..24）")
        print("跳过（无真实数据）：补线中 PS 低于目标且不供车不报 C8/C13（全年 pass 03-12、08-11）")
        skipped = 2

    # ---- 3) 补线首日 PS 等车不计入停线（停线清单长度不变） ----
    raw_in3 = json.loads((ROOT / "cases" / "1c-long-stop" / "input.json").read_text(encoding="utf-8"))
    plan3 = json.loads((ROOT / "cases" / "1c-long-stop" / "_reference-plan.json").read_text(encoding="utf-8"))
    inp3 = InputModel(raw_in3)
    j3 = _judge(inp3, plan3)
    stop3_ok = True
    ph0302 = j3.phases.get("2026-03-02", "")
    if "STOP" in ph0302.split("+"):
        stop3_ok = False
        fails.append(f"停线截断：03-02 阶段 {ph0302} 仍含 STOP")
    if "REFILL" not in ph0302.split("+"):
        stop3_ok = False
        fails.append(f"停线截断：03-02 阶段 {ph0302} 缺 REFILL")
    win = next((w for w in j3.stop_windows if w["start"] == "2026-02-14"), None)
    if win is None or win["end"] != "2026-03-01" or win["length"] != 16:
        stop3_ok = False
        fails.append(f"停线截断：停线窗口 {win} 未保持 16 天（02-14..03-01）")
    mark3 = "PASS" if stop3_ok else "FAIL"
    print(f"[{mark3}] 补线首日 PS 等车不计入停线（1c-long-stop 03-02 = REFILL，停线长度 16 不变）")
    print(f"   预期条款      : 03-02 为 REFILL 非 STOP；停线窗口 02-14..03-01 长 16")
    print(f"   实得条款      : 03-02 = {ph0302}；窗口 " + json.dumps(win, ensure_ascii=False) if win else "无")
    print()

    return 3 - skipped, len(fails), skipped


def _run_round4_case() -> tuple[int, int, int]:
    """构造 1 份第四轮自检：两车型、A 在 BS1 清线中（02-13 清线第三天 BS1 0/0）、BS2
    （绑定车型 B，当月 PR 为 0）空闲。按 C13「只在**该车型**…时成立」，焊装线 BS2 只判
    其绑定车型 B（cumFOK 0 ≥ cumPR 0，已排完），空闲合法、不报 C13（共享车间才看所有车型）。

    用全年 pass 计划的 02-13（A 在 BS1 清线、BS2 空闲、B 尚未开工）验证：修后该日不再报
    C13（BS2），整份计划应为 ACCEPT。返回 (运行份数, 失败数, 跳过份数)。
    """
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    ANN = ROOT / "cases" / "1d-annual-feedback"
    if not all(p.exists() for p in (ANN / "feedback-pass.input.json",
                                   ANN / "_out" / "T-07-feedback-pass-1.plan.json")):
        print("跳过（无真实数据）：C13 焊装线只判绑定车型（A 在 BS1 清线、BS2 当月 PR=0 空闲 → 不报 C13）")
        return 0, 0, 1
    raw_in = json.loads((ANN / "feedback-pass.input.json").read_text(encoding="utf-8"))
    plan = json.loads((ANN / "_out" / "T-07-feedback-pass-1.plan.json").read_text(encoding="utf-8"))
    inp = InputModel(raw_in)
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()

    fails: list[str] = []
    c13_bs2 = [e for e in j.hard_errors if e.rule == "C13" and e.node == "BS2"]
    ok = len(c13_bs2) == 0
    mark = "PASS" if ok else "FAIL"
    if not ok:
        fails.append("焊装线 C13 只判绑定车型")
    print(f"[{mark}] C13 焊装线只判绑定车型（A 在 BS1 清线、BS2 当月 PR=0 空闲 → 不报 C13）")
    print("   预期条款      : 不含 C13（BS2）")
    print(f"   实得条款      : {sorted({e.rule for e in j.hard_errors})}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
          f"L1a={j.objective['L1a']} L1b={j.objective['L1b']} L1c={j.objective['L1c']} "
          f"L2={j.objective['L2']} L3a={j.objective['L3a']} L3b={j.objective['L3b']} "
          f"L4={j.objective['L4']} L5={j.objective['L5']}")
    for e in j.hard_errors:
        if e.date == "2026-02-13":
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()
    return 1, len(fails), 0


def _run_round5_cases() -> tuple[int, int]:
    """构造 2 份第五轮（CLR-07）自检，基于 1c-long-stop：清线前一天（02-11）BS1 减量投入
    40 台（日末仍达目标）不报 C14；清线前两天（02-10）BS1 减量投入 40 台报 C14。

    清线开始日 = 02-12（BS1 0/67），故清线前一天 = 02-11、前两天 = 02-10。减量投入那天
    下游（PS/AS_MAIN/AS_FIN）同步减到 40，使各节点日末仍达目标、上游镜像（WBS=PBS=AS_MAIN
    =tgt）让下游不满产合法，只暴露 BS1 自身「段中不满产」是否被 CLR-07 豁免。返回 (份数, 失败数)。
    """
    import copy as _copy
    import json
    from judge.model import InputModel
    from judge.core import Judge
    from judge.constraints import check_all

    S1C = ROOT / "cases" / "1c-long-stop"
    raw_in = json.loads((S1C / "input.json").read_text(encoding="utf-8"))
    ref = json.loads((S1C / "_reference-plan.json").read_text(encoding="utf-8"))
    inp = InputModel(raw_in)

    def _rebuld(plan_days):
        plan = {"schema": "aps-core/plan/v1", "status": "FEASIBLE",
                "days": plan_days, "stop_list": ref.get("stop_list", []),
                "objective": {"levels": []}, "findings": []}
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

    def _judge(plan):
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()
        got = sorted({e.rule for e in j.hard_errors})
        return j, got

    def _shrink(day: dict) -> None:
        """把某天 BS1/PS/AS_MAIN/AS_FIN 减量到 in=out=40（A 车型）。"""
        for w in ("BS1", "PS", "AS_MAIN", "AS_FIN"):
            day["workshops"][w]["in"] = {"A": 40}
            day["workshops"][w]["out"] = {"A": 40}

    fails: list[str] = []

    # 1) 清线前一天（02-11）BS1 减量 40 → 不报 C14（CLR-07 豁免，整份计划 ACCEPT）
    days = _copy.deepcopy(ref["days"])
    d11 = next(d for d in days if d["date"] == "2026-02-11")
    _shrink(d11)
    j, got = _judge(_rebuld(days))
    ok1 = "C14" not in got
    mark1 = "PASS" if ok1 else "FAIL"
    if not ok1:
        fails.append("CLR-07 清线前一天减量不报 C14")
    print(f"[{mark1}] CLR-07 清线前一天减量投入 40 不报 C14（02-11）")
    print("   预期条款      : 不含 C14")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
          f"L1a={j.objective['L1a']} L2={j.objective['L2']} L5={j.objective['L5']}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # 2) 清线前两天（02-10）BS1 减量 40 → 报 C14（非清线前一天，不豁免）
    days = _copy.deepcopy(ref["days"])
    d10 = next(d for d in days if d["date"] == "2026-02-10")
    _shrink(d10)
    j, got = _judge(_rebuld(days))
    ok2 = "C14" in got
    mark2 = "PASS" if ok2 else "FAIL"
    if not ok2:
        fails.append("CLR-07 清线前两天减量报 C14")
    print(f"[{mark2}] CLR-07 清线前两天减量投入 40 报 C14（02-10）")
    print("   预期条款      : ['C14']")
    print(f"   实得条款      : {got}")
    print(f"   判定     : {'REJECT' if j.hard_errors else 'ACCEPT'}  "
          f"L1a={j.objective['L1a']} L2={j.objective['L2']} L5={j.objective['L5']}")
    for e in j.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    return 2, len(fails)


if __name__ == "__main__":
    sys.exit(main())
