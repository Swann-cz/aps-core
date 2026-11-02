"""T-31 S1-1–S1-4；只向 cases/*/_out/ 写运行产物。"""
import argparse
from copy import deepcopy
from datetime import date, timedelta
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .segments import _settings, prepare_fast
from .segment_plan import LEVELS, replay_segments, solve_segments, improve_segments


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(command):
    print("COMMAND: " + " ".join(command), flush=True)
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    print(result.stdout + result.stderr, end="", flush=True)
    print(f"exit_code={result.returncode}", flush=True)
    assert result.returncode == 0
    return result.stdout


def _source(label):
    base = Path("cases/1d-annual-feedback" if label == "pass" else "cases/t30-trial")
    input_path = base / ("feedback-pass.input.json" if label == "pass" else "trial-2models.input.json")
    return base, input_path


def controls(label):
    """只提取段日期、班制、停点/尾差和清线日期，不传递参考日流量/水位。"""
    base, input_path = _source(label)
    data = _read(input_path)
    source = base / "_out" / ("T-31b-R3-pass.segments.json" if label == "pass" else "T-31b-trial-2models.segments.json")
    old = _read(source)["segments"]
    settings = _settings(data, {})
    result = []
    reference = _read(base / "_out/T-31b-R3-pass.segments.plan.json") if label == "pass" else None
    for index, segment in enumerate(old):
        s = {k: deepcopy(segment[k]) for k in ("model", "start", "end", "tail")}
        s["modes"] = deepcopy(segment.get("modes", {}))
        s["stop_points"] = {}
        s["retain_water"] = segment.get("retain_month_end", False)
        # 各月给出停点，日期变体仍由调用方控制，不使用累计 FOK 缩产。
        for mo in data["demand"]["PR"][s["model"]]:
            work = [d for d in settings if d[:7] == mo and any(settings[d]["caps"].values())]
            if work:
                s["stop_points"][mo] = {"date": work[-1]}
        if reference is not None:
            following = old[index + 1]["start"] if index + 1 < len(old) else "9999"
            rows = [r for r in reference["days"] if s["start"] <= r["date"] < following]
            line = data["factory"]["models"][s["model"]]["line"]
            for mo in sorted({r["date"][:7] for r in rows}):
                flowing = [r for r in rows if r["date"][:7] == mo and any(
                    sum(v[k].values()) for v in r["workshops"].values() for k in ("in", "out"))]
                if not flowing:
                    continue
                normal = [r for r in flowing if r["phase"] in (
                    "NORMAL", "PS_PRE_STOP", "REFILL", "FIRST_START", "FIRST_START+CHANGEOVER")]
                last = flowing[-1] if s["tail"]["type"] == "LONG_STOP" and mo == s["end"][:7] else normal[-1] if normal else flowing[-1]
                point = {"date": last["date"]}
                # C14/§9 的显式尾差选择；只在选定月末停点取数量。
                quantity = sum(last["fok"].values())
                if last["phase"] in ("NORMAL", "PS_PRE_STOP") and quantity < settings[last["date"]]["caps"]["AS_FIN"]:
                    point["quantity"] = quantity
                s["stop_points"][mo] = point
            if s["tail"]["type"] == "LONG_STOP":
                clear = next(r for r in rows if "BS_CLEAR" in r["phase"])
                prep = next(r for r in reversed(rows) if r["date"] < clear["date"] and sum(r["workshops"][line]["in"].values()))
                s["tail"].update(preparation_date=prep["date"], clear_start=clear["date"])
            elif s["tail"]["type"] == "CHANGEOVER":
                s["tail"]["clear_start"] = next(r["date"] for r in rows if r["phase"] == "CHANGEOVER")
        result.append(s)
    _write(base / f"_out/T-31-S1-{label}.controls.json", result)
    print(f"source={source}; segments={len(result)}", flush=True)
    print("controls=" + json.dumps([{**{k: v for k, v in s.items() if k not in ('modes', 'stop_points')},
        'stop_points': {mo: p for mo, p in s['stop_points'].items() if s['start'][:7] <= mo <= s['end'][:7]}}
        for s in result], ensure_ascii=False), flush=True)
    return data, result


def s1_replay(label):
    data, segments = controls(label)
    base, input_path = _source(label)
    answer = replay_segments(data, segments)
    plan_path = base / f"_out/T-31-S1-{label}.plan.json"
    verdict_path = base / f"_out/T-31-S1-{label}.verdict.json"
    _write(base / f"_out/T-31-S1-{label}.replay.json", answer)
    _write(plan_path, answer["plan"])
    _run([sys.executable, "-B", "-X", "utf8", "-m", "judge", str(input_path), str(plan_path), str(verdict_path)])
    verdict = _read(verdict_path)
    print(f"verdict={verdict['verdict']}; hard_errors={len(verdict['hard_errors'])}")
    denominator = Fraction(str(data["rules"]["monthly_band_ratio"])).denominator
    for level in LEVELS:
        actual = verdict["objective"][level]
        # IO_CONTRACT §5：按输入月度带的精度对账，保留 judge 原始浮点值。
        normalized = float(Fraction(str(actual)).limit_denominator(denominator)) if level == "L1c" else actual
        equal = answer["levels"][level] == normalized
        print(f"{level}: segment={answer['levels'][level]}; judge_raw={actual}; judge_contract={normalized}; equal={equal}")
        assert equal
    print("monthly_fok=" + json.dumps(answer["flow"]["monthly_fok"], ensure_ascii=False))
    dated = {r["date"]: r for r in answer["plan"]["days"]}
    assert all(all(r[key] == dated[r["date"]][key] for key in ("workshops", "bod", "eod", "fok")) for r in answer["flow"]["days"])
    assert all(sum(b["quantity"] for b in answer["flow"]["exit"]["wbs_batches"] if b["model"] == m)
               == answer["flow"]["exit"]["stock"]["WBS"][m] for m in data["factory"]["models"])
    print("single_flow_plan_and_ledger_equal=True; exit_wbs_batches_equal=True")
    for error in verdict["hard_errors"]:
        print(json.dumps(error, ensure_ascii=False))
    if label == "pass":
        assert verdict["verdict"] == "ACCEPT"


def s1_determinism(repeat_only=False):
    for label in ("pass", "trial"):
        base, input_path = _source(label)
        data = _read(input_path)
        segments = _read(base / f"_out/T-31-S1-{label}.controls.json")
        paths = []
        for number in range(2):
            path = base / f"_out/T-31-S1-{label}-repeat-{number}.json"
            _run([sys.executable, '-B', '-X', 'utf8', '-m', 'engine.segment_plan',
                  str(input_path), str(base / f'_out/T-31-S1-{label}.controls.json'), str(path)])
            paths.append(path)
        same = paths[0].read_bytes() == paths[1].read_bytes()
        same &= paths[0].with_suffix('.plan.json').read_bytes() == paths[1].with_suffix('.plan.json').read_bytes()
        print(f"{label}: replay_and_plan_bytes_equal={same}", flush=True)
        assert same
    if repeat_only:
        return
    cases = ("1a-single-model-two-weeks", "1a2-short-capacity", "1b-two-models-changeover", "1c-long-stop",
        "1c-short-stop", "1c-standard-clear", "1c-standard-refill", "1d-first-start-changeover",
        "1d-initial-drain", "1d-initial-refill", "1d-year-end-stop", "1d-year-end-stop-calendar")
    for name in cases:
        original = Path("cases") / name / "_out/plan.json"
        before = original.read_bytes()
        original.with_name("T-31-S1-before-main.plan.json").write_bytes(before)
        output = _run([sys.executable, "-B", "-X", "utf8", "tools/run_case.py", str(Path("cases") / name)])
        assert "[RESULT] PASS" in output
        same = original.read_bytes() == before
        print(f"{name}: main_plan_bytes_unchanged={same}", flush=True)
        assert same
    base, input_path = _source("pass")
    output = base / "_out/T-31-S1-main-pass.plan.json"
    _run([sys.executable, "-B", "-X", "utf8", "-m", "engine", str(input_path), str(output)])
    reference = Path("D:/APS/aps-core/cases/1d-annual-feedback/_out/T-28-R2-pass.plan.json")
    same = output.read_bytes() == reference.read_bytes()
    print(f"main_pass_vs_T28_R2_bytes_equal={same}", flush=True)
    assert same
    _run(["git", "diff", "--exit-code", "--", "engine/model.py", "engine/monthly.py", "engine/conditions.py",
          "engine/templates.py", "engine/__main__.py", "engine/__init__.py"])


def _variants(data, segments):
    yield "base", segments
    # 计算邻域宽度，非业务参数；各段起止日、有效月停点分别前后移动。
    for index, segment in enumerate(segments):
        for field in ("start", "end"):
            for delta in (-2, -1, 1, 2):
                moved = (date.fromisoformat(segment[field]) + timedelta(days=delta)).isoformat()
                if not data["horizon"]["start"] <= moved <= data["horizon"]["end"]:
                    continue
                if field == "start" and (moved > segment["end"] or index and moved <= segments[index - 1]["end"]):
                    continue
                if field == "end" and (moved < segment["start"] or index + 1 < len(segments) and moved >= segments[index + 1]["start"]):
                    continue
                copy = deepcopy(segments)
                copy[index][field] = moved
                yield f"segment={index} {field} {delta:+}", copy
        for month, point in segment["stop_points"].items():
            if not segment["start"][:7] <= month <= segment["end"][:7]:
                continue
            for delta in (-2, -1, 1, 2):
                moved = (date.fromisoformat(point["date"]) + timedelta(days=delta)).isoformat()
                if moved[:7] != month or not segment["start"] <= moved <= segment["end"]:
                    continue
                copy = deepcopy(segments)
                copy[index]["stop_points"][month]["date"] = moved
                yield f"segment={index} stop={month} {delta:+}", copy


def _difference(left, right, path=""):
    if type(left) != type(right):
        return path
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path + ".keys"
        for key in left:
            diff = _difference(left[key], right[key], path + "." + str(key))
            if diff:
                return diff
    elif isinstance(left, list):
        if len(left) != len(right):
            return path + ".length"
        for i, (a, b) in enumerate(zip(left, right)):
            diff = _difference(a, b, path + f"[{i}]")
            if diff:
                return diff
    elif left != right:
        return path
    return None


def s1_fast():
    for label in ("pass", "trial"):
        base, input_path = _source(label)
        data = _read(input_path)
        segments = _read(base / f"_out/T-31-S1-{label}.controls.json")
        tick = perf_counter()
        table = prepare_fast(data, segments)
        preparation_seconds = perf_counter() - tick
        checked, differences = [], []
        for name, candidate in _variants(data, segments):
            tick = perf_counter()
            full = replay_segments(data, candidate)
            full_seconds = perf_counter() - tick
            tick = perf_counter()
            quick = replay_segments(data, candidate, fast_table=table)
            fast_seconds = perf_counter() - tick
            stats = quick["flow"].pop("fast_stats")
            full["flow"].pop("fast_stats")
            difference = _difference(full, quick)
            if difference:
                index = next((i for i, (a, b) in enumerate(zip(full['flow']['days'], quick['flow']['days'])) if a != b), None)
                differences.append({"variant": name, "date": full['flow']['days'][index]['date'] if index is not None else None, "item": difference})
            checked.append({"variant": name, "full_seconds": full_seconds, "fast_seconds": fast_seconds, **stats})
            if name == "base":
                print(f"{label}: prepare_seconds={preparation_seconds:.6f}; full_single_seconds={full_seconds:.6f}; fast_cold_single_seconds={fast_seconds:.6f}; stats={stats}", flush=True)
                tick = perf_counter()
                warm = replay_segments(data, candidate, fast_table=table)
                print(f"{label}: fast_warm_single_seconds={perf_counter() - tick:.6f}; stats={warm['flow']['fast_stats']}", flush=True)
        _write(base / f"_out/T-31-S1-{label}.fast-check.json", {"preparation_seconds": preparation_seconds,
            "checked": checked, "differences": differences})
        print(f"{label}: variants={len(checked)}; daily_monthly_state_objectives_equal={not differences}; differences={differences}; event_entries={sum(len(v) for v in table['events'].values())}", flush=True)
        assert not differences


def s2_regression(stage='S2'):
    cases = ('1a-single-model-two-weeks', '1a2-short-capacity', '1b-two-models-changeover',
        '1c-long-stop', '1c-short-stop', '1c-standard-clear', '1c-standard-refill',
        '1d-first-start-changeover', '1d-initial-drain', '1d-initial-refill',
        '1d-year-end-stop', '1d-year-end-stop-calendar')
    for name in cases:
        original = Path('cases') / name / '_out/plan.json'
        before = original.read_bytes()
        original.with_name(f'T-31-{stage}-before-main.plan.json').write_bytes(before)
        output = _run([sys.executable, '-B', '-X', 'utf8', 'tools/run_case.py', str(Path('cases') / name)])
        same = before == original.read_bytes()
        print(f'{name}: main_plan_bytes_unchanged={same}', flush=True)
        assert '[RESULT] PASS' in output and same
    base, input_path = _source('pass')
    output = base / f'_out/T-31-{stage}-main-pass.plan.json'
    _run([sys.executable, '-B', '-X', 'utf8', '-m', 'engine', str(input_path), str(output)])
    reference = Path('D:/APS/aps-core/cases/1d-annual-feedback/_out/T-28-R2-pass.plan.json')
    same = output.read_bytes() == reference.read_bytes()
    print(f'main_pass_vs_T28_R2_bytes_equal={same}', flush=True)
    assert same
    _run(['git', 'diff', '--exit-code', '--', 'engine/model.py', 'engine/monthly.py', 'engine/conditions.py',
          'engine/templates.py', 'engine/__main__.py', 'engine/__init__.py'])


def _day_classes(data, answer):
    from .segments import _settings
    settings = _settings(data, answer['modes'])
    counts = dict.fromkeys(('normal', 'normal_clear', 'non_normal', 'non_normal_clear'), 0)
    for row in answer['flow']['days']:
        d = row['date']
        s = settings[d]
        clear = any(p in row['phase'] for p in ('BS_CLEAR', 'REFILL', 'FIRST_START', 'CHANGEOVER', 'INITIAL_DRAIN'))
        abnormal = bool(s['fixed']) or any(sum(row[k][n].values()) > s['targets'][n]
                                          for k in ('bod', 'eod') for n in row[k])
        abnormal |= any(c['type'] == 'WIP_TARGET' and c['start'] <= d <= c['end'] for c in data['conditions'])
        if clear:
            abnormal |= any(c['type'] == 'CAPACITY_LOSS' and c['start'] <= d <= c['end'] for c in data['conditions'])
            abnormal |= 'BS_CLEAR' in row['phase'] and any(0 < sum(row['workshops'][w]['out'].values()) < s['caps'][w]
                for w in ('PS', 'AS_MAIN', 'AS_FIN'))
        counts[('non_normal_clear' if abnormal else 'normal_clear') if clear else
               ('non_normal' if abnormal else 'normal')] += 1
    return counts


def s2_solve(label, beam_width=8):
    base = Path('cases/t30-trial' if label == 'trial' else 'cases/1d-annual-feedback')
    input_path = base / ('trial-2models.input.json' if label == 'trial' else f'feedback-{label}.input.json')
    data = _read(input_path)
    tick = perf_counter()
    answer = solve_segments(data, beam_width=beam_width)
    stem = base / f'_out/T-31-S2-{label}'
    output = stem.with_suffix('.json')
    print('candidate_source=input_only; scope=restricted_fragment_graph; S3=False', flush=True)
    print('stats=' + json.dumps(answer['stats'], ensure_ascii=False), flush=True)
    for row in answer.get('solver', []):
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if 'plan' not in answer:
        _write(stem.with_suffix('.timing.json'), {'stats': answer['stats'], 'solver': answer.get('solver', [])})
        _write(output, answer)
        print('status=UNKNOWN; blocked_month=' + answer.get('blocked_month', 'annual_selection'), flush=True)
        print('findings=' + json.dumps(answer['findings'], ensure_ascii=False), flush=True)
        return
    plan_path, verdict_path = stem.with_suffix('.plan.json'), stem.with_suffix('.verdict.json')
    _write(plan_path, answer['plan'])
    _run([sys.executable, '-B', '-X', 'utf8', '-m', 'judge', str(input_path), str(plan_path), str(verdict_path)])
    verdict = _read(verdict_path)
    answer['status'] = verdict['verdict']
    print(f'verdict={verdict["verdict"]}; hard_errors={len(verdict["hard_errors"])}', flush=True)
    denominator = Fraction(str(data['rules']['monthly_band_ratio'])).denominator
    for level in LEVELS:
        actual = verdict['objective'][level]
        normalized = float(Fraction(str(actual)).limit_denominator(denominator)) if level == 'L1c' else actual
        print(f'{level}: segment={answer["levels"][level]}; judge_raw={actual}; equal={normalized == answer["levels"][level]}', flush=True)
        if verdict['verdict'] == 'ACCEPT':
            assert normalized == answer['levels'][level]
    for error in verdict['hard_errors']:
        print(json.dumps(error, ensure_ascii=False), flush=True)
    answer['stats']['day_classes'] = _day_classes(data, answer)
    answer['stats']['including_judge_seconds'] = perf_counter() - tick
    print('day_classes=' + json.dumps(answer['stats']['day_classes'], ensure_ascii=False), flush=True)
    print(f'including_judge_seconds={answer["stats"]["including_judge_seconds"]:.6f}', flush=True)
    print('monthly_fok=' + json.dumps(answer['flow']['monthly_fok'], ensure_ascii=False), flush=True)
    if label != 'trial':
        reference = Path(f'D:/APS/aps-core/cases/1d-annual-feedback/_out/T-28-R2-{label}.plan.json')
        reference_verdict = stem.with_suffix('.reference.verdict.json')
        _run([sys.executable, '-B', '-X', 'utf8', '-m', 'judge', str(input_path), str(reference), str(reference_verdict)])
        old = _read(reference_verdict)
        print('reference_verdict=' + old['verdict'], flush=True)
        for level in LEVELS:
            a, b = verdict['objective'][level], old['objective'][level]
            print(f'COMPARE {label} {level}: segment={a}; T-28-R2={b}; ' + ('持平' if a == b else '更好' if a < b else '较差'), flush=True)
        # 只在生成和选择结束后读参考数量用于差异归因；不回传候选生成器。
        old_plan = _read(reference)
        changes = []
        for month, values in answer['flow']['monthly_fok'].items():
            for m, quantity in values.items():
                before = sum(r['fok'].get(m, 0) for r in old_plan['days'] if r['date'][:7] == month)
                if before != quantity:
                    changes.append({'month': month, 'model': m, 'new': quantity, 'reference': before, 'delta': quantity - before})
        print('monthly_differences=' + json.dumps(changes, ensure_ascii=False), flush=True)
    _write(stem.with_suffix('.timing.json'), {'stats': answer['stats'], 'solver': answer['solver']})
    # 计划/候选结果保留确定字段；墙钟只放本轮计时产物。
    for key in list(answer['stats']):
        if key.endswith('_seconds'):
            answer['stats'].pop(key)
    for row in answer['solver']:
        row.pop('seconds')
    _write(output, answer)


def s2_stats():
    for label in ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps', 'trial'):
        base = Path('cases/t30-trial' if label == 'trial' else 'cases/1d-annual-feedback')
        path = base / f'_out/T-31-S2-{label}.timing.json'
        value = _read(path)
        stats = value['stats']
        if 'selected_days' not in stats:
            print(json.dumps({'label': label, **stats, 'table_ratio': None, 'single_ratio': None,
                'reason': '没有选出完整年度候选，比例不适用'}, ensure_ascii=False), flush=True)
            continue
        days = stats['selected_days']
        total = sum(days.values())
        print(json.dumps({'label': label, **stats, 'table_ratio': (days['steady_days'] + days['event_hits']) / total,
                          'single_ratio': days['single_days'] / total}, ensure_ascii=False), flush=True)


def s3_solve(label, beam_width=8, move_budget=512, stage='S3'):
    base = Path('cases/t30-trial' if label == 'trial' else 'cases/1d-annual-feedback')
    input_path = base / ('trial-2models.input.json' if label == 'trial' else f'feedback-{label}.input.json')
    data = _read(input_path)
    stem = base / f'_out/T-31-{stage}-{label}'
    tick = perf_counter()
    answer = solve_segments(data, beam_width=beam_width)
    assert 'plan' in answer
    def check(plan, values, suffix):
        plan_path, verdict_path = stem.with_suffix(f'.{suffix}.plan.json'), stem.with_suffix(f'.{suffix}.verdict.json')
        _write(plan_path, plan)
        _run([sys.executable, '-B', '-X', 'utf8', '-m', 'judge', str(input_path), str(plan_path), str(verdict_path)])
        verdict = _read(verdict_path)
        print(f'{suffix}: verdict={verdict["verdict"]}; levels=' + json.dumps(values), flush=True)
        for error in verdict['hard_errors']:
            print(json.dumps(error, ensure_ascii=False), flush=True)
        denominator = Fraction(str(data['rules']['monthly_band_ratio'])).denominator
        for k in LEVELS:
            normalized = Fraction(str(verdict['objective'][k])).limit_denominator(denominator)
            assert normalized == Fraction(str(values[k]))
        return verdict['verdict'] == 'ACCEPT'
    assert check(answer['plan'], answer['levels'], 'baseline')
    before = deepcopy(answer['levels'])
    answer = improve_segments(data, answer, lambda p, v: check(p, v, 'neighbor'),
                              move_budget=move_budget, crew_moves=stage.startswith('S3b'),
                              combined_moves=stage.startswith('S3b'))
    assert tuple(answer['levels'].values()) <= tuple(before.values())
    assert check(answer['plan'], answer['levels'], 'final')
    _write(stem.with_suffix('.plan.json'), answer['plan'])
    answer['status'] = 'ACCEPT'
    answer['stats']['day_classes'] = _day_classes(data, answer)
    answer['stats']['including_judge_seconds'] = perf_counter() - tick
    if stage.startswith('S3b'):
        answer['stats']['beam_width_change'] = beam_width - 8
    else:
        answer['stats']['beam_and_candidate_count_change'] = 0
    print(f'candidate_source=input_only; stage={stage}; crew_moves_enabled={stage.startswith("S3b")}', flush=True)
    print('shift=' + json.dumps(answer['shift'], ensure_ascii=False), flush=True)
    print('stats=' + json.dumps(answer['stats'], ensure_ascii=False), flush=True)
    for row in answer['solver']:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if stage == 'S3b-R2':
        previous = _read(base / f'_out/T-31-S3b-R1-{label}.json')['levels']
        print('round1_comparison=' + json.dumps({'round1': previous, 'round2': answer['levels'],
            'not_worse': tuple(answer['levels'].values()) <= tuple(previous.values())}), flush=True)
        assert tuple(answer['levels'].values()) <= tuple(previous.values())
    if label == 'trial':
        previous = 'S3' if stage.startswith('S3b') else 'S2'
        old = _read(base / f'_out/T-31-{previous}-trial.json')['levels']
        print(previous + '_comparison=' + json.dumps({previous: old, stage: answer['levels'],
            'not_worse': tuple(answer['levels'].values()) <= tuple(old.values())}), flush=True)
        assert tuple(answer['levels'].values()) <= tuple(old.values())
    else:
        reference = Path(f'D:/APS/aps-core/cases/1d-annual-feedback/_out/T-28-R2-{label}.plan.json')
        verdict_path = stem.with_suffix('.reference.verdict.json')
        _run([sys.executable, '-B', '-X', 'utf8', '-m', 'judge', str(input_path), str(reference), str(verdict_path)])
        verdict = _read(verdict_path)
        assert verdict['verdict'] == 'ACCEPT'
        answer['reference_levels'] = {k: verdict['objective'][k] for k in LEVELS}
        for k in LEVELS:
            a, b = answer['levels'][k], verdict['objective'][k]
            print(f'COMPARE {label} {k}: {stage}={a}; T-28-R2={b}; ' + ('持平' if a == b else '更好' if a < b else '较差'), flush=True)
        answer['reference_not_worse'] = tuple(answer['levels'].values()) <= tuple(answer['reference_levels'].values())
        print(f'reference_not_worse={answer["reference_not_worse"]}', flush=True)
        if stage == 'S3b-R2':
            assert answer['reference_not_worse']
        old_plan = _read(reference)
        differences = []
        for month in answer['flow']['monthly_fok']:
            for m, info in data['factory']['models'].items():
                old_rows = [r for r in old_plan['days'] if r['date'][:7] == month]
                new_rows = [r for r in answer['plan']['days'] if r['date'][:7] == month]
                def numbers(rows):
                    return {'fok': sum(r['fok'].get(m, 0) for r in rows),
                        'crew_days': sum(any(sum(r['workshops'][info['line']][k].values()) for k in ('in', 'out')) for r in rows),
                        'weld_in': sum(r['workshops'][info['line']]['in'].get(m, 0) for r in rows)}
                a, b = numbers(new_rows), numbers(old_rows)
                if a != b:
                    differences.append({'month': month, 'model': m, stage: a, 'reference': b})
        answer['reference_differences'] = differences
        print('reference_differences=' + json.dumps(differences, ensure_ascii=False), flush=True)
    print('monthly_fok=' + json.dumps(answer['flow']['monthly_fok']), flush=True)
    print('full_replay_and_judge_levels_equal=True', flush=True)
    _write(stem.with_suffix('.timing.json'), {'stats': answer['stats'], 'solver': answer['solver']})
    for k in list(answer['stats']):
        if k.endswith('_seconds'):
            answer['stats'].pop(k)
    for row in answer['solver']:
        row.pop('seconds')
    _write(stem.with_suffix('.json'), answer)


def s3_differences(stage='S3'):
    for label in ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'):
        base = Path('cases/1d-annual-feedback')
        a = _read(base / f'_out/T-31-{stage}-{label}.json')
        data = _read(base / f'feedback-{label}.input.json')
        reference = _read(Path(f'D:/APS/aps-core/cases/1d-annual-feedback/_out/T-28-R2-{label}.plan.json'))
        ratio = Fraction(str(data['rules']['monthly_band_ratio']))
        def bands(plan):
            done = dict.fromkeys(data['factory']['models'], 0)
            result = {}
            for i, row in enumerate(plan['days']):
                for m in done:
                    done[m] += row['fok'].get(m, 0)
                mo = row['date'][:7]
                if i + 1 == len(plan['days']) or plan['days'][i + 1]['date'][:7] != mo:
                    for m in done:
                        pr = data['demand']['PR'][m]
                        lower = sum(q for d, q in pr.items() if d <= mo) - ratio * pr[mo]
                        result[mo, m] = (done[m], float(max(0, lower - done[m])))
            return result
        current, old = bands(a['plan']), bands(reference)
        band_differences = [{'month': mo, 'model': m, 'cum_fok': current[mo, m][0],
            'reference_cum_fok': old[mo, m][0], 'shortfall': current[mo, m][1],
            'reference_shortfall': old[mo, m][1], 'delta': current[mo, m][1] - old[mo, m][1]}
            for mo, m in current if current[mo, m][1] != old[mo, m][1]]
        # 由固定班组窗口和 C2/§5 的清线零投入得到投入上界，非模板估产。
        settings = _settings(data, a['modes'])
        crew_bounds = []
        for m, info in data['factory']['models'].items():
            slots = []
            for s in a['segments']:
                if s['model'] != m:
                    continue
                end = s['tail'].get('clear_start', s['next_start'])
                slots.extend(d for d in settings if s['start'] <= d < end and d[:7] == s['start'][:7]
                             and settings[d]['caps'][info['line']])
            input_cap = sum(settings[d]['caps'][info['line']] for d in slots)
            initial = sum(v.get(m, 0) for v in data['initial']['wip'].values())
            crew_bounds.append({'model': m, 'input_slots': len(slots), 'input_capacity_bound': input_cap,
                'initial_wip': initial, 'fok_optimistic_bound': input_cap + initial,
                'actual_fok': sum(r['fok'][m] for r in a['plan']['days']),
                'actual_weld_in': sum(r['workshops'][info['line']]['in'].get(m, 0) for r in a['plan']['days'])})
        print(label + ': ' + json.dumps({stage: a['levels'], 'reference': a['reference_levels'],
            'band_differences': band_differences, 'crew_bounds': crew_bounds,
            'monthly_differences': a['reference_differences']}, ensure_ascii=False), flush=True)


def s3_timing(stage='S3'):
    for label in ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps', 'trial'):
        base = Path('cases/t30-trial' if label == 'trial' else 'cases/1d-annual-feedback')
        stats = _read(base / f'_out/T-31-{stage}-{label}.timing.json')['stats']
        print(json.dumps({'label': label, **stats,
            'within_budget': stats['including_judge_seconds'] <= (120 if label == 'trial' else 60)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acceptance", choices=("S1-1", "S1-2", "S1-3", "S1-4", 'S2-1', 'S2-2', 'S2-3', 'S2-4',
                                             'S3-1', 'S3-2', 'S3-3', 'S3-4', 'S3-5',
                                             'S3b-1', 'S3b-2', 'S3b-3', 'S3b-4',
                                             'S3b-R2-1', 'S3b-R2-2', 'S3b-R2-3', 'S3b-R2-4'))
    parser.add_argument('--repeat-only', action='store_true')
    parser.add_argument('--label', choices=('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'))
    parser.add_argument('--beam-width', type=int, default=8)
    parser.add_argument('--move-budget', type=int, default=512)
    args = parser.parse_args()
    {"S1-1": lambda: s1_replay("pass"), "S1-2": lambda: s1_replay("trial"),
     "S1-3": lambda: s1_determinism(args.repeat_only), "S1-4": s1_fast,
     'S2-1': s2_regression, 'S2-2': lambda: [s2_solve(label, args.beam_width) for label in (
         (args.label,) if args.label else ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'))],
     'S2-3': lambda: s2_solve('trial', args.beam_width), 'S2-4': s2_stats,
     'S3-1': lambda: [s3_solve(label, args.beam_width, args.move_budget) for label in (
         (args.label,) if args.label else ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'))],
     'S3-2': s3_differences, 'S3-3': lambda: s3_solve('trial', args.beam_width, args.move_budget),
     'S3-4': s3_timing, 'S3-5': lambda: s2_regression('S3'),
     'S3b-1': lambda: ([s3_solve(label, args.beam_width, args.move_budget, 'S3b') for label in (
         (args.label,) if args.label else ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'))],
         s3_differences('S3b') if not args.label else None),
     'S3b-2': lambda: s3_solve('trial', args.beam_width, args.move_budget, 'S3b'),
     'S3b-3': lambda: s3_timing('S3b'),
     'S3b-4': lambda: (s2_regression('S3b'), _run([
         sys.executable, '-B', '-X', 'utf8', '-m', 'judge.selftest'])),
     'S3b-R2-1': lambda: ([s3_solve(label, args.beam_width, args.move_budget, 'S3b-R2') for label in (
         (args.label,) if args.label else ('pass', 'gap', 'gap-sat', 'pass-caps', 'gap-caps'))],
         s3_differences('S3b-R2') if not args.label else None),
     'S3b-R2-2': lambda: s3_solve('trial', args.beam_width, args.move_budget, 'S3b-R2'),
     'S3b-R2-3': lambda: s3_timing('S3b-R2'),
     'S3b-R2-4': lambda: (s2_regression('S3b-R2'), _run([
         sys.executable, '-B', '-X', 'utf8', '-m', 'judge.selftest']))}[args.acceptance]()
