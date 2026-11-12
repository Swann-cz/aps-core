"""TUNE-1 验收（Claude 维护）：对已有计划做加 / 抽 X 台，检查判定、重算范围外不变、估算一致、nearest 可行。

用法：
  python tools/tune_check.py sweep <stop_sweep 输出目录> <out_dir>
  python tools/tune_check.py real  <全量验收台输出目录（含 <name>.plan.json）> <out_dir>
只读引擎；判定器以子进程调用。
"""
from __future__ import annotations

import json
import time
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.tune import apply_edit  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
from refactor_bench import DATASETS  # noqa: E402

RED = {"C1", "C2", "C4", "C5", "C6", "C7", "C14", "C16", "C17", "SEQ", "BS_CLEAR", "PS_PRE_STOP",
       "REFILL", "CHANGEOVER", "INITIAL_DRAIN", "FIRST_START", "INPUT"}
XS = tuple(int(v) for v in __import__('os').environ.get('TUNE_XS', '1,16,17,48,64,65,80,160,400').split(','))


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def judge(inp: Path, plan: dict, out: Path, tag: str) -> str:
    pp, vp = out / f"{tag}.plan.json", out / f"{tag}.verdict.json"
    pp.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "judge", str(inp), str(pp), str(vp)], cwd=ROOT,
                   capture_output=True, text=True, encoding="utf-8")
    v = load(vp)
    rules = sorted({e["rule"] for e in v["hard_errors"]})
    red = [r for r in rules if r in RED]
    # 微调口径（UI_CONTRACT §11.10）：红线为 0 记 OK，黄线偏差另列
    return ("OK" if not red else "RED " + ",".join(red)) + ("" if len(red) == len(rules) else " yellow " + ",".join(r for r in rules if r not in RED))


def flows(day):
    return ({w: (x["in"], x["out"]) for w, x in day["workshops"].items()}, day["eod"])


def outside_same(old: dict, new: dict, changed: dict) -> bool:
    a = {d["date"]: d for d in old["days"]}
    for d in new["days"]:
        if changed and changed["start"] <= d["date"] <= changed["end"]:
            continue
        if flows(d) != flows(a[d["date"]]):
            return False
    return True


def segments(data, plan):
    """各线各车型的生产段（焊装进线 > 0 的连续工作段，以普通周末/短空档相连不切）：返回段末日列表。"""
    out = []
    for m, info in data["factory"]["models"].items():
        line = info["line"]
        days = [d["date"] for d in plan["days"] if d["workshops"][line]["in"].get(m, 0) > 0]
        from datetime import date
        for i, d in enumerate(days):
            # 下一次进线隔了 4 个自然日以上（不是普通周末），或者没有下一次：这一天是段末。
            if i + 1 == len(days) or (date.fromisoformat(days[i + 1]) - date.fromisoformat(d)).days > 4:
                out.append((line, m, d))
    return out


def check(inp: Path, plan: dict, edit: dict, out: Path, tag: str, stats: dict, log: list):
    data = load(inp)
    tick = time.perf_counter()
    r = apply_edit(data, plan, edit)
    seconds = round(time.perf_counter() - tick, 2)
    stats['slow'] += seconds > 2
    row = {"tag": tag, "edit": edit, "feasible": r["feasible"], "reason": r.get("reason"),
           "actual": r.get("actual_quantity"), "nearest": r.get("nearest"),
           "before": (r.get("stop_before") or {}).get("stop_class"),
           "after": (r.get("stop_after") or {}).get("stop_class"),
           "W_after": (r.get("stop_after") or {}).get("W"), "match": r.get("estimate_matches"), "seconds": seconds}
    if r["feasible"]:
        stats["feasible"] += 1
        row["verdict"] = judge(inp, r["plan"], out, tag)
        stats["accept"] += row["verdict"].startswith("OK")
        row["outside_same"] = outside_same(plan, r["plan"], r.get("changed"))
        stats["outside_same"] += row["outside_same"]
        if r.get("estimate") is not None:
            stats["est"] += 1
            stats["est_match"] += bool(r.get("estimate_matches"))
    else:
        stats["infeasible"] += 1
        ok = []
        for q in r.get("nearest") or []:
            e2 = dict(edit, quantity=q) if q > 0 else dict(edit, quantity=-q, type="REMOVE" if edit["type"] == "ADD" else "ADD")
            ok.append(apply_edit(data, plan, e2)["feasible"])
        row["nearest_ok"] = ok
        stats["nearest_total"] += len(ok)
        stats["nearest_ok"] += sum(ok)
    log.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


def main():
    mode, src, out = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stats = {k: 0 for k in ("feasible", "accept", "outside_same", "est", "est_match", "infeasible",
                            "nearest_total", "nearest_ok", "slow")}
    log = []
    if mode == "sweep":
        for inp in sorted(src.glob("*.input.json")):
            name = inp.name[:-len(".input.json")]
            plan = load(src / f"{name}.plan.json")
            if not plan.get("days"):
                continue
            data = load(inp)
            # 包含 3 月最后一个进线日的那一段的真实段末（3、4 月连成一段时段末在 4 月）
            march = [d["date"] for d in plan["days"] if d["date"][:7] == "2026-03"
                     and d["workshops"]["BS1"]["in"].get("A", 0) > 0]
            if not march:
                continue
            march = [min(e for _, _, e in segments(data, plan) if e >= march[-1])]
            for x in XS:
                for t in ("ADD", "REMOVE"):
                    edit = {"type": t, "line": "BS1", "model": "A", "segment_end": march[-1], "quantity": x}
                    check(inp, plan, edit, out, f"{name}-{t}-{x}", stats, log)
    else:
        rnd = random.Random(20261109)
        for ds in DATASETS:
            name = ds.split("/")[-1]
            inp = ROOT / "cases" / f"{ds}.input.json"
            plan = load(src / f"{name}.plan.json")
            if not plan.get("days"):
                continue
            data = load(inp)
            phases = {d["date"]: d.get("phase", "") for d in plan["days"]}
            cands = [s for s in segments(data, plan)
                     if not any("CHANGEOVER" in p for k, p in phases.items() if k[:7] == s[2][:7])]
            for line, m, end in rnd.sample(cands, min(3, len(cands))):
                for t in ("ADD", "REMOVE"):
                    edit = {"type": t, "line": line, "model": m, "segment_end": end, "quantity": 16}
                    check(inp, plan, edit, out, f"{name}-{end}-{t}", stats, log)
    (out / "tune_check.json").write_text(json.dumps({"stats": stats, "rows": log}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print("STATS", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
