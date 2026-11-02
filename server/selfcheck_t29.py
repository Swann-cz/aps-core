"""T-29 S1：临时目录检查上传原件、运行归档及页面托管。"""

from datetime import datetime
from io import BytesIO
import importlib
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from . import full_import, imports
from .selfcheck import request
from .selfcheck_t20 import save

backend = importlib.import_module("server.app")
ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"state", "started_at", "finished_at", "seconds", "error", "warm_start", "kept_previous"}
LEVELS = ("L1a", "L1b", "L1c", "L2", "L3a", "L3b", "L4", "L5", "L6")


def records(path):
    result = sorted((path / "runs").iterdir())
    for item in result:
        run = backend.read(item / "run.json")
        assert set(run) == FIELDS, run
        assert run["state"] in ("IDLE", "FAILED")
        assert datetime.fromisoformat(run["finished_at"]) >= datetime.fromisoformat(run["started_at"])
        assert run["seconds"] >= 0
        assert isinstance(run["warm_start"], bool) and isinstance(run["kept_previous"], bool)
    return result


def main():
    if not (ROOT / "cases/1d-annual-feedback/feedback-pass-caps.input.json").exists():
        print("跳过（无真实数据）")
        return
    base = backend.read(ROOT / "cases/1d-annual-feedback/feedback-pass-caps.input.json")
    with tempfile.TemporaryDirectory(prefix="t29-", dir=ROOT / "server") as temp:
        scenarios = Path(temp) / "scenarios"
        scenarios.mkdir()
        dist = Path(temp) / "ui" / "dist"
        with patch.object(backend, "SCENARIOS", scenarios), patch.object(backend, "UI_DIST", dist), TestClient(backend.app) as client:
            book = load_workbook(BytesIO(full_import.template(base, 2026, "T29")))
            for row in book["销售计划"].iter_rows(min_row=2):
                row[2].value = row[3].value = 0
            content = save(book)
            book.close()
            files = {"file": ('原始<计划>:表|?*.xlsx', content)}
            assert request(client, "POST", "/api/import/preview", files=files)["ok"]
            assert list(scenarios.iterdir()) == []
            imported = request(client, "POST", "/api/import", files=files)
            path = scenarios / imported["id"]
            originals = list((path / "uploads").iterdir())
            assert len(originals) == 1 and originals[0].read_bytes() == content
            assert originals[0].name.endswith("-file-原始_计划__表___.xlsx")
            print("PASS S1 import: original bytes identical; Windows filename characters replaced; full preview saved nothing", flush=True)

            parts = {kind: (f"{kind}.xlsx", imports.template(base, kind, 2026))
                     for kind in ("sales", "initial", "calendar")}
            form = {"base_id": imported["id"], **base["horizon"]}
            before = {p.relative_to(scenarios): p.read_bytes() for p in scenarios.rglob("*") if p.is_file()}
            assert request(client, "POST", "/api/new-plan/preview", data=form, files=parts)["ok"]
            assert {p.relative_to(scenarios): p.read_bytes() for p in scenarios.rglob("*") if p.is_file()} == before
            created = request(client, "POST", "/api/new-plan", data={**form, "name": "T29 三文件"}, files=parts)
            uploads = scenarios / created["id"] / "uploads"
            for field, (name, value) in parts.items():
                saved = list(uploads.glob(f"*-{field}-{name}"))
                assert len(saved) == 1 and saved[0].read_bytes() == value
            print("PASS S1 new-plan: sales/initial/calendar original bytes identical; split preview saved nothing", flush=True)

            calls = []
            mode = "success"
            plan = {"status": "FEASIBLE", "days": [{}], "findings": []}
            objective = dict.fromkeys(LEVELS, 0)

            def invoke(command, **kwargs):
                calls.append(command)
                kwargs["stdout"].write((command[2] + " " + mode + "\n").encode())
                if command[2] == "engine":
                    if mode == "engine-failure":
                        return subprocess.CompletedProcess(command, 1)
                    backend.write(Path(command[4]), plan)
                else:
                    if mode == "judge-failure":
                        return subprocess.CompletedProcess(command, 1)
                    value = dict(objective)
                    if mode == "worse" and command[4].endswith("plan.next.json"):
                        value["L1a"] = 1
                    rejected = mode == "reject"
                    backend.write(Path(command[5]), {"verdict": "REJECT" if rejected else "ACCEPT",
                                  "hard_errors": [{"detail": "自检拒绝"}] if rejected else [], "objective": value})
                return subprocess.CompletedProcess(command, 0)

            with patch.object(backend.subprocess, "run", side_effect=invoke), patch.object(backend, "now", return_value="2026-10-26T12:00:00"):
                url = f"/api/scenarios/{imported['id']}"
                request(client, "POST", url + "/run")
                backend.active_thread.join()
                first = records(path)[0]
                for name in ("input.json", "plan.json", "verdict.json", "run.log"):
                    assert (first / name).read_bytes() == (path / name).read_bytes()
                snapshot = {p.name: p.read_bytes() for p in first.iterdir()}
                mode = "worse"
                request(client, "POST", url + "/run")
                backend.active_thread.join()
                runs = records(path)
                assert len(runs) == 2 and runs[1].name == runs[0].name + "-2"
                assert backend.read(runs[1] / "run.json")["kept_previous"] is True
                assert backend.read(runs[1] / "run.json")["warm_start"] is True
                assert backend.read(runs[1] / "verdict.json")["objective"]["L1a"] == 1
                assert backend.read(runs[1] / "verdict.prev.json")["objective"]["L1a"] == 0
                assert (runs[1] / "plan.prev.json").read_bytes() == (path / "plan.json").read_bytes()
                assert (runs[1] / "run.log").read_bytes() == (path / "run.log").read_bytes()
                assert all((first / name).read_bytes() == value for name, value in snapshot.items())
                print("PASS S1 two runs: two independent records in same second; run.json fields complete; kept_previous preserves generated and previous results", flush=True)

                kept = {name: (path / name).read_bytes() for name in ("plan.json", "verdict.json")}
                for mode, expected in (("engine-failure", "生成器异常退出"), ("judge-failure", "判定器异常退出")):
                    request(client, "POST", url + "/run")
                    backend.active_thread.join()
                    failed = records(path)[-1]
                    run = backend.read(failed / "run.json")
                    assert run["state"] == "FAILED" and run["error"] == expected
                    assert (failed / "input.json").read_bytes() == (path / "input.json").read_bytes()
                    assert (failed / "run.log").read_bytes() == (path / "run.log").read_bytes()
                    assert (failed / "plan.json").exists() == (mode == "judge-failure")
                    assert not (failed / "verdict.json").exists()
                    assert all((path / name).read_bytes() == value for name, value in kept.items())
                print("PASS S1 failed runs: engine/judge failures archived; missing outputs omitted; previous live plan/verdict unchanged", flush=True)

                meta = backend.read(path / "meta.json")
                meta["run"]["state"] = "IDLE"
                backend.write(path / "meta.json", meta)
                current = {"stage": "CANDIDATES_DONE", "usage": {"saturdays_used": [], "overtime_used": []}}
                with patch.object(backend, "get_suggest", return_value=current):
                    for mode, expected_status in (("success", 200), ("reject", 409), ("judge-failure", 409)):
                        data = backend.read(path / "input.json")
                        data["conditions"] = [{"id": "CAND-SAT-20260103", "type": "SATURDAY_AUTH", "date": "2026-01-03"}]
                        backend.write(path / "input.json", data)
                        before = {name: (path / name).read_bytes() for name in ("input.json", "meta.json", "plan.json", "verdict.json")}
                        count = len(records(path))
                        request(client, "POST", url + "/suggest/apply", expected=expected_status)
                        runs = records(path)
                        assert len(runs) == count + 1
                        last = runs[-1]
                        assert backend.read(last / "input.json")["conditions"] == []
                        assert (last / "plan.json").read_bytes() == before["plan.json"]
                        assert (last / "run.log").read_bytes() == (path / "run.log").read_bytes()
                        assert backend.read(last / "run.json")["state"] == ("IDLE" if expected_status == 200 else "FAILED")
                        assert (last / "verdict.json").exists() == (mode != "judge-failure")
                        if expected_status != 200:
                            assert all((path / name).read_bytes() == value for name, value in before.items())
                print("PASS S1 apply-only judge: success/rejection/CLI failure each archived with attempted input; rejected live files unchanged (subprocess fixture)", flush=True)

            for route, body in ((url + "/finalize", {"note": "T29"}), ("/api/scenarios", {"from_id": imported["id"], "name": "T29 副本"})):
                copied = request(client, "POST", route, json=body)
                for name in ("runs", "uploads"):
                    original = {p.relative_to(path / name): p.read_bytes() for p in (path / name).rglob("*") if p.is_file()}
                    target = scenarios / copied["id"] / name
                    assert {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()} == original
            print("PASS S1 finalize/save-as: runs and uploads copied byte-for-byte", flush=True)

            assert client.get("/").status_code == 404
            assert client.get("/monthly-filling").status_code == 404
            dist.mkdir(parents=True)
            html = b"<!doctype html><html><body>T29 SPA</body></html>"
            (dist / "index.html").write_bytes(html)
            (dist / "assets").mkdir()
            (dist / "assets" / "app.js").write_bytes(b"window.T29=true;")
            for route in ("/", "/monthly-filling?month=2026-01"):
                response = client.get(route)
                assert response.status_code == 200 and response.content == html
                assert response.headers["content-type"].startswith("text/html")
            assert client.get("/assets/app.js").content == b"window.T29=true;"
            assert isinstance(request(client, "GET", "/api/scenarios"), list)
            assert client.get("/api/unknown").status_code == 404
            print("PASS S1 static: missing dist keeps 404; / and /monthly-filling serve index; assets served; /api/scenarios unchanged; unknown API stays 404", flush=True)
    print("PASS T29 S1 temporary scenarios removed; workspace untouched; run subprocesses use fixtures", flush=True)


if __name__ == "__main__":
    main()
