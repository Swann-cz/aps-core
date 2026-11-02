"""按 UI_CONTRACT §6 汇总文件中的显示数据。"""

WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]
NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
PHASES = ["PS_PRE_STOP", "STOP", "BS_CLEAR", "REFILL", "FIRST_START",
          "CHANGEOVER", "MODEL_EXIT", "INITIAL_DRAIN"]


def node_caps(data):
    return {node: values.get("cap_max")
            for node, values in {**data["factory"]["workshops"], **data["factory"]["buffers"]}.items()}


def months_in(horizon):
    year, month = map(int, horizon["start"][:7].split("-"))
    result = []
    while f"{year:04d}-{month:02d}" <= horizon["end"][:7]:
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def conditions_on(conditions, day):
    result = []
    for condition in conditions:
        if condition["type"] == "PRE_STOP_TARGET":
            covers = condition["pre_stop_date"] == day
        elif "date" in condition:
            covers = condition["date"] == day
        else:
            covers = condition["start"] <= day <= condition["end"]
        if covers:
            result.append({k: condition[k] for k in ("id", "type")})
    return result


def day_views(data, plan, verdict):
    models = sorted(data["demand"]["PR"])
    calendar = {d["date"]: d["is_working_capable"] for d in data["calendar"]}
    cumulative = {w: {"in": 0, "out": 0} for w in WORKSHOPS}
    fok_cum = ws_cum = 0
    result = []
    for day in plan["days"]:
        date = day["date"]
        row = {"date": date, "is_working_capable": calendar[date],
               "phase": verdict["phases"][date] if verdict is not None else day["phase"],
               "conditions": conditions_on(data["conditions"], date),
               "mode_summary": max((w["mode"] for w in day["workshops"].values()),
                                   key=data["factory"]["modes"].__getitem__),
               "hours_max": max(w["hours"] for w in day["workshops"].values()),
               "workshops": {}, "buffers": {}}
        for node in NODES:
            by_model = {}
            for model in models:
                if node in WORKSHOPS:
                    incoming = day["workshops"][node]["in"].get(model, 0)
                    outgoing = day["workshops"][node]["out"].get(model, 0)
                else:
                    upstream, downstream = ((["BS1", "BS2"], "PS") if node == "WBS"
                                            else (["PS"], "AS_MAIN"))
                    incoming = sum(day["workshops"][w]["out"].get(model, 0) for w in upstream)
                    outgoing = day["workshops"][downstream]["in"].get(model, 0)
                by_model[model] = {"bod": day["bod"].get(node, {}).get(model, 0),
                                   "in": incoming, "out": outgoing,
                                   "eod": day["eod"].get(node, {}).get(model, 0)}
            values = {k: sum(v[k] for v in by_model.values()) for k in ("bod", "in", "out", "eod")}
            values["by_model"] = by_model
            if node in WORKSHOPS:
                for k in ("in", "out"):
                    cumulative[node][k] += values[k]
                    values[k + "_cum"] = cumulative[node][k]
                values.update(mode=day["workshops"][node]["mode"],
                              hours=day["workshops"][node]["hours"],
                              jph=data["factory"]["workshops"][node]["jph"])
                row["workshops"][node] = values
            else:
                row["buffers"][node] = values
        by_model = {m: {"fok": day["fok"].get(m, 0),
                        "ws": data["demand"]["WS_daily"].get(m, {}).get(date, 0),
                        "eod": day["fin"].get(m, 0), "bl": day["bl"].get(m, 0)} for m in models}
        fin = {k: sum(v[k] for v in by_model.values()) for k in ("fok", "ws", "eod", "bl")}
        fok_cum += fin["fok"]
        ws_cum += fin["ws"]
        row["fin"] = dict(fin, fok_cum=fok_cum, ws_cum=ws_cum, by_model=by_model)
        result.append(row)
    return result


def monthly(data, plan, verdict, summary, month):
    return {"scenario": summary, "month": month, "models": sorted(data["demand"]["PR"]),
            "targets": data["wip_targets"], "caps": node_caps(data),
            "days": [d for d in day_views(data, plan, verdict) if d["date"][:7] == month]}


def annual(data, plan, verdict, summary):
    days = day_views(data, plan, verdict)
    months = months_in(data["horizon"])
    grouped = {mo: [d for d in days if d["date"][:7] == mo] for mo in months}
    models = []
    for model in sorted(data["demand"]["PR"]):
        cum_pr = cum_fok = 0
        model_months = {}
        for mo in months:
            pr = data["demand"]["PR"][model][mo]
            fok = sum(d["fin"]["by_model"][model]["fok"] for d in grouped[mo])
            cum_pr += pr
            cum_fok += fok
            model_months[mo] = {"pr": pr, "fok": fok, "cum_gap": max(0, cum_pr - cum_fok),
                                "band_short": max(0, cum_pr - data["rules"]["monthly_band_ratio"] * pr - cum_fok)}
        models.append({"model": model, "annual_pr": cum_pr, "annual_fok": cum_fok,
                       "annual_gap": max(0, cum_pr - cum_fok), "months": model_months})

    def production(day):
        return any(w["mode"] != "OFF" for w in day["workshops"].values())

    def saturday(day):
        return not day["is_working_capable"] and production(day)

    def overtime(day):
        return any(w["mode"] not in ("OFF", data["factory"]["default_mode"])
                   for w in day["workshops"].values())

    month_rows = []
    for mo in months:
        rows = grouped[mo]
        # TODO(边界): 非可行计划若没有逐日数据，月末库存显示为 0。
        last_nodes = {**rows[-1]["workshops"], **rows[-1]["buffers"]} if rows else {}
        phases = {p for d in rows for p in d["phase"].split("+")}
        month_rows.append({"month": mo,
                           **{k: sum(m["months"][mo][k] for m in models)
                              for k in ("pr", "fok", "cum_gap", "band_short")},
                           "ws": sum(d["fin"]["ws"] for d in rows),
                           "fin_eom": rows[-1]["fin"]["eod"] if rows else 0,
                           "wip_eom": {n: last_nodes[n]["eod"] if rows else 0 for n in NODES},
                           "weld_days": {w: sum(d["workshops"][w]["in"] > 0 or d["workshops"][w]["out"] > 0
                                                 for d in rows) for w in ("BS1", "BS2")},
                           "saturday_days": sum(map(saturday, rows)),
                           "overtime_days": sum(map(overtime, rows)),
                           "phases": [p for p in PHASES if p in phases]})
    return {"scenario": summary, "horizon": data["horizon"], "caps": node_caps(data),
            "totals": {**{k: sum(m[k] for m in models) for k in ("annual_pr", "annual_fok", "annual_gap")},
                       "production_days": sum(map(production, days)),
                       "saturday_days": sum(map(saturday, days)), "overtime_days": sum(map(overtime, days))},
            "models": models, "months": month_rows,
            "days": [{**{k: d[k] for k in ("date", "is_working_capable", "phase", "conditions")},
                      "fok": d["fin"]["fok"],
                      "mode_summary": max((w["mode"] for w in d["workshops"].values()),
                                          key=data["factory"]["modes"].__getitem__)} for d in days],
            "stop_list": plan["stop_list"], "findings": plan["findings"],
            "hard_errors": verdict["hard_errors"][:50] if verdict is not None else []}
