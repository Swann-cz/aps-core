"""T-34-S：导入预检的单日条件、缓冲区期初和 OFF 班制回归。"""

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook

from . import full_import
from .selfcheck_t20 import save

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases" / "t33-redteam"


def check(content):
    return full_import.preview(SimpleNamespace(file=BytesIO(content), filename="t34.xlsx"))


def workbook(name="R10-single-date-import"):
    return load_workbook(CASES / f"{name}.xlsx")


def reject(result, sheet, rows, column, text):
    assert result["ok"] is False, result
    assert {e["row"] for e in result["errors"]} == set(rows), result
    assert all(e["sheet"] == sheet and e["column"] == column and text in e["message"]
               and f"第{e['row']}行" in e["message"] and "填了“" in e["message"]
               for e in result["errors"]), result


def main():
    source = json.loads((CASES / "R10-single-date-import.input.json").read_text(encoding="utf-8"))
    result, actual, _ = check((CASES / "R10-single-date-import.xlsx").read_bytes())
    assert result["ok"] is True and result["errors"] == [], result
    assert actual["conditions"] == source["conditions"], actual["conditions"]
    print("PASS S1 R10-single-date-import.xlsx：ok=true；conditions 与同名 input.json 完全一致", flush=True)
    single_day = source["conditions"][0]["start"]
    mode = next(m for m in source["factory"]["modes"] if m not in ("OFF", source["factory"]["default_mode"]))
    rows = [
        ["SAT", "周六授权", None, None, single_day],
        ["MODE", "加班模式授权", None, None, single_day, "PS", None, mode],
        ["STOP", "计划停线", None, None, single_day],
        ["LOSS", "产能损失", None, None, single_day, "PS", None, None, source["conditions"][0]["hours_max"]],
        ["WIP", "人工目标在制", None, None, single_day, None, "WBS", None, source["wip_targets"]["WBS"]],
    ]
    for row in rows:
        book = workbook()
        sheet = book["排产条件"]
        sheet.delete_rows(2, sheet.max_row - 1)
        sheet.append(row)
        result, data, _ = check(save(book))
        assert result["ok"], result
        expected = data["conditions"]
        assert expected[0]["start"] == expected[0]["end"] == single_day
        assert "date" not in expected[0]
        sheet["E2"] = None
        sheet["C2"] = sheet["D2"] = single_day
        result, data, _ = check(save(book))
        assert result["ok"] and data["conditions"] == expected, result
        for columns in (("C2",), ("D2",), ("C2", "D2")):
            sheet["C2"] = sheet["D2"] = None
            sheet["E2"] = single_day
            for column in columns:
                sheet[column] = single_day
            result, _, _ = check(save(book))
            reject(result, "排产条件", [2], "单日日期", "单日日期和开始/结束日期只填一种")
        book.close()
        print(f"PASS S3 R10 {row[1]}：单日与起止转换一致；混填开始、结束、两者均报错并定位第2行", flush=True)

    result, _, _ = check((CASES / "R11-buffer-scope.xlsx").read_bytes())
    reject(result, "期初在制", [5], "数量", "PBS 期初 400 台，超过物理上限 150 台；缓冲区期初不能超过上限，请核对盘点数或上限")
    print("PASS S2 R11-buffer-scope.xlsx：ok=false；" + result["errors"][0]["message"], flush=True)
    for node in ("WBS", "PBS"):
        book = workbook("R11-buffer-scope")
        initial = book["期初在制"]
        initial["C5"] = source["factory"]["buffers"]["PBS"]["cap_max"]
        book["车型"].append(["B", "BS2", source["factory"]["models"]["A"]["glue_age_max"]])
        book["销售计划"].append([single_day[:7], "B", 0, 0])
        target_row = next(r for r in initial.iter_rows(min_row=2) if r[0].value == node)
        cap = source["factory"]["buffers"][node]["cap_max"]
        target_row[2].value = cap - 1
        initial.append([node, "B", 1])
        result, _, _ = check(save(book))
        assert result["ok"], result
        target_row[2].value = cap
        result, _, _ = check(save(book))
        reject(result, "期初在制", [target_row[0].row, initial.max_row], "数量",
               f"{node} 期初 {cap + 1} 台，超过物理上限 {cap} 台")
        book.close()
        print(f"PASS S3 R11 {node}：两车型合计等于上限放行；合计超1台报错并定位两条期初行", flush=True)
    book = workbook()
    for node in full_import.WORKSHOPS:
        node_row = next(r for r in book["节点"].iter_rows(min_row=2) if r[0].value == node)
        node_row[3].value = source["wip_targets"][node]
        for initial_row in book["期初在制"].iter_rows(min_row=2):
            if initial_row[0].value == node:
                initial_row[2].value = node_row[3].value + 1
    result, _, _ = check(save(book))
    assert result["ok"], result
    book.close()
    print("PASS S3 R11：车间已填物理上限且期初超上限仍放行", flush=True)

    result, _, _ = check((CASES / "R12-missing-off.xlsx").read_bytes())
    reject(result, "班制", [2], "班制编号", "班制表必须保留 OFF（停）这一行，小时填 0")
    print("PASS S2 R12-missing-off.xlsx：ok=false；" + result["errors"][0]["message"], flush=True)
    book = workbook("R12-missing-off")
    book["班制"].append(["OFF", "停", 0, "否"])
    result, _, _ = check(save(book))
    assert result["ok"], result
    off_row = book["班制"].max_row
    book["班制"].cell(off_row, 3, 1)
    result, _, _ = check(save(book))
    reject(result, "班制", [off_row], "小时", "OFF 的小时必须为 0")
    book.close()
    print("PASS S3 R12：补回 OFF=0 放行；OFF 小时非0仍报错并定位对应行", flush=True)

    spec = (ROOT / "spec" / "IMPORT_TEMPLATE.md").read_text(encoding="utf-8")
    instructions = spec[spec.index("## 3. 填写说明"):]
    book = load_workbook(BytesIO(full_import.template(None, 2026)))
    assert [r[0] or "" for r in book["填写说明"].values] == instructions.splitlines()
    assert "缓冲区 WBS、PBS** 期初台数不能超过物理上限" in instructions
    assert "OFF（停）这一行必须保留" in instructions
    assert "下表写“开始日期、结束日期”的类型都适用（v1.7）" in instructions
    book.close()
    print("PASS S3 填写说明：生成结果与 IMPORT_TEMPLATE v1.7 第3节逐行一致，包含三项新规则", flush=True)
    print("PASS T34-S：S1–S3 导入回归通过；工作簿变体仅在内存中构造", flush=True)


if __name__ == "__main__":
    main()
