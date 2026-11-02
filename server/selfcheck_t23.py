"""T-23 A：只在新复制的方案上运行候选授权流程。"""

from datetime import date, timedelta
from copy import deepcopy
import shutil
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from .app import app, write
from . import suggestions, views
from .selfcheck import SCENARIOS, read, request


def run(client, base):
    request(client, "POST", base + "/run")
    for action in ("candidates", "apply", "discard"):
        request(client, "POST", base + "/suggest/" + action, expected=409)
    while True:
        summary = request(client, "GET", base + "/conditions")["scenario"]
        if summary["state"] != "RUNNING":
            break
        time.sleep(1)
    assert summary["state"] == "READY", summary
    return summary


def metrics(summary):
    return ", ".join(f"{k}={summary['objective'][k]}" for k in ("L1a", "L1c", "L3a", "L3b")) + f", seconds={summary['run']['seconds']}"


def check_rev9(client, path, base, summary):
    before = {name: (path / name).read_bytes() for name in ("input.json", "meta.json")}
    data, plan, meta = (read(path / name) for name in ("input.json", "plan.json", "meta.json"))
    view = request(client, "GET", base + "/suggest")
    annual = views.annual(data, plan, None, summary)
    expected = sorted([
        {"month": month, "model": model["model"], "cum_gap": row["cum_gap"], "band_short": row["band_short"]}
        for model in annual["models"] for month, row in model["months"].items()
        if row["band_short"] > 0 or (month == data["horizon"]["end"][:7] and row["cum_gap"] > 0)
    ], key=lambda row: (row["month"], row["model"]))
    assert view["gaps"] == expected
    assert view["next_mode"] == "SINGLE_8P2"
    print("PASS T23 rev9 gaps exactly band_short>0 or final-month cum_gap>0", flush=True)
    candidates = suggestions.generate(data, plan, view["gaps"], meta)
    months = sorted(c["start"][:7] for c in candidates if c["type"] == "MODE_AUTH")
    try:
        meta["suggest_tried"] = [{"mode": "SINGLE_8P2", "months": months}]
        write(path / "meta.json", meta)
        assert request(client, "GET", base + "/suggest")["next_mode"] == "SINGLE_8P3"
        pending = request(client, "POST", base + "/suggest/candidates")
        assert pending["next_mode"] is None
        assert {c["mode"] for c in pending["candidates"]["overtime"]} == {"SINGLE_8P3"}
        request(client, "POST", base + "/suggest/discard")
        assert read(path / "meta.json")["suggest_tried"] == meta["suggest_tried"]
        print("PASS T23 rev9 SINGLE_8P2 tried -> next_mode/candidates SINGLE_8P3; discard preserves tried", flush=True)

        meta["suggest_tried"].append({"mode": "SINGLE_8P3", "months": months})
        assert suggestions.view(data, plan, meta, summary)["next_mode"] == "DOUBLE_SHIFT"
        meta["suggest_tried"].append({"mode": "DOUBLE_SHIFT", "months": months})
        saturday_only = suggestions.view(data, plan, meta, summary)
        assert saturday_only["stage"] == "HAS_GAP" and saturday_only["next_mode"] is None
        data["conditions"].extend(dict(c, id=c["id"].removeprefix("CAND-"))
                                  for c in candidates if c["type"] == "SATURDAY_AUTH")
        write(path / "input.json", data)
        write(path / "meta.json", meta)
        exhausted = request(client, "GET", base + "/suggest")
        assert exhausted["stage"] == "EXHAUSTED" and exhausted["next_mode"] is None
        request(client, "POST", base + "/suggest/candidates", expected=409)
        print("PASS T23 rev9 DOUBLE_SHIFT next; all tiers tried with new Saturday -> HAS_GAP; no new Saturday -> EXHAUSTED, candidates=409", flush=True)

        partial = {"suggest_tried": [{"mode": "SINGLE_8P2", "months": months[:1]}]}
        remaining = suggestions.generate(data, plan, view["gaps"], partial)
        assert {c["start"][:7] for c in remaining if c["type"] == "MODE_AUTH"} == set(months[1:])
        assert all(c["mode"] == "SINGLE_8P2" for c in remaining if c["type"] == "MODE_AUTH")
        print("PASS T23 rev9 partially tried tier only generates untried window months", flush=True)
    finally:
        for name, content in before.items():
            (path / name).write_bytes(content)


def main():
    created = []
    seeds = {p: p.read_bytes() for name in ("gap", "gap-sat", "pass")
             for p in (SCENARIOS / name).iterdir() if p.is_file()}
    try:
        with TestClient(app) as client:
            def copy():
                new = request(client, "POST", "/api/scenarios", json={"from_id": "gap", "name": "T-23 后端自检"})
                path = (SCENARIOS / new["id"]).resolve()
                assert path.parent == SCENARIOS.resolve() and new["id"].startswith("s-")
                created.append(path)
                return path, f"/api/scenarios/{new['id']}"

            path, base = copy()
            assert request(client, "GET", base + "/suggest")["stage"] == "NEED_RUN"
            request(client, "POST", base + "/suggest/candidates", expected=409)
            initial_summary = run(client, base)
            check_rev9(client, path, base, initial_summary)
            view = request(client, "GET", base + "/suggest")
            assert view["stage"] == "HAS_GAP"
            assert any(g["month"] == "2026-03" and g["model"] == "A" and g["cum_gap"] == 422 for g in view["gaps"])
            print("PASS T23 A1 HAS_GAP, 2026-03 A cum_gap=422", flush=True)
            view = request(client, "POST", base + "/suggest/candidates")
            assert view["stage"] == "CANDIDATES_PENDING" and view["gaps"] == [] and view["usage"] is None
            data = read(path / "input.json")
            plan = read(path / "plan.json")
            calendar = {d["date"]: d["is_working_capable"] for d in data["calendar"]}
            sat = view["candidates"]["saturdays"]
            assert sat and view["candidates"]["overtime"]
            for d in sat:
                assert date.fromisoformat(d).weekday() == 5 and not calendar[d]
                assert calendar[(date.fromisoformat(d) - timedelta(days=1)).isoformat()]
                assert not any(s["start"] <= d <= s["end"] for s in plan["stop_list"])
            assert all(c["mode"] == "SINGLE_8P2" for c in view["candidates"]["overtime"])
            assert read(path / "meta.json")["suggest"] == {"baseline": view["baseline"], "created_rev": 2}
            assert view["baseline"]["L1a"] == 82
            request(client, "POST", base + "/suggest/candidates", expected=409)
            print(f"PASS T23 A2 CANDIDATES_PENDING, saturdays={len(sat)}, overtime={len(view['candidates']['overtime'])}, mode=SINGLE_8P2, baseline.L1a=82, repeat=409", flush=True)
            summary = run(client, base)
            print(f"T23 A3 run status={summary['plan_status']}, objective={summary['objective']}, seconds={summary['run']['seconds']}", flush=True)
            if summary["objective"] is None:
                print(f"T23 A3 findings={read(path / 'plan.json')['findings']}", flush=True)
            view = request(client, "GET", base + "/suggest")
            assert view["stage"] == "CANDIDATES_DONE" and view["current"]["L1a"] < 82
            usage = view["usage"]
            expected_tried = [{"mode": "SINGLE_8P2", "months": sorted(
                c["start"][:7] for c in view["candidates"]["overtime"])}]
            assert set(usage["saturdays_used"]) | set(usage["saturdays_unused"]) == set(sat)
            assert not set(usage["saturdays_used"]) & set(usage["saturdays_unused"])
            print("PASS T23 A3 CANDIDATES_DONE, " + metrics(summary), flush=True)
            plan = read(path / "plan.json")
            expected_segments = 0
            for item in usage["overtime_used"]:
                used_dates = {d["date"] for d in item["days"]}
                active = False
                for day in plan["days"]:
                    if day["date"] in used_dates:
                        expected_segments += not active
                        active = True
                    elif any(w["mode"] != "OFF" for w in day["workshops"].values()):
                        active = False
            before = {name: (path / name).read_bytes()
                      for name in ("input.json", "meta.json", "plan.json", "verdict.json")}
            original_apply = suggestions.apply

            def omit_saturday(data, plan, usage):
                incomplete = deepcopy(usage)
                # 本输入可能一个周六都没用（L3a = 0），那就拿掉一段用到的加班
                if incomplete["saturdays_used"]:
                    incomplete["saturdays_used"].pop(0)
                else:
                    incomplete["overtime_used"].pop(0)
                return original_apply(data, plan, incomplete)

            with patch.object(suggestions, "apply", side_effect=omit_saturday):
                rejected = request(client, "POST", base + "/suggest/apply", expected=409)
            assert rejected["detail"].startswith("采纳后判定未通过：")
            assert all((path / name).read_bytes() == content for name, content in before.items())
            print("PASS T23 A4 reject omitted used authorization: 409, input/meta/plan/verdict unchanged", flush=True)
            started = time.monotonic()
            applied = request(client, "POST", base + "/suggest/apply")
            apply_seconds = round(time.monotonic() - started, 3)
            assert applied["stage"] in ("HAS_GAP", "NO_GAP", "EXHAUSTED") and applied["baseline"] is None
            conditions = request(client, "GET", base + "/conditions")
            assert conditions["scenario"]["state"] == "READY"
            assert conditions["scenario"]["verdict"] == "ACCEPT"
            assert conditions["scenario"]["objective"] == summary["objective"]
            assert (path / "plan.json").read_bytes() == before["plan.json"]
            assert "suggest" not in read(path / "meta.json")
            assert read(path / "meta.json")["suggest_tried"] == expected_tried
            print("PASS T23 rev9 apply appends all candidate overtime months (including unused)", flush=True)
            rows = conditions["conditions"]
            assert not any(c["id"].startswith("CAND-") for c in rows)
            assert sum(c["id"].startswith("SAT-") for c in rows) == len(usage["saturdays_used"])
            assert sum(c["id"].startswith("OT-") for c in rows) == expected_segments
            for item in usage["overtime_used"]:
                for day in item["days"]:
                    for workshop in day["workshops"]:
                        assert any(c["id"].startswith("OT-") and c["mode"] == item["mode"]
                                   and c["start"] <= day["date"] <= c["end"]
                                   and workshop in c["workshops"] for c in rows)
            values = ", ".join(f"{k}={summary['objective'][k]}" for k in ("L1a", "L1c", "L3a", "L3b"))
            print(f"PASS T23 A4 READY, plan bytes unchanged, ACCEPT, objective unchanged, SAT={len(usage['saturdays_used'])}, OT={expected_segments}, overtime coverage complete, {values}, apply_seconds={apply_seconds}", flush=True)
            other, other_base = copy()
            run(client, other_base)
            request(client, "POST", other_base + "/suggest/candidates")
            request(client, "POST", other_base + "/suggest/discard")
            assert read(other / "input.json")["conditions"] == []
            assert "suggest" not in read(other / "meta.json")
            assert "suggest_tried" not in read(other / "meta.json")
            print("PASS T23 A5 discard: conditions=[], meta.suggest removed", flush=True)
            formal = request(client, "POST", base + "/finalize", json={"note": "T-23 自检"})
            formal_path = (SCENARIOS / formal["id"]).resolve()
            assert formal_path.parent == SCENARIOS.resolve() and formal_path.name.startswith("f-")
            created.append(formal_path)
            for action in ("candidates", "apply", "discard"):
                request(client, "POST", f"/api/scenarios/{formal['id']}/suggest/{action}", expected=409)
            print("PASS T23 formal writes=409, running writes=409", flush=True)
    finally:
        for path in created:
            assert path.parent == SCENARIOS.resolve() and path.name not in ("gap", "gap-sat", "pass")
            shutil.rmtree(path)
        assert all(p.read_bytes() == content for p, content in seeds.items())
        print("PASS T23 selfcheck scenarios removed, seed files unchanged", flush=True)


if __name__ == "__main__":
    main()
