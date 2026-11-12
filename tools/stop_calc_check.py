"""STOP-1 对照（Claude 维护）：在真实求解里截获 3 月 _stop_options 的入参，调用
engine.stop_calc.stop_candidates，再把每个候选用现有回放核对 d / t / 类别。

用法：python tools/stop_calc_check.py <stop_sweep 输出目录> [A-840 B-912 ...]
不传点名时跑目录里全部 *.input.json。只读，不改引擎。
"""
from __future__ import annotations

import datetime as dt
import json
import runpy
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine.segment_plan as sp  # noqa: E402
from engine.stop_calc import stop_candidates  # noqa: E402

MONTH = None if "--all-months" in sys.argv else "2026-03"
if "--all-months" in sys.argv:
    sys.argv.remove("--all-months")


def replay_check(data, entry, month, first, last, controls, table, cand):
    trial = deepcopy(controls)
    seg = trial[-1]
    seg["end"] = cand["date"]
    seg["stop_points"][month] = {"date": cand["date"], "quantity": cand["tail"]}
    seg["retain_water"] = cand["shape"] == "RETAIN"
    try:
        flow, _ = sp._run_fragment(data, entry, first, last, trial, table)
    except Exception as exc:  # 对照脚本：记下回放异常，不中断
        return {"replay_error": repr(exc)[:160]}
    m = seg["model"]
    line = data["factory"]["models"][m]["line"]
    rows = flow["days"]
    last_ps = max((r["date"] for r in rows if sum(r["workshops"]["PS"]["in"].values())
                   + sum(r["workshops"]["PS"]["out"].values())), default=None)
    last_in = max((r["date"] for r in rows if sum(r["workshops"][line]["in"].values())), default=None)
    tail = next((r["fok"][m] for r in rows if r["date"] == cand["date"]), None)
    return {"fok": flow["exit"]["fok"][m], "last_ps": last_ps, "last_in": last_in, "tail_fok": tail}


def run(inp: Path):
    data = json.loads(inp.read_text(encoding="utf-8"))
    seen, out = set(), []
    orig = sp._stop_options

    def spy(data_, entry, month, first, last, controls, table, flow):
        if (MONTH is None or month == MONTH) and len(controls) == 1:
            key = (sp._fragment_json(entry), id(table))
            if key not in seen:
                seen.add(key)
                cands = stop_candidates(data_, entry, month, first, last, controls[-1], table)
                for c in cands:
                    r = replay_check(data_, entry, month, first, last, controls, table, c)
                    ok = "replay_error" not in r and r["fok"] == c["fok"]
                    if ok and c["stop_class"] != "LONG":
                        # 不清线时 PS 与焊装同日停：回放的 PS 末日应等于计算器的停点。
                        ok = r["last_ps"] == c["date"]
                    out.append({**c, "replay": r, "match": bool(ok),
                                "switches": table.get("switches"), "band": table.get("band")})
        yield from orig(data_, entry, month, first, last, controls, table, flow)

    sp._stop_options = spy
    tmp = inp.with_suffix(".check.plan.json")
    sys.argv = ["engine", str(inp), str(tmp), "--solver", "segment"]
    try:
        runpy.run_module("engine", run_name="__main__")
    except SystemExit:
        pass
    finally:
        sp._stop_options = orig
    return out


def main():
    d = Path(sys.argv[1]).resolve()
    names = sys.argv[2:] or sorted(p.name[:-len(".input.json")] for p in d.glob("*.input.json"))
    total = match = 0
    report = {}
    for n in names:
        cands = run(d / f"{n}.input.json")
        report[n] = cands
        for c in cands:
            total += 1
            match += c["match"]
        print(n, [(c["label"], c["fok"], c["date"][5:], c["tail"], c["stop_class"], c["shape"],
                   c.get("W"), c.get("k"), c.get("next_tail"), "OK" if c["match"] else "MISMATCH")
                  for c in cands], flush=True)
    (d / "stop_calc_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"一致 {match}/{total}")


if __name__ == "__main__":
    main()
