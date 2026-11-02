"""生成 1b 算例文件（Claude 维护）。手算过程见 README.md。

python cases/1b-two-models-changeover/build.py
产出：input.json、expected.json、counter/*.plan.json

计划按“车间合计流量”手算；车型拆分按 C16 先进先出队列生成（期初在制排在前，
PBS 期初的 B 20 台排在该节点队首），得到一份合法的逐车型计划，供反例和自检使用。
生成器只按合计比对（expected.engine.compare = "aggregate"）。
"""
from __future__ import annotations

import datetime as dt
import json
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent

START, END = dt.date(2026, 3, 2), dt.date(2026, 3, 31)
DAYS = [START + dt.timedelta(n) for n in range((END - START).days + 1)]
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
MODELS = ["A", "B"]
LINE = {"A": "BS1", "B": "BS2"}
TARGET = {"BS1": 69, "BS2": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40}
INV0 = {"BS1": {"A": 69}, "WBS": {"A": 37}, "PS": {"A": 147}, "PBS": {"B": 20, "A": 60},
        "AS_MAIN": {"A": 100}, "AS_FIN": {"A": 40}}
PR = {"A": 1333, "B": 187}
WS = {"A": {dt.date(2026, 3, 31): 1333},
      "B": {dt.date(2026, 3, 31): 187}}


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


def optimal_flows(c: int = 12) -> dict[dt.date, dict[str, tuple[int, int]]]:
    """手算的车间合计流量 {日期: {车间: (IN, OUT)}}；c 为第几个工作日清 BS1（换型首日）。

    1..c-1：A 在 BS1 满产 80，全链 80。
    c：BS1 清线 IN 0 / OUT 69，全链 69。
    c+1：BS2 首日 IN 64、未到 69 不得出车，下游全部 0。
    c+2：BS2 IN 64 / OUT 59（到 69 后超额当天流转），全链 59；换型结束。
    之后：BS2 满产 64，下游跟着 64（上游已在目标，C15 镜像）。
    """
    flows = {}
    for d in DAYS:
        f = {w: (0, 0) for w in WORKSHOPS}
        if working(d):
            k = WDAYS.index(d) + 1
            if k < c:
                chain, f["BS1"] = 80, (80, 80)
            elif k == c:
                chain, f["BS1"] = 69, (0, 69)
            elif k == c + 1:
                chain, f["BS2"] = 0, (64, 0)
            elif k == c + 2:
                chain, f["BS2"] = 59, (64, 59)
            else:
                chain, f["BS2"] = 64, (64, 64)
            for w in ("PS", "AS_MAIN", "AS_FIN"):
                f[w] = (chain, chain)
        flows[d] = f
    return flows


def take(queue: deque, qty: int) -> dict[str, int]:
    """从先进先出队列队首取 qty 台，返回车型拆分（C16）。"""
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
    net = {m: 0 for m in MODELS}  # fin − bl
    days = []
    for d in DAYS:
        f = flows[d]
        bod = {n: count(q) for n, q in inv.items()}
        ins, outs = {}, {}
        # 焊装：每条线只有自己的车型
        for w in ("BS1", "BS2"):
            m = "A" if w == "BS1" else "B"
            ins[w] = {m: f[w][0]} if f[w][0] else {}
            add(inv[w], ins[w])
            outs[w] = take(inv[w], f[w][1]) if f[w][1] else {}
        # 当天只有一条线有产出（C4），按顺序进 WBS
        for w in ("BS1", "BS2"):
            add(inv["WBS"], outs[w])
        # 下游逐站：投入取自上游节点队首（含当天流入），产出取自本车间队首
        upstream = {"PS": "WBS", "AS_MAIN": "PBS"}
        for w in ("PS", "AS_MAIN", "AS_FIN"):
            if w == "AS_FIN":
                ins[w] = dict(outs["AS_MAIN"])  # AS_FIN 投入 = AS_MAIN 产出
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
CHANGEOVER_DAYS = {"2026-03-17", "2026-03-18", "2026-03-19"}


def main() -> None:
    flows = optimal_flows()
    plan = build_plan(flows)

    # 反例 1：清线日 PS 只吃 37、次日再吃 32；全部合法，只有 L5 = 32（WBS 03-17 压了 32 台）
    f1 = {d: dict(v) for d, v in flows.items()}
    f1[dt.date(2026, 3, 17)].update({w: (37, 37) for w in ("PS", "AS_MAIN", "AS_FIN")})
    f1[dt.date(2026, 3, 18)].update({w: (32, 32) for w in ("PS", "AS_MAIN", "AS_FIN")})
    hold = build_plan(f1)
    hold["findings"] = ["反例：换型清线日 WBS 留 69 台，次日才送出 32 台"]

    # 反例 2：BS2 未补满时 WBS 低于目标仍向 PS 供车（违反换型逐级补满）
    f2 = {d: dict(v) for d, v in flows.items()}
    f2[dt.date(2026, 3, 18)].update({w: (37, 37) for w in ("PS", "AS_MAIN", "AS_FIN")})
    f2[dt.date(2026, 3, 19)].update({w: (22, 22) for w in ("PS", "AS_MAIN", "AS_FIN")})
    early = build_plan(f2)
    early["findings"] = ["反例：03-18 WBS 日末 0 < 37 仍向 PS 供车 37 台"]

    phases = {day["date"]: ("CHANGEOVER" if day["date"] in CHANGEOVER_DAYS else "NORMAL")
              for day in plan["days"]}
    expected = {
        "case": "1b-two-models-changeover",
        "spec": "CORE_MODEL §8 1b；C4、C15 镜像、§5 换型（2026-10-24 裁决）、C16 顺接换型（rev 169）",
        "engine": {
            "status": "FEASIBLE",
            "compare": "aggregate",
            "model_totals": {"fok": PR},
            "objective": {**ZERO, "L2": 1},
            "stop_list": [],
            "days": [aggregate_day(day) for day in plan["days"]],
        },
        "judge_on_engine": {"verdict": "ACCEPT", "objective": {**ZERO, "L2": 1}, "phases": phases},
        "counter_plans": [
            {"file": "counter/wbs-hold-32.plan.json",
             "why": "03-17 PS 只吃 37、WBS 压到 69：上游有车、下游未满，换型补满期 PS 不满产（rev 182 起违反 C14）",
             "judge": {"verdict": "REJECT", "rules": ["C14"]},
             "engine_must_differ": True},
            {"file": "counter/refill-early-supply.plan.json",
             "why": "换型期 WBS 未回到目标就向 PS 供车，违反逐级补满",
             "judge": {"verdict": "REJECT", "rules": ["C14", "CHANGEOVER"]},
             "engine_must_differ": True},
        ],
    }

    def dump(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "wbs-hold-32.plan.json", hold)
    dump(HERE / "counter" / "refill-early-supply.plan.json", early)
    dump(HERE / "_reference-plan.json", plan)


if __name__ == "__main__":
    main()
