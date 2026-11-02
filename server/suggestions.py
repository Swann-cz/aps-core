"""UI_CONTRACT §9：候选授权与实际使用情况。"""

from calendar import monthrange
from datetime import date, timedelta

from . import views

LEVELS = ("L1a", "L1b", "L1c", "L3a", "L3b")


def usage_for(candidates, plan):
    days = {d["date"]: d for d in plan["days"]}
    result = {"saturdays_used": [], "saturdays_unused": [],
              "overtime_used": [], "overtime_unused_ids": []}
    for c in candidates:
        if c["type"] == "SATURDAY_AUTH":
            # TODO(边界): 非可行计划没有逐日数据时，候选没有可统计的实际使用量。
            used = any(w["mode"] != "OFF" for day, row in days.items() if day == c["date"]
                       for w in row["workshops"].values())
            result["saturdays_used" if used else "saturdays_unused"].append(c["date"])
        elif c["type"] == "MODE_AUTH":
            used_days = []
            for day, row in sorted(days.items()):
                if c["start"] <= day <= c["end"]:
                    workshops = [w for w in c["workshops"] if row["workshops"][w]["mode"] == c["mode"]]
                    if workshops:
                        used_days.append({"date": day, "workshops": workshops})
            if used_days:
                result["overtime_used"].append({"id": c["id"], "mode": c["mode"], "days": used_days})
            else:
                result["overtime_unused_ids"].append(c["id"])
    return result


def view(data, plan, meta, summary):
    candidates = [c for c in data["conditions"] if c["id"].startswith("CAND-")]
    ready = summary["state"] == "READY"
    gaps = []
    if ready:
        # annual 只在日视图中需要判定阶段；缺口口径直接复用其车型月数据。
        annual = views.annual(data, plan, None, summary)
        gaps = sorted(({"month": month, "model": model["model"],
                        "cum_gap": row["cum_gap"], "band_short": row["band_short"]}
                       for model in annual["models"] for month, row in model["months"].items()
                       if row["band_short"] > 0 or
                       (month == data["horizon"]["end"][:7] and row["cum_gap"] > 0)),
                      key=lambda row: (row["month"], row["model"]))
    if candidates:
        stage = "CANDIDATES_DONE" if ready else "CANDIDATES_PENDING"
    else:
        stage = "NEED_RUN" if not ready else "HAS_GAP" if gaps else "NO_GAP"
    next_mode = None
    if stage == "HAS_GAP":
        available = generate(data, plan, gaps, meta)
        if not available:
            stage = "EXHAUSTED"
        else:
            next_mode = next((c["mode"] for c in available if c["type"] == "MODE_AUTH"), None)
    objective = summary["objective"]
    return {"stage": stage, "next_mode": next_mode, "gaps": gaps,
            "candidates": {
                "saturdays": [c["date"] for c in candidates if c["type"] == "SATURDAY_AUTH"],
                "overtime": [{k: c[k] for k in ("id", "mode", "start", "end")}
                             for c in candidates if c["type"] == "MODE_AUTH"]},
            "usage": usage_for(candidates, plan) if candidates and ready else None,
            "baseline": meta.get("suggest", {}).get("baseline"),
            "current": {k: objective[k] for k in LEVELS} if objective is not None else None}


def generate(data, plan, gaps, meta):
    months = set()
    for gap in gaps:
        first = date.fromisoformat(gap["month"] + "-01")
        months.update((gap["month"], (first - timedelta(days=1)).isoformat()[:7]))
    months.intersection_update(views.months_in(data["horizon"]))
    calendar = {d["date"]: d["is_working_capable"] for d in data["calendar"]}
    excluded = [*plan["stop_list"], *[c for c in data["conditions"]
                if c["type"] in ("SHUTDOWN", "SATURDAY_AUTH") and not c["id"].startswith("CAND-")]]
    result = []
    for day, capable in sorted(calendar.items()):
        if not data["horizon"]["start"] <= day <= data["horizon"]["end"] or day[:7] not in months:
            continue
        parsed = date.fromisoformat(day)
        if parsed.weekday() != 5 or capable:
            continue
        if not calendar.get((parsed - timedelta(days=1)).isoformat(), False):
            continue
        if any(c.get("start", c.get("date")) <= day <= c.get("end", c.get("date")) for c in excluded):
            continue
        result.append({"id": "CAND-SAT-" + day.replace("-", ""), "type": "SATURDAY_AUTH",
                       "date": day, "reason": "候选（缺口建议）"})
    modes = data["factory"]["modes"]
    higher = [m for m in modes if modes[m] > modes[data["factory"]["default_mode"]]]
    for mode in sorted(higher, key=modes.__getitem__):
        tried = {month for entry in meta.get("suggest_tried", []) if entry["mode"] == mode
                 for month in entry["months"]}
        untried = months - tried
        if not untried:
            continue
        for month in sorted(untried):
            year, number = map(int, month.split("-"))
            result.append({"id": "CAND-OT-" + month.replace("-", ""), "type": "MODE_AUTH",
                           "mode": mode, "start": max(month + "-01", data["horizon"]["start"]),
                           "end": min(f"{month}-{monthrange(year, number)[1]:02d}", data["horizon"]["end"]),
                           "workshops": list(views.WORKSHOPS), "reason": "候选（缺口建议）"})
        break
    return result


def apply(data, plan, usage):
    result = [c for c in data["conditions"] if not c["id"].startswith("CAND-")]
    ids = {c["id"] for c in result}

    def append(condition, base):
        identifier = base
        suffix = 2
        while identifier in ids:
            identifier = f"{base}-{suffix}"
            suffix += 1
        ids.add(identifier)
        result.append(dict(condition, id=identifier, reason="补缺口（建议采纳）"))

    used_ot = {c["id"]: {d["date"]: d["workshops"] for d in c["days"]}
               for c in usage["overtime_used"]}
    for c in data["conditions"]:
        if not c["id"].startswith("CAND-"):
            continue
        if c["type"] == "SATURDAY_AUTH" and c["date"] in usage["saturdays_used"]:
            append(c, "SAT-" + c["date"].replace("-", ""))
        elif c["type"] == "MODE_AUTH" and c["id"] in used_ot:
            segments = []
            segment = None
            for day in sorted(plan["days"], key=lambda d: d["date"]):
                day_date = day["date"]
                if not c["start"] <= day_date <= c["end"]:
                    continue
                workshops = used_ot[c["id"]].get(day_date)
                if workshops:
                    if segment is None:
                        segment = {"type": "MODE_AUTH", "mode": c["mode"], "start": day_date,
                                   "end": day_date, "workshops": []}
                        segments.append(segment)
                    segment["end"] = day_date
                    segment["workshops"] = [w for w in views.WORKSHOPS
                                            if w in segment["workshops"] or w in workshops]
                elif any(w["mode"] != "OFF" for w in day["workshops"].values()):
                    segment = None
            for segment in segments:
                append(segment, "OT-" + segment["start"].replace("-", ""))
    return result
