"""判定器命令行入口：python -m judge <input.json> <plan.json> <verdict.json>

输出符合 IO_CONTRACT §4。只用标准库。
"""
from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(input_path: str, plan_path: str, verdict_path: str) -> None:
    from .model import InputModel
    from .core import Judge
    from .constraints import check_all

    raw_in = load(input_path)
    raw_plan = load(plan_path)

    inp = InputModel(raw_in)
    j = Judge(inp, raw_plan)

    if inp.condition_errors:
        for detail in inp.condition_errors:
            j._err("INPUT", None, None, None, detail)
    else:
        j.recompute_inventory()
        j.reconcile()
        j.compute_phases()
        check_all(j)
        j.compute_objective()

    verdict = {
        "schema": "aps-core/verdict/v1",
        "verdict": "ACCEPT" if not j.hard_errors else "REJECT",
        "hard_errors": [e.to_dict() for e in j.hard_errors],
        "reports": j.reports,
        "phases": j.phases,
        "objective": j.objective,
    }

    with open(verdict_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("用法：python -m judge <input.json> <plan.json> <verdict.json>", file=sys.stderr)
        return 2
    run(argv[0], argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
