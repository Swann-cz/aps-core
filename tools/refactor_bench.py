"""生成器验收台（Claude 维护；原 REFACTOR-ENGINE 验收台）：一次跑完第 5 节的全部检查，并与基线比较。

用法：
  python -B -X utf8 tools/refactor_bench.py --out tasks/logs/<目录> [--baseline tasks/logs/<基线目录>]
         [--identical] [--only selftest,cases,server,data] [--sets 名称,名称]

输出 <out>/summary.json、<out>/summary.txt，以及每份数据集的计划、判定和日志。
--identical：除 plan['solver'] 外，计划文件必须与基线逐字节相同（纯重构步骤用）。
退出码：0 全部通过；1 有不通过项。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [
    "t38-retrofit/retrofit",
    "1d-annual-feedback/feedback-pass", "1d-annual-feedback/feedback-gap",
    "1d-annual-feedback/feedback-gap-sat", "1d-annual-feedback/feedback-pass-caps",
    "1d-annual-feedback/feedback-gap-caps",
    "t30-trial/trial-2models",
    "t32-half-year-switch/switch-1", "t32-half-year-switch/switch-2",
    "t36-high-jph/fb-0949", "t36-high-jph/fb-0949-cap69-75",
    "t39-holiday/holiday", "t39-holiday/holiday-wip", "t39-holiday/wip",
    # 附加慢输入（DeepSeek 2026-11-03 指出：生成阶段最慢的几份不在原 14 份里）
    "1d-annual-feedback/feedback-gap-applied", "1d-annual-feedback/feedback-gap-pool",
    "1d-annual-feedback/feedback-gap-satpool", "1d-annual-feedback/feedback-gap-step2",
]
LEVELS = ("L1a", "L1b", "L1c", "L2", "L3a", "L3b", "L4", "L5", "L6")
SECONDS_LIMIT = 60.0


def run(cmd, log, env=None):
    tick = perf_counter()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, **(env or {})})
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    return p.returncode, perf_counter() - tick, (p.stdout + p.stderr).strip().splitlines()


def structure(plan):
    """计划的结构摘要：换型/首次启动/清线的起始日、停前日。"""
    starts = {}
    previous = set()
    for day in plan.get("days", []):
        phases = set(day["phase"].split("+"))
        for p in ("CHANGEOVER", "FIRST_START", "BS_CLEAR"):
            if p in phases and p not in previous:
                starts.setdefault(p, []).append(day["date"])
        previous = phases
    return {"changeover": starts.get("CHANGEOVER", []), "first_start": starts.get("FIRST_START", []),
            "bs_clear": starts.get("BS_CLEAR", []),
            "pre_stop": [s["pre_stop_date"] for s in plan.get("stop_list", [])]}


def stages(lines):
    """从生成器日志取分阶段用时与尝试次数（候选生成、挪移、库存细调）。"""
    found = {}
    for line in lines:
        if line.startswith("segment_search_stats="):
            stats = json.loads(line.split("=", 1)[1])
            found.update(attempts=stats.get("attempts"),
                         generation_seconds=round(stats.get("generation_seconds", 0), 1))
        elif line.startswith("segment_shift_seconds="):
            found["shift_seconds"] = round(float(line.split("=", 1)[1].split(";")[0]), 1)
        elif line.startswith("segment_refine_seconds="):
            found["refine_seconds"] = round(float(line.split("=", 1)[1].split(";")[0]), 1)
    return found


def bench_data(out, names):
    rows = {}
    for path in DATASETS:
        name = path.rsplit("/", 1)[1]
        if names and name not in names:
            continue
        source = ROOT / "cases" / f"{path}.input.json"
        plan_path, verdict_path = out / f"{name}.plan.json", out / f"{name}.verdict.json"
        rc, seconds, lines = run([sys.executable, "-B", "-X", "utf8", "-m", "engine", str(source),
                                  str(plan_path), "--solver", "segment"], out / f"{name}.engine.log")
        row = {"engine_rc": rc, "seconds": round(seconds, 1), "stages": stages(lines)}
        if rc == 0:
            jrc, _, _ = run([sys.executable, "-B", "-X", "utf8", "-m", "judge", str(source),
                             str(plan_path), str(verdict_path)], out / f"{name}.judge.log")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if jrc == 0 else {}
            row.update(status=plan["status"], verdict=verdict.get("verdict"),
                       levels=[verdict.get("objective", {}).get(k) for k in LEVELS],
                       structure=structure(plan))
        rows[name] = row
        print(f"data {name}: {row.get('verdict')} {row['seconds']}s {row.get('levels')}", flush=True)
    return rows


def bench_cases(out):
    rows = {}
    for case in sorted(p for p in (ROOT / "cases").iterdir() if (p / "expected.json").is_file()):
        rows[case.name] = {}
        for solver in ("legacy", "segment"):
            rc, seconds, _ = run([sys.executable, "-B", "-X", "utf8", "tools/run_case.py", str(case)],
                                 out / f"case-{case.name}.{solver}.log", env={"APS_SOLVER": solver})
            rows[case.name][solver] = {"rc": rc, "seconds": round(seconds, 1)}
        print(f"case {case.name}: {rows[case.name]}", flush=True)
    return rows


def check(summary, baseline, identical, out, base_dir):
    problems = []
    if "selftest" in summary and summary["selftest"]["rc"] != 0:
        problems.append(f"judge.selftest rc={summary['selftest']['rc']}")
    for name, solvers in summary.get("cases", {}).items():
        for solver, row in solvers.items():
            if row["rc"] != 0:
                problems.append(f"算例 {name} {solver} rc={row['rc']}")
    for name, row in summary.get("server", {}).items():
        if row["rc"] != 0:
            problems.append(f"{name} rc={row['rc']}")
    for name, row in summary.get("data", {}).items():
        if row.get("verdict") != "ACCEPT":
            problems.append(f"数据集 {name}: engine_rc={row['engine_rc']} verdict={row.get('verdict')}")
            continue
        old = (baseline or {}).get("data", {}).get(name)
        # 基线（223610c）已有两份单独运行也超过 60 秒；上限取 60 秒与基线 1.1 倍的较大者。
        limit = max(SECONDS_LIMIT, round(old["seconds"] * 1.1, 1)) if old else SECONDS_LIMIT
        if row["seconds"] > limit:
            problems.append(f"数据集 {name}: 用时 {row['seconds']} 秒 > {limit}")
        if old and old.get("levels") and row["levels"] > old["levels"]:
            problems.append(f"数据集 {name}: 目标变差 {old['levels']} → {row['levels']}")
        if identical and old:
            mine = json.loads((out / f"{name}.plan.json").read_text(encoding="utf-8"))
            theirs = json.loads((base_dir / f"{name}.plan.json").read_text(encoding="utf-8"))
            mine.pop("solver", None)
            theirs.pop("solver", None)
            if mine != theirs:
                problems.append(f"数据集 {name}: 计划与基线不同（--identical）")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--identical", action="store_true")
    parser.add_argument("--only", default="selftest,cases,server,data")
    parser.add_argument("--sets", default="")
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(","))
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    summary = {"commit": head}
    if "selftest" in only:
        rc, _, lines = run([sys.executable, "-B", "-X", "utf8", "-m", "judge.selftest"], out / "selftest.log")
        summary["selftest"] = {"rc": rc, "last": lines[-1] if lines else ""}
        print(f"selftest rc={rc} {summary['selftest']['last']}", flush=True)
    if "cases" in only:
        summary["cases"] = bench_cases(out)
    if "server" in only:
        summary["server"] = {}
        for name in ("selfcheck_t34", "selfcheck_t38"):
            rc, _, lines = run([sys.executable, "-B", "-X", "utf8", "-m", f"server.{name}"], out / f"{name}.log")
            summary["server"][name] = {"rc": rc, "last": lines[-1] if lines else ""}
            print(f"{name} rc={rc}", flush=True)
    if "data" in only:
        summary["data"] = bench_data(out, set(filter(None, args.sets.split(","))))
    base_dir = None
    baseline = None
    if args.baseline:
        base_dir = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
        baseline = json.loads((base_dir / "summary.json").read_text(encoding="utf-8"))
    problems = check(summary, baseline, args.identical, out, base_dir)
    summary["problems"] = problems
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"commit {head}"]
    if "selftest" in summary:
        lines.append(f"judge.selftest rc={summary['selftest']['rc']} {summary['selftest']['last']}")
    for name, solvers in summary.get("cases", {}).items():
        lines.append(f"case {name:32s} " + " ".join(f"{s}={r['rc']}" for s, r in solvers.items()))
    for name, row in summary.get("server", {}).items():
        lines.append(f"{name} rc={row['rc']}")
    for name, row in summary.get("data", {}).items():
        levels = "/".join(str(v) for v in row.get("levels") or [])
        st = row.get("stages", {})
        lines.append(f"data {name:22s} {row.get('verdict')} {row['seconds']:6.1f}s {levels}"
                     f"  生成 {st.get('generation_seconds')}s/{st.get('attempts')} 次 挪移 {st.get('shift_seconds')}s 细调 {st.get('refine_seconds')}s")
    lines.append("通过" if not problems else "不通过：\n  " + "\n  ".join(problems))
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
