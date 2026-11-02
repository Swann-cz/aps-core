"""T-37：没填物理上限的车间不算「下游已到上限」（CORE_MODEL rev 202，C6、C15）。

判定器改动（judge/constraints.py _downstream_full）：下游是车间且没填 cap_max 时，
上限随目标、日末等于目标是常态，不能据此让上游少产（不免 C14）。

自检场景复用 T-36 合成输入（单车型 A、各车间 80/天）：第 4 个正常日总装主线和完成线
只做 30 台，车压在 PBS（150 上限内）。
1. 完成线没填上限 → 总装主线当天报 C14（改动前被「下游已满」放过）；
2. 完成线填上限 40（= 目标，当天日末 40）→ 下游真到上限，总装主线不报 C14；
3. 完成线没填上限，但当天产量由排产条件指定为 30 → 完成线自己受限，总装主线不报 C14。

rev 203（judge/constraints.py check_bs_clear 第 3 项）：焊装清空后仍在 PS 停前降库期、
PS 当天不投入只消化自身在制的工作日属于清线期，不算「清得太早」的空档。
4. 清线前一天焊装投 56 出 80，清线第 1 天焊装出 43、PS 投 80 把 WBS 吃空（02-11 清空），
   02-12（PS 停前日）PS 不投入、出 56 降到停前目标 91 → 不报 BS_CLEAR，整份 ACCEPT；
5. 同上但 02-12 PS 多出 1 台（57，日末 90）→ 由 PS_PRE_STOP 报出（放宽不漏网），仍不报空档。
"""
from __future__ import annotations

import copy

from judge.model import InputModel

from .t36 import CLEAR_D1, CLEAR_D2, NORM_DAYS, _build, _judge, _make_input

LOW_DAY = NORM_DAYS[3]


def _flows() -> dict:
    flows = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in NORM_DAYS}
    flows[LOW_DAY] = {"BS1": 80, "PS": 80, "AS_MAIN": 30, "AS_FIN": 30}
    flows[CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
    flows[CLEAR_D2] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": 80}
    return flows


def run_t37_cases() -> tuple[int, int]:
    failures: list[str] = []
    cases = [("完成线没填上限：总装主线少产报 C14", None, False, True),
             ("完成线填上限 40 且已到上限：总装主线少产不报 C14", 40, False, False),
             ("完成线当天指定产量 30：总装主线跟着少产不报 C14", None, True, False)]
    for name, cap, fixed, expect in cases:
        raw = copy.deepcopy(_make_input())
        if cap is not None:
            raw["factory"]["workshops"]["AS_FIN"]["cap_max"] = cap
        if fixed:
            raw.setdefault("conditions", []).append({"id": "C1", "type": "FIXED_OUTPUT", "reason": "自检",
                                                     "date": LOW_DAY, "workshop": "AS_FIN", "out": 30})
        inp = InputModel(raw)
        j = _judge(inp, _build(inp, _flows()))
        hit = [e for e in j.hard_errors if e.rule == "C14" and e.node == "AS_MAIN" and e.date == LOW_DAY]
        ok = bool(hit) == expect
        if not ok:
            failures.append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] T-37 {name}")
        print(f"   {LOW_DAY} AS_MAIN C14 : 预期 {'有' if expect else '无'}，实得 {'有' if hit else '无'}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
    for name, ps_out, expect_rules in (
            ("焊装清空后 PS 只降库（不投入、出 56 到 91）：不算空档", 56, []),
            ("同上但 PS 多出 1 台：报 PS_PRE_STOP、不报空档", 57, ["PS_PRE_STOP"])):
        inp = InputModel(_make_input())
        flows = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in NORM_DAYS}
        flows[NORM_DAYS[-1]] = {"BS1": (56, 80), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
        flows[CLEAR_D1] = {"BS1": (0, 43), "PS": 80, "AS_MAIN": 80, "AS_FIN": 80}
        flows[CLEAR_D2] = {"PS": (0, ps_out), "AS_MAIN": ps_out, "AS_FIN": ps_out}
        j = _judge(inp, _build(inp, flows))
        got = sorted({e.rule for e in j.hard_errors})
        ok = got == expect_rules and len(j.bs_clear_events) == 1             and j.bs_clear_events[0]["end"] == CLEAR_D1
        if not ok:
            failures.append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] T-37 {name}")
        print(f"   预期条款 : {expect_rules}，清空日 {CLEAR_D1}")
        print(f"   实得条款 : {got}，清线事件 {[(ev['start'], ev['end']) for ev in j.bs_clear_events]}")
        for e in j.hard_errors:
            print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
        print()
        cases.append(name)
    total = len(cases)
    print(f"== T-37 结果：{total - len(failures)}/{total} ==")
    return total, len(failures)


if __name__ == "__main__":
    total, failed = run_t37_cases()
    raise SystemExit(bool(failed))
