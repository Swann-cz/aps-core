"""T-28 S1：隔离方案验证导入、上限展示数据及条件保存。"""

from copy import deepcopy
from io import BytesIO
import importlib
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from . import full_import
from .selfcheck import request

backend = importlib.import_module("server.app")
ROOT = Path(__file__).resolve().parents[1]


def workbook(base):
    book = load_workbook(BytesIO(full_import.template(base, 2026, "T28")))
    for row in book["销售计划"].iter_rows(min_row=2):
        row[2].value = 0
        row[3].value = 0
    return book


def upload(book):
    stream = BytesIO()
    book.save(stream)
    return {"file": ("t28.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def main():
    if not (ROOT / "cases/1d-annual-feedback/feedback-pass-caps.input.json").exists():
        print("跳过（无真实数据）")
        return
    base = backend.read(ROOT / "cases/1d-annual-feedback/feedback-pass-caps.input.json")
    uncapped = deepcopy(base)
    for values in uncapped["factory"]["workshops"].values():
        del values["cap_max"]
    with tempfile.TemporaryDirectory(prefix="t28-", dir=ROOT / "server") as temp:
        with patch.object(backend, "SCENARIOS", Path(temp)), TestClient(backend.app) as client:
            for label, data in (("blank", uncapped), ("filled", base)):
                book = workbook(data)
                result = request(client, "POST", "/api/import/preview", files=upload(book))
                assert result["ok"], result
                scenario = request(client, "POST", "/api/import", files=upload(book))
                path = Path(temp) / scenario["id"]
                saved = backend.read(path / "input.json")
                assert saved["factory"]["workshops"] == data["factory"]["workshops"]
                response = client.get(f"/api/templates/full?year=2026&base_id={scenario['id']}")
                assert response.status_code == 200
                prefilled = load_workbook(BytesIO(response.content))
                for row in prefilled["节点"].iter_rows(min_row=2, values_only=True):
                    if row[0] in full_import.WORKSHOPS:
                        assert row[3] == data["factory"]["workshops"][row[0]].get("cap_max")
                prefilled.close()
                options = request(client, "GET", f"/api/scenarios/{scenario['id']}/conditions")["options"]
                assert options["caps"] == backend.views.node_caps(data)
                empty_plan = {"days": [], "stop_list": [], "findings": []}
                assert backend.views.monthly(saved, empty_plan, None, scenario, "2026-01")["caps"] == options["caps"]
                assert backend.views.annual(saved, empty_plan, None, scenario)["caps"] == options["caps"]
                print(f"PASS {label}: import/preview + import, workshop cap_max preserved/omitted, template prefill, conditions/monthly/annual caps", flush=True)

                for node in full_import.NODES:
                    cap = options["caps"][node]
                    value = cap if cap is not None else saved["wip_targets"][node] + 1
                    condition = {"id": "T28", "type": "WIP_TARGET", "node": node,
                                 "start": saved["horizon"]["start"], "end": saved["horizon"]["end"], "target": value}
                    url = f"/api/scenarios/{scenario['id']}/conditions"
                    request(client, "PUT", url, json={"conditions": [condition]})
                    if cap is not None:
                        before = {name: (path / name).read_bytes() for name in ("input.json", "meta.json")}
                        condition["target"] = cap + 1
                        rejected = request(client, "PUT", url, expected=422, json={"conditions": [condition]})
                        assert f"不能超过上限 {cap}" in rejected["detail"]
                        assert all((path / name).read_bytes() == content for name, content in before.items())
                        print(f"PASS {label} {node}: equal-cap save=200; over-cap save=422 {rejected['detail']}; input/meta unchanged", flush=True)
                    else:
                        print(f"PASS {label} {node}: uncapped manual target above base target save=200", flush=True)
                book.close()

            for node in full_import.WORKSHOPS:
                book = workbook(base)
                row = next(row for row in book["节点"].iter_rows(min_row=2) if row[0].value == node)
                row[3].value = base["wip_targets"][node] - 1
                result = request(client, "POST", "/api/import/preview", files=upload(book))
                assert not result["ok"]
                error = next(e for e in result["errors"] if "物理上限不能小于目标在制" in e["message"])
                assert (error["sheet"], error["row"], error["column"]) == ("节点", row[0].row, "物理上限")
                print(f"PASS below-target {node}: {error['message']}", flush=True)
                book.close()

            for node in full_import.NODES:
                cap = backend.views.node_caps(base)[node]
                book = workbook(base)
                book["排产条件"].append(["T28", "人工目标在制", base["horizon"]["start"], base["horizon"]["end"], None, None, node, None, cap + 1])
                result = request(client, "POST", "/api/import/preview", files=upload(book))
                error = next(e for e in result["errors"] if f"不能超过上限 {cap}" in e["message"])
                assert (error["sheet"], error["row"], error["column"]) == ("排产条件", 2, "数值")
                request(client, "POST", "/api/import", expected=422, files=upload(book))
                book["排产条件"]["I2"] = cap
                assert request(client, "POST", "/api/import/preview", files=upload(book))["ok"]
                print(f"PASS manual target {node}: over-cap preview error + import=422; equal-cap preview ok; {error['message']}", flush=True)
                book.close()
    print("PASS T28 S1 isolated scenarios removed", flush=True)


if __name__ == "__main__":
    main()
