"""T-11 condition precheck and per-day effective inputs."""
from datetime import date


def prepare(data, days):
    factory = data["factory"]
    workshops = list(factory["workshops"])
    nodes = workshops + list(factory["buffers"])
    required = {
        "SATURDAY_AUTH": (), "MODE_AUTH": ("mode", "start", "end", "workshops"),
        "SHUTDOWN": ("start", "end"),
        "CAPACITY_LOSS": ("start", "end", "workshops", "hours_max"),
        "WIP_TARGET": ("node", "start", "end", "target"),
        "PRE_STOP_TARGET": ("pre_stop_date", "target"),
        "FIXED_OUTPUT": ("workshop", "date", "out"),
    }
    errors, seen, entries = [], set(), []
    targets, fixed, shutdown, manual = {}, {}, set(), {}
    models = factory["models"]
    if "OFF" not in factory["modes"]:
        errors.append("班制表缺少 OFF（停工）模式，请保留 OFF 班制，工时填 0。")
    for n, settings in factory["buffers"].items():
        initial = sum(data["initial"]["wip"].get(n, {}).values())
        if initial > settings["cap_max"]:
            errors.append(f"缓冲区 {n} 期初在制合计 {initial} 台超过物理上限 {settings['cap_max']} 台，请核对盘点数或上限。")
    bindings = [settings["line"] for settings in models.values()]
    if len(models) not in (1, 2) or len(set(bindings)) != len(bindings):
        actual = "、".join(f"{m}→{settings['line']}" for m, settings in models.items()) or "无车型"
        errors.append("车型最多 2 个，每条焊装线最多一个车型（BS1 一个、BS2 一个）；"
                      f"实际车型及绑定：{actual}。")
    for w, settings in factory["workshops"].items():
        if "cap_max" in settings and settings["cap_max"] < data["wip_targets"][w]:
            errors.append(f"车间 {w}: 物理上限 {settings['cap_max']} 不能小于目标在制 {data['wip_targets'][w]}")
    for c in data["conditions"]:
        cid = c.get("id", "<missing>")
        kind = c.get("type")
        reasons = []
        if "id" not in c or not isinstance(cid, str):
            reasons.append("id 必须为字符串")
        if cid in seen:
            reasons.append("id 重复")
        seen.add(cid)
        if kind not in required:
            errors.append(f"条件 {cid}: 未知 type {kind}")
            continue
        missing = [key for key in required[kind] if key not in c]
        if kind == "SATURDAY_AUTH" and "date" not in c:
            missing += [key for key in ("start", "end") if key not in c]
        if missing:
            errors.append(f"条件 {cid}: 缺必填字段 {', '.join(missing)}")
            continue
        first = c.get("pre_stop_date", c.get("date", c.get("start")))
        last = c.get("pre_stop_date", c.get("date", c.get("end")))
        try:
            begin, end = date.fromisoformat(first), date.fromisoformat(last)
        except (ValueError, TypeError):
            errors.append(f"条件 {cid}: 日期格式错误")
            continue
        if first < days[0] or last > days[-1] or begin > end:
            reasons.append("日期出 horizon 或 start > end")
        shops = c.get("workshops", [c["workshop"]] if "workshop" in c else workshops)
        if any(w not in workshops for w in shops):
            reasons.append("车间不存在")
        if kind == "WIP_TARGET" and c["node"] not in nodes:
            reasons.append("节点不存在")
        if kind == "MODE_AUTH" and (c["mode"] not in factory["modes"] or c["mode"] in ("OFF", factory["default_mode"])):
            reasons.append("模式不存在或为 OFF / default_mode")
        for key in ("hours_max", "target", "out"):
            if key in c and (type(c[key]) is not int or c[key] < 0):
                reasons.append(f"{key} 必须为非负整数")
        if kind == "WIP_TARGET" and c["node"] in factory["buffers"] and isinstance(c["target"], int) and c["target"] > factory["buffers"][c["node"]]["cap_max"]:
            reasons.append("目标超过缓冲区物理上限")
        if kind == "WIP_TARGET" and c["node"] in workshops and isinstance(c["target"], int):
            settings = factory["workshops"][c["node"]]
            if "cap_max" in settings and c["target"] > settings["cap_max"]:
                reasons.append("目标超过车间物理上限")
        if reasons:
            errors.extend(f"条件 {cid}: {reason}" for reason in reasons)
            continue
        indices = [i for i, day in enumerate(days) if first <= day <= last]
        entries.append((c, indices, shops))
        for i in indices:
            if kind in ("WIP_TARGET", "FIXED_OUTPUT"):
                key = (c["node"] if kind == "WIP_TARGET" else c["workshop"], i)
                table = targets if kind == "WIP_TARGET" else fixed
                value = c["target"] if kind == "WIP_TARGET" else c["out"]
                if key in table and table[key] != value:
                    errors.append(f"条件 {cid}: 同日同节点 {kind} 值冲突")
                table[key] = value
            elif kind == "SHUTDOWN":
                shutdown.update((w, i) for w in shops)
            elif kind == "PRE_STOP_TARGET":
                manual[i] = c
    for c, indices, shops in entries:
        if c["type"] == "FIXED_OUTPUT" and c["out"] > 0 and (c["workshop"], indices[0]) in shutdown:
            errors.append(f"条件 {c['id']}: FIXED_OUTPUT 落在停线日且 out > 0")
        if c["type"] == "WIP_TARGET":
            for stop, _, stop_shops in entries:
                if (stop["type"] == "SHUTDOWN" and set(stop_shops) == set(workshops)
                        and c["start"] <= stop["end"] and stop["start"] <= c["end"]
                        and not (c["start"] <= stop["start"] and c["end"] >= stop["end"])):
                    errors.append(f"条件 {c['id']}: 人工目标在制与全线停线 {stop['id']} "
                                  f"（{stop['start']}..{stop['end']}）重叠，须盖住整段停线")
    calendar = {row["date"]: row["is_working_capable"] for row in data["calendar"]}
    available = {(w, i): calendar[day] for i, day in enumerate(days) for w in workshops}
    allowed = {(w, i): ["OFF", factory["default_mode"]] for i in range(len(days)) for w in workshops}
    hours = {(w, i): dict(factory["modes"]) for i in range(len(days)) for w in workshops}
    for c, indices, shops in entries:
        for i in indices:
            for w in shops:
                if c["type"] == "SATURDAY_AUTH":
                    available[w, i] = True
                elif c["type"] == "MODE_AUTH" and c["mode"] not in allowed[w, i]:
                    allowed[w, i].append(c["mode"])
                elif c["type"] == "CAPACITY_LOSS":
                    hours[w, i] = {k: min(h, c["hours_max"]) for k, h in hours[w, i].items()}
    for key in available:
        available[key] = available[key] and key not in shutdown
        if not available[key]:
            allowed[key] = ["OFF"]
    effective_targets = {(n, i): targets.get((n, i), data["wip_targets"][n]) for n in nodes for i in range(len(days))}
    return errors, available, allowed, hours, effective_targets, fixed, manual


def stop_days(data):
    """rev 204：停线水位覆盖判定使用日历工作日或实际可用的授权日。"""
    days = sorted(r["date"] for r in data["calendar"]
                  if data["horizon"]["start"] <= r["date"] <= data["horizon"]["end"])
    _, available, *_ = prepare(data, days)
    calendar = {r["date"]: r["is_working_capable"] for r in data["calendar"]}
    return [d for i, d in enumerate(days) if calendar[d] or any(
        available[w, i] for w in data["factory"]["workshops"])]


def stop_level(data, node, start, end, *, days=None):
    """§4 rev 204/205：覆盖全部可生产日或整条落在合并窗口内的停前水位。"""
    covered = [d for d in (stop_days(data) if days is None else days) if start <= d <= end]
    for c in data["conditions"]:
        if (c["type"] == "WIP_TARGET" and c["node"] == node and (
                covered and all(c["start"] <= d <= c["end"] for d in covered)
                or start <= c["start"] and c["end"] <= end)):
            return c["target"], c["id"]
    return None
