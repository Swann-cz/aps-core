"""IMPORT_TEMPLATE v1.10：完整工作簿下载与预检。"""

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import re

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from .imports import days
from .views import months_in

HEADERS = {
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
NODES = dict(zip(("BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"),
                 ("焊装1", "焊装2", "焊装缓冲", "涂装", "涂装缓冲", "总装主线", "总装完成线")))
WORKSHOPS = [n for n in NODES if n not in ("WBS", "PBS")]
FLOW = ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN", "AS_MAIN>AS_FIN", "AS_FIN>FIN"]
TYPES = dict(zip(("周六授权", "加班模式授权", "计划停线", "产能损失", "人工目标在制", "人工停前目标", "指定产量"),
                 ("SATURDAY_AUTH", "MODE_AUTH", "SHUTDOWN", "CAPACITY_LOSS", "WIP_TARGET", "PRE_STOP_TARGET", "FIXED_OUTPUT")))
RULES = {
    "停线最短天数": ("ps_stop_min_days", 3, "涂装连续停几天以上算停线"),
    "长停线天数": ("ps_long_stop_days", 15, "停线达到几天算长停线"),
    "短停线停前目标": ("ps_pre_stop_target_short", 131, "短停线前一天涂装最多留的台数"),
    "长停线停前目标": ("ps_pre_stop_target_long", 91, "长停线前一天涂装最多留的台数"),
    "月度带比例": ("monthly_band_ratio", 0.1, "月度产量允许低于 PR 的比例（唯一允许小数的格）"),
    "共享焊装能力": ("shared_welding_jph_max", 13, "两条焊装线合计的 JPH 上限"),
}


def instructions():
    text = (Path(__file__).resolve().parents[1] / "spec" / "IMPORT_TEMPLATE.md").read_text(encoding="utf-8")
    return text[text.index("## 3. 填写说明"):]


def template(base, year, base_name=""):
    book = Workbook()
    book.active.title = "填写说明"
    for line in instructions().splitlines():
        book.active.append([line])
    for name, headers in HEADERS.items():
        book.create_sheet(name).append(headers)
    base_name = base_name.replace("\r", "").replace("\n", "").strip()
    book["计划信息"].append([f"{base_name} {year}" if base else None, f"{year}-01-01", f"{year}-12-31", base["wbs_hi"] if base else None])
    for node, name in NODES.items():
        book["节点"].append([node, name,
                             base["factory"]["workshops"][node]["jph"] if base and node in WORKSHOPS else None,
                             base["factory"]["workshops" if node in WORKSHOPS else "buffers"][node].get("cap_max") if base else None,
                             base["wip_targets"][node] if base else None])
    modes = base["factory"]["modes"] if base else {"OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16}
    default = base["factory"]["default_mode"] if base else "SINGLE_8H"
    for mode, hours in modes.items():
        book["班制"].append([mode, None, hours, "是" if mode == default else "否"])
    if base:
        for cell in book["期初在制"][1]:
            cell.comment = Comment(f"照抄自来源方案 {base_name} 的期初，请按本次计划开始日的最新盘点核对后再上传", "aps-core")
        for model, values in base["factory"]["models"].items():
            book["车型"].append([model, values["line"], values["glue_age_max"]])
        for node, values in {**base["initial"]["wip"], "成品": base["initial"]["fin"]}.items():
            for model, value in values.items():
                book["期初在制"].append([node, model, value])
        for month in range(1, 13):
            for model in base["factory"]["models"]:
                book["销售计划"].append([f"{year}-{month:02d}", model])
    calendar = {r["date"]: r["is_working_capable"] for r in base["calendar"]} if base else {}
    for day in days(date(year, 1, 1), date(year + 1, 1, 14)):
        capable = day.weekday() < 5
        reason = None
        if day.isoformat() in calendar:
            capable = calendar[day.isoformat()]
            if capable != (day.weekday() < 5):
                reason = "沿用来源方案：调休上班" if capable else "沿用来源方案：放假或停产"
        elif day == date(year + 1, 1, 1):
            capable = False
            reason = "元旦（次年日历未发布时的默认）"
        book["生产行事历"].append([day.isoformat(), "是" if capable else "否", reason])
    for name, (key, default_value, meaning) in RULES.items():
        value = base["factory"][key] if base and name == "共享焊装能力" else base["rules"][key] if base else default_value
        book["规则常数"].append([name, value, meaning])
    for sheet, column, formula in (
        ("生产行事历", "B", '"是,否"'), ("班制", "D", '"是,否"'),
        ("车型", "B", '"BS1,BS2"'), ("排产条件", "B", '"' + ",".join(TYPES) + '"'),
        ("期初在制", "A", '"' + ",".join([*NODES, "成品"]) + '"'),
        ("期初在制", "B", 'INDIRECT("\'车型\'!$A$2:$A$1048576")'),
        ("销售计划", "B", 'INDIRECT("\'车型\'!$A$2:$A$1048576")'),
        ("排产条件", "G", '"' + ",".join(NODES) + '"'),
        ("排产条件", "H", 'INDIRECT("\'班制\'!$A$2:$A$1048576")'),
    ):
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        validation.showErrorMessage = True
        validation.error = "请从下拉列表选择"
        book[sheet].add_data_validation(validation)
        validation.add(f"{column}2:{column}1048576")
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def preview(upload):
    errors, warnings = [], []

    def error(sheet, row, column, value, expected):
        errors.append({"sheet": sheet, "row": row, "column": column,
                       "message": f"{sheet} · 第{row}行 · {column} · 填了“{value if value is not None else '空'}” · {expected}"})

    def result(data=None):
        summary = {}
        if data:
            summary = {"models": {m: {"pr": sum(data["demand"]["PR"][m].values()),
                                      "ws": sum(data["demand"]["WS_daily"].get(m, {}).values()),
                                      "initial_wip": sum(v.get(m, 0) for v in data["initial"]["wip"].values())}
                                  for m in data["factory"]["models"]},
                       "working_days": sum(r["is_working_capable"] for r in data["calendar"] if r["date"] <= data["horizon"]["end"]),
                       "fin0": data["initial"]["fin"]}
        return {"ok": not errors, "errors": errors, "summary": summary, "warnings": warnings}

    try:
        book = load_workbook(upload.file, read_only=True, data_only=True)
    except Exception:
        error("工作簿", 1, "文件", upload.filename, "请上传可读取的 .xlsx 文件")
        return result(), None, None
    tables = {}
    try:
        for name in ["填写说明", *HEADERS]:
            if name not in book.sheetnames:
                error(name, 1, "工作表", None, f"请保留名为“{name}”的工作表")
                continue
            if name == "填写说明":
                continue
            values = list(book[name].values)
            headers = list(values[0]) if values else []
            for column in HEADERS[name]:
                if column not in headers:
                    error(name, 1, column, "、".join(str(v) for v in headers), f"请保留表头“{column}”")
            if all(c in headers for c in HEADERS[name]):
                tables[name] = [(i, {c: row[headers.index(c)] for c in HEADERS[name]})
                                for i, row in enumerate(values[1:], 2) if any(v is not None for v in row)]
    finally:
        book.close()
    if errors:
        return result(), None, None

    def number(s, r, c, v, decimal=False):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or (not decimal and v != int(v)):
            error(s, r, c, v, "请填写非负数" if decimal else "请填写非负整数")
            return 0
        return v if decimal else int(v)

    def day(s, r, c, v, start=None, end=None):
        original = v
        if isinstance(v, (date, datetime)):
            v = v.strftime("%Y-%m-%d")
        try:
            if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise ValueError()
            date.fromisoformat(v)
        except ValueError:
            error(s, r, c, original, "请填写有效日期，格式为 YYYY-MM-DD")
            return None
        if start and not start <= v <= end:
            error(s, r, c, original, f"请填写 {start} 至 {end} 内的日期")
            return None
        return v

    def choice(s, r, c, v, options):
        if v not in options:
            error(s, r, c, v, "请填写：" + "、".join(options))
            return False
        return True

    s = "计划信息"
    if len(tables[s]) != 1 or tables[s][0][0] != 2:
        error(s, 2, "方案名称", None, "请只在第2行填写一条计划信息")
        return result(), None, None
    r, info = tables[s][0]
    name = info["方案名称"]
    if name is None or not str(name).strip():
        error(s, r, "方案名称", name, "请填写方案名称")
    start = day(s, r, "计划开始日", info["计划开始日"])
    end = day(s, r, "计划结束日", info["计划结束日"])
    wbs_hi = number(s, r, "WBS 经验上限", info["WBS 经验上限"]) if info["WBS 经验上限"] is not None else None
    if start and end and start > end:
        error(s, r, "计划结束日", end, "结束日不得早于开始日")
    if errors:
        return result(), None, name
    horizon = {"start": start, "end": end}
    months = months_in(horizon)
    workshops, buffers, targets, modes, models, rules = {}, {}, {}, {}, {}, {}
    seen = set()
    s = "节点"
    for r, v in tables[s]:
        node = v["节点编号"]
        if not choice(s, r, "节点编号", node, NODES):
            continue
        if node in seen:
            error(s, r, "节点编号", node, "每个节点只填写一行")
        seen.add(node)
        targets[node] = number(s, r, "目标在制", v["目标在制"])
        if node in WORKSHOPS:
            workshops[node] = {"jph": number(s, r, "JPH", v["JPH"])}
            if v["物理上限"] is not None:
                workshops[node]["cap_max"] = number(s, r, "物理上限", v["物理上限"])
                if workshops[node]["cap_max"] < targets[node]:
                    error(s, r, "物理上限", v["物理上限"], "物理上限不能小于目标在制")
        else:
            buffers[node] = {"cap_max": number(s, r, "物理上限", v["物理上限"])}
            if targets[node] > buffers[node]["cap_max"]:
                error(s, r, "目标在制", v["目标在制"], f"目标在制不能超过物理上限 {buffers[node]['cap_max']}")
            if v["JPH"] is not None:
                error(s, r, "JPH", v["JPH"], "该节点此列应留空")
    for node in NODES.keys() - seen:
        error(s, 2, "节点编号", None, f"请补齐节点 {node}")
    defaults = []
    s = "班制"
    for r, v in tables[s]:
        mode = v["班制编号"]
        if not isinstance(mode, str) or not re.fullmatch(r"[A-Z0-9_]+", mode):
            error(s, r, "班制编号", mode, "请只用大写字母、数字、下划线")
            continue
        if mode in modes:
            error(s, r, "班制编号", mode, "每种班制只填写一行")
        modes[mode] = number(s, r, "小时", v["小时"])
        if mode == "OFF" and modes[mode] != 0:
            error(s, r, "小时", v["小时"], "OFF 的小时必须为 0")
        choice(s, r, "是否默认", v["是否默认"], ["是", "否"])
        if v["是否默认"] == "是":
            defaults.append(mode)
            if mode == "OFF" or len(defaults) > 1:
                error(s, r, "是否默认", v["是否默认"], "有且只有一个非 OFF 班制填“是”")
    if not defaults:
        error(s, 2, "是否默认", None, "有且只有一个非 OFF 班制填“是”")
    if "OFF" not in modes:
        error(s, 2, "班制编号", None, "班制表必须保留 OFF（停）这一行，小时填 0")
    s = "车型"
    for r, v in tables[s]:
        model = v["车型编号"]
        if model is None:
            error(s, r, "车型编号", model, "请填写车型编号")
            continue
        model = str(model)
        if model in models:
            error(s, r, "车型编号", model, "每个车型只填写一行")
        choice(s, r, "焊装线", v["焊装线"], ["BS1", "BS2"])
        bound = [m for m, values in models.items() if values["line"] == v["焊装线"] and m != model]
        if bound:
            error(s, r, "焊装线", v["焊装线"], f"每条焊装线最多绑定一个车型；{v['焊装线']} 已绑定车型 {'、'.join(bound)}，请将两个车型分别绑定 BS1、BS2")
        models[model] = {"line": v["焊装线"], "glue_age_max": number(s, r, "胶龄", v["胶龄"])}
        if len(models) > 2:
            error(s, r, "车型编号", model, "车型最多 2 个，请只保留 1 或 2 个车型")
    if not models:
        error(s, 2, "车型编号", None, "请填写 1 或 2 个车型，每条焊装线最多绑定一个车型")
    initial = {"wip": {}, "fin": {}}
    s = "期初在制"
    seen = set()
    for r, v in tables[s]:
        node, model = v["位置"], str(v["车型"]) if v["车型"] is not None else None
        valid_node = choice(s, r, "位置", node, [*NODES, "成品"])
        valid_model = choice(s, r, "车型", model, models)
        if not valid_node or not valid_model:
            continue
        if (node, model) in seen:
            error(s, r, "车型", model, "同一位置同一车型只填写一行")
        seen.add((node, model))
        if node in ("BS1", "BS2") and models[model]["line"] != node:
            error(s, r, "位置", node, f"车型 {model} 只能放在绑定焊装线 {models[model]['line']}")
        target = initial["fin"] if node == "成品" else initial["wip"].setdefault(node, {})
        target[model] = number(s, r, "数量", v["数量"])
    for r, v in tables[s]:
        node = v["位置"]
        if node in buffers:
            total = sum(initial["wip"].get(node, {}).values())
            cap = buffers[node]["cap_max"]
            if total > cap:
                error(s, r, "数量", v["数量"],
                      f"{node} 期初 {total} 台，超过物理上限 {cap} 台；缓冲区期初不能超过上限，请核对盘点数或上限")
    for model in models:
        initial["fin"].setdefault(model, 0)
    s = "规则常数"
    shared = None
    seen = set()
    for r, v in tables[s]:
        label = v["名称"]
        if not choice(s, r, "名称", label, RULES):
            continue
        if label in seen:
            error(s, r, "名称", label, "每项规则只填写一行")
        seen.add(label)
        key = RULES[label][0]
        value = number(s, r, "数值", v["数值"], label == "月度带比例")
        if label == "共享焊装能力":
            shared = value
        else:
            rules[key] = value
    for label in RULES.keys() - seen:
        error(s, 2, "名称", None, f"请补齐规则 {label}")
    cal = {d.isoformat(): d.weekday() < 5 for d in days(date.fromisoformat(start), date.fromisoformat(end) + timedelta(days=14))}
    s = "生产行事历"
    for r, v in tables[s]:
        d = day(s, r, "日期", v["日期"], start, max(cal))
        valid = choice(s, r, "能否生产", v["能否生产"], ["是", "否"])
        if d and valid:
            cal[d] = v["能否生产"] == "是"
    pr = {m: dict.fromkeys(months, 0) for m in models}
    ws = {m: {} for m in models}
    seen = set()
    s = "销售计划"
    for r, v in tables[s]:
        mo = v["月份"].strftime("%Y-%m") if isinstance(v["月份"], (date, datetime)) else v["月份"]
        model = str(v["车型"]) if v["车型"] is not None else None
        valid_month = choice(s, r, "月份", mo, months)
        valid_model = choice(s, r, "车型", model, models)
        if not valid_month or not valid_model:
            continue
        if (mo, model) in seen:
            error(s, r, "车型", model, "同月同车型只填写一行")
        seen.add((mo, model))
        pr[model][mo] = number(s, r, "PR", v["PR"])
        amount = number(s, r, "WS", v["WS"])
        month_days = [d for d in cal if start <= d <= end and d[:7] == mo]
        delivery = day(s, r, "交付日", v["交付日"], month_days[0], month_days[-1]) if v["交付日"] is not None else ([d for d in month_days if cal[d]] or month_days)[-1]
        if delivery and amount:
            ws[model][delivery] = amount
    for mo in months:
        for model in models:
            if (mo, model) not in seen:
                error(s, max((r for r, _ in tables[s]), default=1) + 1, "月份", None,
                      f"请补齐月份 {mo}、车型 {model} 的一行销售计划；没有需求时 PR、WS 填 0")
    conditions, condition_rows = [], []
    seen = set()
    s = "排产条件"
    for index, (r, v) in enumerate(tables[s], 1):
        before = len(errors)
        label = v["条件类型"]
        if not choice(s, r, "条件类型", label, TYPES):
            continue
        kind = TYPES[label]
        cid = str(v["条件编号"]) if v["条件编号"] is not None else f"C-{index:03d}"
        if cid in seen:
            error(s, r, "条件编号", cid, "请填写不重复的条件编号")
        seen.add(cid)
        c = {"id": cid, "type": kind}
        if v["备注"] is not None:
            c["reason"] = str(v["备注"])
        if v["单日日期"] is not None and (v["开始日期"] is not None or v["结束日期"] is not None):
            error(s, r, "单日日期", v["单日日期"], "单日日期和开始/结束日期只填一种")
        if kind == "PRE_STOP_TARGET":
            c["pre_stop_date"] = day(s, r, "停前日", v["停前日"], start, end)
        elif kind == "FIXED_OUTPUT":
            c["date"] = day(s, r, "单日日期", v["单日日期"], start, end)
        elif v["单日日期"] is not None:
            c["start"] = c["end"] = day(s, r, "单日日期", v["单日日期"], start, end)
        else:
            c["start"] = day(s, r, "开始日期", v["开始日期"], start, end)
            c["end"] = day(s, r, "结束日期", v["结束日期"], start, end)
            if c["start"] and c["end"] and c["start"] > c["end"]:
                error(s, r, "结束日期", v["结束日期"], "结束日期不得早于开始日期")
        if kind in ("SATURDAY_AUTH", "MODE_AUTH", "SHUTDOWN", "CAPACITY_LOSS", "FIXED_OUTPUT"):
            if v["车间"] is not None:
                selected = str(v["车间"]).split(",")
                for w in selected:
                    choice(s, r, "车间", w, WORKSHOPS)
                if kind == "FIXED_OUTPUT":
                    if len(selected) != 1:
                        error(s, r, "车间", v["车间"], "指定产量只填写一个车间")
                    c["workshop"] = selected[0]
                else:
                    c["workshops"] = selected
            elif kind not in ("SATURDAY_AUTH", "SHUTDOWN"):
                error(s, r, "车间", None, "请填写车间编号")
        if kind == "MODE_AUTH":
            choice(s, r, "班制", v["班制"], [m for m in modes if m != "OFF" and m not in defaults])
            c["mode"] = v["班制"]
        if kind == "WIP_TARGET":
            choice(s, r, "节点", v["节点"], NODES)
            c["node"] = v["节点"]
        if kind in ("CAPACITY_LOSS", "WIP_TARGET", "PRE_STOP_TARGET", "FIXED_OUTPUT"):
            field = "hours_max" if kind == "CAPACITY_LOSS" else "out" if kind == "FIXED_OUTPUT" else "target"
            c[field] = number(s, r, "数值", v["数值"])
        if kind == "WIP_TARGET" and len(errors) == before:
            cap = {**workshops, **buffers}.get(c["node"], {}).get("cap_max")
            if cap is not None and c["target"] > cap:
                error(s, r, "数值", c["target"], f"节点 {c['node']} 的人工目标在制不能超过上限 {cap}")
        if len(errors) == before:
            conditions.append(c)
            condition_rows.append(r)
    targets_by_day, outputs_by_day, shutdowns = {}, {}, set()
    for c in conditions:
        if c["type"] == "SHUTDOWN":
            for d in days(date.fromisoformat(c["start"]), date.fromisoformat(c["end"])):
                shutdowns.update((w, d.isoformat()) for w in c.get("workshops", WORKSHOPS))
    for r, c in zip(condition_rows, conditions):
        if c["type"] == "WIP_TARGET":
            for stop in conditions:
                if (stop["type"] == "SHUTDOWN"
                        and set(stop.get("workshops", WORKSHOPS)) == set(WORKSHOPS)
                        and c["start"] <= stop["end"] and stop["start"] <= c["end"]
                        and not (c["start"] <= stop["start"] and c["end"] >= stop["end"])):
                    error(s, r, "开始日期/结束日期", f"{c['start']}..{c['end']}",
                          f"人工目标在制与全线计划停线 {stop['id']}（{stop['start']}..{stop['end']}）重叠，"
                          "开始日期须不晚于停线开始、结束日期须不早于停线结束，盖住整段停线")
            for d in days(date.fromisoformat(c["start"]), date.fromisoformat(c["end"])):
                key = c["node"], d.isoformat()
                if key in targets_by_day and targets_by_day[key] != c["target"]:
                    error(s, r, "数值", c["target"], f"同一节点 {key[0]} 在 {key[1]} 的目标在制必须一致")
                    break
                targets_by_day[key] = c["target"]
        elif c["type"] == "FIXED_OUTPUT":
            key = c["workshop"], c["date"]
            if key in outputs_by_day and outputs_by_day[key] != c["out"]:
                error(s, r, "数值", c["out"], "同一车间同一天的指定产量必须一致")
            outputs_by_day[key] = c["out"]
            if key in shutdowns and c["out"] > 0:
                error(s, r, "数值", c["out"], "该车间在指定日期计划停线，产量须为 0")
    data = {"schema": "aps-core/input/v1", "horizon": horizon,
            "factory": {"workshops": workshops, "buffers": buffers, "modes": modes,
                        "default_mode": defaults[0] if defaults else None, "models": models,
                        "flow": FLOW, "shared_welding_jph_max": shared},
            "wip_targets": targets, "wbs_hi": wbs_hi, "rules": rules, "initial": initial,
            "demand": {"PR": pr, "WS_daily": {m: values for m, values in ws.items() if values}}, "conditions": conditions,
            "calendar": [{"date": d, "is_working_capable": flag} for d, flag in cal.items()]}
    return result(data), data, str(name)
