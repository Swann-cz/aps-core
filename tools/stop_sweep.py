"""停线门槛扫描（Claude 维护，数据全是假设值）。

单车型 A、单焊装线 BS1，计划期 2026-03-02 至 04-30，只有普通周末。3 月需求 Q 逐点加大
（= 往停前那段加量），3 月产完后自建空闲等 4 月复工，看零流窗口 W、是否清线复线、判定结论。

  A：胶龄 14、各车间 80 台/天、WBS 目标 37 → k = 1，W ≤ 13 不需清线
  B：胶龄 7、各车间 48 台/天、WBS 目标 60 → k = 2，W ≤ 5 不需清线

用法：python tools/stop_sweep.py --out <dir> [--solver segment|legacy] [--baseline <dir>]
退出码：0 全部通过；1 有不通过项。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START, END = dt.date(2026, 3, 2), dt.date(2026, 4, 30)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
VARIANTS = {
    "A": {"lg": 14, "jph": 10, "wbs": 37, "points": list(range(800, 1761, 40))},
    "B": {"lg": 7, "jph": 6, "wbs": 60, "points": list(range(480, 1057, 24))},
}
# 已证明存在“不清线”且 L1a = 0 的解（旧解法实排或相邻点推得），这些点不得清线复线。
NO_CLEAR = {"A": {840} | set(range(880, 1761, 40)), "B": set(range(888, 1057, 24))}
LEVELS = ["L1a", "L1b", "L1c", "L2", "L3a", "L3b", "L4", "L5", "L6"]


def build(v: dict, q: int) -> dict:
    april = (sum(1 for d in DAYS if d.month == 4 and d.weekday() < 5) - 4) * v["jph"] * 8
    inv0 = {"BS1": 67, "WBS": v["wbs"], "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": START.isoformat(), "end": END.isoformat()},
        "calendar": [{"date": d.isoformat(), "is_working_capable": d.weekday() < 5} for d in DAYS],
        "factory": {
            "workshops": {w: {"jph": v["jph"]} for w in ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")},
            "buffers": {"WBS": {"cap_max": 69}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": v["lg"]}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {"A": {"2026-03": q, "2026-04": april}},
                   "WS_daily": {"A": {"2026-03-31": q, "2026-04-30": april}}},
        "initial": {"wip": {n: {"A": x} for n, x in inv0.items()}, "fin": {"A": 0}},
        "wip_targets": {"BS1": 67, "BS2": 67, "WBS": v["wbs"], "PS": 147, "PBS": 80,
                        "AS_MAIN": 100, "AS_FIN": 40},
        "wbs_hi": None, "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def flow(day: dict, w: str) -> int:
    x = day["workshops"][w]
    return sum(x["in"].values()) + sum(x["out"].values())


def measure(plan: dict, verdict: dict) -> dict:
    days = plan["days"]
    levels = {x["level"]: x["value"] for x in plan.get("objective", {}).get("levels", [])}
    row = {"verdict": verdict.get("verdict"),
           "errors": sorted({e["rule"] for e in verdict.get("hard_errors", [])}),
           "levels": [levels.get(k) for k in LEVELS]}
    if not days:
        return row
    march = [d for d in days if d["date"][:7] == "2026-03"]
    ps_last = max((d["date"] for d in march if flow(d, "PS")), default=None)
    restart = min((d["date"] for d in days if ps_last and d["date"] > ps_last and flow(d, "BS1")), default=None)
    phases = verdict.get("phases", {})
    row.update(
        march_fok=sum(sum(d["fok"].values()) for d in march),
        bs_last_in=max((d["date"] for d in march if sum(d["workshops"]["BS1"]["in"].values())), default=None),
        ps_last=ps_last, bs_restart=restart,
        W=(dt.date.fromisoformat(restart) - dt.date.fromisoformat(ps_last)).days - 1 if ps_last and restart else None,
        # 4 月的 REFILL 只能来自 3 月这次停线清过线（计划期末尾停不会补线）。
        cleared=any("REFILL" in s for k, s in phases.items() if k[:7] == "2026-04"))
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--solver", default="segment")
    ap.add_argument("--baseline")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    base = json.loads((Path(args.baseline).resolve() / "summary.json").read_text(encoding="utf-8")) \
        if args.baseline else {}
    summary, failures = {}, []
    for name, v in VARIANTS.items():
        for q in v["points"]:
            key = f"{name}-{q}"
            inp, plan, ver = (out / f"{key}.{s}.json" for s in ("input", "plan", "verdict"))
            inp.write_text(json.dumps(build(v, q), ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "engine", str(inp), str(plan), "--solver", args.solver],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0 or not plan.exists():
                row = {"verdict": "CRASH", "detail": (r.stdout + r.stderr)[-300:]}
            else:
                subprocess.run([sys.executable, "-m", "judge", str(inp), str(plan), str(ver)], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8")
                row = measure(json.loads(plan.read_text(encoding="utf-8")),
                              json.loads(ver.read_text(encoding="utf-8")))
            summary[key] = row
            why = []
            if row["verdict"] != "ACCEPT":
                why.append(f"判定 {row['verdict']} {row.get('errors', '')}")
            elif row["levels"][0]:
                why.append(f"L1a = {row['levels'][0]}")
            if q in NO_CLEAR[name] and row.get("cleared"):
                why.append(f"存在不清线解，却清线复线（W = {row.get('W')}）")
            old = base.get(key)
            if old and old.get("verdict") == "ACCEPT" and row["verdict"] == "ACCEPT" \
                    and [x or 0 for x in row["levels"]] > [x or 0 for x in old["levels"]]:
                why.append(f"目标比基线差：{row['levels']} > {old['levels']}")
            if why:
                failures.append(f"{key}: " + "；".join(why))
            print(key, row.get("verdict"), "W", row.get("W"), "清线" if row.get("cleared") else "",
                  "L", row.get("levels"), flush=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("不通过：" if failures else "全部通过")
    for f in failures:
        print("  " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
