"""Run with: python -m engine input.json plan.json [--solver legacy|segment|best]."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

from .model import solve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--warm-start", type=Path)
    parser.add_argument("--solver", choices=("legacy", "segment", "best"))
    args = parser.parse_args()
    route = args.solver or os.environ.get("APS_SOLVER", "legacy")
    if route not in ("legacy", "segment", "best"):
        parser.error("APS_SOLVER 必须为 legacy、segment 或 best")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    tick = perf_counter()
    if route == "legacy":
        previous = json.loads(args.warm_start.read_text(encoding="utf-8")) if args.warm_start else None
        plan = solve(data, previous)
    else:
        from .segment_plan import solve_product
        segment = solve_product(data, args.input, args.output)
        plan = segment
        if route == "best" and segment["status"] != "INPUT_INVALID":
            segment_seconds = perf_counter() - tick
            previous = json.loads(args.warm_start.read_text(encoding="utf-8")) if args.warm_start else None
            legacy_tick = perf_counter()
            legacy = solve(data, previous)
            segment_values = tuple(r["value"] for r in segment["objective"]["levels"])
            legacy_values = tuple(r["value"] for r in legacy["objective"]["levels"])
            selected = "segment"
            if legacy["days"] and (not segment["days"] or legacy_values < segment_values):
                plan, selected = legacy, "legacy"
            print(f"route=segment; seconds={segment_seconds:.6f}; levels={segment_values}")
            print(f"route=legacy; seconds={perf_counter() - legacy_tick:.6f}; levels={legacy_values}")
            plan["findings"].append(f"两种解法都运行了，本次采用{'段级解法' if selected == 'segment' else '旧解法'}的结果。")
        if args.warm_start:
            plan["findings"].append("段级解法每次按本次条件重新排，不沿用上一版计划。")
        plan["solver"] = {"name": route, "seconds": perf_counter() - tick}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"status={plan['status']}; days={len(plan['days'])}")
    for level in plan["objective"]["levels"]:
        print(f"{level['level']}={level['value']}; proven_optimal={level['proven_optimal']}")
    print(f"solver={route}; seconds={perf_counter() - tick:.6f}")


if __name__ == "__main__":
    main()
