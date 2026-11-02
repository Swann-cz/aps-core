"""T-30 S1：临时目录核对一键导入范围及没排出计划的摘要。"""

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
from .selfcheck_t20 import save

backend = importlib.import_module("server.app")
ROOT = Path(__file__).resolve().parents[1]


def workbook(data):
    year = int(data["horizon"]["start"][:4])
    book = load_workbook(BytesIO(full_import.template(data, year, "T30")))
    book["计划信息"]["B2"] = data["horizon"]["start"]
    book["计划信息"]["C2"] = data["horizon"]["end"]
    for row in book["销售计划"].iter_rows(min_row=2):
        month, model = row[0].value, row[1].value
        row[2].value = data["demand"]["PR"][model][month]
        deliveries = [(d, n) for d, n in data["demand"]["WS_daily"].get(model, {}).items() if d[:7] == month]
        assert len(deliveries) <= 1
        row[3].value = sum(n for _, n in deliveries)
        row[4].value = deliveries[0][0] if deliveries else None
    labels = {kind: label for label, kind in full_import.TYPES.items()}
    for c in data["conditions"]:
        book["排产条件"].append([c["id"], labels[c["type"]], c.get("start"), c.get("end"), c.get("date"),
                                  ",".join(c["workshops"]) if "workshops" in c else c.get("workshop"),
                                  c.get("node"), c.get("mode"), c.get("target", c.get("out", c.get("hours_max"))),
                                  c.get("pre_stop_date"), c.get("reason")])
    return book


def main():
    if not all((ROOT / "cases/t30-trial" / name).exists()
               for name in ("trial-2models.input.json", "trial-3models.input.json")):
        print("跳过（无真实数据）")
        return
    trial2 = backend.read(ROOT / "cases/t30-trial/trial-2models.input.json")
    trial3 = backend.read(ROOT / "cases/t30-trial/trial-3models.input.json")
    for c in trial2["conditions"]:
        if c["type"] == "SATURDAY_AUTH" and "date" in c:
            c["start"] = c["end"] = c.pop("date")
    with tempfile.TemporaryDirectory(prefix="t30-", dir=ROOT / "server") as temp:
        scenarios = Path(temp)
        with patch.object(backend, "SCENARIOS", scenarios), TestClient(backend.app) as client:
            def post(book, route="/api/import/preview", expected=200):
                return request(client, "POST", route, expected=expected,
                               files={"file": ("t30.xlsx", save(book))})

            def reject(book, sheet, column, text):
                checked = post(book)
                assert not checked["ok"], checked
                error = next(e for e in checked["errors"]
                             if e["sheet"] == sheet and e["column"] == column and text in e["message"])
                assert f"第{error['row']}行" in error["message"] and "填了“" in error["message"]
                assert post(book, "/api/import", 422) == {"detail": "预检未通过", "errors": checked["errors"]}
                print("PASS S1 反例：" + error["message"] + "；创建返回 422", flush=True)
                book.close()

            book = workbook(trial3)
            reject(book, "车型", "车型编号", "车型最多 2 个")
            assert not list(scenarios.iterdir())
            book = workbook(trial2)
            preview = post(book)
            assert preview["ok"] and not preview["errors"], preview
            assert preview["summary"]["models"]["A"]["pr"] == sum(trial2["demand"]["PR"]["A"].values())
            created = post(book, "/api/import")
            path = scenarios / created["id"]
            actual = backend.read(path / "input.json")
            for key in ("factory", "initial", "wip_targets", "horizon", "conditions", "demand", "calendar", "rules", "wbs_hi"):
                assert actual[key] == trial2[key], key
            assert created["no_plan"] is True and created["findings"] == []
            book.close()
            print("PASS S1 trial-2models：工作簿预检通过；创建后输入与原数据逐项一致", flush=True)

            book = workbook(trial2)
            book["车型"]["B3"] = "BS1"
            reject(book, "车型", "焊装线", "每条焊装线最多绑定一个车型")
            book = workbook(trial2)
            book["车型"].delete_rows(2, book["车型"].max_row - 1)
            reject(book, "车型", "车型编号", "请填写 1 或 2 个车型")
            for node in ("WBS", "PBS"):
                book = workbook(trial2)
                row = next(r for r in book["节点"].iter_rows(min_row=2) if r[0].value == node)
                row[4].value = row[3].value + 1
                reject(book, "节点", "目标在制", "目标在制不能超过物理上限")
            book = workbook(trial2)
            book["销售计划"].delete_rows(2)
            reject(book, "销售计划", "月份", "请补齐月份 2026-01、车型 A")

            # 已有的第 2、3、5 条也从导入入口逐项核对。
            book = workbook(trial2)
            book["节点"].delete_rows(2)
            reject(book, "节点", "节点编号", "请补齐节点 BS1")
            book = workbook(trial2)
            book["节点"].append(["EXTRA", "多余节点", 1, 1, 1])
            reject(book, "节点", "节点编号", "请填写：")
            book = workbook(trial2)
            book["期初在制"]["B2"] = "B"
            reject(book, "期初在制", "位置", "只能放在绑定焊装线")
            book = workbook(trial2)
            row = next(r for r in book["节点"].iter_rows(min_row=2) if r[0].value == "PS")
            row[3].value = row[4].value - 1
            reject(book, "节点", "物理上限", "物理上限不能小于目标在制")
            book = workbook(trial2)
            book["排产条件"].append(["T30", "人工目标在制", trial2["horizon"]["start"], trial2["horizon"]["end"],
                                      None, None, "WBS", None, trial2["factory"]["buffers"]["WBS"]["cap_max"] + 1])
            reject(book, "排产条件", "数值", "人工目标在制不能超过上限")
            allowed = deepcopy(trial2)
            for node, values in allowed["initial"]["wip"].items():
                if node in full_import.WORKSHOPS:
                    model = next(iter(values))
                    values[model] += allowed["wip_targets"][node]
            allowed["conditions"].append({"id": "T30-UNCAPPED", "type": "WIP_TARGET", "node": "AS_MAIN",
                                           **allowed["horizon"], "target": allowed["wip_targets"]["AS_MAIN"] + 1})
            book = workbook(allowed)
            assert post(book)["ok"]
            book.close()
            print("PASS S1 允许范围：共享节点混车型、车间期初超上限、车间未填物理上限的人工目标均放行；物流顺序固定生成", flush=True)

            findings = ["求解器在时限内没找到可行计划，不能证明输入不可行", {"阶段": "L1a", "用时秒": 4}]
            errors = [{"rule": "C1", "date": trial2["horizon"]["start"], "node": None, "model": None,
                       "detail": "计划缺少某日记录"} for _ in range(1500)]
            verdict = {"verdict": "REJECT", "hard_errors": errors, "objective": {}, "phases": {}}
            backend.write(path / "verdict.json", verdict)
            meta = backend.read(path / "meta.json")
            meta["plan_input_rev"] = meta["input_rev"]
            backend.write(path / "meta.json", meta)
            url = f"/api/scenarios/{created['id']}"
            for status in ("FEASIBLE", "UNKNOWN", "INPUT_INVALID", "PROVEN_INFEASIBLE", "EXECUTION_ERROR"):
                backend.write(path / "plan.json", {"status": status, "days": [], "stop_list": [], "findings": findings})
                summary = next(s for s in request(client, "GET", "/api/scenarios") if s["id"] == created["id"])
                assert summary["no_plan"] is True and summary["findings"] == findings
                assert summary["verdict"] == "REJECT" and summary["hard_error_count"] == len(errors)
                for route in ("/annual", "/monthly?month=2026-01", "/conditions"):
                    view = request(client, "GET", url + route)
                    assert view["scenario"]["no_plan"] is True and view["scenario"]["findings"] == findings
                assert request(client, "GET", url + "/annual")["findings"] == findings
                assert backend.read(path / "verdict.json") == verdict
                print(f"PASS S1 {status} / days=[]：summary.no_plan=true；findings 原样；annual/monthly/conditions 可达；1500 条 C1 原始判定保留", flush=True)
            for status, no_plan in (("UNKNOWN", True), ("FEASIBLE", False)):
                backend.write(path / "plan.json", {"status": status, "days": [{}], "stop_list": [], "findings": findings})
                summary = backend.summary(path)
                assert summary["no_plan"] is no_plan
                print(f"PASS S1 {status} / days 非空：summary.no_plan={str(no_plan).lower()}", flush=True)
    print("PASS T30 S1：临时方案已清理；未调用生成器或判定器", flush=True)


if __name__ == "__main__":
    main()
