"""建界面用的初始方案（Claude 维护）。格式见 spec/UI_CONTRACT.md §3。

python tools/seed_workspace.py
用 cases/1d-annual-feedback 的三组输入建 pass、gap、gap-sat 三个方案；
当前终版计划（_out/T-19-<组>-1.plan.json 与 T-19-<组>.verdict.json，rev 188）存在时一并放入。
已存在的方案目录整个覆盖。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cases" / "1d-annual-feedback"
DST = ROOT / "workspace" / "scenarios"
GROUPS = [
    ("pass", "pass 组（10–12 月周六上班）", "2026-10-25T09:00:00"),
    ("gap", "gap 组（无周六授权）", "2026-10-25T09:01:00"),
    ("gap-sat", "gap 组 + 三个全线周六", "2026-10-25T09:02:00"),
]


def main() -> None:
    for gid, name, created in GROUPS:
        d = DST / gid
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copyfile(SRC / f"feedback-{gid}.input.json", d / "input.json")
        plan = SRC / "_out" / f"T-19-{gid}-1.plan.json"
        verdict = SRC / "_out" / f"T-19-{gid}.verdict.json"
        has_plan = plan.exists() and verdict.exists()
        if has_plan:
            shutil.copyfile(plan, d / "plan.json")
            shutil.copyfile(verdict, d / "verdict.json")
        meta = {"id": gid, "name": name, "created_at": created, "input_rev": 1,
                "plan_input_rev": 1 if has_plan else None,
                "run": {"state": "IDLE", "started_at": None, "finished_at": None,
                        "seconds": None, "error": None}}
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{gid}: {'含计划' if has_plan else '仅输入'}")


if __name__ == "__main__":
    main()
