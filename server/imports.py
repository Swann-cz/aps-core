"""UI_CONTRACT §8.1 的 Excel 模板与输入转换。"""

from copy import deepcopy
from datetime import date, datetime, timedelta
from io import BytesIO
import re

from openpyxl import Workbook, load_workbook

from .views import months_in

HEADERS = {"sales": ["月份", "车型类别", "PR", "WS"],
           "initial": ["输入项", "车型类别", "数量"],
           "calendar": ["日期", "是否具备生产能力", "原因"]}
ITEMS = {"成品库存": None, "BS在制": "BS", "WBS缓冲": "WBS", "PS在制": "PS",
         "PBS缓冲": "PBS", "AS主线在制": "AS_MAIN", "AS终线在制": "AS_FIN"}


def days(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def default_calendar(base, start, end):
    defaults = {row["date"][5:]: row["is_working_capable"] for row in base["calendar"]}
    return {d.isoformat(): defaults.get(d.strftime("%m-%d"), d.weekday() < 5)
            for d in days(start, end)}


def initial_node(base, item, model):
    node = ITEMS[item]
    return base["factory"]["models"][model]["line"] if node == "BS" else node


def template(base, kind, year):
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS[kind])
    models = sorted(base["factory"]["models"])
    if kind == "sales":
        for month in range(1, 13):
            for model in models:
                sheet.append([f"{year:04d}-{month:02d}", model, None, None])
    elif kind == "initial":
        for item in ITEMS:
            for model in models:
                node = initial_node(base, item, model)
                values = base["initial"]["fin"] if node is None else base["initial"]["wip"].get(node, {})
                sheet.append([item, model, values.get(model, 0)])
    else:
        for day, capable in default_calendar(base, date(year, 1, 1), date(year, 12, 31)).items():
            sheet.append([day, "是" if capable else "否", None])
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def rows(upload, kind, errors):
    def error(row, message):
        errors.append({"file": upload.filename, "row": row, "message": message})
    try:
        if not upload.filename.lower().endswith(".xlsx"):
            raise ValueError("not xlsx")
        book = load_workbook(upload.file, read_only=True, data_only=True)
        try:
            values = list(book.worksheets[0].values)
        finally:
            book.close()
    except Exception:
        error(1, "无法读取 Excel 文件")
        return []
    headers = list(values[0]) if values else []
    missing = [name for name in HEADERS[kind] if name not in headers]
    if missing:
        error(1, "缺表头：" + "、".join(missing))
        return []
    return [(index, {name: row[headers.index(name)] for name in HEADERS[kind]})
            for index, row in enumerate(values[1:], 2) if any(v is not None for v in row)]


def preview(base, start, end, sales, initial=None, calendar=None):
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    horizon = {"start": start, "end": end}
    months = months_in(horizon)
    models = base["factory"]["models"]
    errors = []
    pr = {m: dict.fromkeys(months, 0) for m in models}
    ws = {m: dict.fromkeys(months, 0) for m in models}
    cal = default_calendar(base, start_day, end_day + timedelta(days=14))
    initial_data = deepcopy(base["initial"]) if initial is None else {"wip": {}, "fin": {}}

    def error(upload, row, message):
        errors.append({"file": upload.filename, "row": row, "message": message})

    def quantity(upload, row, value, label):
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value != int(value):
            error(upload, row, f"{label}数量必须为非负整数：{value}")
            return 0
        return int(value)

    seen = set()
    for row, values in rows(sales, "sales", errors):
        month = values["月份"]
        if isinstance(month, (date, datetime)):
            month = month.strftime("%Y-%m")
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            error(sales, row, f"月份格式错误：{month}")
            continue
        if month not in months:
            error(sales, row, f"月份不在计划期：{month}")
            continue
        model = values["车型类别"]
        if model not in models:
            error(sales, row, f"车型类别不存在：{model}")
            continue
        if (month, model) in seen:
            error(sales, row, f"同月同车型重复：{month} / {model}")
        seen.add((month, model))
        pr[model][month] = quantity(sales, row, values["PR"], "PR")
        ws[model][month] = quantity(sales, row, values["WS"], "WS")

    if initial is not None:
        seen = set()
        for row, values in rows(initial, "initial", errors):
            item, model = values["输入项"], values["车型类别"]
            if item not in ITEMS:
                error(initial, row, f"输入项不存在：{item}")
                continue
            if model not in models:
                error(initial, row, f"车型类别不存在：{model}")
                continue
            if (item, model) in seen:
                error(initial, row, f"期初同一输入项同车型重复：{item} / {model}")
            seen.add((item, model))
            node = initial_node(base, item, model)
            target = initial_data["fin"] if node is None else initial_data["wip"].setdefault(node, {})
            target[model] = quantity(initial, row, values["数量"], "期初")

    if calendar is not None:
        for row, values in rows(calendar, "calendar", errors):
            day = values["日期"]
            if isinstance(day, (date, datetime)):
                day = day.strftime("%Y-%m-%d")
            try:
                if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                    raise ValueError()
                date.fromisoformat(day)
            except ValueError:
                error(calendar, row, f"日期格式错误：{day}")
                continue
            if day not in cal:
                error(calendar, row, f"日期不在计划期及之后14天内：{day}")
                continue
            flag = str(values["是否具备生产能力"]).strip().lower()
            if flag not in ("是", "否", "1", "0", "true", "false", "y", "n"):
                error(calendar, row, f"是否具备生产能力须为是/否：{values['是否具备生产能力']}")
                continue
            cal[day] = flag in ("是", "1", "true", "y")

    ws_daily = {m: {} for m in models}
    for month in months:
        month_days = [d for d in cal if start <= d <= end and d[:7] == month]
        working = [d for d in month_days if cal[d]]
        delivery = (working or month_days)[-1]
        for model in models:
            ws_daily[model][delivery] = ws[model][month]
    data = {"schema": base["schema"], "horizon": horizon,
            **{key: deepcopy(base[key]) for key in ("factory", "wip_targets", "wbs_hi", "rules")},
            "calendar": [{"date": d, "is_working_capable": capable} for d, capable in cal.items()],
            "demand": {"PR": pr, "WS_daily": ws_daily}, "initial": initial_data, "conditions": []}
    result = {"ok": not errors, "errors": errors,
              "summary": {"models": {m: {"pr": sum(pr[m].values()), "ws": sum(ws[m].values()),
                                          "initial_wip": sum(n.get(m, 0) for n in initial_data["wip"].values())}
                                     for m in models},
                          "working_days": sum(v for d, v in cal.items() if start <= d <= end),
                          "fin0": initial_data["fin"]}}
    return result, data
