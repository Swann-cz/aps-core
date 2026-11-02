"""生成 1d 期初双线排空算例文件（Claude 维护）。手算过程见 README.md。

python cases/1d-initial-drain/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json

计划按车间合计流量手算；车型拆分按 C16 先进先出队列生成（期初在制在前，排空线的
B 30 台进 WBS 后排在 WBS 期初 A 的后面）。生成器只按合计比对。
"""
from __future__ import annotations

import datetime as dt
import json
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent

START, END = dt.date(2026, 3, 2), dt.date(2026, 3, 13)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
MODELS = ["A", "B"]
TARGET = {"BS1": 69, "BS2": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
INV0 = {"BS1": {"A": 69}, "BS2": {"B": 30}, "WBS": {"A": 37}, "PS": {"A": 147},
        "PBS": {"A": 80}, "AS_MAIN": {"A": 100}, "AS_FIN": {"A": 40}}
PR = {"A": 720, "B": 30}
WS = {"A": {END: 720}, "B": {END: 30}}


def working(d: dt.date) -> bool:
    return d.weekday() < 5


WDAYS = [d for d in DAYS if working(d)]


def build_input() -> dict:
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": START.isoformat(), "end": END.isoformat()},
        "calendar": [{"date": d.isoformat(), "is_working_capable": working(d)} for d in DAYS],
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8}, "PS": {"jph": 10},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 69}, "PBS": {"cap_max": 150}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": 14},
                       "B": {"line": "BS2", "glue_age_max": 30}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": {m: {"2026-03": q} for m, q in PR.items()},
                   "WS_daily": {m: {d.isoformat(): q for d, q in ws.items()} for m, ws in WS.items()}},
        "initial": {"wip": INV0, "fin": {"A": 0, "B": 0}},
        "wip_targets": TARGET,
        "wbs_hi": None,
        "conditions": [],
        "rules": {"ps_stop_min_days": 3, "ps_long_stop_days": 15,
                  "ps_pre_stop_target_short": 131, "ps_pre_stop_target_long": 91,
                  "monthly_band_ratio": 0.1},
    }


def optimal_flows() -> dict:
    """{日期: {车间: (IN, OUT)}}。第 1 个工作日 BS2 排空 30 台、全链流 30；之后 BS1 满产 80。"""
    flows = {}
    for d in DAYS:
        f = {w: (0, 0) for w in WORKSHOPS}
        if working(d):
            if d == WDAYS[0]:
                chain, f["BS2"] = 30, (0, 30)
            else:
                chain, f["BS1"] = 80, (80, 80)
            for w in ("PS", "AS_MAIN", "AS_FIN"):
                f[w] = (chain, chain)
        flows[d] = f
    return flows


def take(queue: deque, qty: int) -> dict[str, int]:
    got = {}
    while qty:
        m, q = queue[0]
        k = min(q, qty)
        got[m] = got.get(m, 0) + k
        qty -= k
        if k == q:
            queue.popleft()
        else:
            queue[0] = (m, q - k)
    return got


def add(queue: deque, part: dict[str, int]) -> None:
    for m, q in part.items():
        if q:
            queue.append((m, q))


def count(queue: deque) -> dict[str, int]:
    out = {}
    for m, q in queue:
        out[m] = out.get(m, 0) + q
    return out


def build_plan(flows: dict) -> dict:
    inv = {n: deque((m, q) for m, q in INV0.get(n, {}).items() if q) for n in NODES}
    net = {m: 0 for m in MODELS}
    days = []
    for d in DAYS:
        f = flows[d]
        bod = {n: count(q) for n, q in inv.items()}
        ins, outs = {}, {}
        for w in ("BS1", "BS2"):
            m = "A" if w == "BS1" else "B"
            ins[w] = {m: f[w][0]} if f[w][0] else {}
            add(inv[w], ins[w])
            outs[w] = take(inv[w], f[w][1]) if f[w][1] else {}
        for w in ("BS1", "BS2"):
            add(inv["WBS"], outs[w])
        upstream = {"PS": "WBS", "AS_MAIN": "PBS"}
        for w in ("PS", "AS_MAIN", "AS_FIN"):
            if w == "AS_FIN":
                ins[w] = dict(outs["AS_MAIN"])
            else:
                ins[w] = take(inv[upstream[w]], f[w][0]) if f[w][0] else {}
            add(inv[w], ins[w])
            outs[w] = take(inv[w], f[w][1]) if f[w][1] else {}
            if w == "PS":
                add(inv["PBS"], outs[w])
        fok = outs["AS_FIN"]
        fin, bl = {}, {}
        for m in MODELS:
            net[m] += fok.get(m, 0) - WS[m].get(d, 0)
            if net[m] > 0:
                fin[m] = net[m]
            elif net[m] < 0:
                bl[m] = -net[m]
        ws = {}
        for w in WORKSHOPS:
            active = bool(f[w][0] or f[w][1])
            ws[w] = {"mode": "SINGLE_8H" if active else "OFF", "hours": 8 if active else 0,
                     "in": ins[w], "out": outs[w]}
        eod = {n: count(q) for n, q in inv.items()}
        clean = lambda st: {n: {m: q for m, q in v.items() if q} for n, v in st.items() if any(v.values())}
        days.append({"date": d.isoformat(), "workshops": ws, "bod": clean(bod), "eod": clean(eod),
                     "fok": fok, "fin": fin, "bl": bl, "phase": "NORMAL"})
    return {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}


def aggregate_day(day: dict) -> dict:
    s = lambda v: sum((v or {}).values())
    return {"date": day["date"],
            "workshops": {w: {"mode": v["mode"], "in": s(v["in"]), "out": s(v["out"])}
                          for w, v in day["workshops"].items()},
            "eod": {n: s(v) for n, v in day["eod"].items() if s(v)},
            "fok": s(day["fok"]), "fin": s(day["fin"]), "bl": s(day["bl"])}


ZERO = {"L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0}


def main() -> None:
    flows = optimal_flows()
    plan = build_plan(flows)
    d1, d2 = WDAYS[0], WDAYS[1]
    off = {w: (0, 0) for w in WORKSHOPS}

    # 反例 1：排空推迟到第 2 个工作日，第 1 天先开 BS1 → 排空不在最前（INITIAL_DRAIN），
    # 闲置线 BS2 带着 30 台过了一天（C8）
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[d1] = {**off, "BS1": (80, 80), **{w: (80, 80) for w in ("PS", "AS_MAIN", "AS_FIN")}}
    f1[d2] = {**off, "BS2": (0, 30), **{w: (30, 30) for w in ("PS", "AS_MAIN", "AS_FIN")}}
    late = build_plan(f1)
    late["findings"] = ["反例：期初排空推迟到第 2 个工作日"]

    # 反例 2：排空期 BS2 又投入 10 台（排空期不投入），第 2 天才清空
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[d1] = {**f2[d1], "BS2": (10, 30)}
    f2[d2] = {**off, "BS2": (0, 10), **{w: (10, 10) for w in ("PS", "AS_MAIN", "AS_FIN")}}
    feed = build_plan(f2)
    feed["findings"] = ["反例：期初排空期间 BS2 仍投入"]

    phases = {d.isoformat(): ("INITIAL_DRAIN" if d == d1 else "NORMAL") for d in DAYS}
    objective = {**ZERO, "L2": 1}
    expected = {
        "case": "1d-initial-drain",
        "spec": "CORE_MODEL §5 期初双线排空行（B16）、C4、C16 期初口径（rev 178）",
        "engine": {"status": "FEASIBLE", "compare": "aggregate", "model_totals": {"fok": PR},
                   "objective": objective, "stop_list": [],
                   "days": [aggregate_day(day) for day in plan["days"]]},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": objective, "phases": phases},
        "counter_plans": [
            {"file": "counter/drain-late.plan.json",
             "why": "期初排空没有放在第一个工作日，闲置线带车过了一天",
             "judge": {"verdict": "REJECT", "rules": ["C8", "INITIAL_DRAIN", "SEQ"]}, "engine_must_differ": True},
            {"file": "counter/drain-with-input.plan.json",
             "why": "期初排空期间排空线仍投入",
             "judge": {"verdict": "REJECT", "rules": ["C10", "C12", "INITIAL_DRAIN", "SEQ"]}, "engine_must_differ": True},
        ],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "drain-late.plan.json", late)
    dump(HERE / "counter" / "drain-with-input.plan.json", feed)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
