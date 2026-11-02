"""把一份计划整理成人能读的逐月汇总（Claude 维护，只读，不参与判定）。

python tools/plan_summary.py <input.json> <plan.json> [verdict.json]
输出 Markdown 到标准输出：逐月交付与缺口、焊装开线天数、月末在制、停线与换型清单、结论说明。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

NODES = ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
CN = {"BS1": "焊装1", "BS2": "焊装2", "WBS": "焊装缓存", "PS": "涂装", "PBS": "涂装缓存",
      "AS_MAIN": "总装主线", "AS_FIN": "完成线"}


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    inp, plan = load(sys.argv[1]), load(sys.argv[2])
    verdict = load(sys.argv[3]) if len(sys.argv) > 3 else None
    models = sorted(inp["demand"]["PR"])
    lines = {m: inp["factory"]["models"][m]["line"] for m in models}
    pr = inp["demand"]["PR"]
    ratio = inp["rules"]["monthly_band_ratio"]
    targets = inp["wip_targets"]
    cal = {c["date"]: c["is_working_capable"] for c in inp["calendar"]}

    fok = defaultdict(lambda: defaultdict(int))
    weld_days = defaultdict(lambda: defaultdict(int))
    sat_days = defaultdict(int)
    month_end = {}
    peaks = {n: (0, "") for n in NODES}
    phases_seen = defaultdict(set)
    for row in plan["days"]:
        mo = row["date"][:7]
        for m, q in row["fok"].items():
            fok[mo][m] += q
        for w, v in row["workshops"].items():
            if w in ("BS1", "BS2") and (sum(v["in"].values()) or sum(v["out"].values())):
                weld_days[mo][w] += 1
            if v["mode"] != "OFF" and not cal.get(row["date"], True):
                sat_days[mo] += 1
        totals = {n: sum(row["eod"].get(n, {}).values()) for n in NODES}
        month_end[mo] = totals
        for n in NODES:
            if totals[n] > peaks[n][0]:
                peaks[n] = (totals[n], row["date"])
        phases_seen[mo].update(p for p in row.get("phase", "NORMAL").split("+") if p != "NORMAL")

    months = sorted(month_end)
    print(f"# 计划汇总：{sys.argv[2]}\n")
    print(f"- 结论：{plan['status']}" + (f"；判定：{verdict['verdict']}，硬错误 {len(verdict['hard_errors'])} 条" if verdict else ""))
    levels = {lv["level"]: lv["value"] for lv in plan["objective"]["levels"]}
    names = {"L1a": "年度欠产", "L1b": "交付欠交台·天", "L1c": "月度带下限缺口", "L2": "换型与清线次数",
             "L3a": "周六使用（车间·日）", "L3b": "加班模式使用（车间·日）", "L4": "WBS 越带天数", "L5": "高于目标的在制（台·天）"}
    print("- 目标：" + "；".join(f"{names[k]} {v}" for k, v in levels.items() if k in names) + "\n")

    print("## 逐月交付\n")
    head = "| 月份 | " + " | ".join(f"{m} 需求 | {m} 完工 | {m} 累计缺口 | {m} 低于月度带" for m in models) + " | 焊装开线天数 | 周六车间·日 | 特殊阶段 |"
    print(head)
    print("|" + " --- |" * (head.count("|") - 1))
    cum_pr, cum_fok = defaultdict(int), defaultdict(int)
    for mo in months:
        cells = []
        for m in models:
            p = pr[m].get(mo, 0)
            cum_pr[m] += p
            cum_fok[m] += fok[mo][m]
            gap = max(0, cum_pr[m] - cum_fok[m])
            band = max(0.0, cum_pr[m] - ratio * p - cum_fok[m])
            cells += [str(p), str(fok[mo][m]), str(gap) if gap else "—", f"{band:g}" if band else "—"]
        weld = "、".join(f"{w} {d}" for w, d in sorted(weld_days[mo].items())) or "—"
        ph = "、".join(sorted(phases_seen[mo])) or "—"
        print(f"| {mo} | " + " | ".join(cells) + f" | {weld} | {sat_days[mo] or '—'} | {ph} |")

    print("\n## 月末在制（台，括号内为目标）\n")
    print("| 月份 | " + " | ".join(f"{CN[n]}({targets[n]})" for n in NODES) + " |")
    print("|" + " --- |" * (len(NODES) + 1))
    for mo in months:
        print(f"| {mo} | " + " | ".join(str(month_end[mo][n]) for n in NODES) + " |")
    print("\n全年日末峰值：" + "；".join(f"{CN[n]} {peaks[n][0]}（{peaks[n][1]}）" for n in NODES))

    print("\n## 停线清单\n")
    if plan["stop_list"]:
        print("| 起 | 止 | 天数 | 停前日 | 停前 PS 目标 | 来源 |\n| --- | --- | --- | --- | --- | --- |")
        for s in plan["stop_list"]:
            print(f"| {s['start']} | {s['end']} | {s['length']} | {s['pre_stop_date'] or '—'} | {s['target'] if s['target'] is not None else '—'} | {s['source']} |")
    else:
        print("无")

    print("\n## 换型与焊装切换\n")
    prev = None
    for row in plan["days"]:
        active = [w for w in ("BS1", "BS2") if sum(row["workshops"][w]["in"].values())]
        if active and active[0] != prev:
            model = next(m for m in models if lines[m] == active[0])
            print(f"- {row['date']}：{active[0]} 开始投入（车型 {model}）")
            prev = active[0]

    print("\n## 结论说明（生成器 findings）\n")
    for f in plan.get("findings", []):
        print(f"- {f}")


if __name__ == "__main__":
    main()
