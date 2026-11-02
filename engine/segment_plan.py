"""T-31 精确模板片段、受限年度候选图及产品段级路线。"""
import argparse
from copy import deepcopy
from fractions import Fraction
import json
import subprocess
import sys
from pathlib import Path
from datetime import date, timedelta
from math import ceil, floor
from itertools import chain
from time import perf_counter
from ortools.sat.python import cp_model
from .conditions import prepare
from .monthly import prebuild, prebuild_findings
from .stop_plan import predict_stop
from .segments import (initial_state, replay_template, expand_segments, prepare_fast,
                       _schedule, _days, _resume, needs_clear, _level_settings, _settings)

LEVELS = ("L1a", "L1b", "L1c", "L2", "L3a", "L3b")


def solve_product(data, input_path, output_path):
    """S4：预检、独立搜索、全部挪移及命令行判定使用同一路线。"""
    from .model import result

    days = _days(data['horizon']['start'], data['horizon']['end'])
    errors, *_ = prepare(data, days)
    if errors:
        return result('INPUT_INVALID', errors)
    answer = solve_segments(data)
    print('segment_search_stats=' + json.dumps(answer['stats'], ensure_ascii=False), flush=True)
    if 'plan' not in answer:
        month = answer.get('blocked_month', '')
        return result('UNKNOWN', [f'没有排出计划：{month} 月找不到同时满足全部规则的安排。请检查该月及前后月份的产能、停线和目标在制设置。',
                                  *answer['findings']])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path = output_path.with_name(output_path.stem + '.segment-candidate.plan.json')
    verdict_path = output_path.with_name(output_path.stem + '.segment-candidate.verdict.json')
    denominator = Fraction(str(data['rules']['monthly_band_ratio'])).denominator

    def check(plan, values):
        candidate_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'judge',
                        str(input_path), str(candidate_path), str(verdict_path)], check=True)
        verdict = json.loads(verdict_path.read_text(encoding='utf-8'))
        if verdict['verdict'] != 'ACCEPT':
            return verdict
        assert all(Fraction(str(verdict['objective'][k])).limit_denominator(denominator)
                   == Fraction(str(values[k])) for k in LEVELS)
        return verdict

    verdict = check(answer['plan'], answer['levels'])
    if verdict['verdict'] != 'ACCEPT':
        return result('EXECUTION_ERROR', ['段级排产结果没有通过复核（程序内部错误），请打包反馈给维护人员。',
            *[f"{e['rule']}，{e['date']}：{e['detail']}" for e in verdict['hard_errors']]])
    answer = improve_segments(data, answer,
        lambda plan, values: check(plan, values)['verdict'] == 'ACCEPT',
        crew_moves=True, combined_moves=True)
    print(f"segment_shift_seconds={answer['stats']['shift_seconds']:.6f}; attempts={answer['shift']['attempts']}", flush=True)
    plan = answer['plan']
    verdict = check(plan, answer['levels'])
    assert verdict['verdict'] == 'ACCEPT'
    plan['status'] = 'FEASIBLE'
    plan['objective']['levels'] = [
        {'level': k, 'value': float(Fraction(str(verdict['objective'][k])).limit_denominator(denominator))
         if k == 'L1c' else verdict['objective'][k], 'proven_optimal': False}
        for k in (*LEVELS, 'L4', 'L5', 'L6')]
    from .model import refine_segment
    refined = refine_segment(data, plan)
    if refined is not plan:
        refined_verdict = check(refined, answer['levels'])
        if refined_verdict['verdict'] == 'ACCEPT':
            plan = refined
        else:
            plan['findings'].append('库存细调结果未通过复核，已沿用段级排产结果；缺口、换型、加班等主要结果不受影响。')
    return plan


def measure(data, replay):
    """IO_CONTRACT §5：FOK、欠交、真实事件和用量均来自同一回放。"""
    done = {m: 0 for m in data["factory"]["models"]}
    ratio = Fraction(str(data["rules"]["monthly_band_ratio"]))
    band, backlog = Fraction(0), 0
    for i, row in enumerate(replay["days"]):
        for m in done:
            done[m] += row["fok"][m]
            backlog += row["bl"][m]
        month = row["date"][:7]
        if i + 1 == len(replay["days"]) or replay["days"][i + 1]["date"][:7] != month:
            for m in done:
                pr = data["demand"]["PR"][m]
                band += max(0, sum(v for mo, v in pr.items() if mo <= month) - ratio * pr[month] - done[m])
    return dict(zip(LEVELS, (sum(max(0, sum(data["demand"]["PR"][m].values()) - done[m]) for m in done),
        backlog, float(band), sum(e["type"] in ("CHANGEOVER", "BS_CLEAR") for e in replay["events"]),
        replay["L3a"], replay["L3b"])))


def replay_segments(data, segments, *, fast_table=None):
    modes = {d: dict(v) for s in segments for d, v in s.get("modes", {}).items()}
    flow = replay_template(data, initial_state(data), data["horizon"]["start"],
        data["horizon"]["end"], modes, segments, prepared=fast_table, fast=fast_table is not None)
    plan = expand_segments(data, segments, replay=flow)
    values = measure(data, flow)
    plan["objective"]["levels"] = [{"level": k, "value": v, "proven_optimal": False} for k, v in values.items()]
    ledger = []
    for index, s in enumerate(segments):
        rows = [r for r in flow["days"] if r["segment"] == index]
        ledger.append({"model": s["model"], "start": s["start"], "end": s["end"],
            "months": {mo: {"fok": {m: sum(r["fok"][m] for r in rows if r["date"][:7] == mo)
                for m in data["factory"]["models"]},
                "water": [{"date": r["date"], "bod": r["bod"], "eod": r["eod"]} for r in rows if r["date"][:7] == mo]}
                for mo in sorted({r["date"][:7] for r in rows})}})
    return {"segments": deepcopy(segments), "levels": values, "ledger": ledger,
            "flow": flow, "plan": plan, "scope": "fixed_chain_replay"}


def _limits(data, month, early=None):
    ratio = Fraction(str(data['rules']['monthly_band_ratio']))
    early = prebuild(data) if early is None else early
    result = {}
    for m, pr in data['demand']['PR'].items():
        months = sorted(pr)
        pos = months.index(month)
        total = sum(v for mo, v in pr.items() if mo <= month)
        following = pr[months[pos + 1]] if pos + 1 < len(months) else 0
        result[m] = (total, floor(total + max(ratio * following, early[m][month])))
    return result


def _stop_dates(data, schedule, first, last):
    """第 5 轮：按输入停线顺序记录真实停前日，供 L1a–L1c 相同时择晚。"""
    dates = []
    for stop in sorted((c for c in data['conditions'] if c['type'] == 'SHUTDOWN'
            and set(c.get('workshops', data['factory']['workshops']))
            == set(data['factory']['workshops'])), key=lambda c: (c['start'], c['end'])):
        matches = [date.fromisoformat(d).toordinal() for d, c in schedule.items()
            if first <= d <= last and 'pre_stop' in c and d < stop['start']
            and (date.fromisoformat(d) + timedelta(days=c['stop_length'])).isoformat() >= stop['end']]
        dates.append(max(matches, default=0))
    return tuple(dates)


def _selection_key(data, answer):
    levels = answer['levels']
    stops = _stop_dates(data, answer['schedule'], data['horizon']['start'], data['horizon']['end'])
    return (*[levels[k] for k in LEVELS[:3]], tuple(-d for d in stops),
            *[levels[k] for k in LEVELS[3:]])


def _tables(data, early=None):
    """C3：只枚举输入已经授权的加班/周六开关。"""
    calendar = {r['date']: r['is_working_capable'] for r in data['calendar']}
    days = _days(data['horizon']['start'], data['horizon']['end'])
    has_ot = any(c['type'] == 'MODE_AUTH' for c in data['conditions'])
    has_sat = any(c['type'] == 'SATURDAY_AUTH' for c in data['conditions'])
    early = prebuild(data) if early is None else early
    result = []
    for overtime in range(1 + has_ot):
        for saturday in range(1 + has_sat):
            modes = {}
            for d in days:
                modes[d] = {}
                for c in sorted((c for c in data['conditions'] if c['type'] == 'MODE_AUTH'),
                                key=lambda c: (data['factory']['modes'][c['mode']], c['mode'])):
                    if overtime and c['start'] <= d <= c['end']:
                        modes[d].update({w: c['mode'] for w in c['workshops']})
                if not calendar[d] and not saturday:
                    modes[d].update({w: 'OFF' for w in data['factory']['workshops']})
            table = prepare_fast(data, [{'modes': modes}])
            table['prebuild'] = early
            table['switches'] = {'overtime': bool(overtime), 'saturday': bool(saturday)}
            result.append(table)
            # C6/C13/C17、§5 期初补线：下游超目标在制先流动一天，
            # 上游暂不开工；其后仍按原模板满产补满。这是另一份显式
            # 启动候选，不能用缩短月末生产来替代它的水位和流量。
            stock = initial_state(data)['stock']
            target = data['wip_targets']
            if (sum(stock['AS_FIN'].values()) > target['AS_FIN'] and any(
                    sum(stock[n].values()) < target[n] for n in ('WBS', 'PS'))):
                first = next(d for d in days if table['settings'][d]['caps']['AS_FIN'])
                delayed = deepcopy(modes)
                delayed[first].update({w: 'OFF' for w in (
                    *[v['line'] for v in data['factory']['models'].values()], 'PS')})
                alternate = prepare_fast(data, [{'modes': delayed}])
                alternate['prebuild'] = early
                alternate['switches'] = dict(table['switches'], initial_downstream=True)
                result.append(alternate)
    # C3、C14、§6 L3：授权是逐日选择，不能把“允许整月加班”当
    # “整月都用”。单车型稳态的月度需求断点给出最少加班日候选；
    # 产量、尾差、停线仍交同一模板精算，不以理论值代替真实流量。
    if len(data['factory']['models']) == 1 and has_ot:
        m, info = next(iter(data['factory']['models'].items()))
        stock = initial_state(data)['stock']
        for base in list(result):
            if base['switches']['overtime'] or base['switches'].get('initial_downstream'):
                continue
            high = next(t for t in result if t['switches']['overtime']
                        and t['switches']['saturday'] == base['switches']['saturday'])
            mixed = deepcopy(base['modes'])
            for month, demand in data['demand']['PR'][m].items():
                demand += early[m][month]
                previous = [mo for mo in data['demand']['PR'][m] if mo < month]
                if previous:
                    demand -= early[m][max(previous)]
                local = [d for d in days if d[:7] == month]
                total = sum(base['rates'][m][d] for d in local)
                if month == days[0][:7]:
                    total -= sum(max(0, data['wip_targets'][n] - sum(stock[n].values()))
                                 for n in (info['line'], 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN'))
                for d in local:
                    extra = high['rates'][m][d] - base['rates'][m][d]
                    if total >= demand or extra <= 0:
                        continue
                    mixed[d] = dict(high['modes'][d])
                    total += extra
            if mixed not in [t['modes'] for t in result]:
                table = prepare_fast(data, [{'modes': mixed}])
                table['prebuild'] = early
                table['switches'] = {**base['switches'], 'overtime': True, 'partial_overtime': True}
                result.append(table)
    return result


def _month_controls(data, entry, month, first, last, table, *, two_switches=False, not_before=None,
                    stop_search='all', forecast_stops=None, fallback_stops=()):
    """§8/§9：从输入和可达入口生成端点，未读取任何参考计划。

    一个月至多两次换型为本轮有限候选域，不是业务段数约束；月界保留
    物理状态、FIFO 和阶段记忆。所有可用日期都可作为换型端点。
    """
    settings = table['settings']
    models = list(data['factory']['models'])
    start = max(first, not_before or first)
    work = [d for d in settings if start <= d <= last and any(
        settings[d]['caps'][v['line']] for v in data['factory']['models'].values())]
    current = entry['current_model'] or max(models, key=lambda m: sum(entry['stock'][n][m] for n in entry['stock']))
    following = next((d for d in settings if d > last and any(
        settings[d]['caps'][v['line']] for v in data['factory']['models'].values())), _resume(data))
    limits = _limits(data, month, table['prebuild'])
    idle_end = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
    base = {'model': current, 'start': start if work else first,
            'end': work[-1] if work else idle_end,
            'stop_points': {month: {'date': work[-1] if work else idle_end}},
            'tail': {'type': 'PLAN_END'}, 'next_start': max(following, not_before or following),
            'retain_water': False}
    pending_stop = next((p for p in entry['pending_phases'] if p['type'] == 'STOP_DRAIN'), None)
    if pending_stop is not None:
        if stop_search == 'fallback':
            return
        overrides = {d: modes for v in pending_stop['tail'].get('level_drains', {}).values()
                     for d, modes in v['modes'].items()}
        if any({**settings[d]['modes'], **overrides.get(d, {})} != modes
               for d, modes in pending_stop['modes'].items()
               if first <= d <= pending_stop['end']):
            return
        carried = deepcopy(base)
        carried['model'] = pending_stop['model']
        carried['tail'] = deepcopy(pending_stop['tail'])
        carried['start'] = first
        carried['end'] = min(last, pending_stop['end'])
        carried['stop_points'][month] = {'date': carried['end']}
        carried['next_start'] = pending_stop['tail']['stop_window']['restart']
        yield [carried]
        return
    # §5/rev 200/205：自建空闲接上全线 SHUTDOWN；停前日、准备日均可在前月。
    # TODO(边界): 日历假期形成的停线仍按原同月模板，不扩展跨月清线候选。
    stops = [c for c in sorted(data['conditions'], key=lambda c: c.get('start', ''))
             if c['type'] == 'SHUTDOWN' and start <= last and c['start'] > start
             and set(c.get('workshops', data['factory']['workshops']))
             == set(data['factory']['workshops'])]
    for stop in stops:
        pre = next((d for d in reversed(settings) if d < stop['start'] and settings[d]['caps']['PS']), None)
        restart = next((d for d in settings if d > stop['end'] and any(
            settings[d]['caps'][v['line']] for v in data['factory']['models'].values())), _resume(data))
        length = (date.fromisoformat(restart) - date.fromisoformat(pre)).days - 1 if pre else 0
        if pre is not None and length >= data['rules']['ps_stop_min_days']:
            line = data['factory']['models'][current]['line']
            prediction = predict_stop(data, entry, start, pre, restart, table,
                {mo: _limits(data, mo, table['prebuild'])
                 for mo in {d[:7] for d in settings if start <= d <= pre}})
            if prediction is None:
                continue  # 第 7 轮：无关月份不预判，也不进入提前停线的完整枚举。
            forecast = None
            stop_key = (stop['start'], table['band']) if stop_search != 'all' else None
            if stop_search == 'forecast':
                forecast = prediction
                forecast_stops.add(stop_key)
            before_days = (forecast['before'] if forecast is not None else
                [pre] if settings[pre]['manual'] is not None else
                reversed([d for d in settings if start <= d <= pre
                          and settings[d]['caps']['PS'] and settings[d]['caps'][line]]))
            if stop_search == 'fallback' and stop_key not in fallback_stops:
                before_days = ()
            for before in before_days:
                length = (date.fromisoformat(restart) - date.fromisoformat(before)).days - 1
                clear = needs_clear(data, current, settings, before, length)
                if not clear and forecast is None:
                    continue
                anticipated = deepcopy(base)
                anticipated['end'] = min(before, last)
                anticipated['stop_points'][month] = {'date': min(before, last)}
                anticipated['next_start'] = restart
                anticipated['tail']['stop_window'] = {'pre_stop': before, 'restart': restart}
                if forecast is None:
                    yield [anticipated]
                else:
                    anticipated['tail']['stop_forecast'] = {
                        'stop': stop['start'], 'starts': forecast['starts'][before]}
                    if not clear:
                        yield [anticipated]
                preparations = (forecast['preparations'][before] if forecast is not None else
                    reversed([d for d in work if d <= before and settings[d]['caps'][line]]))
                for prep in preparations:
                    earlier = deepcopy(anticipated)
                    earlier['tail']['preparation_date'] = prep
                    yield [earlier]
    if stop_search == 'fallback':
        return
    # C10/C13、§5 期首停线：需求在日初已完成，可以整月不启动。
    if all(entry['fok'][m] >= total for m, (total, _) in limits.items()):
        idle = deepcopy(base)
        idle['end'] = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
        idle['stop_points'][month] = {'date': idle['end']}
        yield [idle]
    def hold_shapes(m):
        if not work or not all(data['factory']['buffers'][n]['cap_max'] > data['wip_targets'][n] for n in ('WBS', 'PBS')):
            return ()
        line = data['factory']['models'][m]['line']
        # C15 rev 202：下游能力富余且无真实受限来源时只生成不蓄车模板。
        # 可能受限的候选仍由 _step 按实际 BOD/EOD、流量及指定产量逐日核对。
        if not any(
                any(w in settings[x]['fixed'] for w in (line, 'PS', 'AS_MAIN', 'AS_FIN'))
                or settings[x]['caps'][line] >= min(settings[x]['caps'][w]
                    for w in ('PS', 'AS_MAIN', 'AS_FIN')) > 0
                or 'cap_max' in data['factory']['workshops']['AS_FIN']
                or any(sum(entry['stock'][w].values()) > settings[x]['targets'][w]
                    for w in ('PS', 'AS_MAIN', 'AS_FIN'))
                for x in work):
            return ()
        result = [True]
        d = work[-1]
        minimum = settings[d]['caps']['PS'] - settings[d]['targets'][line] + 1
        length = (date.fromisoformat(following) - date.fromisoformat(d)).days - 1
        if (settings[d]['targets']['WBS'] < minimum < data['factory']['buffers']['WBS']['cap_max']
                and length >= data['rules']['ps_stop_min_days'] and needs_clear(data, m, settings, d, length)):
            result.append('minimal_wbs')
        return result
    yield [base]
    line = data['factory']['models'][current]['line']
    if any(first <= d <= last and (any(w in settings[d]['fixed'] for w in (line, 'PS'))
            or not settings[d]['caps'][line] and settings[d]['caps']['PS']) for d in settings):
        buffered = deepcopy(base)
        buffered['anticipate_buffers'] = True
        yield [buffered]
    for shape in hold_shapes(current):
        # §8/§10：真实水位超过目标才进入非正常模板，不因填写上限改日分类。
        hold = deepcopy(base)
        hold['tail']['hold_buffers'] = shape
        yield [hold]
    for other in models:
        # C12 允许预排下一月带内的量；旧车型需求不再增长时，
        # 提前清旧线并接新线，用 C16 的顺接流动消化旧车型在制。
        # 仍按 §5 换型生成端点、尾差和补满，不采用车型退出豁免。
        closing = not any(q for mo, q in data['demand']['PR'][current].items() if mo > month)
        if other == current or (limits[other][1] if closing else limits[other][0]) <= entry['fok'][other]:
            continue
        line = data['factory']['models'][current]['line']
        for pos in range(1, len(work)):
            # C3/C4、§5 换型：清旧线只占用旧线实际可生产的日期。
            old_work = [d for d in work[:pos] if settings[d]['caps'][line]]
            if not old_work:
                continue
            before = old_work[-1]
            count = ceil(Fraction(settings[before]['targets'][line], settings[before]['caps'][line]))
            if len(old_work) < count:
                continue
            clear = old_work[-count] if count else before
            a = deepcopy(base)
            a.update(end=clear, next_start=work[pos], tail={'type': 'CHANGEOVER', 'clear_start': clear})
            b = deepcopy(base)
            b.update(model=other, start=work[pos])
            yield [a, b]
            for shape in hold_shapes(other):
                held = deepcopy(b)
                held['tail']['hold_buffers'] = shape
                yield [a, held]
            if not two_switches:
                continue
            # §5 换型/B13、C16：第二次清线只能接在新线和全链补满后。
            try:
                prefix, _ = _run_fragment(data, entry, first, last, [a, b], table)
            except ValueError:
                # T-37：枚举器的前缀展开不在调用方 try 内；失败只淘汰此换型日期。
                continue
            ready = next((r['date'] for r in prefix['days'] if r['date'] >= b['start']
                and all(sum(r['eod'][n].values()) >= settings[r['date']]['targets'][n]
                        for n in (data['factory']['models'][other]['line'], 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN'))
                and not any(p in r['phase'] for p in ('REFILL', 'FIRST_START', 'CHANGEOVER'))), None)
            if ready is None:
                continue
            other_line = data['factory']['models'][other]['line']
            for back in range(pos + 1, len(work)):
                other_work = [d for d in work[pos:back] if settings[d]['caps'][other_line]]
                if not other_work:
                    continue
                before_back = other_work[-1]
                clear_days = ceil(Fraction(settings[before_back]['targets'][other_line], settings[before_back]['caps'][other_line]))
                if len(other_work) < clear_days:
                    continue
                clear_day = other_work[-clear_days] if clear_days else before_back
                if clear_day <= work[pos] or clear_day <= ready:
                    continue
                middle = deepcopy(b)
                middle.update(end=clear_day, next_start=work[back],
                              tail={'type': 'CHANGEOVER', 'clear_start': clear_day})
                final = deepcopy(base)
                final['start'] = work[back]
                yield [a, middle, final]


def _run_fragment(data, entry, first, last, controls, table):
    schedule = _schedule(data, controls, table['settings'], level_days=table['stop_days'])
    authorization = table.get('level_authorization')
    if any('stop_forecast' in c['tail'] for c in controls) and authorization is None:
        days = list(table['settings'])
        _, _, allowed, hours, *_ = prepare(data, days)
        authorization = {d: {w: max(allowed[w, i], key=lambda k: (hours[w, i][k], k))
            for w in ('AS_MAIN', 'AS_FIN')} for i, d in enumerate(days)}
    for d, c in schedule.items():
        if ('pre_stop' in c and c['kind'] != 'BS_CLEAR'
                and 'stop_forecast' in controls[c['segment']]['tail']
                and controls[c['segment']]['tail']['stop_window']['pre_stop'] == d):
            # 无 BS 清线沿用只在停前日降库的模板，预判只选择该日的最高授权总装班制。
            c['level_modes'] = {w: authorization[d][w] for w in ('AS_MAIN', 'AS_FIN')
                                if w in c['stop_levels'] and table['settings'][d]['caps'][w]}
    final = max([last, *[c['tail']['stop_window']['pre_stop'] for c in controls
                        if 'stop_window' in c['tail']]])
    limits = {mo: _limits(data, mo, table['prebuild'])
              for mo in {d[:7] for d in table['settings'] if first <= d <= final}}
    # §5 rev 205：逐个停线窗口从晚到早找首个可精确到水位的降库起点。
    # 预演一直走到真实停前日；不能仅凭本月月底水位选中跨月候选。
    windows = [d for d, c in schedule.items() if c['kind'] == 'BS_CLEAR'
               and d == c['clear_end'] and any(n in c.get('stop_levels', {})
                                              for n in ('AS_MAIN', 'AS_FIN'))]
    for end in windows:
        c = schedule[end]
        index = c['segment']
        if end in controls[index]['tail'].get('level_drains', {}) or end < first:
            continue
        if len(data['factory']['models']) == 1:
            # C1/C12：稳态正常前缀的焊入量已不可撤回；即使准备日零投入，
            # 清到指定终态仍会超过上限时，不再枚举提前降库起点。
            line = data['factory']['models'][c['model']]['line']
            path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
            prefix = [d for d in schedule if first <= d < c['preparation_date']]
            steady = (all(sum(entry['stock'][n].values()) == table['settings'][first]['targets'][n]
                          for n in path)
                and all((schedule[d]['kind'] == 'IDLE' and not any(table['settings'][d]['caps'].values())
                    or schedule[d]['kind'] == 'NORMAL'
                    and not any(k in schedule[d] for k in ('pre_stop', 'hold', 'finish_limit', 'weld_input'))
                    and not table['settings'][d]['fixed']
                    and all(table['settings'][d]['caps'][line] <= table['settings'][d]['caps'][w]
                            for w in ('PS', 'AS_MAIN', 'AS_FIN')))
                    and all(table['settings'][d]['targets'][n] == table['settings'][first]['targets'][n]
                            for n in path) for d in prefix))
            final_water = {**table['settings'][end]['targets'], **c['drain_levels'], line: 0, 'WBS': 0}
            least = (entry['fok'][c['model']] + sum(entry['stock'][n][c['model']] for n in path)
                + sum(table['rates'][c['model']][d] for d in prefix) - sum(final_water[n] for n in path))
            if steady and least > limits[end[:7]][c['model']][1]:
                raise ValueError(f'{end}：正常前缀加停前出清已超过月度带上限')
        if authorization is None:
            days = list(table['settings'])
            _, _, allowed, hours, *_ = prepare(data, days)
            authorization = {d: {w: max(allowed[w, i], key=lambda k: (hours[w, i][k], k))
                for w in ('AS_MAIN', 'AS_FIN')} for i, d in enumerate(days)}
        forecast = controls[index]['tail'].get('stop_forecast')
        if controls[index]['tail'].get('stop_window', {}).get('pre_stop') != end:
            forecast = None  # 同一片段内更早的停线仍按其自身原模板回放。
        if forecast is not None and not forecast['starts'] and c['stop_levels']:
            # 第 6 轮：不需提前降库时，仍按授权最高总装班制回放清线段。
            modes = {d: {w: authorization[d][w] for w in ('AS_MAIN', 'AS_FIN')
                         if w in c['stop_levels'] and table['settings'][d]['caps'][w]}
                     for d in table['settings'] if c['clear_start'] <= d <= end}
            controls[index]['tail'].setdefault('level_drains', {})[end] = {
                'start': c['clear_start'], 'modes': modes}
            schedule = _schedule(data, controls, table['settings'], level_days=table['stop_days'])
        if forecast is None or not forecast['starts']:
            try:
                probe = replay_template(data, entry, first, end, table['modes'], controls,
                                        prepared=table, fast=True, schedule=schedule, fok_limits=limits)
                if _applicable(data, entry, probe, schedule, table['settings'], table['prebuild']):
                    continue
            except ValueError:
                pass  # 原模板未到水位，转入本任务要求的提前降库候选。
        starts = [d for d, s in schedule.items() if first <= d < c['clear_start']
                  and s['segment'] == index and s['kind'] in ('NORMAL', 'PREPARE')
                  and any(table['settings'][d]['caps'][w] for w in ('AS_MAIN', 'AS_FIN')
                          if w in c['stop_levels'])]
        if forecast is not None:
            starts = [d for d in starts if d in forecast['starts']]
        chosen = None
        for start in reversed(starts):
            trial = deepcopy(controls)
            modes = {d: {w: authorization[d][w] for w in ('AS_MAIN', 'AS_FIN')
                         if w in c['stop_levels'] and table['settings'][d]['caps'][w]}
                     for d in table['settings'] if start <= d <= end}
            trial[index]['tail'].setdefault('level_drains', {})[end] = {'start': start, 'modes': modes}
            trial_schedule = _schedule(data, trial, table['settings'], level_days=table['stop_days'])
            try:
                probe = replay_template(data, entry, first, end, table['modes'], trial,
                                        prepared=table, fast=True, schedule=trial_schedule, fok_limits=limits)
            except ValueError:
                continue
            if _applicable(data, entry, probe, trial_schedule, table['settings'], table['prebuild']):
                chosen = trial, trial_schedule
                break
        if chosen is None:
            raise ValueError(f'{first}..{end}：未找到精确到人工停前水位的提前降库起点')
        controls[:], schedule = chosen
    for d in _days(first, last):
        if d not in schedule:
            schedule[d] = {'model': controls[0]['model'], 'segment': 0, 'kind': 'IDLE', 'retain_water': False}
    flow = replay_template(data, entry, first, last, table['modes'], controls,
                           prepared=table, fast=True, schedule=schedule)
    return flow, schedule


def _stop_options(data, entry, month, first, last, controls, table, flow):
    """§9/S3b：需求、窗口边界、月末及普通周末停点。"""
    yield controls
    segment = controls[-1]
    # 此候选的真实停前日已明确；月末不再另插一次停线。
    if 'stop_window' in segment['tail']:
        return
    m = segment['model']
    settings = table['settings']
    limits = _limits(data, month, table['prebuild'])[m]
    candidates = []
    work = [d for d in settings if segment['start'] <= d <= last
            and settings[d]['caps'][data['factory']['models'][m]['line']]]
    if work:
        candidates.append((work[-1], None))
        # 只留下至下个片段之间全为日历休息、且短于停线最短天数的窗。
        calendar = {r['date']: r['is_working_capable'] for r in data['calendar']}
        for d in work:
            rest = _days((date.fromisoformat(d) + timedelta(days=1)).isoformat(),
                         (date.fromisoformat(segment['next_start']) - timedelta(days=1)).isoformat())
            if rest and len(rest) < data['rules']['ps_stop_min_days'] and all(
                    not calendar.get(x, False) for x in rest):
                candidates.append((d, None))
    cumulative = entry['fok'][m]
    for row in flow['days']:
        before = cumulative
        cumulative += row['fok'][m]
        for goal in limits:
            if before < goal <= cumulative and row['date'] >= segment['start']:
                candidates.append((row['date'], None))
    following = segment['next_start']
    for window in (data['rules']['ps_stop_min_days'], data['factory']['models'][m]['glue_age_max']):
        cutoff = (date.fromisoformat(following) - timedelta(days=window)).isoformat()
        day = next((d for d in settings if max(cutoff, segment['start']) <= d <= last
                    and settings[d]['caps'][data['factory']['models'][m]['line']]), None)
        if day:
            candidates.append((day, None))
    used = set()
    for day, quantity in candidates:
        if day in used or day == segment['end']:
            continue
        used.add(day)
        copy = deepcopy(controls)
        copy[-1]['end'] = day
        copy[-1]['stop_points'][month] = {'date': day}
        yield copy


def _cap_candidate(data, entry, month, first, last, controls, table, flow, schedule, *, close_old=False, models=None):
    """C10/C12：选择最后正常日的明确尾差表项，再精确重算。

    不改变已算表项；超出一个尾差日的候选由其他端点覆盖。
    """
    limits = _limits(data, month, table['prebuild'])
    if close_old:
        limits = {m: (total, min(upper, sum(data['demand']['PR'][m].values())
                       - sum(node[m] for node in flow['exit']['stock'].values())))
                  for m, (total, upper) in limits.items()}
    controls = deepcopy(controls)
    for m, (_, upper) in limits.items():
        if models is not None and m not in models:
            continue
        excess = flow['exit']['fok'][m] - upper
        if excess <= 0:
            continue
        if any(c['model'] == m and 'stop_window' in c['tail'] for c in controls):
            # §5/C14：跨月段尾已固定准备日，不在它之前插入普通尾差；
            # 超上限交给其他准备日期，而非截断这次清线。
            return None
        days = [d for d, c in schedule.items() if first <= d <= last
                and c['model'] == m and c['kind'] == 'NORMAL'
                and table['settings'][d]['caps'][data['factory']['models'][m]['line']]]
        if not days:
            return None
        d = days[-1]
        capacity = min(table['settings'][d]['caps'][w] for w in (
            data['factory']['models'][m]['line'], 'PS', 'AS_MAIN', 'AS_FIN'))
        if excess > capacity:
            return None
        # 尾差量与模板 FOK 有水位/停前关系；在完整整数区间找最大的合法值。
        low, high, chosen = 0, capacity, None
        while low <= high:
            q = (low + high) // 2
            trial = deepcopy(controls)
            index = schedule[d]['segment']
            if 'hold' in schedule[d]:
                # C15 物理上限受限日可减量，保留后面的清线和人工停前日。
                trial[index].setdefault('tail_quantities', {})[d] = q
            else:
                # C14 普通尾差必须成为真实段末，不能在清线准备日前另插尾差。
                trial[index]['stop_points'][month] = {'date': d, 'quantity': q}
            f, s = _run_fragment(data, entry, first, last, trial, table)
            if f['exit']['fok'][m] <= upper:
                chosen = trial, f, s
                low = q + 1
            else:
                high = q - 1
        if chosen is None:
            return None
        controls, flow, schedule = chosen
    return controls, flow, schedule


def _applicable(data, entry, flow, schedule, settings, early=None):
    """候选适用条件：停前降库公式、C7 前缀、C10/C12 上限、C13 停点。"""
    settings = _level_settings(data, settings, schedule)
    # rev 200/205：只承认实际全厂零流、且接上已知全线 SHUTDOWN 的合并停线。
    stop_windows = [p['stop_window'] for p in entry['pending_phases']
                    if p['type'] == 'REFILL' and p.get('waiting') and 'stop_window' in p]
    stop_windows += [{'pre_stop': d, 'restart': (date.fromisoformat(d)
        + timedelta(days=c['stop_length'] + 1)).isoformat()}
        for d, c in schedule.items() if 'pre_stop' in c]
    stop_windows = [s for s in stop_windows if any(c['type'] == 'SHUTDOWN'
        and set(c.get('workshops', data['factory']['workshops'])) == set(data['factory']['workshops'])
        and s['pre_stop'] < c['start'] <= c['end'] < s['restart'] for c in data['conditions'])]
    # §5 rev 205：以实际连续低于正常目标的日末反推起点，不能凭候选标签免 C14。
    level_days, level_windows = {}, []
    for end, c in schedule.items():
        if 'pre_stop' not in c or not c.get('stop_levels'):
            continue
        rows = [r for r in flow['days'] if r['date'] <= end]
        clear = next((r['date'] for r in rows if 'BS_CLEAR' in r['phase']
                      and schedule[r['date']].get('clear_end') == end), c.get('clear_start', end))
        starts = {}
        for n, value in c['stop_levels'].items():
            start = end
            for r in reversed([r for r in rows if r['date'] < end]):
                if sum(r['eod'][n].values()) >= settings[r['date']]['targets'][n]:
                    break
                start = r['date']
            starts[n] = min(start, clear)
            for r in rows:
                if starts[n] <= r['date']:
                    level_days.setdefault(r['date'], {})[n] = value
        level_windows.append((end, clear, starts, c['stop_levels']))
    done = dict(entry['fok'])
    batches = deepcopy(entry['wbs_batches'])
    started = set(entry['started_models'])
    calendar = {r['date']: r['is_working_capable'] for r in data['calendar']}
    early = prebuild(data) if early is None else early
    limits = {mo: _limits(data, mo, early) for mo in {r['date'][:7] for r in flow['days']}}
    for row in flow['days']:
        d = row['date']
        c = schedule.get(d)
        if c is None:
            continue
        idle = not any(sum(v[k].values()) for v in row['workshops'].values() for k in ('in', 'out'))
        stopped = idle and any(s['pre_stop'] < d < s['restart'] for s in stop_windows)
        lowering = level_days.get(d, {})
        assembly_drain = set()
        if 'PBS' in lowering or 'AS_MAIN' in lowering:
            assembly_drain.add('AS_MAIN')
        if 'AS_FIN' in lowering or 'AS_MAIN' in assembly_drain:
            assembly_drain.add('AS_FIN')
        if 'pre_stop' in c and not any(sum(row['workshops']['PS'][k].values()) for k in ('in', 'out')):
            # §5：停前日是实际最后一个 PS 生产日，不能靠标签把零流日当停前日。
            return False
        if 'pre_stop' in c and sum(row['eod']['PS'].values()) != c['pre_stop']:
            return False
        if 'pre_stop' in c and any(sum(row['eod'][n].values()) != value
                                  for n, value in c.get('stop_levels', {}).items()):
            return False
        if c['kind'] == 'PREPARE' and 'BS_CLEAR' not in row['phase']:
            # §5 rev 205：减量投入日只有实际进入人工水位降库的节点可低于正常目标。
            if any(sum(row['eod'][n].values()) < settings[d]['targets'][n]
                   for n in ('PBS', 'AS_MAIN', 'AS_FIN') if n not in lowering):
                return False
        if c['kind'] == 'BS_CLEAR' and d == c['clear_end']:
            line = data['factory']['models'][c['model']]['line']
            final = {**settings[d]['targets'], **c.get('drain_levels', {}), line: 0, 'WBS': 0}
            if any(sum(row['eod'][n].values()) != final[n]
                   for n in (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')):
                return False
        # TODO(边界): 停前人工水位要求升库时不支持；无清线仅停前日降库，达不到即淘汰。
        levels = dict(lowering)
        if c['kind'] != 'PREPARE' or 'BS_CLEAR' in row['phase']:
            levels.update(c.get('drain_levels', {}))
        for n, value in levels.items():
            if not value <= sum(row['eod'][n].values()) <= sum(row['bod'][n].values()):
                return False
            if n in ('AS_MAIN', 'AS_FIN'):
                shop = row['workshops'][n]
                want = min(settings[d]['caps'][n], sum(row['bod'][n].values())
                           + sum(shop['in'].values()) - value)
                if sum(shop['out'].values()) != want:
                    return False
        # rev 205 / 第 4 轮：清线前主线投入按 PBS 实际可供量做尽，不按 C14 判满产。
        if 'AS_MAIN' in assembly_drain and any(d < clear and d <= end
                and any(starts.get(n, end) <= d for n in ('PBS', 'AS_MAIN') if n in values)
                for end, clear, starts, values in level_windows):
            shop = row['workshops']['AS_MAIN']
            cap = settings[d]['caps']['AS_MAIN'] if shop['mode'] != 'OFF' else 0
            keep = lowering.get('PBS', settings[d]['targets']['PBS'])
            want = min(cap, sum(row['bod']['PBS'].values())
                       + sum(row['workshops']['PS']['out'].values()) - keep)
            if sum(shop['in'].values()) != want:
                return False
        # C3：IDLE 也是候选的真实零流，不能越过指定产量固定点。
        if any(sum(row['workshops'][w]['out'].values()) != q
               for w, q in settings[d]['fixed'].items()):
            return False
        # C14/C15：中段固定点的减投必须有受限水位或真实段末依据。
        if c['kind'] == 'NORMAL' and settings[d]['fixed']:
            later = [r for r in flow['days'] if r['date'] > d and r['date'][:7] == d[:7]]
            downstream = {v['line']: 'WBS' for v in data['factory']['models'].values()}
            downstream.update(PS='PBS', AS_MAIN='AS_FIN')
            upstream = {'PS': 'WBS', 'AS_MAIN': 'PBS', 'AS_FIN': 'AS_MAIN'}
            for w, shop in row['workshops'].items():
                if w in assembly_drain:
                    continue  # §5 rev 205：总装由降库公式核对，焊装和 PS 仍按原口径。
                q = sum(shop['in'].values())
                if not 0 < q < settings[d]['caps'][w]:
                    continue
                if any(p in row['phase'] for p in ('REFILL', 'FIRST_START', 'CHANGEOVER')):
                    continue
                if not any(sum(r['workshops'][w][k].values()) for r in later for k in ('in', 'out')):
                    continue
                below = downstream.get(w)
                at_cap = False
                if below is not None:
                    eod = sum(row['eod'][below].values())
                    if below in data['factory']['buffers']:
                        at_cap = eod >= data['factory']['buffers'][below]['cap_max']
                    elif 'cap_max' in data['factory']['workshops'][below]:
                        at_cap = eod >= data['factory']['workshops'][below]['cap_max']
                    else:
                        # C6/C15 rev 202：(a) 超目标；(b) 自己满产；(c) 指定产量。
                        target = settings[d]['targets'][below]
                        shop_below = row['workshops'][below]
                        cap = settings[d]['caps'][below] if shop_below['mode'] != 'OFF' else 0
                        at_cap = (max(sum(row['bod'][below].values()), eod) > target
                            or eod >= target and (below in settings[d]['fixed']
                                or sum(shop_below['out'].values()) >= cap > 0))
                above = upstream.get(w)
                at_target = above is not None and sum(row['eod'][above].values()) == settings[d]['targets'][above]
                if not (at_cap or at_target):
                    return False
        # C13：另一线占班组须有当天真实流量；当前线清线不豁免闲置旧线。
        active = {m for m, info in data['factory']['models'].items() if any(
            sum(row['workshops'][info['line']][k].values()) for k in ('in', 'out'))}
        replenishing = any(p in row['phase'] for p in ('REFILL', 'FIRST_START', 'CHANGEOVER', 'INITIAL_DRAIN'))
        for m, info in data['factory']['models'].items():
            if (m in started and m not in active and not active and calendar[d]
                    and settings[d]['caps'][info['line']] and not replenishing
                    and not stopped
                    and not (m == c['model'] and 'BS_CLEAR' in row['phase'])
                    and done[m] < limits[d[:7]][m][0]):
                return False
            if sum(row['workshops'][info['line']]['in'].values()):
                started.add(m)
        if idle and calendar[d] and any(settings[d]['caps'].values()) and not replenishing and not stopped:
            if any(done[m] < total for m, (total, _) in limits[d[:7]].items() if m in started):
                return False
        for m, info in data['factory']['models'].items():
            q = row['workshops'][info['line']]['out'].get(m, 0)
            if q:
                batches.append({'date': d, 'model': m, 'quantity': q})
            used = row['workshops']['PS']['in'].get(m, 0)
            for b in batches:
                if b['model'] == m:
                    take = min(used, b['quantity'])
                    b['quantity'] -= take
                    used -= take
            done[m] += row['fok'][m]
        if any(done[m] > upper for m, (_, upper) in limits[d[:7]].items()):
            return False
        if any(b['quantity'] and (date.fromisoformat(d) - date.fromisoformat(b['date'])).days
               >= data['factory']['models'][b['model']]['glue_age_max'] for b in batches):
            return False
        batches = [b for b in batches if b['quantity']]
    # rev 205：各总装节点从自己的真实起点核对，不满后不得再满产，包含清线段。
    for end, clear, starts, values in level_windows:
        rows = [r for r in flow['days'] if r['date'] <= end]
        for w in ('AS_MAIN', 'AS_FIN'):
            if w not in values:
                continue
            partial = False
            for r in rows:
                if r['date'] < starts[w]:
                    continue
                shop = r['workshops'][w]
                cap = settings[r['date']]['caps'][w] if shop['mode'] != 'OFF' else 0
                out = sum(shop['out'].values())
                want = min(cap, sum(r['bod'][w].values()) + sum(shop['in'].values())
                           - values[w])
                if out != want or partial and out >= cap > 0:
                    return False
                partial = partial or out < cap
    return all(done[m] <= upper for m, (_, upper) in limits[flow['days'][-1]['date'][:7]].items())


def solve_segments(data, *, beam_width=8, deterministic_seconds=0.1):
    """C12：两种上限分域保留月度束，共用一次年度图比较。"""
    return _solve_segments(data, prebuild(data), beam_width=beam_width,
                           deterministic_seconds=deterministic_seconds)


def _solve_segments(data, early, *, beam_width=8, deterministic_seconds=0.1, _two_switch_months=()):
    """§8：精确可达片段图 + 六级年度路径选择，受限搜索。"""
    tick = perf_counter()
    tables = _tables(data, early)
    for table in tables:
        table['band'] = 'prebuild'
    if any(v for months in early.values() for v in months.values()):
        ordinary = {m: dict.fromkeys(months, 0) for m, months in early.items()}
        old_tables = _tables(data, ordinary)
        # 旧上限生成的部分加班班制也加入实际 E 域，不能只保留整月开关。
        for table in old_tables:
            physical = next((t for t in tables if t['modes'] == table['modes']), None)
            if physical is None:
                physical = {**table, 'prebuild': early, 'band': 'prebuild'}
                tables.append(physical)
            # 同一班制的两种上限复用已有精确事件表和准备日表，不重复计算日转移。
            table['events'] = physical['events']
            table['preparations'] = physical.setdefault('preparations', [])
            table['band'] = 'ordinary'
        tables.extend(old_tables)
    dates = _days(data['horizon']['start'], data['horizon']['end'])
    _, _, allowed, hours, *_ = prepare(data, dates)
    authorization = {d: {w: max(allowed[w, i], key=lambda k: (hours[w, i][k], k))
        for w in data['factory']['workshops']} for i, d in enumerate(dates)}
    default_settings, high_settings = _settings(data, {}), _settings(data, authorization)
    for table in tables:
        table['level_authorization'] = authorization
        table['stop_default'], table['stop_high'] = default_settings, high_settings
    months = sorted({d[:7] for d in dates})
    root = initial_state(data)
    empty_stops = _stop_dates(data, {}, dates[0], dates[-1])
    nodes = [{'state': root, 'cost': (0, Fraction(0), 0, 0, 0), 'parent': None,
              'stop_dates': empty_stops, 'ordinary': True}]
    frontier, edges, attempts, failures = [0], [], 0, []
    ordinary_frontier = {0}
    widened = []
    samples = []
    ratio = Fraction(str(data['rules']['monthly_band_ratio']))
    for month in months:
        local_days = [d for d in dates if d[:7] == month]
        first, last = local_days[0], local_days[-1]
        next_frontier = []
        forecast_stops, accepted_stops = set(), set()
        for stop_search in ('forecast', 'fallback'):
            fallback_stops = forecast_stops - accepted_stops
            if stop_search == 'fallback':
                if not fallback_stops:
                    break
                widened.extend(f'{d} 停线：预判范围内没有合法排法，已放宽搜索'
                               for d, _ in sorted(fallback_stops))
            for parent in frontier:
                entry = nodes[parent]['state']
                for table_index, table in enumerate(tables):
                    if table['band'] == 'ordinary' and parent not in ordinary_frontier:
                        continue
                    if table['switches'].get('initial_downstream') and month != months[0]:
                        continue
                    for base in _month_controls(data, entry, month, first, last, table,
                                               two_switches=month in _two_switch_months,
                                               not_before=nodes[parent].get('not_before'),
                                               stop_search=stop_search, forecast_stops=forecast_stops,
                                               fallback_stops=fallback_stops):
                        attempts += 1
                        try:
                            initial, initial_schedule = _run_fragment(data, entry, first, last, base, table)
                            for controls in _stop_options(data, entry, month, first, last, base, table, initial):
                                attempts += 1
                                flow, schedule = ((initial, initial_schedule) if controls is base else
                                    _run_fragment(data, entry, first, last, controls, table))
                                close_options = [False]
                                if any(sum(data['demand']['PR'][m].values())
                                       - sum(node[m] for node in flow['exit']['stock'].values()) < upper
                                       for m, (_, upper) in _limits(data, month, table['prebuild']).items()):
                                    close_options.append(True)
                                for close_old in close_options:
                                    capped = _cap_candidate(data, entry, month, first, last, controls, table, flow, schedule,
                                                            close_old=close_old)
                                    if capped is None:
                                        continue
                                    selected_controls, f, s = capped
                                    # §5：上月停前目标使用的复工日，必须与
                                    # 本月实际焊装复工日相接；不能换一张授权表
                                    # 后提前开工，把三天停线变成普通两天周末。
                                    restart = nodes[parent].get('not_before')
                                    if (restart is not None and entry['current_model'] is not None
                                            and not any(p['type'] == 'STOP_DRAIN' for p in entry['pending_phases'])):
                                        actual = next((r['date'] for r in f['days'] if any(
                                            sum(r['workshops'][v['line']][k].values())
                                            for v in data['factory']['models'].values() for k in ('in', 'out'))), None)
                                        if actual is not None and actual != restart:
                                            continue
                                    if not _applicable(data, entry, f, s, table['settings'], table['prebuild']):
                                        continue
                                    accepted_stops.update((c['tail']['stop_forecast']['stop'], table['band'])
                                        for c in selected_controls if 'stop_forecast' in c['tail'])
                                    # 第 9 轮：普通候选回放识别的 PS 停前日也计入对应停线，避免重复兜底。
                                    stop_windows = [{'pre_stop': e['date'], 'restart': (date.fromisoformat(e['date'])
                                        + timedelta(days=s[e['date']]['stop_length'] + 1)).isoformat()}
                                        for e in f['events'] if e['type'] == 'PS_PRE_STOP']
                                    # 上月已出清、当前等复工也是合法停线候选；不能因其他入口失败而误报放宽。
                                    stop_windows += [p['stop_window'] for p in entry['pending_phases']
                                        if p['type'] == 'REFILL' and p.get('waiting') and 'stop_window' in p]
                                    for window in stop_windows:
                                        accepted_stops.update((stop['start'], table['band'])
                                            for stop in data['conditions'] if stop['type'] == 'SHUTDOWN'
                                            and set(stop.get('workshops', data['factory']['workshops']))
                                                == set(data['factory']['workshops'])
                                            and window['pre_stop'] < stop['start'] <= stop['end'] < window['restart'])
                                    if month not in samples:
                                        full = replay_template(data, entry, first, last, table['modes'], selected_controls,
                                                               prepared=table, schedule=s)
                                        assert all(full[k] == f[k] for k in ('days', 'exit', 'events', 'monthly_fok', 'production', 'L3a', 'L3b'))
                                        samples.append(month)
                                    band = sum(max(0, Fraction(total) - ratio * data['demand']['PR'][m][month]
                                                   - f['exit']['fok'][m]) for m, (total, _) in _limits(data, month, early).items())
                                    increments = (sum(sum(r['bl'].values()) for r in f['days']), band,
                                        sum(e['type'] in ('CHANGEOVER', 'BS_CLEAR') for e in f['events']), f['L3a'], f['L3b'])
                                    cost = tuple(a + b for a, b in zip(nodes[parent]['cost'], increments))
                                    stop_dates = tuple(max(a, b) for a, b in zip(nodes[parent]['stop_dates'],
                                        _stop_dates(data, s, first, last)))
                                    preference = (cost[:2], tuple(-d for d in stop_dates), cost[2:])
                                    # 实测出现相同状态挤满束宽；只合并逐字段完全相等的标签。
                                    not_before = selected_controls[-1]['next_start']
                                    ordinary_path = parent in ordinary_frontier and table['band'] == 'ordinary'
                                    same = [n for n in next_frontier if nodes[n]['state'] == f['exit']
                                            and nodes[n]['not_before'] == not_before
                                            and nodes[n]['ordinary'] == ordinary_path]
                                    if any((nodes[n]['cost'][:2], tuple(-d for d in nodes[n]['stop_dates']),
                                            nodes[n]['cost'][2:]) <= preference for n in same):
                                        continue
                                    next_frontier = [n for n in next_frontier if n not in same]
                                    child = len(nodes)
                                    nodes.append({'state': f['exit'], 'cost': cost, 'parent': parent,
                                                  'not_before': not_before, 'stop_dates': stop_dates,
                                                  'ordinary': ordinary_path})
                                    edges.append({'from': parent, 'to': child, 'flow': f, 'schedule': s,
                                        'controls': selected_controls, 'table': table_index, 'cost': increments,
                                        'stop_dates': _stop_dates(data, s, first, last)})
                                    next_frontier.append(child)
                        except ValueError as exc:
                            # 模板情形未覆盖是显式拒绝候选，不把受限找不到当输入不可行。
                            failures.append(str(exc))
        ordinary_blocked = (any(t['band'] == 'ordinary' for t in tables)
            and any(nodes[n]['ordinary'] for n in frontier)
            and not any(nodes[n]['ordinary'] for n in next_frontier))
        if not next_frontier or ordinary_blocked:
            # C12/C16：给出入口中可直接复查的换型卡点，不把它当无解证明。
            for parent in frontier:
                state = nodes[parent]['state']
                for m, pr in data['demand']['PR'].items():
                    water = sum(v[m] for v in state['stock'].values())
                    upper = _limits(data, month, early)[m][1]
                    if (water and not any(q for mo, q in pr.items() if mo >= month)
                            and state['fok'][m] + water > upper):
                        failures.append(f"{month} 换型时 {m} 车型链上还有 {water} 台在制，"
                            f"累计已完成 {state['fok'][m]} 台，全部流出会超过累计需求带上限 {upper} 台。")
            # 按可达图的阻塞月份向前展开双换型候选，避免无关月份的日期对乘积。
            expand = next((mo for mo in reversed(months[:months.index(month) + 1])
                           if mo not in _two_switch_months), None)
            if expand is not None and len(data['factory']['models']) > 1:
                generation_seconds = perf_counter() - tick
                answer = _solve_segments(data, early, beam_width=beam_width,
                    deterministic_seconds=deterministic_seconds,
                    _two_switch_months=(*_two_switch_months, expand))
                answer['stats']['generation_seconds'] += generation_seconds
                notices = list(dict.fromkeys([*widened, *answer.get('stop_search_findings', [])]))
                answer['stop_search_findings'] = notices
                answer['findings'] = list(dict.fromkeys([*notices, *answer['findings']]))
                if 'plan' in answer:
                    answer['plan']['findings'] = list(dict.fromkeys([*answer['plan']['findings'], *notices]))
                return answer
            if not next_frontier:
                return {'status': 'UNKNOWN', 'scope': 'restricted_fragment_graph', 'segments': [],
                    'findings': list(dict.fromkeys([*widened, *failures])), 'blocked_month': month,
                    'blocked_entries': [nodes[n]['state'] for n in frontier],
                    'stats': {'attempts': attempts, 'candidates': len(edges), 'generation_seconds': perf_counter() - tick}}
        # 搜索宽度是计算预算；保留精确整数，不合并不同水位/FIFO/累计量。
        next_frontier.sort(key=lambda n: (-sum(nodes[n]['state']['fok'].values()),
            *nodes[n]['cost'][:2], tuple(-d for d in nodes[n]['stop_dates']), *nodes[n]['cost'][2:], n))
        # 第 7 轮：实际 E 不能占用 E=0 的束名额，两域各自保留原产量排序的前 beam_width 名。
        frontier = []
        next_ordinary = set()
        for pool in ([n for n in next_frontier if not nodes[n]['ordinary']],
                     [n for n in next_frontier if nodes[n]['ordinary']]):
            # C12 带上限/C16 后续可行性：需求不再增长的旧车型，保留
            # FOK + 链上余量不超过最终上限的一组，防止高 FOK 状态挤掉收线入口。
            closing = [m for m, pr in data['demand']['PR'].items()
                       if sum(pr.values()) and not any(q for mo, q in pr.items() if mo > month)
                       and any(q for other, demand in data['demand']['PR'].items() if other != m
                               for mo, q in demand.items() if mo > month)]
            groups = {}
            for n in pool:
                state = nodes[n]['state']
                key = tuple(state['fok'][m] + sum(v[m] for v in state['stock'].values())
                            <= sum(data['demand']['PR'][m].values()) for m in closing)
                if key and all(key):
                    groups.setdefault((key, state['current_model']), n)
            reserved = list(groups.values())
            # §5：高累计产量的正常月末不能挤掉已开始跨月清线的可达入口。
            draining = {}
            for n in pool:
                for pending in nodes[n]['state']['pending_phases']:
                    if pending['type'] == 'STOP_DRAIN':
                        draining.setdefault((pending['model'], pending['end']), n)
            # 第 5 轮：已经提前出清、正在等计划停线结束的入口也必须保留。
            for n in pool:
                for pending in nodes[n]['state']['pending_phases']:
                    if pending['type'] == 'REFILL' and pending.get('waiting') and 'stop_window' in pending:
                        draining.setdefault((pending['model'], pending['stop_window']['restart']), n)
            reserved = list(dict.fromkeys([*draining.values(), *reserved]))
            selected_beam = (reserved + [n for n in pool if n not in reserved])[:beam_width]
            next_ordinary.update(n for n in selected_beam if nodes[n]['ordinary'])
            # §6：达到当月需求后，多预排的 FOK 不能挤掉少加班的续接路线。
            # 原产量束完整保留；每域、每个在产车型另留一个按当月未完成需求、
            # 累计 L1b/L1c/L2/L3a/L3b 择优的入口，年度 L1a 仍由最终图比较。
            efficient = {}
            for n in sorted(pool, key=lambda n: (
                    sum(max(0, sum(q for mo, q in pr.items() if mo <= month)
                        - nodes[n]['state']['fok'][m]) for m, pr in data['demand']['PR'].items()),
                    *nodes[n]['cost'][:2], tuple(-d for d in nodes[n]['stop_dates']),
                    *nodes[n]['cost'][2:], -sum(nodes[n]['state']['fok'].values()), n)):
                if nodes[n]['state']['current_model'] is not None:
                    efficient.setdefault(nodes[n]['state']['current_model'], n)
            selected_beam.extend(n for n in efficient.values() if n not in selected_beam)
            frontier.extend(n for n in selected_beam if n not in frontier)
        # 额外少加班入口下一月可用实际 E，但不反过来挤占原 E=0 束的续接名额。
        ordinary_frontier = next_ordinary
        print(f"segment_month={month}; attempts={attempts}; candidates={len(edges)}; seconds={perf_counter() - tick:.6f}", flush=True)
    generation_seconds = perf_counter() - tick
    # 删去没有通往末层的边；节点编号和真实状态连接，不拼接不同入口的后缀。
    live = set(frontier)
    for e in reversed(edges):
        if e['to'] in live:
            live.add(e['from'])
    edges = [e for e in edges if e['to'] in live]
    model = cp_model.CpModel()
    choose = [model.new_bool_var(f'fragment_{i}') for i in range(len(edges))]
    intervals = []
    for i, e in enumerate(edges):
        start = dates.index(e['flow']['days'][0]['date'])
        length = len(e['flow']['days'])
        intervals.append(model.new_optional_fixed_size_interval_var(start, length, choose[i], f'crew_{i}'))
    model.add_no_overlap(intervals)
    for n in sorted(live):
        incoming = [choose[i] for i, e in enumerate(edges) if e['to'] == n]
        outgoing = [choose[i] for i, e in enumerate(edges) if e['from'] == n]
        if n == 0:
            model.add(sum(outgoing) == 1)
        elif n not in frontier:
            model.add(sum(incoming) == sum(outgoing))
    model.add(sum(choose[i] for i, e in enumerate(edges) if e['to'] in frontier) == 1)
    # §8 年度前缀：系数直接取表项，包含期初 WBS，不再写第二套产量公式。
    for m, info in data['factory']['models'].items():
        model.add(sum(choose[i] * e['flow']['production'][m] for i, e in enumerate(edges))
                  <= sum(data['demand']['PR'][m].values()))
        for month in months:
            model.add(sum(choose[i] * sum(r['fok'][m] for r in e['flow']['days'] if r['date'][:7] <= month)
                          for i, e in enumerate(edges)) <= _limits(data, month, early)[m][1])
        for day in dates:
            deadline = (date.fromisoformat(day) - timedelta(days=info['glue_age_max'])).isoformat()
            due = data['initial']['wip'].get('WBS', {}).get(m, 0) if deadline >= (
                date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat() else 0
            model.add(due + sum(choose[i] * sum(r['workshops'][info['line']]['out'].get(m, 0)
                         for r in e['flow']['days'] if r['date'] <= deadline) for i, e in enumerate(edges))
                      <= sum(choose[i] * sum(r['workshops']['PS']['in'].get(m, 0)
                         for r in e['flow']['days'] if r['date'] <= day) for i, e in enumerate(edges)))
    denominator = ratio.denominator
    total_pr = sum(sum(v.values()) for v in data['demand']['PR'].values())
    objectives = [total_pr - sum(choose[i] * sum(e['flow']['production'].values()) for i, e in enumerate(edges))]
    objectives.extend(sum(choose[i] * int(e['cost'][k] * (denominator if k == 1 else 1))
                          for i, e in enumerate(edges)) for k in range(len(nodes[0]['cost'])))
    logs, selected = [], None
    solve_tick = perf_counter()
    for level, objective in zip(LEVELS, objectives):
        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = 0
        solver.parameters.num_workers = 1
        solver.parameters.max_deterministic_time = deterministic_seconds
        start = perf_counter()
        status = solver.solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected = [i for i, x in enumerate(choose) if solver.value(x)]
            value = solver.value(objective)
        elif selected is not None:
            value = (total_pr - sum(sum(edges[i]['flow']['production'].values()) for i in selected)
                     if level == 'L1a' else sum(int(edges[i]['cost'][LEVELS.index(level) - 1]
                         * (denominator if level == 'L1c' else 1)) for i in selected))
        else:
            return {'status': 'UNKNOWN', 'scope': 'restricted_fragment_graph', 'segments': [],
                'findings': [*dict.fromkeys(widened), '全年方案比较没有在时限内完成。'],
                'stop_search_findings': list(dict.fromkeys(widened)),
                'stats': {'candidates': len(edges), 'generation_seconds': generation_seconds}}
        model.add(objective == value)
        logs.append({'level': level, 'value': value / denominator if level == 'L1c' else value,
                     'candidate_table_optimal': status == cp_model.OPTIMAL, 'proven_optimal': False,
                     'budget_deterministic_seconds': deterministic_seconds,
                     'deterministic_seconds': solver.response_proto.deterministic_time,
                     'seconds': perf_counter() - start, 'status': solver.status_name(status)})
        if level == 'L1c':
            # 第 5 轮：固定前三项目标后逐次择晚，不改计划的九级目标定义。
            for pos in range(len(empty_stops)):
                latest = sum(choose[i] * e['stop_dates'][pos] for i, e in enumerate(edges))
                model.maximize(latest)
                status = solver.solve(model)
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    selected = [i for i, x in enumerate(choose) if solver.value(x)]
                    value = solver.value(latest)
                else:
                    value = sum(edges[i]['stop_dates'][pos] for i in selected)
                model.add(latest == value)
    solve_seconds = perf_counter() - solve_tick
    selected.sort(key=lambda i: edges[i]['flow']['days'][0]['date'])
    combined_schedule, modes, segments = {}, {}, []
    state, rows, events, monthly, l3a, l3b = root, [], [], {}, 0, 0
    stats = {'steady_days': 0, 'event_hits': 0, 'single_days': 0}
    for i in selected:
        e = edges[i]
        assert nodes[e['from']]['state'] == state
        fragment = e['flow']
        for r in fragment['days']:
            d = r['date']
            combined_schedule[d] = e['schedule'][d]
            modes[d] = {**tables[e['table']]['modes'][d], **e['schedule'][d].get('level_modes', {})}
        rows.extend(fragment['days'])
        events.extend(fragment['events'])
        monthly.update(fragment['monthly_fok'])
        state = fragment['exit']
        l3a += fragment['L3a']
        l3b += fragment['L3b']
        segments.extend(e['controls'])
        for k in stats:
            stats[k] += fragment['fast_stats'][k]
    flow = {'days': rows, 'exit': state, 'events': events, 'monthly_fok': monthly,
            'production': dict(state['fok']), 'L3a': l3a, 'L3b': l3b, 'fast_stats': stats}
    # 最终选择用完整模板从期初再走一遍；不能以片段各自可行代替拼接核对。
    verified = replay_template(data, root, dates[0], dates[-1], modes, segments, schedule=combined_schedule)
    assert all(flow[k] == verified[k] for k in ('days', 'exit', 'events', 'monthly_fok', 'production', 'L3a', 'L3b'))
    plan = expand_segments(data, segments, replay=verified)
    values = measure(data, verified)
    assert values == {r['level']: r['value'] for r in logs}
    plan['objective']['levels'] = [{k: row[k] for k in ('level', 'value', 'proven_optimal', 'candidate_table_optimal')} for row in logs]
    plan['findings'] = ['本计划由段级解法排出：按月比较不同的停线日期和换型日期（每月最多两次换型）后取最好的方案，不保证是理论最优。',
                        *dict.fromkeys(widened), *prebuild_findings(data, plan['days'])]
    return {'status': 'CANDIDATE', 'scope': 'restricted_fragment_graph', 'segments': segments,
            'levels': values, 'flow': flow, 'plan': plan, 'solver': logs,
            'schedule': combined_schedule, 'modes': modes,
            'stats': {'attempts': attempts, 'candidates': len(edges), 'generated_fragments': len(nodes) - 1,
                      'generation_seconds': generation_seconds, 'solve_seconds': solve_seconds,
                      'model_build_seconds': solve_tick - tick - generation_seconds,
                      'expand_seconds': perf_counter() - solve_tick - solve_seconds,
                      'beam_width': beam_width, 'selected_fragments': len(selected),
                      'sample_months_checked': samples,
                      'selected_days': stats, 'full_replay_equal': True},
            'findings': list(dict.fromkeys([*widened, *failures])),
            'stop_search_findings': list(dict.fromkeys(widened))}


def _shift_points(data, base, settings, early=None):
    """C4/C13/C14、§5：只在原班组占用范围内移动停点，不移动换型。

    相同车型的月片段只是计算切片；相邻月和同车型前后段均可配对。
    尾差数量仍是显式控制，清线/停前/复线形状交给原模板计算。
    """
    segments = base['segments']
    points = []
    cumulative, breaks = dict.fromkeys(data['factory']['models'], 0), {}
    ratio = Fraction(str(data['rules']['monthly_band_ratio']))
    early = prebuild(data) if early is None else early
    for month, produced in base['flow']['monthly_fok'].items():
        for m, q in produced.items():
            cumulative[m] += q
            total, upper = _limits(data, month, early)[m]
            lower = total - ratio * data['demand']['PR'][m][month]
            breaks[month, m] = (upper - cumulative[m], ceil(lower - cumulative[m]))
    for index, s in enumerate(segments):
        line = data['factory']['models'][s['model']]['line']
        for month, point in s['stop_points'].items():
            boundary = min(data['horizon']['end'], month + '-31',
                (date.fromisoformat(s['next_start']) - timedelta(days=1)).isoformat())
            if s['tail']['type'] == 'CHANGEOVER':
                boundary = min(boundary, (date.fromisoformat(s['tail']['clear_start'])
                                         - timedelta(days=1)).isoformat())
            work = [d for d in settings if s['start'] <= d <= boundary
                    and d[:7] == month and settings[d]['caps'][line]]
            if not work:
                continue
            before = [d for d in work if d < point['date']]
            after = [d for d in work if d > point['date']]
            choices = []
            if after:
                choices.append({'date': after[0]})
            if 'quantity' in point and point['date'] in work:
                choices.append({'date': point['date']})
            if before:
                choices.append({'date': before[-1]})
            # S3b：直接覆盖月末完整生产及只留下普通休息窗口的停点，
            # 不能要求经过若干个目标值不变的单日移动才能到达。
            if work[-1] != point['date'] and {'date': work[-1]} not in choices:
                choices.append({'date': work[-1]})
            # 从真实累计表的硬上限余量/下限缺口取整数断点；仅用于生成
            # 明确尾差候选，候选的数量和目标仍由精确模板转移记账。
            for choice in list(choices):
                cap = min(settings[choice['date']]['caps'][w] for w in (line, 'PS', 'AS_MAIN', 'AS_FIN'))
                available = {v for (mo, model), values in breaks.items()
                    if model == s['model'] and mo >= month for v in values if 0 < v < cap}
                quantities = sorted(available, reverse=True)
                for q in quantities:
                    choices.append({'date': choice['date'], 'quantity': q})
            points.append((index, month, s['model'], choices))
    for index, month, m, choices in points:
        for point in choices:
            yield m, [(index, month, point)]
    # 不同车型的班组时间不相让；只配同车型相邻停点的相反方向。
    for m in data['factory']['models']:
        chain = [p for p in points if p[2] == m]
        for left, right in zip(chain, chain[1:]):
            for a in left[3]:
                for b in right[3]:
                    old_a = segments[left[0]]['stop_points'][left[1]]
                    old_b = segments[right[0]]['stop_points'][right[1]]
                    direction_a = (a['date'] > old_a['date']) - (a['date'] < old_a['date'])
                    direction_b = (b['date'] > old_b['date']) - (b['date'] < old_b['date'])
                    if direction_a * direction_b < 0:
                        yield m, [(left[0], left[1], a), (right[0], right[1], b)]


def _shift_cap(data, entry, month, first, last, controls, table, flow, schedule, moved_model):
    """C10/C12/C14：尾差不够吸收前移产量时，把同车型停点前移。"""
    capped = _cap_candidate(data, entry, month, first, last, controls, table, flow, schedule,
                            models=(moved_model,))
    if capped is not None and any('pre_stop' in capped[2].get(r['date'], {})
            and sum(r['eod']['PS'].values()) != capped[2][r['date']]['pre_stop']
            for r in capped[1]['days']):
        capped = None
    if flow['exit']['fok'][moved_model] <= _limits(data, month, table['prebuild'])[moved_model][1]:
        return capped
    if capped is not None:
        # C14/§5：紧接旧线清线前的最后正常日可以使用显式尾差；
        # _cap_candidate 保留原清线日，不在准备日前另造一个空档。
        return capped
    normal = [d for d, c in schedule.items() if first <= d <= last
        and c['model'] == moved_model and c['kind'] == 'NORMAL'
        and table['settings'][d]['caps'][data['factory']['models'][moved_model]['line']]]
    if not normal:
        return None
    index = schedule[normal[-1]]['segment']
    # 清线/换型后不可把普通尾差另插在准备日前；其余端点由邻域显式生成。
    if controls[index]['tail']['type'] == 'CHANGEOVER' or any(
            c['model'] == moved_model and c['kind'] in ('PREPARE', 'BS_CLEAR')
            for d, c in schedule.items() if normal[-1] < d <= last):
        return None
    for d in reversed(normal[:-1]):
        changed = deepcopy(controls)
        changed[index]['end'] = d
        changed[index]['stop_points'][month] = {'date': d}
        f, s = _run_fragment(data, entry, first, last, changed, table)
        capped = _cap_candidate(data, entry, month, first, last, changed, table, f, s,
                                models=(moved_model,))
        if capped is not None and all('pre_stop' not in capped[2].get(r['date'], {})
                or sum(r['eod']['PS'].values()) == capped[2][r['date']]['pre_stop']
                for r in capped[1]['days']):
            return capped
    return None


def _shift_replay(data, base, edits, moved_model, table, *, crew_edits=()):
    """§10/§11：只重算受影响后缀，物理入口相等时复用原表项。

    累计 FOK/net 不参与物理模板；复用日流量时精确更新欠交和出口账。
    遇 C10/C12 上限，仅给挪移车型选后续显式尾差，不动其他车型控制。
    """
    segments = deepcopy(base['segments'])
    moved_models = moved_model if crew_edits else (moved_model,)
    for index, control in crew_edits:
        segments[index] = deepcopy(control)
    for index, month, point in edits:
        s = segments[index]
        s['stop_points'][month] = dict(point)
        if s['tail']['type'] != 'CHANGEOVER':
            s['end'] = max(p['date'] for p in s['stop_points'].values())
    dates = list(table['settings'])
    months = sorted({d[:7] for d in dates})
    first_changed = min([month for _, month, _ in edits]
                        + [s['start'][:7] for _, s in crew_edits])
    entry, rows, events, schedule = initial_state(data), [], [], {}
    l3a = l3b = 0
    monthly, recalculated, reused = {}, [], []
    month_entries, month_flows, month_schedules = {}, {}, {}
    stats = dict.fromkeys(('steady_days', 'event_hits', 'single_days'), 0)
    for month in months:
        local = [d for d in dates if d[:7] == month]
        first, last = local[0], local[-1]
        indices = [i for i, s in enumerate(segments) if s['start'][:7] == month]
        controls = [segments[i] for i in indices]
        old_controls = [base['segments'][i] for i in indices]
        old = base['month_flows'][month]
        old_entry = base['month_entries'][month]
        if month > first_changed and (entry['fok'] != old_entry['fok'] or entry['stock'] != old_entry['stock']):
            # 前段挪移后，后段原来的尾差量不再合适；重新选择该车型的
            # 显式尾差，再按真实月度上限封顶，避免补水位导致需求未完先停。
            controls = deepcopy(controls)
            for c in controls:
                if c['model'] in moved_models and c['tail']['type'] != 'CHANGEOVER':
                    c['stop_points'][month].pop('quantity', None)
        physical_equal = all(entry[k] == old_entry[k] for k in entry if k not in ('fok', 'net'))
        if month < first_changed or controls == old_controls and physical_equal:
            f = deepcopy(old)
            delta = {m: entry['fok'][m] - old_entry['fok'][m] for m in entry['fok']}
            for row in f['days']:
                for m in delta:
                    net = row['fin'][m] - row['bl'][m] + delta[m]
                    row['fin'][m], row['bl'][m] = max(0, net), max(0, -net)
            for k in ('fok', 'net'):
                f['exit'][k] = {m: old['exit'][k][m] + delta[m] for m in delta}
            s = base['month_schedules'][month]
            reused.append(month)
        else:
            f, s = _run_fragment(data, entry, first, last, controls, table)
            recalculated.append(month)
        for m in moved_models:
            capped = _shift_cap(data, entry, month, first, last, controls, table, f, s, m)
            if capped is None:
                return None
            controls, f, s = capped
            # C10/C16：旧车型今后只有零投入清线时，此月须把仍在
            # 全链的旧车计入年度余量；尾差仍由同一模板显式选择。
            future_input = any(c['model'] == m and any(
                table['settings'][d]['caps'][data['factory']['models'][m]['line']]
                and d <= c['stop_points'][d[:7]]['date']
                for d in dates if last < d <= c['end'] and c['start'] <= d
                and d < c['tail'].get('clear_start', '9999')) for c in segments)
            if not future_input and any(c['model'] == m and c['tail']['type'] == 'CHANGEOVER'
                                        and c['end'] > last for c in segments):
                capped = _cap_candidate(data, entry, month, first, last, controls, table, f, s,
                                        models=(m,), close_old=True)
                if capped is None:
                    return None
                controls, f, s = capped
        if not _applicable(data, entry, f, s, table['settings'], table['prebuild']):
            return None
        for i, control in zip(indices, controls):
            segments[i] = control
        month_entries[month], month_flows[month], month_schedules[month] = entry, f, s
        rows.extend(f['days'])
        events.extend(f['events'])
        schedule.update(s)
        monthly.update(f['monthly_fok'])
        l3a += f['L3a']
        l3b += f['L3b']
        for k in stats:
            stats[k] += f['fast_stats'][k]
        entry = f['exit']
    flow = {'days': rows, 'exit': entry, 'events': events, 'monthly_fok': monthly,
            'production': dict(entry['fok']), 'L3a': l3a, 'L3b': l3b, 'fast_stats': stats}
    return {'segments': segments, 'flow': flow, 'schedule': schedule,
            'levels': measure(data, flow), 'recalculated_months': recalculated, 'reused_months': reused,
            'month_entries': month_entries, 'month_flows': month_flows, 'month_schedules': month_schedules}


def _crew_points(data, base, settings):
    """C4/C16、§5 换型：移动同月交接日，重新留足旧线零投入清空日。"""
    groups = []
    for index, (a, b) in enumerate(zip(base['segments'], base['segments'][1:])):
        if (a['model'] == b['model'] or a['tail']['type'] != 'CHANGEOVER'
                or a['start'][:7] != b['start'][:7]):
            continue
        month = a['start'][:7]
        line = data['factory']['models'][a['model']]['line']
        other = data['factory']['models'][b['model']]['line']
        work = [d for d in settings if a['start'] <= d <= b['end'] and d[:7] == month
                and settings[d]['caps'][line] and settings[d]['caps'][other]]
        choices = []
        # 全部可用交接日按离原点的距离排序；不假定平移只能一天。
        for day in sorted((d for d in work if d != b['start']),
                          key=lambda d: (abs(work.index(d) - work.index(b['start'])), d)):
            pos = work.index(day)
            before = work[pos - 1] if pos else None
            if before is None:
                continue
            count = ceil(Fraction(settings[before]['targets'][line], settings[before]['caps'][line]))
            if pos < count:
                continue
            clear = work[pos - count]
            left, right = deepcopy(a), deepcopy(b)
            left.update(end=clear, next_start=day, tail={'type': 'CHANGEOVER', 'clear_start': clear})
            left['stop_points'][month] = {'date': clear}
            right['start'] = day
            right['stop_points'][month].pop('quantity', None)
            edits = [(index, left), (index + 1, right)]
            steps = pos - work.index(b['start'])
            choices.append((steps, edits))
            yield (a['model'], b['model']), edits
        groups.append(((a['model'], b['model']), choices))
    # C10/C12：同一车型的进入和退出同时前移/后移，才能保持全年
    # 投入余量并改变月间分配；两个换型事件仍各自只计一次。
    for (models, left), (following, right) in zip(groups, groups[1:]):
        if models != tuple(reversed(following)):
            continue
        for step, a in left:
            for other_step, b in right:
                if step == other_step:
                    yield models, a + b


def _shift_months(data, answer, table):
    """为已有合法链建立入口/出口查表；不使用参考计划生成候选。"""
    entry = initial_state(data)
    answer['month_entries'], answer['month_flows'], answer['month_schedules'] = {}, {}, {}
    for month in sorted(answer['flow']['monthly_fok']):
        local = [d for d in table['settings'] if d[:7] == month]
        controls = [s for s in answer['segments'] if s['start'][:7] == month]
        f, s = _run_fragment(data, entry, local[0], local[-1], controls, table)
        assert f['days'] == [r for r in answer['flow']['days'] if r['date'][:7] == month]
        answer['month_entries'][month] = entry
        answer['month_flows'][month], answer['month_schedules'][month] = f, s
        entry = f['exit']


def _combined_points(data, base, settings, early=None):
    """S3b 第 2 轮：换型与停点一起改，整组转移之后才比较字典序。

    C6/C15 允许月末在缓冲物理空间内留车；C14 允许当月最后生产日
    使用尾差。沿用 retain_water 的日模板，不另写高水位流量公式。
    """
    points = list(_shift_points(data, base, settings, early))
    for models, crew in _crew_points(data, base, settings):
        index = crew[0][0]
        if crew[1][1]['start'] >= base['segments'][crew[1][0]]['start']:
            continue
        # 前移换型，同时调旧车型前一月/本月的停点，或新车型本月停点。
        for m, edits in points:
            if m in models and all(index - 1 <= i <= index + 1 for i, _, _ in edits):
                yield models, edits, crew
        # 连续多步：前两个月间挪量，前一月保留实际缓冲水位，再移动
        # 进入/退出换型。中间目标值可以变差，不据此丢弃最终组合。
        if index < 2:
            continue
        earlier, previous = base['segments'][index - 2:index]
        if any(s['model'] != models[0] or s['tail']['type'] == 'CHANGEOVER'
               for s in (earlier, previous)):
            continue
        month = earlier['start'][:7]
        line = data['factory']['models'][models[0]]['line']
        point = earlier['stop_points'][month]
        work = [d for d in settings if earlier['start'] <= d < earlier['next_start']
                and d[:7] == month and settings[d]['caps'][line]]
        after = [d for d in work if d > point['date']]
        if not after:
            continue
        retained = deepcopy(previous)
        retained['retain_water'] = True
        combined = crew + [(index - 1, retained)]
        for day in dict.fromkeys((after[0], work[-1])):
            room = sum(max(0, info['cap_max'] - settings[day]['targets'][n])
                       for n, info in data['factory']['buffers'].items())
            capacity = min(settings[day]['caps'][w] for w in (line, 'PS', 'AS_MAIN', 'AS_FIN'))
            for q in dict.fromkeys((room, capacity - room, capacity)):
                if 0 < q <= capacity:
                    yield models, [(index - 2, month, {'date': day, 'quantity': q})], combined


def improve_segments(data, answer, accept, *, move_budget=512, crew_moves=False, combined_moves=False):
    """第 8 轮：从同一入口分别按实际 E、E=0 挪移，取六级目标字典序较优者。"""
    tick = perf_counter()
    table = prepare_fast(data, [{'modes': answer['modes']}])
    early = table['prebuild']
    ordinary = {m: dict.fromkeys(values, 0) for m, values in early.items()}
    months = sorted(answer['flow']['monthly_fok'])
    bands = [early, ordinary] if any(_limits(data, mo, early) != _limits(data, mo, ordinary)
                                   for mo in months) else [early]
    candidates = [_improve_segments(data, deepcopy(answer), accept, table, band,
        move_budget=move_budget, crew_moves=crew_moves, combined_moves=combined_moves)
        for band in bands]
    selected = min(candidates, key=lambda a: tuple(a['levels'][k] for k in LEVELS))
    selected['stats']['shift_seconds'] = perf_counter() - tick
    return selected


def _improve_segments(data, answer, accept, table, early, *, move_budget, crew_moves, combined_moves):
    """S3/S3b 停点与班组局部改进；accept 通过命令行判定改进候选。

    候选次数是确定性计算预算，不能据此声明全年最优。S3b 可移动
    换型日，L2 不增加；前三项目标相同时先比较停前日，再比较后三项目标。
    """
    tick = perf_counter()
    before = dict(answer['levels'])
    # 入口按真实 C12 上限复原；它可能已使用 E，不要求先满足 E=0 的候选上限。
    _shift_months(data, answer, table)
    table = {**table, 'prebuild': early}
    attempts, accepted, rejected, failures = 0, [], [], []
    attempts_by_kind = {'stop': 0, 'crew': 0, 'combined': 0}
    exhausted = False
    while attempts < move_budget:
        improved = False
        moves = ((m, edits, ()) for m, edits in _shift_points(data, answer, table['settings'], early))
        if crew_moves:
            moves = chain(moves, ((models, [], edits) for models, edits in
                                 _crew_points(data, answer, table['settings'])))
        if combined_moves:
            moves = chain(moves, _combined_points(data, answer, table['settings'], early))
        for m, edits, crew_edits in moves:
            if attempts >= move_budget:
                exhausted = True
                break
            attempts += 1
            kind = 'combined' if crew_edits and edits else 'crew' if crew_edits else 'stop'
            attempts_by_kind[kind] += 1
            try:
                candidate = _shift_replay(data, answer, edits, m, table, crew_edits=crew_edits)
            except ValueError as exc:
                failures.append(str(exc))
                continue
            if candidate is None or _selection_key(data, candidate) >= _selection_key(data, answer):
                continue
            if candidate['levels']['L2'] > answer['levels']['L2']:
                continue
            plan = expand_segments(data, candidate['segments'], replay=candidate['flow'])
            plan['objective']['levels'] = [{'level': k, 'value': v, 'proven_optimal': False}
                                          for k, v in candidate['levels'].items()]
            if not accept(plan, candidate['levels']):
                rejected.append({'model': m, 'edits': edits, 'levels': candidate['levels']})
                continue
            changes = [{'index': i, 'model': s['model'], 'before': s, 'after': candidate['segments'][i]}
                       for i, s in enumerate(answer['segments']) if s != candidate['segments'][i]]
            assert all(c['model'] in m if crew_edits else c['model'] == m for c in changes)
            intermediate = None
            if kind == 'combined':
                moved = [(i, c) for i, c in crew_edits if c['start'] != answer['segments'][i]['start']
                         or c['tail'] != answer['segments'][i]['tail']]
                step = _shift_replay(data, answer, [], m, table, crew_edits=moved)
                intermediate = step['levels'] if step is not None else None
            accepted.append({'model': m, 'kind': kind, 'intermediate_crew_levels': intermediate,
                'edits': edits, 'controls': changes,
                'before': answer['levels'], 'after': candidate['levels'],
                'recalculated_months': candidate['recalculated_months'], 'reused_months': candidate['reused_months']})
            answer.update({k: candidate[k] for k in ('segments', 'flow', 'schedule', 'levels',
                                                   'month_entries', 'month_flows', 'month_schedules')})
            answer['plan'] = plan
            improved = True
            break
        if not improved:
            break
    verified = replay_template(data, initial_state(data), data['horizon']['start'],
        data['horizon']['end'], answer['modes'], answer['segments'], schedule=answer['schedule'])
    assert all(answer['flow'][k] == verified[k] for k in (
        'days', 'exit', 'events', 'monthly_fok', 'production', 'L3a', 'L3b'))
    assert measure(data, verified) == answer['levels']
    selected_days = answer['flow']['fast_stats']
    answer['flow'] = verified
    answer['plan'] = expand_segments(data, answer['segments'], replay=verified)
    answer['plan']['objective']['levels'] = [{'level': k, 'value': v, 'proven_optimal': False}
                                           for k, v in answer['levels'].items()]
    answer['plan']['findings'] = ['本计划由段级解法排出：按月比较不同的停线日期和换型日期后取最好的方案，不保证是理论最优。' + (
        '已在两个车型之间调整换型日的班组时间，换型次数没有增加。' if crew_moves else ''),
        *answer.get('stop_search_findings', []), *prebuild_findings(data, answer['plan']['days'])]
    answer['shift'] = {'before': before, 'after': answer['levels'], 'attempts': attempts,
        'attempts_by_kind': attempts_by_kind,
        'move_budget': move_budget, 'stop': 'move_budget' if exhausted or attempts == move_budget else 'no_improvement',
        'accepted': accepted, 'rejected': rejected, 'template_failures': list(dict.fromkeys(failures)),
        'full_replay_equal': True}
    answer['stats']['shift_seconds'] = perf_counter() - tick
    answer['stats']['selected_days'] = selected_days
    for key in ('month_entries', 'month_flows', 'month_schedules'):
        answer.pop(key)
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("segments", type=Path, help="回放段文件；--search 时为输出文件")
    parser.add_argument("output", type=Path, nargs='?')
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--beam-width", type=int, default=8)
    parser.add_argument("--deterministic-seconds", type=float, default=0.1)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if args.search:
        answer = solve_segments(data, beam_width=args.beam_width, deterministic_seconds=args.deterministic_seconds)
        output = args.segments
        print('stats=' + json.dumps(answer['stats'], ensure_ascii=False))
        print('status=' + answer['status'])
        for row in answer.get('solver', []):
            print(json.dumps(row, ensure_ascii=False))
        output.with_suffix('.timing.json').write_text(json.dumps(
            {'stats': answer['stats'], 'solver': answer.get('solver', [])}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for key in list(answer['stats']):
            if key.endswith('_seconds'):
                answer['stats'].pop(key)
        for row in answer.get('solver', []):
            row.pop('seconds')
    else:
        segments = json.loads(args.segments.read_text(encoding="utf-8"))
        answer = replay_segments(data, segments, fast_table=prepare_fast(data, segments) if args.fast else None)
        answer["flow"].pop("fast_stats")
        output = args.output
    output.write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if 'plan' in answer:
        output.with_suffix(".plan.json").write_text(json.dumps(answer["plan"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
