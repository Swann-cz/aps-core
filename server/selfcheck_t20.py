"""T-20 A：模板、往返、中文预检错误；只删除自建方案。"""

from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import shutil

from openpyxl import load_workbook


def save(book):
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def check(client, scenarios, request, read):
    created = []
    seeds = {p: p.read_bytes() for name in ("gap", "gap-sat", "pass")
             for p in (scenarios / name).rglob("*") if p.is_file()}
    base = read(scenarios / "gap-sat" / "input.json")
    headers = {
        "计划信息": ["方案名称", "计划开始日", "计划结束日", "WBS 经验上限"],
        "节点": ["节点编号", "节点名称", "JPH", "物理上限", "目标在制"],
        "班制": ["班制编号", "班制名称", "小时", "是否默认"],
        "车型": ["车型编号", "焊装线", "胶龄"],
        "期初在制": ["位置", "车型", "数量"],
        "销售计划": ["月份", "车型", "PR", "WS", "交付日"],
        "生产行事历": ["日期", "能否生产", "原因"],
        "排产条件": ["条件编号", "条件类型", "开始日期", "结束日期", "单日日期", "车间", "节点", "班制", "数值", "停前日", "备注"],
        "规则常数": ["名称", "数值", "含义"],
    }

    def download(params):
        response = client.get("/api/templates/full", params=params)
        assert response.status_code == 200, response.text
        assert "attachment" in response.headers["content-disposition"]
        return load_workbook(BytesIO(response.content))

    def post(route, content, expected=200):
        return request(client, "POST", route, expected=expected, files={"file": ("full.xlsx", content)})

    try:
        book = download({"year": 2026, "base_id": "gap-sat"})
        assert book.sheetnames == ["填写说明", *headers]
        for name, columns in headers.items():
            assert list(next(book[name].values)) == columns, name
        spec = (Path(__file__).resolve().parents[1] / "spec" / "IMPORT_TEMPLATE.md").read_text(encoding="utf-8")
        assert [row[0] or "" for row in book["填写说明"].values] == spec[spec.index("## 3. 填写说明"):].splitlines()
        calendar = list(book["生产行事历"].values)[1:]
        expected_days = [date(2026, 1, 1) + timedelta(days=n) for n in range(379)]
        source_calendar = {r["date"]: r["is_working_capable"] for r in base["calendar"]}
        assert [(r[0], r[1]) for r in calendar] == [
            (d.isoformat(), "是" if source_calendar.get(d.isoformat(), d.weekday() < 5 and d != date(2027, 1, 1)) else "否")
            for d in expected_days]
        for sheet, columns in {"生产行事历": "B", "班制": "D", "车型": "B", "排产条件": "BGH", "期初在制": "AB", "销售计划": "B"}.items():
            for column in columns:
                assert any(f"{column}2" in v for v in book[sheet].data_validations.dataValidation)
        assert book["排产条件"].max_row == 1
        assert len(list(book["销售计划"].values)) == 25
        assert all(r[2:] == (None, None, None) for r in list(book["销售计划"].values)[1:])
        print("PASS T20 A1 full: 10 sheets, headers, complete instructions, 379 calendar days, dropdowns, base prefill", flush=True)

        empty = download({"year": 2026})
        assert all(all(v is None for v in r[2:]) for r in list(empty["节点"].values)[1:])
        assert empty["车型"].max_row == empty["期初在制"].max_row == 1
        assert [(r[0], r[2], r[3]) for r in list(empty["班制"].values)[1:]] == [
            ("OFF", 0, "否"), ("SINGLE_8H", 8, "是"), ("SINGLE_8P2", 10, "否"), ("DOUBLE_SHIFT", 16, "否")]
        assert [r[1] for r in list(empty["规则常数"].values)[1:]] == [3, 15, 131, 91, 0.1, 13]
        assert empty["计划信息"]["D2"].value is None
        empty.close()
        print("PASS T20 A1 v1.1 no base: blank business inputs, four modes, rule defaults", flush=True)

        book["计划信息"]["A2"] = "T-20 后端自检"
        book["计划信息"]["B2"] = base["horizon"]["start"]
        book["计划信息"]["C2"] = base["horizon"]["end"]
        for row in book["销售计划"].iter_rows(min_row=2):
            mo, model = row[0].value, row[1].value
            row[2].value = base["demand"]["PR"][model][mo]
            deliveries = [(d, n) for d, n in base["demand"]["WS_daily"].get(model, {}).items() if d[:7] == mo]
            assert len(deliveries) <= 1
            row[3].value = sum(n for _, n in deliveries)
            row[4].value = deliveries[0][0] if deliveries else None
        cal = {r["date"]: r["is_working_capable"] for r in base["calendar"]}
        for row in book["生产行事历"].iter_rows(min_row=2):
            if row[0].value in cal:
                row[1].value = "是" if cal[row[0].value] else "否"
        labels = dict(zip(("SATURDAY_AUTH", "MODE_AUTH", "SHUTDOWN", "CAPACITY_LOSS", "WIP_TARGET", "PRE_STOP_TARGET", "FIXED_OUTPUT"),
                          ("周六授权", "加班模式授权", "计划停线", "产能损失", "人工目标在制", "人工停前目标", "指定产量")))
        for c in base["conditions"]:
            book["排产条件"].append([c["id"], labels[c["type"]], c.get("start"), c.get("end"), c.get("date"),
                                      ",".join(c["workshops"]) if "workshops" in c else c.get("workshop"),
                                      c.get("node"), c.get("mode"), c.get("target", c.get("out", c.get("hours_max"))),
                                      c.get("pre_stop_date"), c.get("reason")])
        content = save(book)
        book.close()
        preview = post("/api/import/preview", content)
        assert preview["ok"] and preview["errors"] == [], preview
        new = post("/api/import", content)
        path = (scenarios / new["id"]).resolve()
        assert path.parent == scenarios.resolve() and path.name not in ("gap", "gap-sat", "pass")
        created.append(path)
        actual = read(path / "input.json")
        assert new["state"] == "NO_PLAN" and read(path / "meta.json")["input_rev"] == 1
        for key in ("horizon", "factory", "wip_targets", "wbs_hi", "rules", "initial"):
            assert actual[key] == base[key], key
        assert actual["demand"] == base["demand"]
        assert [r for r in actual["calendar"] if r["date"] <= actual["horizon"]["end"]] == [r for r in base["calendar"] if r["date"] <= base["horizon"]["end"]]
        assert actual["calendar"][-1]["date"] == "2027-01-14"
        def strip(cs):
            normalized = []
            for c in cs:
                c = {k: v for k, v in c.items() if k not in ("id", "reason")}
                if c["type"] == "SATURDAY_AUTH" and "date" in c:
                    c["start"] = c["end"] = c.pop("date")
                normalized.append(c)
            return normalized
        assert strip(actual["conditions"]) == strip(base["conditions"])
        assert preview["summary"]["models"]["A"]["ws"] == sum(base["demand"]["WS_daily"]["A"].values())
        print("PASS T20 A2 roundtrip: preview/create, NO_PLAN/rev1, exact factory/initial/rules/PR/WS/calendar, conditions", flush=True)

        invalid = [
            ("missing sheet", "车型", 1, "工作表", lambda b: b.remove(b["车型"])),
            ("changed header", "销售计划", 1, "PR", lambda b: setattr(b["销售计划"]["C1"], "value", "生产量")),
            ("WBS missing cap", "节点", 4, "物理上限", lambda b: setattr(b["节点"]["D4"], "value", None)),
            ("two default modes", "班制", 4, "是否默认", lambda b: setattr(b["班制"]["D4"], "value", "是")),
            ("BS3 model line", "车型", 2, "焊装线", lambda b: setattr(b["车型"]["B2"], "value", "BS3")),
            ("A on BS2", "期初在制", 2, "位置", lambda b: setattr(b["期初在制"]["A2"], "value", "BS2")),
            ("delivery outside month", "销售计划", 2, "交付日", lambda b: setattr(b["销售计划"]["E2"], "value", "2026-02-01")),
            ("unknown condition", "排产条件", 2, "条件类型", lambda b: setattr(b["排产条件"]["B2"], "value", "错别字")),
            ("mode auth missing mode", "排产条件", 5, "班制", lambda b: b["排产条件"].append([None, "加班模式授权", "2026-11-02", "2026-11-30", None, "BS1"])),
            ("bad date", "生产行事历", 2, "日期", lambda b: setattr(b["生产行事历"]["A2"], "value", "2026/01/01")),
        ]
        for label, sheet, row, column, mutate in invalid:
            bad = load_workbook(BytesIO(content))
            mutate(bad)
            bad_content = save(bad)
            bad.close()
            checked = post("/api/import/preview", bad_content)
            assert not checked["ok"], label
            assert any(e["sheet"] == sheet and e["row"] == row and e["column"] == column
                       and "填了" in e["message"] and "第" in e["message"] for e in checked["errors"]), checked
            failed = post("/api/import", bad_content, expected=422)
            assert failed == {"detail": "预检未通过", "errors": checked["errors"]}
            print(f"PASS T20 A3 {label}: Chinese sheet/row/column, create=422", flush=True)
    finally:
        for path in created:
            assert path.parent == scenarios.resolve() and path.name not in ("gap", "gap-sat", "pass")
            shutil.rmtree(path)
            assert not path.exists()
        assert all(p.read_bytes() == value for p, value in seeds.items())
        print("PASS T20 A4 selfcheck scenarios removed, seed files byte-identical", flush=True)
