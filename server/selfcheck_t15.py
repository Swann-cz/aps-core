"""T-15 A 验收；所有写入仅落在本次新建方案。"""

from datetime import date, timedelta
from io import BytesIO
import shutil

from openpyxl import Workbook, load_workbook


def xlsx(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def check(client, scenarios, request, read):
    created = []
    seeds = {p: p.read_bytes() for name in ("gap", "gap-sat", "pass")
             for p in (scenarios / name).rglob("*") if p.is_file()}
    base = read(scenarios / "gap" / "input.json")
    models = base["factory"]["models"]
    year = int(base["horizon"]["start"][:4])
    headers = {"sales": ["月份", "车型类别", "PR", "WS"],
               "initial": ["输入项", "车型类别", "数量"],
               "calendar": ["日期", "是否具备生产能力", "原因"]}
    nodes = {"成品库存": None, "BS在制": "BS", "WBS缓冲": "WBS", "PS在制": "PS",
             "PBS缓冲": "PBS", "AS主线在制": "AS_MAIN", "AS终线在制": "AS_FIN"}

    def remember(result):
        path = (scenarios / result["id"]).resolve()
        assert path.parent == scenarios.resolve() and path.name not in ("gap", "gap-sat", "pass")
        created.append(path)
        return path

    try:
        templates = {}
        for kind in headers:
            response = client.get(f"/api/templates/{kind}", params={"base_id": "gap", "year": year})
            assert response.status_code == 200
            assert "attachment" in response.headers["content-disposition"]
            book = load_workbook(BytesIO(response.content))
            rows = list(book.active.values)
            book.close()
            assert list(rows[0]) == headers[kind]
            templates[kind] = response.content
            if kind == "initial":
                assert len(rows) == 1 + 7 * len(models)
                for item, model, value in rows[1:]:
                    node = models[model]["line"] if nodes[item] == "BS" else nodes[item]
                    values = base["initial"]["fin"] if node is None else base["initial"]["wip"].get(node, {})
                    assert value == values.get(model, 0)
            elif kind == "sales":
                assert len(rows) == 1 + 12 * len(models)
                assert all(row[2:] == (None, None) for row in rows[1:])
            else:
                assert len(rows) == 1 + (date(year + 1, 1, 1) - date(year, 1, 1)).days
            print(f"PASS T15 A1 {kind}: download, xlsx, headers, template values", flush=True)

        sales_rows = [headers["sales"]]
        for model, months in base["demand"]["PR"].items():
            for month, pr in months.items():
                ws = sum(v for d, v in base["demand"]["WS_daily"].get(model, {}).items() if d[:7] == month)
                sales_rows.append([month, model, pr, ws])
        sales = xlsx(sales_rows)
        form = {"base_id": "gap", **base["horizon"]}
        files = {"sales": ("sales.xlsx", sales), "initial": ("initial.xlsx", templates["initial"])}
        preview = request(client, "POST", "/api/new-plan/preview", data=form, files=files)
        assert preview["ok"] and preview["errors"] == []
        new = request(client, "POST", "/api/new-plan", data={**form, "name": "T-15 后端自检"}, files=files)
        path = remember(new)
        assert new["state"] == "NO_PLAN" and new["formal"] is None
        assert read(path / "meta.json")["input_rev"] == 1
        assert not (path / "plan.json").exists()
        actual = read(path / "input.json")
        for key in ("initial", "factory", "wip_targets", "wbs_hi", "rules"):
            assert actual[key] == base[key], key
        assert actual["demand"]["PR"] == base["demand"]["PR"]
        assert actual["conditions"] == []
        cal = {r["date"]: r["is_working_capable"] for r in actual["calendar"]}
        start = date.fromisoformat(form["start"])
        end = date.fromisoformat(form["end"])
        assert list(cal) == [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 15)]
        defaults = {r["date"][5:]: r["is_working_capable"] for r in base["calendar"]}
        assert all(flag == defaults.get(d[5:], date.fromisoformat(d).weekday() < 5) for d, flag in cal.items())
        for month, model, pr, ws in sales_rows[1:]:
            entries = {d: v for d, v in actual["demand"]["WS_daily"].get(model, {}).items() if d[:7] == month}
            month_days = [d for d in cal if form["start"] <= d <= form["end"] and d[:7] == month]
            expected_day = ([d for d in month_days if cal[d]] or month_days)[-1]
            assert entries == {expected_day: ws}
        for model in models:
            assert preview["summary"]["models"][model] == {
                "pr": sum(base["demand"]["PR"][model].values()),
                "ws": sum(base["demand"]["WS_daily"].get(model, {}).values()),
                "initial_wip": sum(n.get(model, 0) for n in base["initial"]["wip"].values())}
        assert preview["summary"]["fin0"] == base["initial"]["fin"]
        assert preview["summary"]["working_days"] == sum(v for d, v in cal.items() if d <= form["end"])
        print("PASS T15 A2 preview/create: PR, monthly WS, initial, factory, targets, rules, calendar +14 days, summary", flush=True)

        first = sales_rows[1]
        invalid = [
            ("unknown model", "sales", xlsx([headers["sales"], [first[0], "UNKNOWN", 0, 0]]), "车型类别不存在", 2),
            ("outside month", "sales", xlsx([headers["sales"], ["1900-01", first[1], 0, 0]]), "月份不在计划期", 2),
            ("negative PR", "sales", xlsx([headers["sales"], [first[0], first[1], -1, 0]]), "PR数量必须为非负整数", 2),
            ("duplicate", "sales", xlsx([headers["sales"], first, first]), "同月同车型重复", 3),
            ("bad date", "calendar", xlsx([headers["calendar"], ["bad-date", "是", None]]), "日期格式错误", 2),
            ("non Excel", "sales", b"not an Excel file", "无法读取 Excel 文件", 1),
        ]
        for label, kind, content, message, row in invalid:
            bad_files = {**files, kind: (f"{kind}.xlsx", content)}
            result = request(client, "POST", "/api/new-plan/preview", data=form, files=bad_files)
            assert not result["ok"]
            assert any(e["file"] == f"{kind}.xlsx" and e["row"] == row and message in e["message"]
                       for e in result["errors"]), result
            failed = request(client, "POST", "/api/new-plan", expected=422,
                             data={**form, "name": "错误方案"}, files=bad_files)
            assert failed == {"detail": "预检未通过", "errors": result["errors"]}
            print(f"PASS T15 A3 {label}: Chinese error, file/row, create=422, same errors", flush=True)

        formal = request(client, "POST", "/api/scenarios/gap-sat/finalize", json={"note": "T-15 自检"})
        formal_path = remember(formal)
        assert formal["formal"]["source_id"] == "gap-sat"
        assert formal["formal"]["note"] == "T-15 自检"
        assert "（正式 " in formal["name"] and formal["state"] == "READY"
        for p in (scenarios / "gap-sat").rglob("*"):
            if p.is_file() and p.name != "meta.json":
                assert (formal_path / p.relative_to(scenarios / "gap-sat")).read_bytes() == p.read_bytes()
        for method, route, body in (("PUT", "conditions", {"conditions": []}),
                                    ("POST", "run", None), ("POST", "finalize", {"note": ""})):
            result = request(client, method, f"/api/scenarios/{formal['id']}/{route}", expected=409, json=body)
            assert result == {"detail": "正式版本只读"}
        listed = request(client, "GET", "/api/scenarios")
        assert next(s for s in listed if s["id"] == formal["id"])["formal"]["source_id"] == "gap-sat"
        copy = request(client, "POST", "/api/scenarios", json={"from_id": formal["id"], "name": "T-15 自检副本"})
        remember(copy)
        assert copy["formal"] is None and copy["state"] == "NO_PLAN"
        assert all(p.read_bytes() == data for p, data in seeds.items())
        print("PASS T15 A4 finalize: full copy, formal/source/name, three 409s, list, editable copy, source unchanged", flush=True)
    except Exception as exc:
        print(f"FAIL T15 {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        for path in created:
            assert path.parent == scenarios.resolve() and path.name not in ("gap", "gap-sat", "pass")
            shutil.rmtree(path)
            assert not path.exists()
        assert all(p.read_bytes() == content for p, content in seeds.items())
        listed = request(client, "GET", "/api/scenarios")
        assert all(s["id"] not in {p.name for p in created} for s in listed)
        print("PASS T15 A5 created scenarios removed, removed formal absent, seed files byte-identical", flush=True)
