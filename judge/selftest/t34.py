"""T-34-J（R05）：普通周末两条焊装线都无流量时，不把在产线误判成闲置线。

问题（tasks/reports/T-33-redteam.md R05）：保留 A、B 两个车型基础资料、本期只做 A
（B 需求与期初均为 0、无换型）时，普通周末两条焊装线都 OFF，`_current_welding_line`
按「当天有正流量的线」兜底返回 None，`check_c8` 随后把在产线 BS1 当成闲置线、要求其
库存为 0，误报 C8。CORE_MODEL §5 / C14：普通周末不切段、不改变「当前在产线」；非生产日
应沿用最近一个生产日的在产线。只有真正换型后的旧线才是闲置线。

自检（复用 cases/t33-redteam 的 R05 输入与见证计划）：
  ① 两车型输入（多登记零需求 B）+ 见证计划 → ACCEPT，且周末 03-07/03-08 不报 C8；
  ② 同流量的单车型对照输入（去掉 B 车型）→ ACCEPT，九级与两车型一致。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from judge.constraints import check_all
from judge.core import Judge
from judge.model import InputModel

ROOT = Path(__file__).resolve().parents[2]
R05_DIR = ROOT / "cases" / "t33-redteam"
WEEKEND = ("2026-03-07", "2026-03-08")


def _judge(inp: InputModel, plan: dict) -> Judge:
    j = Judge(inp, plan)
    j.recompute_inventory()
    j.reconcile()
    j.compute_phases()
    check_all(j)
    j.compute_objective()
    return j


def _single_model_input(raw_in: dict) -> dict:
    """从 R05 两车型输入去掉零需求车型 B，构造同流量的单车型对照输入。"""
    raw = copy.deepcopy(raw_in)
    raw["factory"]["models"] = {"A": raw["factory"]["models"]["A"]}
    raw["demand"]["PR"] = {"A": raw["demand"]["PR"]["A"]}
    # WS_daily 原本只有 A；initial.wip 无 BS2 条目；fin 去掉 B。
    raw["initial"]["fin"] = {"A": raw["initial"]["fin"].get("A", 0)}
    return raw


def run_t34_cases() -> tuple[int, int]:
    failures: list[str] = []

    raw_two = json.loads((R05_DIR / "R05-unused-model-weekend.input.json").read_text(encoding="utf-8"))
    plan = json.loads((R05_DIR / "witnesses" / "R05-unused-model-weekend.plan.json").read_text(encoding="utf-8"))

    # ---- ① 两车型（多登记零需求 B）周末不报闲置线 C8 ----
    j_two = _judge(InputModel(raw_two), plan)
    weekend_c8 = [e for e in j_two.hard_errors if e.rule == "C8" and e.date in WEEKEND]
    ok1 = not j_two.hard_errors and not weekend_c8
    if not ok1:
        failures.append("R05 两车型周末误报闲置线 C8")
    print(f"[{'PASS' if ok1 else 'FAIL'}] T-34 两车型（多登记零需求 B）周末不报闲置线 C8")
    print("   预期条款      : 无（ACCEPT），且 03-07/03-08 无 C8")
    print(f"   实得条款      : {sorted({e.rule for e in j_two.hard_errors})}")
    print(f"   判定     : {'REJECT' if j_two.hard_errors else 'ACCEPT'}")
    for e in j_two.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    # ---- ② 同流量的单车型对照与两车型判定结论、九级一致 ----
    j_one = _judge(InputModel(_single_model_input(raw_two)), plan)
    same_objective = j_one.objective == j_two.objective
    ok2 = (not j_one.hard_errors) and same_objective
    if not ok2:
        failures.append("R05 单车型对照与两车型判定不一致")
    print(f"[{'PASS' if ok2 else 'FAIL'}] T-34 同流量单车型对照与两车型判定一致")
    print("   预期条款      : 无（ACCEPT），九级与两车型一致")
    print(f"   实得条款      : {sorted({e.rule for e in j_one.hard_errors})}")
    print(f"   判定     : {'REJECT' if j_one.hard_errors else 'ACCEPT'}")
    print(f"   九级一致      : {same_objective}（L1a={j_one.objective['L1a']} L1b={j_one.objective['L1b']} "
          f"L1c={j_one.objective['L1c']} L2={j_one.objective['L2']} L3a={j_one.objective['L3a']} "
          f"L3b={j_one.objective['L3b']} L4={j_one.objective['L4']} L5={j_one.objective['L5']} "
          f"L6={j_one.objective['L6']}）")
    for e in j_one.hard_errors:
        print(f"     - {e.rule} {e.date} {e.node} {e.model} {e.detail}")
    print()

    total = 2
    print(f"== T-34 结果：{total - len(failures)}/{total} ==")
    return total, len(failures)


if __name__ == "__main__":
    total, failed = run_t34_cases()
    raise SystemExit(bool(failed))
