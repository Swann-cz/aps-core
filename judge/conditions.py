"""T-11 条件预检，IO_CONTRACT §2.1。"""
from datetime import date


def parse_conditions(inp):
    errors = []
    for node, cap in inp.workshop_caps.items():
        if cap < inp.wip_targets[node]:
            errors.append(f"车间 {node} 物理上限 {cap} 不能小于目标在制 {inp.wip_targets[node]}")
    valid = []
    ids = set()
    required = {
        "SATURDAY_AUTH": (),
        "MODE_AUTH": ("mode", "start", "end", "workshops"),
        "SHUTDOWN": ("start", "end"),
        "CAPACITY_LOSS": ("start", "end", "workshops", "hours_max"),
        "WIP_TARGET": ("node", "start", "end", "target"),
        "PRE_STOP_TARGET": ("pre_stop_date", "target"),
        "FIXED_OUTPUT": ("workshop", "date", "out"),
    }
    for c in inp.conditions:
        cid = c.get("id") if isinstance(c, dict) else None
        def error(reason):
            errors.append(f"条件 {cid!r}: {reason}")
        if not isinstance(c, dict):
            error("条件必须是对象")
            continue
        kind = c.get("type")
        if not isinstance(cid, str):
            error("id 必须是字符串")
            continue
        if cid in ids:
            error("id 重复")
        ids.add(cid)
        if not isinstance(kind, str) or kind not in required:
            error("未知 type")
            continue
        fields = required[kind]
        if kind == "SATURDAY_AUTH":
            fields = ("date",) if "date" in c else ("start", "end")
        missing = [f for f in fields if f not in c]
        if missing:
            error(f"缺必填字段 {missing}")
            continue
        before = len(errors)
        for field in ("hours_max", "target", "out"):
            if field in c and (type(c[field]) is not int or c[field] < 0):
                error(f"{field} 必须是非负整数")
        workshops = c.get("workshops", list(inp.workshops))
        if not isinstance(workshops, list) or any(
                not isinstance(w, str) or w not in inp.workshops for w in workshops):
            error("workshops 必须是存在的车间 id 列表")
        for field, available in (("workshop", inp.workshops),
                                  ("node", {*inp.workshops, *inp.buffers}),
                                  ("mode", inp.modes)):
            if field in c and (not isinstance(c[field], str) or c[field] not in available):
                error(f"{field} 不存在")
        if kind == "MODE_AUTH" and c["mode"] in ("OFF", inp.default_mode):
            error("MODE_AUTH 不允许 OFF / default_mode")
        if kind == "WIP_TARGET" and len(errors) == before:
            caps = {**inp.buffers, **inp.workshop_caps}
            if c["node"] in caps and c["target"] > caps[c["node"]]:
                error(f"人工目标在制 {c['target']} 大于节点 {c['node']} 物理上限 {caps[c['node']]}")
        try:
            dates = {f: date.fromisoformat(c[f]) for f in
                     ("start", "end", "date", "pre_stop_date") if f in c}
        except (ValueError, TypeError):
            error("日期格式错误")
            continue
        if any(d < inp.start or d > inp.end for d in dates.values()):
            error("日期出 horizon")
        start = dates.get("start", dates.get("date", dates.get("pre_stop_date")))
        end = dates.get("end", start)
        if start > end:
            error("start > end")
        if len(errors) == before:
            valid.append({**c, "start_date": start, "end_date": end,
                          "workshops": workshops})
    targets, outputs = {}, {}
    shutdowns = {}
    for c in valid:
        for d in inp.dates:
            if not c["start_date"] <= d <= c["end_date"]:
                continue
            kind = c["type"]
            if kind == "SHUTDOWN":
                for w in c["workshops"]:
                    shutdowns[w, d] = c["id"]
            if kind in ("WIP_TARGET", "FIXED_OUTPUT"):
                table = targets if kind == "WIP_TARGET" else outputs
                node = c["node"] if kind == "WIP_TARGET" else c["workshop"]
                value = c["target"] if kind == "WIP_TARGET" else c["out"]
                key = node, d
                if key in table and table[key][0] != value:
                    errors.append(f"条件 {c['id']}: {d} {node} 与条件 {table[key][1]} 的 {kind} 值冲突")
                table[key] = value, c["id"]
    for key, (value, cid) in outputs.items():
        if value > 0 and key in shutdowns:
            errors.append(f"条件 {cid}: {key[1]} {key[0]} 停线日 out > 0（SHUTDOWN {shutdowns[key]}）")
    # rev 204：人工目标在制与全线停线重叠时必须盖住整段停线（停前水位）。
    full = set(inp.workshops)
    for s in valid:
        if s["type"] != "SHUTDOWN" or set(s["workshops"]) != full:
            continue
        for c in valid:
            if (c["type"] == "WIP_TARGET" and c["start_date"] <= s["end_date"]
                    and c["end_date"] >= s["start_date"]
                    and not (c["start_date"] <= s["start_date"] and c["end_date"] >= s["end_date"])):
                errors.append(f"条件 {c['id']}: 人工目标在制 {c['start_date']}..{c['end_date']} 只盖住全线停线 "
                              f"{s['id']}（{s['start_date']}..{s['end_date']}）的一部分；停线期间的目标在制要盖住整段停线")
    return valid, errors
