"""T-13 A：在真实 workspace 上检查接口，只改动本次创建的方案。"""

import json
import argparse
from pathlib import Path
import shutil
import time

from fastapi.testclient import TestClient

from .app import app
from .selfcheck_t15 import check as check_t15
from .selfcheck_t20 import check as check_t20
from .selfcheck_t21 import check as check_t21


SCENARIOS = Path(__file__).resolve().parents[1] / "workspace" / "scenarios"
SEEDS = {"gap-sat": 0, "gap": 115, "pass": 0}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def request(client, method, url, expected=200, **kwargs):
    response = client.request(method, url, **kwargs)
    assert response.status_code == expected, (url, response.status_code, response.text)
    return response.json()


def check_views(client, scenario_id, gap):
    path = SCENARIOS / scenario_id
    data = read(path / "input.json")
    plan = read(path / "plan.json")
    verdict = read(path / "verdict.json")
    base = f"/api/scenarios/{scenario_id}"
    annual = request(client, "GET", base + "/annual")
    gap = verdict["objective"]["L1a"]  # 年度缺口 = 判定器的 L1a，随种子计划更新，不写死
    assert annual["totals"]["annual_gap"] == gap
    assert annual["scenario"]["objective"] == verdict["objective"]
    assert len(annual["days"]) == len(plan["days"])
    year, month = map(int, data["horizon"]["start"][:7].split("-"))
    months = []
    while f"{year:04d}-{month:02d}" <= data["horizon"]["end"][:7]:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    assert [m["month"] for m in annual["months"]] == months
    print(f"PASS A2 {scenario_id}: annual_gap={gap}, objective=verdict, "
          f"days={len(plan['days'])}, months={len(months)}", flush=True)

    models = sorted(data["demand"]["PR"])
    annual_days = {d["date"]: d for d in annual["days"]}
    cumulative = {w: {"in": 0, "out": 0} for w in data["factory"]["workshops"]}
    fok_cum = ws_cum = 0
    for facts in annual["months"]:
        month = facts["month"]
        view = request(client, "GET", base + "/monthly", params={"month": month})
        assert view["models"] == models
        assert view["targets"] == data["wip_targets"]
        assert [d["date"] for d in view["days"]] == [
            d["date"] for d in plan["days"] if d["date"][:7] == month]
        for day in view["days"]:
            workshops, buffers, fin = day["workshops"], day["buffers"], day["fin"]
            assert day["mode_summary"] == annual_days[day["date"]]["mode_summary"]
            assert day["hours_max"] == max(w["hours"] for w in workshops.values())
            for node in [*workshops.values(), *buffers.values()]:
                assert list(node["by_model"]) == models
                assert node["bod"] + node["in"] - node["out"] == node["eod"]
                for field in ("bod", "in", "out", "eod"):
                    assert node[field] == sum(v[field] for v in node["by_model"].values())
                for values in node["by_model"].values():
                    assert values["bod"] + values["in"] - values["out"] == values["eod"]
            for model in [None, *models]:
                nodes = {k: v if model is None else v["by_model"][model]
                         for k, v in {**workshops, **buffers}.items()}
                assert nodes["WBS"]["in"] == nodes["BS1"]["out"] + nodes["BS2"]["out"]
                assert nodes["WBS"]["out"] == nodes["PS"]["in"]
                assert nodes["PBS"]["in"] == nodes["PS"]["out"]
                assert nodes["PBS"]["out"] == nodes["AS_MAIN"]["in"]
                values = fin if model is None else fin["by_model"][model]
                assert values["fok"] == nodes["AS_FIN"]["out"]
            assert list(fin["by_model"]) == models
            for field in ("fok", "ws", "eod", "bl"):
                assert fin[field] == sum(v[field] for v in fin["by_model"].values())
            for name, workshop in workshops.items():
                for field in ("in", "out"):
                    cumulative[name][field] += workshop[field]
                    assert workshop[field + "_cum"] == cumulative[name][field]
            fok_cum += fin["fok"]
            ws_cum += fin["ws"]
            assert fin["fok_cum"] == fok_cum
            assert fin["ws_cum"] == ws_cum
        last = view["days"][-1]
        assert {k: v["eod"] for k, v in {**last["workshops"], **last["buffers"]}.items()} == facts["wip_eom"]
        assert last["fin"]["eod"] == facts["fin_eom"]
        print(f"PASS A3 {scenario_id} {month}: flow, by_model, cumulative, wip_eom", flush=True)
    print(f"PASS R3 {scenario_id}: all months/days mode_summary=annual, hours_max=max workshop hours",
          flush=True)


def main(skip_run=False):
    created = None
    seed_files = {p: p.read_bytes() for name in SEEDS
                  for p in (SCENARIOS / name).iterdir() if p.is_file()}
    try:
        with TestClient(app) as client:
            summaries = request(client, "GET", "/api/scenarios")
            for name in SEEDS:
                assert next(s for s in summaries if s["id"] == name)["state"] == "READY"
            print("PASS A1 GET /api/scenarios: pass, gap, gap-sat READY", flush=True)
            for name, gap in SEEDS.items():
                check_views(client, name, gap)

            new = request(client, "POST", "/api/scenarios",
                          json={"from_id": "gap-sat", "name": "T-13 后端自检"})
            created = (SCENARIOS / new["id"]).resolve()
            assert created.parent == SCENARIOS.resolve() and new["id"] not in SEEDS
            assert new["state"] == "NO_PLAN"
            assert (created / "input.json").read_bytes() == (SCENARIOS / "gap-sat" / "input.json").read_bytes()
            base = f"/api/scenarios/{new['id']}"
            request(client, "GET", base + "/annual", expected=404)
            request(client, "GET", base + "/monthly?month=2026-01", expected=404)
            request(client, "PUT", base + "/conditions", json={"conditions": []})
            assert read(created / "meta.json")["input_rev"] == 2
            conditions = request(client, "GET", base + "/conditions")
            assert conditions["conditions"] == []
            data = read(created / "input.json")
            assert conditions["options"]["auth_modes"] == [
                mode for mode in data["factory"]["modes"]
                if mode not in ("OFF", data["factory"]["default_mode"])]
            print("PASS A4 copy=NO_PLAN, missing plan=404, empty conditions, input_rev=2, auth_modes", flush=True)

            check_t15(client, SCENARIOS, request, read)
            check_t20(client, SCENARIOS, request, read)
            check_t21(client, SCENARIOS, request, read)
            if skip_run:
                print("SKIP T13 A5 expensive engine run (user authorized)", flush=True)
                return

            started = request(client, "POST", base + "/run")
            assert started["state"] == "RUNNING"
            request(client, "POST", base + "/run", expected=409)
            request(client, "PUT", base + "/conditions", expected=409, json={"conditions": []})
            print("PASS A5 run=RUNNING, immediate second run=409, PUT while running=409", flush=True)
            while True:
                result = next(s for s in request(client, "GET", "/api/scenarios") if s["id"] == new["id"])
                if result["state"] != "RUNNING":
                    break
                time.sleep(1)
            assert result["state"] == "READY", result
            gap_l1a = read(SCENARIOS / "gap" / "verdict.json")["objective"]["L1a"]
            assert result["objective"]["L1a"] == gap_l1a, result
            assert read(created / "meta.json")["plan_input_rev"] == 2
            print(f"PASS A5 state=READY, objective.L1a={gap_l1a} (= gap), plan_input_rev=2, "
                  f"seconds={result['run']['seconds']}", flush=True)
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        # TestClient 退出会等待后台线程，清理时不会删除仍在运行的文件。
        if created is not None:
            assert created.parent == SCENARIOS.resolve() and created.name not in SEEDS
            shutil.rmtree(created)
            assert not created.exists()
            print("PASS A6 selfcheck scenario removed", flush=True)
        assert all(p.read_bytes() == content for p, content in seed_files.items())
        print("PASS seed files unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-run", action="store_true", help="跳过旧 T-13 A5 耗时运行项")
    main(skip_run=parser.parse_args().skip_run)
