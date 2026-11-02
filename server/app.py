import json
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.responses import Response, JSONResponse, FileResponse

from . import views, imports, full_import, suggestions

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "workspace" / "scenarios"
UI_DIST = ROOT / "ui" / "dist"
lock = threading.RLock()
active_thread = None


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now():
    return datetime.now().isoformat(timespec="seconds")


def save_uploads(path, **uploads):
    target = path / "uploads"
    target.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for field, upload in uploads.items():
        if upload is not None:
            filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", upload.filename).rstrip(" .")
            upload.file.seek(0)
            with (target / f"{stamp}-{field}-{filename}").open("wb") as output:
                shutil.copyfileobj(upload.file, output)


def archive_run(path, run, input_path, artifacts):
    base = path / "runs" / datetime.fromisoformat(run["started_at"]).strftime("%Y%m%d-%H%M%S")
    target = base
    suffix = 2
    while target.exists():
        target = base.with_name(f"{base.name}-{suffix}")
        suffix += 1
    target.mkdir(parents=True)
    for source, name in [(input_path, "input.json"), (path / "run.log", "run.log"), *artifacts]:
        if source.is_file():
            shutil.copyfile(source, target / name)
    write(target / "run.json", run)


def folder(scenario_id):
    path = (SCENARIOS / scenario_id).resolve()
    if path.parent != SCENARIOS.resolve() or not (path / "meta.json").is_file():
        raise HTTPException(404, "方案不存在")
    return path


def summary(path):
    meta = read(path / "meta.json")
    plan = read(path / "plan.json") if (path / "plan.json").exists() else None
    verdict = read(path / "verdict.json") if (path / "verdict.json").exists() else None
    if meta["run"]["state"] in ("RUNNING", "FAILED"):
        state = meta["run"]["state"]
    elif plan is None:
        state = "NO_PLAN"
    elif meta["plan_input_rev"] != meta["input_rev"]:
        state = "STALE"
    else:
        state = "READY"
    return {**{k: meta[k] for k in ("id", "name", "created_at", "run")}, "state": state,
            "plan_status": plan["status"] if plan is not None else None,
            "no_plan": plan is None or not plan["days"] or plan["status"] != "FEASIBLE",
            "findings": plan["findings"] if plan is not None else [],
            "solver": plan.get("solver") if plan is not None else None,
            "verdict": verdict["verdict"] if verdict is not None else None,
            "hard_error_count": len(verdict["hard_errors"]) if verdict is not None else 0,
            "objective": verdict["objective"] if verdict is not None else None,
            "formal": meta.get("formal")}


def running():
    return any(read(p)["run"]["state"] == "RUNNING" for p in SCENARIOS.glob("*/meta.json"))


@asynccontextmanager
async def lifespan(app):
    with lock:
        for path in SCENARIOS.glob("*/meta.json"):
            meta = read(path)
            if meta["run"]["state"] == "RUNNING":
                meta["run"].update(state="FAILED", error="后端重启，运行中断", finished_at=now())
                write(path, meta)
    yield
    if active_thread is not None:
        active_thread.join()


app = FastAPI(lifespan=lifespan)


@app.get("/api/scenarios")
def list_scenarios():
    with lock:
        return sorted((summary(p.parent) for p in SCENARIOS.glob("*/meta.json")),
                      key=lambda s: s["created_at"], reverse=True)


@app.post("/api/scenarios")
def create_scenario(body: dict):
    with lock:
        source = folder(body["from_id"])
        base = "s-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        scenario_id = base
        suffix = 2
        while (SCENARIOS / scenario_id).exists():
            scenario_id = f"{base}-{suffix}"
            suffix += 1
        path = SCENARIOS / scenario_id
        path.mkdir()
        (path / "input.json").write_bytes((source / "input.json").read_bytes())
        for name in ("runs", "uploads"):
            if (source / name).is_dir():
                shutil.copytree(source / name, path / name)
        write(path / "meta.json", {"id": scenario_id, "name": body["name"], "created_at": now(),
                                  "input_rev": 1, "plan_input_rev": None,
                                  "run": {"state": "IDLE", "started_at": None, "finished_at": None,
                                          "seconds": None, "error": None,
                                          "warm_start": False, "kept_previous": False}})
        return summary(path)


@app.get("/api/scenarios/{scenario_id}/conditions")
def get_conditions(scenario_id: str):
    with lock:
        path = folder(scenario_id)
        data = read(path / "input.json")
        return {"scenario": summary(path), "conditions": data["conditions"],
                "options": {"caps": views.node_caps(data), "horizon": data["horizon"], "workshops": views.WORKSHOPS, "nodes": views.NODES,
                            "auth_modes": [m for m in data["factory"]["modes"]
                                           if m not in ("OFF", data["factory"]["default_mode"])]}}


@app.put("/api/scenarios/{scenario_id}/conditions")
def put_conditions(scenario_id: str, body: dict):
    with lock:
        path = folder(scenario_id)
        require_editable(path)
        if running():
            raise HTTPException(409, "方案运行中，不能修改条件")
        data = read(path / "input.json")
        caps = views.node_caps(data)
        for condition in body["conditions"]:
            if condition["type"] == "WIP_TARGET":
                cap = caps[condition["node"]]
                if cap is not None and condition["target"] > cap:
                    raise HTTPException(422, f"节点 {condition['node']} 的人工目标在制不能超过上限 {cap}")
        data["conditions"] = body["conditions"]
        write(path / "input.json", data)
        meta = read(path / "meta.json")
        meta["input_rev"] += 1
        write(path / "meta.json", meta)
        return summary(path)


def execute(path, input_rev):
    start = time.monotonic()
    error = None
    judged = False
    kept_previous = False
    for name in ("plan.next.json", "verdict.next.json", "verdict.prev.json"):
        (path / name).unlink(missing_ok=True)
    previous = read(path / "plan.json") if (path / "plan.json").exists() else None
    warm_start = previous is not None and previous["status"] in ("FEASIBLE", "UNKNOWN") and bool(previous["days"])
    command = [sys.executable, "-m", "engine", str(path / "input.json"), str(path / "plan.next.json")]
    if warm_start:
        command.extend(["--warm-start", str(path / "plan.json")])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    with (path / "run.log").open("wb") as log:
        result = subprocess.run(command, cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            error = "生成器异常退出"
        elif read(path / "plan.next.json")["status"] in ("FEASIBLE", "UNKNOWN"):
            judged = True
            result = subprocess.run([sys.executable, "-m", "judge", str(path / "input.json"),
                                     str(path / "plan.next.json"), str(path / "verdict.next.json")],
                                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                error = "判定器异常退出"
        if error is None and previous is not None:
            result = subprocess.run([sys.executable, "-m", "judge", str(path / "input.json"),
                                     str(path / "plan.json"), str(path / "verdict.prev.json")],
                                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                error = "判定器异常退出"
            else:
                old = read(path / "verdict.prev.json")
                new = read(path / "verdict.next.json") if judged else None
                levels = ("L1a", "L1b", "L1c", "L2", "L3a", "L3b", "L4", "L5", "L6")
                kept_previous = old["verdict"] == "ACCEPT" and (
                    new is None or new["verdict"] != "ACCEPT"
                    or tuple(old["objective"][k] for k in levels) < tuple(new["objective"][k] for k in levels))
    with lock:
        meta = read(path / "meta.json")
        meta["run"].update(state="FAILED" if error else "IDLE", error=error,
                           warm_start=warm_start, kept_previous=kept_previous,
                           finished_at=now(), seconds=round(time.monotonic() - start, 3))
        artifacts = [(path / "plan.next.json", "plan.json"),
                     (path / "verdict.next.json", "verdict.json")]
        if (path / "verdict.prev.json").exists():
            artifacts.extend([(path / "plan.json", "plan.prev.json"),
                              (path / "verdict.prev.json", "verdict.prev.json")])
        archive_run(path, meta["run"], path / "input.json", artifacts)
        if error is None:
            if kept_previous:
                shutil.copyfile(path / "verdict.prev.json", path / "verdict.json")
            else:
                (path / "plan.next.json").replace(path / "plan.json")
            if judged and not kept_previous:
                (path / "verdict.next.json").replace(path / "verdict.json")
            elif not kept_previous:
                (path / "verdict.json").unlink(missing_ok=True)
            meta["plan_input_rev"] = input_rev
        write(path / "meta.json", meta)


@app.post("/api/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str):
    global active_thread
    with lock:
        path = folder(scenario_id)
        require_editable(path)
        if running():
            raise HTTPException(409, "已有方案正在运行")
        meta = read(path / "meta.json")
        meta["run"] = {"state": "RUNNING", "started_at": now(), "finished_at": None,
                       "seconds": None, "error": None, "warm_start": False, "kept_previous": False}
        write(path / "meta.json", meta)
        response = summary(path)
        active_thread = threading.Thread(target=execute, args=(path, meta["input_rev"]))
        active_thread.start()
        return response


def view_inputs(scenario_id):
    path = folder(scenario_id)
    if not (path / "plan.json").exists():
        raise HTTPException(404, "方案尚未运行")
    return (read(path / "input.json"), read(path / "plan.json"),
            read(path / "verdict.json") if (path / "verdict.json").exists() else None, summary(path))


@app.get("/api/scenarios/{scenario_id}/annual")
def get_annual(scenario_id: str):
    with lock:
        return views.annual(*view_inputs(scenario_id))


@app.get("/api/scenarios/{scenario_id}/monthly")
def get_monthly(scenario_id: str, month: str):
    with lock:
        args = view_inputs(scenario_id)
        if month not in views.months_in(args[0]["horizon"]):
            raise HTTPException(404, "月份不在计划期内")
        return views.monthly(*args, month)


def require_editable(path):
    if read(path / "meta.json").get("formal") is not None:
        raise HTTPException(409, "正式版本只读")


@app.get("/api/scenarios/{scenario_id}/suggest")
def get_suggest(scenario_id: str):
    with lock:
        path = folder(scenario_id)
        return suggestions.view(
            read(path / "input.json"),
            read(path / "plan.json") if (path / "plan.json").exists() else None,
            read(path / "meta.json"), summary(path))


@app.post("/api/scenarios/{scenario_id}/suggest/{action}")
def change_suggest(scenario_id: str, action: str):
    with lock:
        path = folder(scenario_id)
        require_editable(path)
        if running():
            raise HTTPException(409, "方案运行中，不能修改建议")
        data = read(path / "input.json")
        meta = read(path / "meta.json")
        current = get_suggest(scenario_id)
        if action == "candidates":
            if any(c["id"].startswith("CAND-") for c in data["conditions"]):
                raise HTTPException(409, "已有候选授权，先采纳或撤销")
            if current["stage"] == "NEED_RUN":
                raise HTTPException(409, "先运行一次，才能生成候选授权")
            if not current["gaps"]:
                raise HTTPException(409, "当前条件下没有缺口")
            candidates = suggestions.generate(data, read(path / "plan.json"), current["gaps"], meta)
            if not candidates:
                raise HTTPException(409, "缺口月附近没有可加的周六或加班")
            data["conditions"].extend(candidates)
            meta["suggest"] = {"baseline": current["current"], "created_rev": meta["input_rev"] + 1}
        elif action == "apply":
            if current["stage"] != "CANDIDATES_DONE":
                raise HTTPException(409, "先运行候选授权，才能采纳")
            tried = {}
            for c in data["conditions"]:
                if c["id"].startswith("CAND-") and c["type"] == "MODE_AUTH":
                    tried.setdefault(c["mode"], set()).add(c["start"][:7])
            data["conditions"] = suggestions.apply(data, read(path / "plan.json"), current["usage"])
            start = time.monotonic()
            run = {"state": "IDLE", "started_at": now(), "finished_at": None,
                   "seconds": None, "error": None, "warm_start": False, "kept_previous": False}
            write(path / "input.next.json", data)
            (path / "verdict.next.json").unlink(missing_ok=True)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
            with (path / "run.log").open("ab") as log:
                result = subprocess.run(
                    [sys.executable, "-m", "judge", str(path / "input.next.json"),
                     str(path / "plan.json"), str(path / "verdict.next.json")],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            error = None
            if result.returncode != 0:
                error = "采纳后判定未通过：判定器异常退出"
            elif read(path / "verdict.next.json")["verdict"] != "ACCEPT":
                error = f"采纳后判定未通过：{read(path / 'verdict.next.json')['hard_errors'][0]['detail']}"
            run.update(state="FAILED" if error else "IDLE", error=error,
                       finished_at=now(), seconds=round(time.monotonic() - start, 3))
            archive_run(path, run, path / "input.next.json",
                        [(path / "plan.json", "plan.json"), (path / "verdict.next.json", "verdict.json")])
            (path / "input.next.json").unlink()
            if error:
                (path / "verdict.next.json").unlink(missing_ok=True)
                raise HTTPException(409, error)
            (path / "verdict.next.json").replace(path / "verdict.json")
            meta["plan_input_rev"] = meta["input_rev"] + 1
            meta.pop("suggest", None)
            for mode, months in tried.items():
                meta.setdefault("suggest_tried", []).append({"mode": mode, "months": sorted(months)})
        elif action == "discard":
            data["conditions"] = [c for c in data["conditions"] if not c["id"].startswith("CAND-")]
            meta.pop("suggest", None)
        else:
            raise HTTPException(404, "建议操作不存在")
        meta["input_rev"] += 1
        write(path / "input.json", data)
        write(path / "meta.json", meta)
        return get_suggest(scenario_id)


@app.get("/api/templates/{kind}")
def get_template(kind: str, year: int, base_id: str | None = None):
    if kind not in imports.HEADERS and kind != "full":
        raise HTTPException(404, "模板不存在")
    with lock:
        if kind == "full":
            source = folder(base_id) if base_id else None
            content = full_import.template(read(source / "input.json") if source else None, year,
                                           read(source / "meta.json")["name"] if source else "")
        else:
            if base_id is None:
                raise HTTPException(422, "请填写来源方案")
            content = imports.template(read(folder(base_id) / "input.json"), kind, year)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{kind}-{year}.xlsx"'})


@app.post("/api/new-plan/preview")
def preview_plan(base_id: str = Form(...), start: str = Form(...), end: str = Form(...),
                 sales: UploadFile = File(...), initial: UploadFile | None = File(None),
                 calendar: UploadFile | None = File(None)):
    with lock:
        result, _ = imports.preview(read(folder(base_id) / "input.json"), start, end, sales, initial, calendar)
        return result


@app.post("/api/import/preview")
def preview_import(file: UploadFile = File(...)):
    result, _, _ = full_import.preview(file)
    return result


@app.post("/api/import")
def import_plan(file: UploadFile = File(...)):
    result, data, name = full_import.preview(file)
    if not result["ok"]:
        return JSONResponse(status_code=422, content={"detail": "预检未通过", "errors": result["errors"]})
    with lock:
        base = "s-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        scenario_id = base
        suffix = 2
        while (SCENARIOS / scenario_id).exists():
            scenario_id = f"{base}-{suffix}"
            suffix += 1
        path = SCENARIOS / scenario_id
        path.mkdir()
        write(path / "input.json", data)
        write(path / "meta.json", {"id": scenario_id, "name": name, "created_at": now(),
                                  "input_rev": 1, "plan_input_rev": None,
                                  "run": {"state": "IDLE", "started_at": None, "finished_at": None,
                                          "seconds": None, "error": None,
                                          "warm_start": False, "kept_previous": False}})
        save_uploads(path, file=file)
        return summary(path)


@app.post("/api/new-plan")
def new_plan(base_id: str = Form(...), start: str = Form(...), end: str = Form(...),
             name: str = Form(...), sales: UploadFile = File(...),
             initial: UploadFile | None = File(None), calendar: UploadFile | None = File(None)):
    with lock:
        result, data = imports.preview(read(folder(base_id) / "input.json"), start, end, sales, initial, calendar)
        if not result["ok"]:
            return JSONResponse(status_code=422, content={"detail": "预检未通过", "errors": result["errors"]})
        created = create_scenario({"from_id": base_id, "name": name})
        path = folder(created["id"])
        write(path / "input.json", data)
        save_uploads(path, sales=sales, initial=initial, calendar=calendar)
        return summary(path)


@app.post("/api/scenarios/{scenario_id}/finalize")
def finalize(scenario_id: str, body: dict):
    with lock:
        source = folder(scenario_id)
        require_editable(source)
        current = summary(source)
        if current["state"] != "READY" or current["verdict"] != "ACCEPT":
            raise HTTPException(409, "仅可定稿已就绪且判定通过的方案")
        stamp = datetime.now()
        base = "f-" + stamp.strftime("%Y%m%d-%H%M%S")
        new_id = base
        suffix = 2
        while (SCENARIOS / new_id).exists():
            new_id = f"{base}-{suffix}"
            suffix += 1
        path = SCENARIOS / new_id
        shutil.copytree(source, path)
        meta = read(path / "meta.json")
        confirmed_at = stamp.isoformat(timespec="seconds")
        meta.update(id=new_id, name=meta["name"] + f"（正式 {stamp:%Y-%m-%d}）", created_at=confirmed_at,
                    formal={"source_id": scenario_id, "confirmed_at": confirmed_at, "note": body.get("note", "")})
        write(path / "meta.json", meta)
        return summary(path)


@app.get("/{page_path:path}")
def page(page_path: str):
    if page_path.startswith("api") or not UI_DIST.is_dir():
        raise HTTPException(404, "Not Found")
    target = (UI_DIST / page_path).resolve()
    if not target.is_relative_to(UI_DIST.resolve()):
        raise HTTPException(404, "Not Found")
    if target.is_file() and target.parent.name == "assets":
        return FileResponse(target)
    # 页面本身不缓存，换新版本后同事刷新即可看到新界面（assets 文件名带哈希，可以缓存）
    return FileResponse(target if target.is_file() else UI_DIST / "index.html", headers={"Cache-Control": "no-cache"})
