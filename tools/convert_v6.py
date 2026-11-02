"""把旧系统 V6 的 PlanningRequest（context + sales）转换成 aps-core/input/v1。

python tools/convert_v6.py <v6 fixture.json> <case id> <out input.json>

只做字段映射；与规格冲突的取值在 OVERRIDES 里显式覆盖，并写进 input.json 的 `_conversion` 说明。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NODE = {"BS1": "BS1", "BS2": "BS2", "PS": "PS", "WBS": "WBS", "PBS": "PBS",
        "AS_MAINLINE": "AS_MAIN", "AS_FINISH_LINE": "AS_FIN", "FINISHED_GOODS": "FIN", "FINISHED": "FIN", "FIN": "FIN"}
# 规格 CORE_MODEL §2：WBS 物理上限 69（2026-10-24 确认）；演示输入里是 60
OVERRIDES = {"buffer_cap": {"WBS": 69}}
RULES = {"ps_stop_min_days": 3, "ps_long_stop_days": 15, "ps_pre_stop_target_short": 131,
         "ps_pre_stop_target_long": 91, "monthly_band_ratio": 0.1}


def convert(req: dict) -> dict:
    ctx, sales = req["context"], req["sales"]
    fm = ctx["factory_model"]
    models = {t["typeclass_id"]: {"line": t["workshop_id"], "glue_age_max": t["glue_limit_calendar_days"]}
              for t in fm["typeclasses"]}
    buffers = {b["buffer_id"]: {"cap_max": OVERRIDES["buffer_cap"].get(b["buffer_id"], b["physical_max_wip"])}
               for b in fm["buffers"]}
    flow = [f"{NODE[e['from_node']]}>{NODE[e['to_node']]}" for e in fm["flow_edges"]]
    if not any(f.startswith("AS_FIN>") for f in flow):
        flow.append("AS_FIN>FIN")
    pr: dict[str, dict[str, int]] = {}
    for m in sales["months"]:
        pr.setdefault(m["typeclass_id"], {})[m["month"]] = m["pr"]
    ws: dict[str, dict[str, int]] = {}
    for row in ctx["daily_ws"]:
        for q in row["ws_by_typeclass"]:
            if q["quantity"]:
                ws.setdefault(q["typeclass_id"], {})[row["date"]] = q["quantity"]
    init = ctx["initial_state"]
    wip: dict[str, dict[str, int]] = {}
    for w in init["workshop_wip_by_typeclass"]:
        wip[NODE[w["workshop_id"]]] = {q["typeclass_id"]: q["quantity"] for q in w["wip_bod_by_typeclass"]}
    for b in init["buffer_bod_by_typeclass"]:
        wip[NODE[b["buffer_id"]]] = {q["typeclass_id"]: q["quantity"] for q in b["wip_bod_by_typeclass"]}
    return {
        "schema": "aps-core/input/v1",
        "horizon": {"start": ctx["horizon_start"], "end": ctx["horizon_end"]},
        "calendar": [{"date": c["date"], "is_working_capable": c["is_working_capable"]} for c in ctx["calendar"]],
        "factory": {
            "workshops": {NODE[w["workshop_id"]]: {"jph": int(w["nominal_jph"])} for w in fm["workshops"]},
            "buffers": buffers,
            "modes": {m["working_mode_id"]: int(m["planned_hours"]) for m in fm["working_modes"]},
            "default_mode": "SINGLE_8H",
            "models": models,
            "flow": flow,
            "shared_welding_jph_max": int(fm["shared_welding_ceiling_jph"]),
        },
        "demand": {"PR": pr, "WS_daily": ws},
        "initial": {"wip": wip,
                    "fin": {q["typeclass_id"]: q["quantity"] for q in init["finished_inventory_bod_by_typeclass"]}},
        "wip_targets": {NODE[t["node_id"]]: t["target_quantity"] for t in ctx["wip_targets"]},
        "wbs_hi": None,
        "conditions": [],
        "rules": RULES,
    }


def main() -> None:
    src, case_id, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    cases = {c["id"]: c for c in json.loads(Path(src).read_text(encoding="utf-8"))["cases"]}
    data = convert(cases[case_id]["request"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
