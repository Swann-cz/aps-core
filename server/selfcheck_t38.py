"""T-38：停线人工目标在制必须覆盖整段全线停线；变体只在内存构造。"""
from datetime import date, timedelta
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import full_import
from server.selfcheck_t20 import save
from server.selfcheck_t34 import CASES, check, reject, workbook


def main():
    source = json.loads((CASES / "R10-single-date-import.input.json").read_text(encoding="utf-8"))
    start = source["horizon"]["start"]
    middle = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
    end = (date.fromisoformat(start) + timedelta(days=2)).isoformat()
    target = source["wip_targets"]["PS"]
    for workshops in (None, ",".join(full_import.WORKSHOPS)):
        for first, last in ((middle, end), (start, middle), (middle, middle), (start, end)):
            book = workbook()
            sheet = book["排产条件"]
            sheet.delete_rows(2, sheet.max_row - 1)
            sheet.append(["STOP", "计划停线", start, end, None, workshops])
            sheet.append(["WIP", "人工目标在制", first, last, None, None, "PS", None, target])
            result, data, _ = check(save(book))
            if first == start and last == end:
                assert result["ok"] and result["errors"] == [], result
                assert data["conditions"][1]["target"] == target
            else:
                reject(result, "排产条件", [3], "开始日期/结束日期", "盖住整段停线")
                assert all("STOP" in e["message"] and start in e["message"] and end in e["message"]
                           for e in result["errors"]), result
            book.close()
        print(f"PASS T38 全线车间={workshops}：部分重叠定位第3行；完整覆盖放行", flush=True)
    for first, last, workshops in ((middle, middle, "PS"), (end, end, None)):
        book = workbook()
        sheet = book["排产条件"]
        sheet.delete_rows(2, sheet.max_row - 1)
        sheet.append(["STOP", "计划停线", start, middle, None, workshops])
        sheet.append(["WIP", "人工目标在制", first, last, None, None, "PS", None, target])
        result, _, _ = check(save(book))
        assert result["ok"] and result["errors"] == [], result
        book.close()
    print("PASS T38：单车间停线、无重叠目标不触发全线覆盖预检", flush=True)


if __name__ == "__main__":
    main()
