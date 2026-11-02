"""T-38：CORE_MODEL rev 204——盖住整次停线的人工目标在制是停前水位；C12 必须提前量。

1. 改造停线例 输入（2/3–3/31 全线改造停线，2 月只有 2/2 一个工作日，授权 11 小时）：
   必须提前量 E(A, 2026-01) = 2 月 PR 424 − 2/2 产能 110 = 314；PS 停前目标取人工目标在制 30，
   PBS / 总装两段停前水位 50 / 0 / 0；
   同一输入若 1/20 起自建空闲接上计划停线（窗口 1/20..3/31），停前水位不变（rev 205 补充）；
2. 人工目标在制只盖住全线停线的一部分 → 条件 INPUT 错误；
3. T-36 合成停线（02-13..02-27）+ 完成线人工目标在制 20 盖住整次停线、完成线能力 104：
   清线两天完成线出 100、80，停前日日末 20 → ACCEPT（降库途中完成线低于目标 40 不报 C8）；
4. 同上但清线第 1 天完成线只出 80（停前日末 40）→ PS_PRE_STOP（停前水位）+ BS_CLEAR（能做尽做）
   + C6（停线期间完成线 40 超过随目标的上限 20）。

rev 205 总装提前降库（停前水位 0、完成线能力 104）：
5. 清线前一天（02-10，正常日）完成线就开始降：进 80 出 104，之后 96、80，停前日 0 → ACCEPT
   （02-10 完成线 16 < 目标 40 不报 C8）；
6. 同上但 02-10 只出 90（能做尽做应为 104），之后 104、86 → PS_PRE_STOP。
7. PBS 停前水位 50、总装主线 60（主线能力 104、完成线 112）：02-09 起提前降库，02-10 PBS 已到 50，
   总装主线只能投 86 < 能力 104（上游 PBS 低于正常目标 80）→ 不报 C14，整份 ACCEPT；
8. 同上但 02-10 总装主线只投 80（能做尽做应为 86）→ PS_PRE_STOP。
9. 改造停线例 见证计划（T-38 第 5 轮生成器候选：1/19 提前停线接计划停线，清线段跨 1/17–1/18 周末）
   → ACCEPT、L1a 0（周末 OFF 日不算“满产日”，不触发“不满之后又满产”）。
10. 改造停线例 见证计划 r6（第 6 轮候选：5/8 周五减量投入、5/11 周一清线）→ ACCEPT
    （清线前一天按本线最后一个可生产日认，隔周末也算）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from judge.model import InputModel

from .t36 import CLEAR_D1, CLEAR_D2, NORM_DAYS, HOLIDAY, SELF_IDLE, _build, _judge, _make_input

ROOT = Path(__file__).resolve().parents[2]


def _check(failures, name, ok, detail):
    if not ok:
        failures.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] T-38 {name}")
    print(f"   {detail}")
    print()


def run_t38_cases() -> tuple[int, int, int]:
    failures: list[str] = []
    total = 0
    skipped = 0
    case = ROOT / "cases" / "t38-retrofit"
    input_path = case / "retrofit.input.json"

    if input_path.exists():
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        inp = InputModel(raw)
        e = inp.prebuild()["A"]
        total += 1
        _check(failures, "改造停线例 必须提前量 E(1 月) = 314", e["2026-01"] == 314 and e["2026-02"] == 0,
               f"E = {{1 月: {e['2026-01']}, 2 月: {e['2026-02']}, 3 月: {e['2026-03']}}}")
        from datetime import date
        s, t = date(2026, 2, 3), date(2026, 3, 31)
        got = {n: inp.stop_level(n, s, t) for n in ("PS", "PBS", "AS_MAIN", "AS_FIN")}
        total += 1
        _check(failures, "改造停线例 停前水位 PS 30、PBS 50、总装两段 0",
               {n: v and v[0] for n, v in got.items()} == {"PS": 30, "PBS": 50, "AS_MAIN": 0, "AS_FIN": 0},
               f"stop_level = {got}")

        early_stop = {n: inp.stop_level(n, date(2026, 1, 20), t) for n in ("PS", "PBS", "AS_MAIN", "AS_FIN")}
        total += 1
        _check(failures, "改造停线例 提前到 1/20 停线（自建空闲接计划停线）停前水位不变",
               {n: v and v[0] for n, v in early_stop.items()} == {"PS": 30, "PBS": 50, "AS_MAIN": 0, "AS_FIN": 0},
               f"stop_level(1/20..3/31) = {early_stop}")

        bad = copy.deepcopy(raw)
        for c in bad["conditions"]:
            if c["id"] == "C007":
                c["start"] = "2026-03-01"
        errs = InputModel(bad).condition_errors
        total += 1
        _check(failures, "人工目标在制只盖住停线一部分 → 条件错误",
               any("C007" in x and "一部分" in x for x in errs), f"条件错误 = {errs}")

    else:
        for name in ("改造停线例 必须提前量 E(1 月) = 314",
                     "改造停线例 停前水位 PS 30、PBS 50、总装两段 0",
                     "改造停线例 提前到 1/20 停线（自建空闲接计划停线）停前水位不变",
                     "人工目标在制只盖住停线一部分 → 条件错误"):
            print(f"跳过（无真实数据）：T-38 {name}")
            skipped += 1

    def synth(fin_d1: int):
        r = copy.deepcopy(_make_input())
        r["factory"]["workshops"]["AS_FIN"]["jph"] = 13
        r["conditions"].append({"id": "L1", "type": "WIP_TARGET", "reason": "自检", "node": "AS_FIN",
                                "start": HOLIDAY[0], "end": SELF_IDLE[-1], "target": 20})
        i = InputModel(r)
        flows = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in NORM_DAYS}
        flows[CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": (80, fin_d1)}
        flows[CLEAR_D2] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": 80}
        return _judge(i, _build(i, flows))

    for name, fin, expect in (("完成线降到停前水位 20（清线出 100、80）→ ACCEPT", 100, []),
                              ("完成线没降（清线第 1 天只出 80）→ PS_PRE_STOP + BS_CLEAR + C6（停线期间超水位）", 80,
                               ["BS_CLEAR", "C6", "PS_PRE_STOP"])):
        j = synth(fin)
        rules = sorted({x.rule for x in j.hard_errors})
        total += 1
        _check(failures, name, rules == expect,
               f"预期 {expect}，实得 {rules}；" + "；".join(f"{x.rule} {x.date} {x.node} {x.detail}"
                                                    for x in j.hard_errors[:6]))

    def early(d10: int, d11: int, d12: int):
        r = copy.deepcopy(_make_input())
        r["factory"]["workshops"]["AS_FIN"]["jph"] = 13
        r["conditions"].append({"id": "L1", "type": "WIP_TARGET", "reason": "自检", "node": "AS_FIN",
                                "start": HOLIDAY[0], "end": SELF_IDLE[-1], "target": 0})
        i = InputModel(r)
        flows = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in NORM_DAYS}
        flows[NORM_DAYS[-1]]["AS_FIN"] = (80, d10)
        flows[CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": 80, "AS_FIN": (80, d11)}
        flows[CLEAR_D2] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": (80, d12)}
        return _judge(i, _build(i, flows))

    for name, outs, expect in (("完成线清线前就提前降库（104、96、80 → 0）→ ACCEPT", (104, 96, 80), []),
                               ("提前降库那天没做尽（90、104、86）→ PS_PRE_STOP", (90, 104, 86), ["PS_PRE_STOP"])):
        j = early(*outs)
        rules = sorted({x.rule for x in j.hard_errors})
        total += 1
        _check(failures, name, rules == expect,
               f"预期 {expect}，实得 {rules}；" + "；".join(f"{x.rule} {x.date} {x.node} {x.detail}"
                                                    for x in j.hard_errors[:6]))

    def pbs_drain(in10: int):
        r = copy.deepcopy(_make_input())
        r["factory"]["workshops"]["AS_MAIN"]["jph"] = 13
        r["factory"]["workshops"]["AS_FIN"]["jph"] = 14  # 完成线 112 不满产，不能借“下游满产”豁免
        for cid, node, v in (("L1", "PBS", 50), ("L2", "AS_MAIN", 60)):
            r["conditions"].append({"id": cid, "type": "WIP_TARGET", "reason": "自检", "node": node,
                                    "start": HOLIDAY[0], "end": SELF_IDLE[-1], "target": v})
        i = InputModel(r)
        flows = {ds: {w: 80 for w in ("BS1", "PS", "AS_MAIN", "AS_FIN")} for ds in NORM_DAYS}
        a9, a10 = (104, 104, 104), ((in10, 104), 104)
        flows[NORM_DAYS[-2]].update({"AS_MAIN": a9[0], "AS_FIN": a9[2]})
        flows[NORM_DAYS[-1]].update({"AS_MAIN": a10[0], "AS_FIN": a10[1]})
        d11_in = 86 if in10 == 80 else 80
        d11_out = 102
        flows[CLEAR_D1] = {"BS1": (0, 67), "PS": 80, "AS_MAIN": (d11_in, d11_out), "AS_FIN": d11_out}
        flows[CLEAR_D2] = {"PS": (24, 80), "AS_MAIN": 80, "AS_FIN": 80}
        return _judge(i, _build(i, flows))

    for name, in10, expect in (("PBS、总装主线提前降库，主线投 86 < 能力 → 不报 C14、ACCEPT", 86, []),
                               ("主线那天只投 80（应投 86）→ PS_PRE_STOP", 80, ["PS_PRE_STOP"])):
        j = pbs_drain(in10)
        rules = sorted({x.rule for x in j.hard_errors})
        total += 1
        _check(failures, name, rules == expect,
               f"预期 {expect}，实得 {rules}；" + "；".join(f"{x.rule} {x.date} {x.node} {x.detail}"
                                                    for x in j.hard_errors[:6]))

    if input_path.exists() and (case / "retrofit.witness.plan.json").exists():
        plan = json.loads((case / "retrofit.witness.plan.json").read_text(encoding="utf-8"))
        j = _judge(inp, plan)
        total += 1
        _check(failures, "改造停线例 见证计划（提前停线、清线跨周末）→ ACCEPT、L1a 0",
               not j.hard_errors and j.objective["L1a"] == 0,
               f"硬错误 {[(x.rule, x.date, x.node) for x in j.hard_errors[:5]]}，L1a {j.objective['L1a']}")

    else:
        print("跳过（无真实数据）：T-38 改造停线例 见证计划（提前停线、清线跨周末）→ ACCEPT、L1a 0")
        skipped += 1

    if input_path.exists() and (case / "retrofit.witness-r6.plan.json").exists():
        plan = json.loads((case / "retrofit.witness-r6.plan.json").read_text(encoding="utf-8"))
        j = _judge(inp, plan)
        total += 1
        _check(failures, "改造停线例 见证计划 r6（清线前一天隔周末）→ ACCEPT",
               not j.hard_errors and j.objective["L1a"] == 0,
               f"硬错误 {[(x.rule, x.date, x.node) for x in j.hard_errors[:5]]}，L1a {j.objective['L1a']}")

    else:
        print("跳过（无真实数据）：T-38 改造停线例 见证计划 r6（清线前一天隔周末）→ ACCEPT")
        skipped += 1

    print(f"== T-38 结果：{total - len(failures)}/{total} ==")
    return total, len(failures), skipped


if __name__ == "__main__":
    total, failed, skipped = run_t38_cases()
    raise SystemExit(bool(failed))
