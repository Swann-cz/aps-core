"""T-26 B：隔离方案副本，真实判定器检查热启动与安全网。"""

import argparse
import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from .selfcheck import request

backend = importlib.import_module("server.app")
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases" / "1d-annual-feedback"
LEVELS = ("L1a", "L1b", "L1c", "L2", "L3a", "L3b", "L4", "L5", "L6")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("S1", "S2"))
    args = parser.parse_args()
    required = [CASE / "feedback-gap-step2.input.json",
                CASE / "_out" / "T-25-final-gap-pool-1.plan.json"]
    if args.only != "S1":
        required.append(CASE / "_out" / "T-25-final-gap-1.plan.json")
    if not all(p.exists() for p in required):
        print("跳过（无真实数据）")
        return
    source = backend.SCENARIOS / "demo-suggest"
    before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    with tempfile.TemporaryDirectory(prefix="t26-", dir=ROOT / "server") as temp:
        scenarios = Path(temp)
        with patch.object(backend, "SCENARIOS", scenarios), TestClient(backend.app) as client:
            for check in ((args.only,) if args.only else ("S1", "S2")):
                path = scenarios / check
                shutil.copytree(source, path)
                shutil.copyfile(CASE / "feedback-gap-step2.input.json", path / "input.json")
                shutil.copyfile(CASE / "_out" / "T-25-final-gap-pool-1.plan.json", path / "plan.json")
                meta = backend.read(path / "meta.json")
                meta.update(id=check, input_rev=meta["input_rev"] + 1)
                meta["run"]["state"] = "IDLE"
                backend.write(path / "meta.json", meta)
                previous = (path / "plan.json").read_bytes()
                commands = []
                real_run = subprocess.run

                def invoke(command, **kwargs):
                    commands.append(command)
                    if check == "S2" and command[1:3] == ["-m", "engine"]:
                        # 假生成器输出已知更差的计划，判定器仍使用真实 CLI。
                        shutil.copyfile(CASE / "_out" / "T-25-final-gap-1.plan.json", command[4])
                        return subprocess.CompletedProcess(command, 0)
                    return real_run(command, **kwargs)

                with patch.object(backend.subprocess, "run", side_effect=invoke):
                    request(client, "POST", f"/api/scenarios/{check}/run")
                    backend.active_thread.join()
                result = request(client, "GET", f"/api/scenarios/{check}/conditions")["scenario"]
                print(f"{check} engine command: {subprocess.list2cmdline(commands[0])}", flush=True)
                print(f"{check} state={result['state']}, verdict={result['verdict']}, objective={result['objective']}, run={result['run']}", flush=True)
                assert result["state"] == "READY" and result["verdict"] == "ACCEPT", result
                assert commands[0][-2:] == ["--warm-start", str(path / "plan.json")]
                assert result["run"]["warm_start"] is True
                assert result["objective"]["L1a"] == 0
                assert backend.read(path / "meta.json")["plan_input_rev"] == meta["input_rev"]
                old = backend.read(path / "verdict.prev.json")
                assert old["verdict"] == "ACCEPT"
                assert tuple(result["objective"][k] for k in LEVELS) <= tuple(old["objective"][k] for k in LEVELS)
                if check == "S2":
                    new = backend.read(path / "verdict.next.json")
                    print(f"S2 fake result: verdict={new['verdict']}, objective={new['objective']}", flush=True)
                    assert new["verdict"] == "ACCEPT"
                    assert tuple(old["objective"][k] for k in LEVELS) < tuple(new["objective"][k] for k in LEVELS)
                    assert result["run"]["kept_previous"] is True
                    assert (path / "plan.json").read_bytes() == previous
                    assert backend.read(path / "verdict.json") == old
                    print("PASS S2 kept_previous=true, plan bytes unchanged, verdict refreshed, plan_input_rev=current", flush=True)
                else:
                    print("PASS S1 --warm-start present, warm_start=true, L1a=0, objective <= previous, plan_input_rev=current", flush=True)
    assert all((source / name).read_bytes() == content for name, content in before.items())
    print("PASS T26 isolated copies removed; demo-suggest files unchanged", flush=True)


if __name__ == "__main__":
    main()
