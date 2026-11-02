"""T-21：模板预填与只补销售计划的导入往返。"""

from copy import deepcopy
from datetime import date
from io import BytesIO
import shutil

from openpyxl import load_workbook

from .full_import import template
from .selfcheck_t20 import save


def check(client, scenarios, request, read):
    created = None
    seeds = {p: p.read_bytes() for name in ("gap", "gap-sat", "pass")
             for p in (scenarios / name).rglob("*") if p.is_file()}
    base = read(scenarios / "gap-sat" / "input.json")
    source_calendar = {r["date"]: r["is_working_capable"] for r in base["calendar"]}

    def download(**params):
        response = client.get("/api/templates/full", params=params)
        assert response.status_code == 200, response.text
        return load_workbook(BytesIO(response.content))

    try:
        book = download(year=2026, base_id="gap-sat")
        for day, capable, reason in list(book["生产行事历"].values)[1:]:
            if day.startswith("2026-"):
                expected = source_calendar[day]
                assert capable == ("是" if expected else "否"), day
                default = date.fromisoformat(day).weekday() < 5
                assert reason == (("沿用来源方案：调休上班" if expected else "沿用来源方案：放假或停产")
                                  if expected != default else None), day
        calendar = {r[0]: r[1:] for r in list(book["生产行事历"].values)[1:]}
        assert calendar["2027-01-01"] == ("否", "元旦（次年日历未发布时的默认）")
        print("PASS T21 A1 source calendar: all 2026 dates and reasons, next New Year off", flush=True)

        empty = download(year=2026)
        for day, capable, reason in list(empty["生产行事历"].values)[1:]:
            expected = date.fromisoformat(day).weekday() < 5 and day != "2027-01-01"
            assert capable == ("是" if expected else "否"), day
            assert reason == ("元旦（次年日历未发布时的默认）" if day == "2027-01-01" else None)
        assert empty["计划信息"]["A2"].value is None
        assert all(c.comment is None for row in empty["期初在制"] for c in row)
        empty.close()
        print("PASS T21 A2 no base: weekday defaults, next New Year off, blank name, no comments", flush=True)

        assert book["计划信息"]["A2"].value == "gap 组 + 三个全线周六 2026"
        comment = "照抄自来源方案 gap 组 + 三个全线周六 的期初，请按本次计划开始日的最新盘点核对后再上传"
        assert all(c.comment and c.comment.text == comment for c in book["期初在制"][1])
        assert all(r[2:] == (None, None, None) for r in list(book["销售计划"].values)[1:])
        assert book["排产条件"].max_row == 1
        print("PASS T21 A3 source name, three header comments, blank sales quantities and conditions", flush=True)

        for row in book["销售计划"].iter_rows(min_row=2):
            month, model = row[0].value, row[1].value
            row[2].value = base["demand"]["PR"][model][month]
            row[3].value = sum(n for d, n in base["demand"]["WS_daily"].get(model, {}).items() if d[:7] == month)
        content = save(book)
        book.close()
        files = {"file": ("full.xlsx", content)}
        preview = request(client, "POST", "/api/import/preview", files=files)
        assert preview["ok"] and preview["errors"] == [], preview
        new = request(client, "POST", "/api/import", files=files)
        created = (scenarios / new["id"]).resolve()
        assert created.parent == scenarios.resolve() and created.name not in ("gap", "gap-sat", "pass")
        actual = read(created / "input.json")
        assert [r for r in actual["calendar"] if r["date"] <= actual["horizon"]["end"]] == [
            r for r in base["calendar"] if r["date"] <= base["horizon"]["end"]]
        assert actual["conditions"] == []
        print("PASS T21 A4 only PR/WS filled: preview ok, created input calendar matches source", flush=True)

        other = download(year=2028, base_id="gap-sat")
        for day, capable, reason in list(other["生产行事历"].values)[1:]:
            expected = date.fromisoformat(day).weekday() < 5 and day != "2029-01-01"
            assert capable == ("是" if expected else "否"), day
            assert reason == ("元旦（次年日历未发布时的默认）" if day == "2029-01-01" else None)
        other.close()
        extended = deepcopy(base)
        extended["calendar"].append({"date": "2027-01-01", "is_working_capable": True})
        special = load_workbook(BytesIO(template(extended, 2026, "  来源\r\n方案  ")))
        assert special["计划信息"]["A2"].value == "来源方案 2026"
        assert all("来源方案 来源方案 的期初" in c.comment.text for c in special["期初在制"][1])
        calendar = {r[0]: r[1:] for r in list(special["生产行事历"].values)[1:]}
        assert calendar["2027-01-01"] == ("是", None)
        special.close()
        print("PASS T21 boundaries: exact dates across years, source New Year wins, name whitespace/newlines removed", flush=True)
    finally:
        if created is not None:
            assert created.parent == scenarios.resolve() and created.name not in ("gap", "gap-sat", "pass")
            shutil.rmtree(created)
            assert not created.exists()
        assert all(p.read_bytes() == content for p, content in seeds.items())
        print("PASS T21 cleanup: created scenario removed, seed files byte-identical", flush=True)
