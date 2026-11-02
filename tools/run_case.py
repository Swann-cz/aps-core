"""跑一个算例：生成 → 判定 → 与 expected.json 比对（Claude 维护）。

用法：python tools/run_case.py cases/<case-dir> [--keep]
输出写在 <case-dir>/_out/（不入库）。
退出码：0 全部一致；1 有不一致；2 生成器或判定器尚未实现 / 异常。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSHOPS = ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"]


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def package_ready(name: str) -> bool:
    return (ROOT / name / "__main__.py").is_file()


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout + p.stderr).strip()


def nz(d: dict | None) -> dict:
    """去掉值为 0 的车型键，便于比较（0 可省略）。"""
    return {k: v for k, v in (d or {}).items() if v}


def norm_nodes(d: dict | None) -> dict:
    return {n: nz(v) for n, v in (d or {}).items() if nz(v)}


def day_signature(day: dict, aggregate: bool = False) -> tuple:
    """一天的可比内容：各车间模式与 IN/OUT、各节点 EOD、FOK。用于判断是否选中反例。
    aggregate=True 时按车型合计比较（车型拆分不唯一的算例）。"""
    f = (lambda v: sum(nz(v).values())) if aggregate else (lambda v: repr(sorted(nz(v).items())))
    ws = {w: (v.get("mode"), f(v.get("in")), f(v.get("out")))
          for w, v in (day.get("workshops") or {}).items()}
    eod = {n: f(v) for n, v in (day.get("eod") or {}).items() if nz(v)}
    return (repr(sorted(ws.items())), repr(sorted(eod.items())), f(day.get("fok")))


def objective_of_plan(plan: dict) -> dict:
    return {lv["level"]: lv["value"] for lv in plan.get("objective", {}).get("levels", [])}


class Report:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []

    def check(self, ok: bool, msg: str) -> None:
        if not ok:
            self.fails.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)


def compare_days(rep: Report, exp_days: list[dict], plan: dict) -> None:
    got = {d["date"]: d for d in plan.get("days", [])}
    rep.check(len(got) == len(exp_days), f"计划天数 {len(got)} ≠ 预期 {len(exp_days)}")
    for e in exp_days:
        g = got.get(e["date"])
        if g is None:
            rep.check(False, f"{e['date']} 缺少当日计划")
            continue
        for w in WORKSHOPS:
            ew, gw = e["workshops"][w], g.get("workshops", {}).get(w, {})
            for key in ("in", "out"):
                rep.check(nz(ew[key]) == nz(gw.get(key)),
                          f"{e['date']} {w} {key.upper()} 预期 {nz(ew[key])} 实得 {nz(gw.get(key))}")
            rep.check(ew["mode"] == gw.get("mode"),
                      f"{e['date']} {w} 模式 预期 {ew['mode']} 实得 {gw.get('mode')}")
        rep.check(norm_nodes(e["eod"]) == norm_nodes(g.get("eod")),
                  f"{e['date']} EOD 预期 {norm_nodes(e['eod'])} 实得 {norm_nodes(g.get('eod'))}")
        for key in ("fok", "fin", "bl"):
            rep.check(nz(e.get(key)) == nz(g.get(key)),
                      f"{e['date']} {key} 预期 {nz(e[key])} 实得 {nz(g.get(key))}")


def total(v) -> int:
    return sum((v or {}).values()) if isinstance(v, dict) else (v or 0)


def compare_days_aggregate(rep: Report, exp_days: list, plan: dict) -> None:
    """共享车间车型拆分不唯一时，按车间/节点合计比对（expected.engine.compare = "aggregate"）。"""
    got = {d["date"]: d for d in plan.get("days", [])}
    rep.check(len(got) == len(exp_days), f"计划天数 {len(got)} ≠ 预期 {len(exp_days)}")
    for e in exp_days:
        g = got.get(e["date"])
        if g is None:
            rep.check(False, f"{e['date']} 缺少当日计划")
            continue
        for w, ew in e["workshops"].items():
            gw = g.get("workshops", {}).get(w, {})
            for key in ("in", "out"):
                rep.check(ew[key] == total(gw.get(key)),
                          f"{e['date']} {w} {key.upper()} 合计 预期 {ew[key]} 实得 {total(gw.get(key))}")
            rep.check(ew["mode"] == gw.get("mode"),
                      f"{e['date']} {w} 模式 预期 {ew['mode']} 实得 {gw.get('mode')}")
        geod = {n: total(v) for n, v in (g.get("eod") or {}).items() if total(v)}
        rep.check(e["eod"] == geod, f"{e['date']} EOD 合计 预期 {e['eod']} 实得 {geod}")
        for key in ("fok", "fin", "bl"):
            rep.check(e[key] == total(g.get(key)),
                      f"{e['date']} {key} 合计 预期 {e[key]} 实得 {total(g.get(key))}")


def compare_verdict(rep: Report, label: str, exp: dict, verdict: dict) -> None:
    rep.check(verdict.get("verdict") == exp["verdict"],
              f"{label}: 判定 预期 {exp['verdict']} 实得 {verdict.get('verdict')}"
              f"；硬错误 {verdict.get('hard_errors', [])[:5]}")
    if "rules" in exp:
        got_rules = sorted({e.get("rule") for e in verdict.get("hard_errors", [])})
        rep.check(got_rules == sorted(exp["rules"]),
                  f"{label}: 违规条款 预期 {sorted(exp['rules'])} 实得 {got_rules}")
    for lv, val in exp.get("objective", {}).items():
        got = verdict.get("objective", {}).get(lv)
        rep.check(got == val, f"{label}: 判定器重算 {lv} 预期 {val} 实得 {got}")
    for date, ph in exp.get("phases", {}).items():
        got = verdict.get("phases", {}).get(date)
        rep.check(got == ph, f"{label}: {date} 阶段 预期 {ph} 实得 {got}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("case_dir")
    args = ap.parse_args()
    case = (ROOT / args.case_dir).resolve() if not Path(args.case_dir).is_absolute() else Path(args.case_dir)
    inp, expected = case / "input.json", load(case / "expected.json")
    out = case / "_out"
    out.mkdir(exist_ok=True)
    rep = Report()
    print(f"== 算例 {expected['case']}（{expected.get('spec', '')}）")

    missing = [n for n in ("engine", "judge") if not package_ready(n)]
    for n in missing:
        print(f"[NOT_IMPLEMENTED] {n}/__main__.py 不存在，跳过 {n} 相关比对")

    plan_path = out / "plan.json"
    plan = None
    if "engine" not in missing:
        code, log = run([sys.executable, "-m", "engine", str(inp), str(plan_path)])
        if code != 0 or not plan_path.is_file():
            print(f"[ENGINE_ERROR] 退出码 {code}\n{log}")
            return 2
        plan = load(plan_path)
        e = expected["engine"]
        rep.check(plan.get("status") == e["status"], f"生成器结论 预期 {e['status']} 实得 {plan.get('status')}")
        if e.get("compare") == "aggregate":
            compare_days_aggregate(rep, e["days"], plan)
        elif e.get("compare") == "none":
            pass  # 逐日流量不唯一：只比结论、目标、停线清单，合法性和阶段交给判定器
        else:
            compare_days(rep, e["days"], plan)
        for key, per_model in e.get("model_totals", {}).items():
            for m, val in per_model.items():
                got = sum((d.get(key) or {}).get(m, 0) for d in plan.get("days", []))
                rep.check(got == val, f"车型 {m} 全期 {key} 预期 {val} 实得 {got}")
        rep.check(plan.get("stop_list", []) == e["stop_list"], f"停线清单 预期 {e['stop_list']} 实得 {plan.get('stop_list')}")
        gobj = objective_of_plan(plan)
        for lv, val in e["objective"].items():
            rep.check(gobj.get(lv) == val, f"生成器自报 {lv} 预期 {val} 实得 {gobj.get(lv)}")
        for d in plan.get("days", []):
            ph = expected.get("judge_on_engine", {}).get("phases", {}).get(d["date"])
            if ph and d.get("phase") != ph:
                rep.warn(f"生成器自报阶段 {d['date']} = {d.get('phase')}（预期 {ph}；B21：只作对照）")

    if "judge" not in missing:
        targets = []
        if plan is not None:
            targets.append(("判定生成器计划", plan_path, expected["judge_on_engine"]))
        for cp in expected.get("counter_plans", []):
            targets.append((f"判定反例 {cp['file']}", case / cp["file"], cp["judge"]))
        for label, ppath, exp in targets:
            vpath = out / (ppath.stem + ".verdict.json")
            code, log = run([sys.executable, "-m", "judge", str(inp), str(ppath), str(vpath)])
            if code != 0 or not vpath.is_file():
                print(f"[JUDGE_ERROR] {label} 退出码 {code}\n{log}")
                return 2
            compare_verdict(rep, label, exp, load(vpath))

    if plan is not None:
        for cp in expected.get("counter_plans", []):
            if cp.get("engine_must_differ"):
                cday = {d["date"]: d for d in load(case / cp["file"])["days"]}
                agg = expected["engine"].get("compare") == "aggregate"
                same = all(day_signature(d, agg) == day_signature(cday.get(d["date"], {}), agg)
                           for d in plan.get("days", []))
                rep.check(not same, f"生成器选中了反例 {cp['file']}")

    for w in rep.warns:
        print(f"[WARN] {w}")
    for f in rep.fails:
        print(f"[FAIL] {f}")
    if missing:
        print(f"[RESULT] INCOMPLETE：未实现 {', '.join(missing)}；已比对部分不一致 {len(rep.fails)} 项")
        return 2
    print(f"[RESULT] {'PASS' if not rep.fails else 'FAIL'}：不一致 {len(rep.fails)} 项")
    return 0 if not rep.fails else 1


if __name__ == "__main__":
    sys.exit(main())
