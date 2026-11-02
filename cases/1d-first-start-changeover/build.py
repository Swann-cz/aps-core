"""生成 1d 首次启动 + 两次换型算例文件（Claude 维护）。手算过程见 README.md。

python cases/1d-first-start-changeover/build.py
产出：input.json、expected.json、counter/*.plan.json、_reference-plan.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from casegen import RULES, WORKSHOPS, days_between, dump  # noqa: E402

DAYS = days_between(dt.date(2026, 11, 16), dt.date(2026, 12, 11))
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
TARGET = {"BS1": 40, "BS2": 100, "WBS": 30, "PS": 50, "PBS": 30, "AS_MAIN": 40, "AS_FIN": 20}
INV0 = {"BS1": 40, "WBS": 30, "PS": 50, "PBS": 30, "AS_MAIN": 40, "AS_FIN": 20}  # 全是 A
PR = {"A": {"2026-11": 360, "2026-12": 680}, "B": {"2026-11": 200, "2026-12": 0}}
WS = {"A": {dt.date(2026, 12, 11): 1040}}
D = {**{k: dt.date(2026, 11, k) for k in (20, 23, 24, 25, 26, 27, 30)}, 1: dt.date(2026, 12, 1)}
DOWN = ("PS", "AS_MAIN", "AS_FIN")


def working(d: dt.date) -> bool:
    return d.weekday() < 5


def chain(a: int = 0, b: int = 0) -> tuple:
    """PS → AS_FIN 同量流过：A a 台、B b 台。"""
    x = {k: v for k, v in (("A", a), ("B", b)) if v}
    return (dict(x), dict(x))


def idle_day() -> dict:
    return {w: ({}, {}) for w in WORKSHOPS}


def reference_flows() -> dict:
    """{日期: {车间: (IN 按车型, OUT 按车型)}}，取自 `_reference-plan.json`。

    rev 169（C16 顺接换型）后的参考计划由生成器 T-09 第二轮求得（八级都证最优），
    判定器判 ACCEPT；Claude 按 README 的手算核对了 L1c = 4、L2 = 2。本脚本不再手写流量。
    """
    ref = json.loads((HERE / "_reference-plan.json").read_text(encoding="utf-8"))
    flows = {}
    for row in ref["days"]:
        d = dt.date.fromisoformat(row["date"])
        flows[d] = {w: ({m: q for m, q in row["workshops"][w]["in"].items() if q},
                        {m: q for m, q in row["workshops"][w]["out"].items() if q}) for w in WORKSHOPS}
    return flows


def build_plan(flows: dict) -> dict:
    inv = {(n, m): (INV0.get(n, 0) if m == "A" else 0) for n in NODES for m in "AB"}
    fin = {"A": 0, "B": 0}
    days = []

    def per_node(src: dict) -> dict:
        out = {}
        for n in NODES:
            v = {m: src[n, m] for m in "AB" if src[n, m]}
            if v:
                out[n] = v
        return out

    for d in DAYS:
        f = flows[d]
        bod = dict(inv)
        for m in "AB":
            for w in WORKSHOPS:
                inv[w, m] += f[w][0].get(m, 0) - f[w][1].get(m, 0)
            inv["WBS", m] += f["BS1"][1].get(m, 0) + f["BS2"][1].get(m, 0) - f["PS"][0].get(m, 0)
            inv["PBS", m] += f["PS"][1].get(m, 0) - f["AS_MAIN"][0].get(m, 0)
            assert f["AS_FIN"][0].get(m, 0) == f["AS_MAIN"][1].get(m, 0), d
            fin[m] += f["AS_FIN"][1].get(m, 0) - WS.get(m, {}).get(d, 0)
        assert all(v >= 0 for v in inv.values()), (d, inv)
        assert all(v >= 0 for v in fin.values()), (d, fin)
        row = {}
        for w in WORKSHOPS:
            active = bool(f[w][0] or f[w][1])
            row[w] = {"mode": "SINGLE_8H" if active else "OFF", "hours": 8 if active else 0,
                      "in": dict(f[w][0]), "out": dict(f[w][1])}
        days.append({"date": d.isoformat(), "workshops": row, "bod": per_node(bod), "eod": per_node(inv),
                     "fok": dict(f["AS_FIN"][1]), "fin": {m: q for m, q in fin.items() if q},
                     "bl": {}, "phase": "NORMAL"})
    return {"schema": "aps-core/plan/v1", "status": "FEASIBLE", "days": days,
            "stop_list": [], "objective": {"levels": []}, "findings": []}


def build_input() -> dict:
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": DAYS[0].isoformat(), "end": DAYS[-1].isoformat()},
        "calendar": [{"date": d.isoformat(), "is_working_capable": working(d)} for d in DAYS],
        "factory": {
            "workshops": {"BS1": {"jph": 10}, "BS2": {"jph": 8}, "PS": {"jph": 10},
                          "AS_MAIN": {"jph": 10}, "AS_FIN": {"jph": 10}},
            "buffers": {"WBS": {"cap_max": 69}, "PBS": {"cap_max": 70}},
            "modes": {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16},
            "default_mode": "SINGLE_8H",
            "models": {"A": {"line": "BS1", "glue_age_max": 15}, "B": {"line": "BS2", "glue_age_max": 7}},
            "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN",
                     "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
            "shared_welding_jph_max": 13,
        },
        "demand": {"PR": PR, "WS_daily": {m: {d.isoformat(): q for d, q in v.items()} for m, v in WS.items()}},
        "initial": {"wip": {n: {"A": q} for n, q in INV0.items()}, "fin": {"A": 0, "B": 0}},
        "wip_targets": TARGET,
        "wbs_hi": None,
        "conditions": [],
        "rules": RULES,
    }


def main() -> None:
    flows = reference_flows()

    # 反例 1：B 首次出车提前一天（11-17），BS2 日末 62 − 26 = 36 < 100 就向 WBS 出车 → FIRST_START + CHANGEOVER
    d17, d18 = dt.date(2026, 11, 17), dt.date(2026, 11, 18)
    f1 = dict(flows)
    f1[d17] = {**flows[d17], "BS2": ({"B": 62}, {"B": 26})}
    f1[d18] = {**flows[d18], "BS2": ({"B": 64}, {})}
    early = build_plan(f1)
    early["findings"] = ["反例：B 首次出车当天 BS2 日末 36 < 100"]

    # 反例 2：11-19 PS 里还剩 10 台 A，就先放 20 台 B（应为 A 54、B 10），11-20 再放这 10 台 A → SEQ
    d19, d20 = dt.date(2026, 11, 19), dt.date(2026, 11, 20)
    f2 = dict(flows)
    f2[d19] = {**flows[d19], "PS": (flows[d19]["PS"][0], {"A": 44, "B": 20})}
    f2[d20] = {**flows[d20], "PS": (flows[d20]["PS"][0], {"A": 10})}
    overtake = build_plan(f2)
    overtake["findings"] = ["反例：新车型 B 在 PS 超过旧车型 A"]

    # 反例 3：11-20 BS2 多投 36 台 B，第二次换型清线后 BS2 还剩 36 台，11-25 就开 BS1 → CHANGEOVER；
    # 之后 BS2 闲置仍有 36 台（闲置线保持 0，C8）
    f3 = dict(flows)
    f3[d20] = {**flows[d20], "BS2": ({"B": flows[d20]["BS2"][0]["B"] + 36}, flows[d20]["BS2"][1])}
    dirty = build_plan(f3)
    dirty["findings"] = ["反例：BS2 留 36 台就换回 BS1"]

    upper = {"L1a": 0, "L1b": 0, "L1c": 4, "L2": 2}
    expected = {
        "case": "1d-first-start-changeover",
        "spec": "CORE_MODEL §5 首次启动、换型（每次清旧线；换型闲置线不算长停，rev 161）、C12 月度带、C16 顺接换型（rev 169）",
        "engine": {"status": "FEASIBLE", "compare": "none", "objective": upper, "stop_list": [],
                   "model_totals": {"fok": {"A": 1040, "B": 200}}},
        "judge_on_engine": {"verdict": "ACCEPT", "objective": upper},
        "counter_plans": [
            {"file": "counter/first-start-early.plan.json",
             "why": "B 首次出车当天 BS2 日末 36，没到目标 100",
             "judge": {"verdict": "REJECT", "rules": ["CHANGEOVER", "FIRST_START"]}, "engine_must_differ": True},
            {"file": "counter/b-overtakes-a-in-ps.plan.json",
             "why": "11-19 PS 里旧车型 A 还剩 10 台，新车型 B 先出 20 台",
             "judge": {"verdict": "REJECT", "rules": ["SEQ"]}, "engine_must_differ": True},
            {"file": "counter/second-change-dirty.plan.json",
             "why": "换回 A 时 BS2 还剩 36 台就开 BS1，之后 BS2 闲置仍有车",
             "judge": {"verdict": "REJECT", "rules": ["C6", "C8", "CHANGEOVER"]}, "engine_must_differ": True},
        ],
    }
    dump(HERE / "input.json", build_input())
    dump(HERE / "expected.json", expected)
    dump(HERE / "counter" / "first-start-early.plan.json", early)
    dump(HERE / "counter" / "b-overtakes-a-in-ps.plan.json", overtake)
    dump(HERE / "counter" / "second-change-dirty.plan.json", dirty)


if __name__ == "__main__":
    main()
