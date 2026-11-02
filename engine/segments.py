"""T-31 S1：显式停点驱动的全链模板；不接入逐日主流程。"""
from copy import deepcopy

from calendar import SATURDAY, SUNDAY

from datetime import date, timedelta

from fractions import Fraction

from math import ceil, floor

from .conditions import prepare, stop_days, stop_level
from .monthly import prebuild, prebuild_findings

def _days(first, last):
    begin, end = date.fromisoformat(first), date.fromisoformat(last)
    return [(begin + timedelta(days=i)).isoformat()
            for i in range((end - begin).days + 1)]

def _settings(data, modes):
    days = _days(data["horizon"]["start"], data["horizon"]["end"])
    _, _, allowed, hours, targets, fixed, manual = prepare(data, days)
    factory = data["factory"]
    rows = {}
    for i, day in enumerate(days):
        selected = {}
        for w in factory["workshops"]:
            choice = modes.get(day, {}).get(w, factory["default_mode"])
            selected[w] = "OFF" if allowed[w, i] == ["OFF"] else choice
        rows[day] = {
            "modes": selected,
            "hours": {w: hours[w, i][selected[w]] for w in selected},
            "caps": {w: floor(Fraction(str(hours[w, i][selected[w]]))
                              * Fraction(str(factory["workshops"][w]["jph"])))
                     for w in selected},
            "targets": {n: targets[n, i] for n in data["wip_targets"]},
            "fixed": {w: value for (w, index), value in fixed.items() if index == i},
            "manual": manual.get(i),
        }
    return rows

def _initial(data):
    return {n: {m: data["initial"]["wip"].get(n, {}).get(m, 0)
                for m in data["factory"]["models"]} for n in data["wip_targets"]}

def _level_settings(data, settings, schedule):
    """rev 205：提前降库只覆盖所选总装班制，上游仍用原表。"""
    overrides = {d: c['level_modes'] for d, c in schedule.items() if c.get('level_modes')}
    if not overrides:
        return settings
    # 第 5 轮枚举会反复调用；只重算已授权的总装覆盖日，不重做全年输入预检。
    result = dict(settings)
    for d, modes in overrides.items():
        row = {**settings[d], **{k: dict(settings[d][k]) for k in ('modes', 'hours', 'caps')}}
        for w, mode in modes.items():
            hours = data['factory']['modes'][mode]
            for c in data['conditions']:
                if (c['type'] == 'CAPACITY_LOSS' and c['start'] <= d <= c['end']
                        and w in c['workshops']):
                    hours = min(hours, c['hours_max'])
            row['modes'][w] = mode
            row['hours'][w] = hours
            row['caps'][w] = floor(Fraction(str(hours)) * Fraction(str(data['factory']['workshops'][w]['jph'])))
        result[d] = row
    return result

def _row(data, day, stock, flow, settings, phase, owner):
    """C1/C5/C16：按流边守恒；期初其他车型优先于本段新车。"""
    factory = data["factory"]
    models = list(factory["models"])
    order = [m for m in models if factory["models"][m]["line"] != owner]
    order += [m for m in models if factory["models"][m]["line"] == owner]
    lines = {v["line"] for v in factory["models"].values()}
    row = {"date": day, "workshops": {}, "bod": {n: dict(v) for n, v in stock.items()}, "phase": phase}
    outgoing = {}
    # C16 期初在制无跨车型先后；新生产批次追加在已有库存之后。
    for n in (owner, *[w for w in lines if w != owner], "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"):
        incoming = ({m: flow.get(n, (0, 0))[0] if factory["models"][m]["line"] == n else 0 for m in models}
                    if n in lines else
                    {m: sum(outgoing[w][m] for w in lines) for m in models} if n == "WBS" else
                    outgoing[{"PS": "WBS", "PBS": "PS", "AS_MAIN": "PBS", "AS_FIN": "AS_MAIN"}[n]])
        amount = flow.get(n, (0, 0))[1] if n in lines or n in factory["workshops"] else (
            flow["PS"][0] if n == "WBS" else flow["AS_MAIN"][0])
        taken = {m: 0 for m in models}
        # C16 旧车型（含同日到车）先流出，初始车型之间可任选顺序。
        for m in order:
            quantity = min(amount, stock[n][m] + incoming[m])
            taken[m] = quantity
            amount -= quantity
        outgoing[n] = taken
        stock[n] = {m: stock[n][m] + incoming[m] - taken[m] for m in models}
        if n in factory["workshops"]:
            used = sum(incoming.values()) + sum(taken.values()) > 0
            row["workshops"][n] = {
                "mode": settings["modes"][n] if used else "OFF",
                "hours": settings["hours"][n] if used else 0,
                "in": dict(incoming), "out": taken,
            }
    for w in factory["workshops"]:
        if w not in row["workshops"]:
            row["workshops"][w] = {"mode": "OFF", "hours": 0,
                                    "in": {m: 0 for m in models}, "out": {m: 0 for m in models}}
    row["eod"] = {n: dict(v) for n, v in stock.items()}
    row["fok"] = dict(outgoing["AS_FIN"])
    return row

def _flows(data, stock, line, settings, *, reserves=None, weld_input=None,
           finish_limit=None, tail_limit=None, drain=False, ps_exception=False,
           upper_overrides=None, weld_output=None, drain_nodes=()):
    """C2/C6/C14/C15/C17、§5 B13：供车下限与物理空间双向传递。"""
    path = (line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")
    cap, target = settings["caps"], settings["targets"]
    before = [sum(stock[n].values()) for n in path]
    lower = [target[n] for n in path] if reserves is None else [reserves[n] for n in path]
    upper = [data["factory"]["buffers"][n]["cap_max"] if n in data["factory"]["buffers"]
             else data["factory"]["workshops"][n].get("cap_max", target[n])
             for p, n in enumerate(path)]
    # C6：仅车间期初超上限享有只减不增的平台；缓冲区无此豁免。
    upper = [max(value, before[p]) if n in data['factory']['workshops']
             and sum(data['initial']['wip'].get(n, {}).values()) > value else value
             for p, (n, value) in enumerate(zip(path, upper))]
    if upper_overrides:
        upper = [upper_overrides.get(n, value) for n, value in zip(path, upper)]
    if before[-1] > upper[-1]:
        # C6/C15：候选选择消化完成线超限库存时，少投入须让直接上游回到目标。
        upper[path.index("AS_MAIN")] = target["AS_MAIN"]
    edges = [cap[line], cap[line], cap["PS"], cap["PS"], cap["AS_MAIN"],
             min(cap["AS_MAIN"], cap["AS_FIN"]), cap["AS_FIN"]]
    if tail_limit is not None:
        # C14 段末尾差、§8 1a：尾差日全链同步减少，不增加缓冲库存。
        edges = [min(value, tail_limit) for value in edges]
    if weld_input is not None:
        edges[0] = weld_input
    if weld_output is not None:
        edges[1] = min(edges[1], weld_output)
    if finish_limit is not None:
        edges[-1] = min(edges[-1], finish_limit)
    for w, value in settings["fixed"].items():
        if w in path:
            edges[path.index(w) + 1] = value
    previous = None
    while previous != edges:
        previous = list(edges)
        for p in range(len(path)):
            edges[p + 1] = min(edges[p + 1], max(0, before[p] + edges[p] - lower[p]))
            if path[p] in data["factory"]["workshops"] and edges[p] == 0:
                if not (drain or path[p] in drain_nodes or path[p] == "PS" and ps_exception):
                    edges[p + 1] = 0
        for p in reversed(range(len(path))):
            edges[p] = min(edges[p], max(0, upper[p] - before[p] + edges[p + 1]))
    for w, value in settings["fixed"].items():
        if w in path and edges[path.index(w) + 1] != value:
            raise ValueError(f"{w}：指定产量 {value} 无法由当前段上下文展开")
    return {line: (edges[0], edges[1]), "PS": (edges[2], edges[3]),
            "AS_MAIN": (edges[4], edges[5]), "AS_FIN": (edges[5], edges[6])}

def _stop_target(data, settings, last, length, *, days=None):
    """§5 PS 停前日；人工停前目标只在匹配日期生效。"""
    manual = settings[last]["manual"]
    if manual is not None:
        return manual["target"], "MANUAL:" + manual["id"]
    start = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    end = (date.fromisoformat(last) + timedelta(days=length)).isoformat()
    level = stop_level(data, 'PS', start, end, days=days)
    if level is not None:
        return level[0], 'WIP_TARGET:' + level[1]
    rule = "ps_pre_stop_target_long" if length >= data["rules"]["ps_long_stop_days"] else "ps_pre_stop_target_short"
    return data["rules"][rule], "DEFAULT"

def needs_clear(data, model, settings, last, length):
    """CORE_MODEL rev 196 §5 BS 清线的 W + ceil(tgt(WBS)/cap) 判定。"""
    line = data["factory"]["models"][model]["line"]
    weld_day = next(d for d in reversed(settings) if d <= last and settings[d]['caps'][line])
    k = ceil(Fraction(settings[last]["targets"]["WBS"], settings[weld_day]["caps"][line]))
    age = data["factory"]["models"][model]["glue_age_max"]
    return length >= age or length + k > age


def initial_state(data):
    """C1/C7/C16：入口水位、WBS 焊出批次、车型历史和未结束阶段。

    WBS 批次为 date/model/quantity；期初批次按期首前一天焊出。
    fok/net 只供记账，绝不用于改变模板流量。pending_phases 保留触发车型
    与换型起点，started_models 区分首次启动前与已生产后的空闲许可。
    """
    previous = (date.fromisoformat(data['horizon']['start']) - timedelta(days=1)).isoformat()
    stock = _initial(data)
    return {'stock': stock, 'wbs_batches': [
        {'date': previous, 'model': m, 'quantity': q}
        for m, q in stock['WBS'].items() if q],
        'current_model': None, 'previous_model': None, 'phase': 'STOP',
        'pending_phases': [], 'started_models': [m for m, info in data['factory']['models'].items()
            if sum(stock[info['line']].values())],
        'refilling': False, 'fok': {m: 0 for m in data['factory']['models']},
        'net': {m: data['initial']['fin'].get(m, 0) for m in data['factory']['models']}}


def _resume(data):
    calendar = {r['date']: r['is_working_capable'] for r in data['calendar']}
    day = date.fromisoformat(data['horizon']['end']) + timedelta(days=1)
    while not calendar.get(day.isoformat(), day.weekday() not in (SATURDAY, SUNDAY)
                           and day.strftime('%m-%d') != '01-01'):
        day += timedelta(days=1)
    return day.isoformat()


def _schedule(data, segments, settings, *, level_days=None):
    """§5、SEGMENT_PLAN §9：停点产生零流窗口及真实停前/清线事件。

    stop_points[month] = {date, quantity?}；quantity 为该日完成线尾差上限，
    是调用方的显式选择。tail.preparation_date/clear_start 可显式指定。
    未指定时按当前目标水位及逐日能力向前定位清线准备，不读取累计 FOK。
    """
    schedule = {}
    level_days = stop_days(data) if level_days is None else level_days
    for index, segment in enumerate(segments):
        model = segment['model']
        line = data['factory']['models'][model]['line']
        following = segment.get('next_start', segments[index + 1]['start'] if index + 1 < len(segments) else _resume(data))
        future_stop = segment['tail'].get('stop_window')
        if future_stop:
            following = future_stop['restart']
        boundary = min(data['horizon']['end'],
                       (date.fromisoformat(following) - timedelta(days=1)).isoformat())
        # 续接片段保留原准备日；只在 replay 的 first..last 记账，不在月界重做清线。
        schedule_start = min(segment['start'], segment['tail'].get('preparation_date', segment['start']),
            *[v['start'] for v in segment['tail'].get('level_drains', {}).values()])
        selected = [d for d in settings if schedule_start <= d <= boundary]
        stop_points = segment['stop_points']
        physical_end = future_stop['pre_stop'] if future_stop else segment['end']
        active = [d for d in selected if d <= physical_end and any(settings[d]['caps'].values())
                  and d <= stop_points.get(d[:7], {'date': physical_end})['date']
                  and not (d == stop_points.get(d[:7], {}).get('date')
                           and stop_points[d[:7]].get('quantity') == 0)]
        for d in selected:
            schedule[d] = {'model': model, 'segment': index, 'kind': 'IDLE',
                           'retain_water': segment.get('retain_water', False)}
        for d in active:
            schedule[d]['kind'] = 'NORMAL'
            point = stop_points.get(d[:7], {'date': physical_end})
            if d == point['date'] and 'quantity' in point:
                schedule[d]['finish_limit'] = point['quantity']
                schedule[d]['month_last'] = True
            if d in segment.get('tail_quantities', {}):
                schedule[d]['finish_limit'] = segment['tail_quantities'][d]
                schedule[d]['month_last'] = True
        if segment['tail']['type'] == 'CHANGEOVER':
            clear_start = (segment['tail']['clear_start'] if 'clear_start' in segment['tail'] else next(
                (d for d in selected if d > active[-1] and settings[d]['caps'][line]), following))
            drain_days = [d for d in selected if d >= clear_start and settings[d]['caps'][line]]
            for i, d in enumerate(drain_days):
                schedule[d].update(kind='CHANGEOVER', future_weld_capacity=sum(
                    settings[x]['caps'][line] for x in drain_days[i + 1:]))
        # 相邻可用日间的窗口也包括日历短停；换型后旧线闲置不是长停。
        flowing = [d for d in selected if schedule[d]['kind'] != 'IDLE']
        windows = []
        for i, d in enumerate(flowing):
            if d == data['horizon']['end']:
                continue
            restart = flowing[i + 1] if i + 1 < len(flowing) else following
            length = (date.fromisoformat(restart) - date.fromisoformat(d)).days - 1
            changing = i + 1 == len(flowing) and segment['tail']['type'] == 'CHANGEOVER'
            if length < data['rules']['ps_stop_min_days']:
                continue
            target, source = _stop_target(data, settings, d, length, days=level_days)
            start = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
            end = (date.fromisoformat(restart) - timedelta(days=1)).isoformat()
            levels = {}
            for n in ('PBS', 'AS_MAIN', 'AS_FIN'):
                level = stop_level(data, n, start, end, days=level_days)
                if level is not None:
                    levels[n] = level[0]
            schedule[d]['stop_levels'] = levels
            long = needs_clear(data, model, settings, d, length)
            if changing:
                schedule[d].update(pre_stop=target, stop_length=length, stop_source=source)
                schedule[d]['drain_levels'] = {**levels, 'PS': target}
                # C7/C16、§5：旧线闲置不是长停；停线前旧 WBS 仍须流完。
                if long:
                    for x in flowing:
                        if schedule[x]['kind'] == 'CHANGEOVER':
                            schedule[x]['drain_wbs'] = True
                continue
            windows.append((d, restart, length, target, source, long, levels))
        for d, restart, length, target, source, long, levels in windows:
            schedule[d].update(pre_stop=target, stop_length=length, stop_source=source)
            if not long:
                # TODO(边界): 无 BS 清线只在停前日降库，达不到人工水位即淘汰候选，不扩模板。
                schedule[d]['drain_levels'] = {**levels, 'PS': target}
                continue
            work = [x for x in active if x <= d]
            tail = segment['tail'] if d == flowing[-1] else {}
            if 'preparation_date' in tail:
                prep = tail['preparation_date']
            elif tail.get('hold_buffers') and len(work) > 2:
                prep = work[-3]
            else:
                path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
                release = (settings[d]['targets'][line] + settings[d]['targets']['WBS']
                           + settings[d]['targets']['PS'] - target)
                release += sum(settings[d]['targets'][n] - value for n, value in levels.items())
                total = 0
                prep = work[0]
                for candidate in reversed(work):
                    # §5 rev 197/199/203：准备日最多只能少投本线已有的在制，
                    # 余量必须由之后的清线日消化；准备日本身仍是正常日。
                    reducible = min(settings[candidate]['caps'][line], settings[candidate]['targets'][line])
                    if candidate < d and total >= max(0, release - reducible):
                        prep = candidate
                        break
                    total += min(settings[candidate]['caps'][w]
                                 for w in ('PS', 'AS_MAIN', 'AS_FIN'))
            clear = tail.get('clear_start', next((x for x in work if x > prep), d))
            tail_days = [x for x in selected if prep <= x <= d]
            for x in tail_days:
                schedule[x].update(kind='PREPARE' if x < clear else 'BS_CLEAR',
                    clear_end=d, clear_target=target, clear_days=tail_days,
                    preparation_date=prep, clear_start=clear, clear_restart=restart,
                    drain_levels={**levels, 'PS': target})
            early = segment['tail'].get('level_drains', {}).get(d)
            if early is not None:
                for x in selected:
                    if early['start'] <= x <= d:
                        schedule[x].update(early_levels=dict(levels), level_start=early['start'],
                            level_end=d, level_modes=early['modes'].get(x, {}))
            if tail.get('hold_buffers'):
                # C6/C15：仅在已填物理空间内形成候选水位；PS 减产须有
                # PBS 到物理上限的实际依据，完成线始终保持正流量。
                before = [x for x in work if x < prep]
                if len(before) >= 2:
                    pbs = data['factory']['buffers']['PBS']['cap_max']
                    wbs = data['factory']['buffers']['WBS']['cap_max']
                    if tail['hold_buffers'] == 'minimal_wbs':
                        # §5 BS 清线：保留首个清线日做尽 PS 后仍有 WBS 的
                        # 最小整数入口；末日按 rev 199 实际供给少产，不强凑满产。
                        wbs = max(settings[d]['targets']['WBS'],
                            settings[clear]['caps']['PS'] - settings[clear]['targets'][line] + 1)
                    first_hold, full_hold = before[-2:]
                    schedule[first_hold]['hold'] = {'PBS': min(pbs, settings[first_hold]['targets']['PBS']
                        + max(0, settings[first_hold]['caps'][line] - 1))}
                    schedule[full_hold]['hold'] = {'PBS': pbs, 'WBS': wbs}
                    schedule[prep]['hold'] = {'PBS': pbs, 'WBS': wbs}
        if segment.get('anticipate_buffers'):
            # C3/C14/C15：指定焊出低于能力时，使直接下游 WBS 满库；
            # PS 的指定低产量或随之少投由 PBS 满库支持，提前一天备车。
            for d in active:
                limited = [w for w in (line, 'PS') if
                           0 < settings[d]['fixed'].get(w, settings[d]['caps'][w]) < settings[d]['caps'][w]]
                if limited:
                    previous = next((x for x in reversed(active) if x < d
                                     and settings[x]['caps'][line]), None)
                    if previous is not None:
                        schedule[previous].setdefault('hold', {})['PBS'] = data['factory']['buffers']['PBS']['cap_max']
                    schedule[d].setdefault('hold', {})['PBS'] = data['factory']['buffers']['PBS']['cap_max']
                    if line in limited:
                        schedule[d]['hold']['WBS'] = data['factory']['buffers']['WBS']['cap_max']
            # C3/C13/C15/C17：只停焊装时，提前留出让下游每日有正
            # 投入的最小整数供给；PBS 满库使 PS 的受限减产有物理依据。
            stopped = []
            for d in [*selected, None]:
                if d is not None and not settings[d]['caps'][line]:
                    if settings[d]['caps']['PS']:
                        stopped.append(d)
                    continue
                if not stopped:
                    continue
                previous = next((x for x in reversed(active) if x < stopped[0]
                                 and settings[x]['caps'][line]), None)
                if previous is not None:
                    schedule[previous].setdefault('hold', {}).update(
                        WBS=settings[previous]['targets']['WBS'] + len(stopped),
                        PBS=data['factory']['buffers']['PBS']['cap_max'])
                    for pos, x in enumerate(stopped):
                        schedule[x].setdefault('hold', {}).update(
                            WBS=settings[x]['targets']['WBS'] + len(stopped) - pos - 1,
                            PBS=(data['factory']['buffers']['PBS']['cap_max'] if pos + 1 < len(stopped)
                                 else settings[x]['targets']['PBS']))
                stopped = []
    return schedule


def _step(data, stock, control, settings, day, preparation_input, replenishing=False):
    """唯一日转移：C1–C6/C14–C17 和 §5 的补线、停前、清线公式。"""
    model, kind = control['model'], control['kind']
    if kind == 'PREPARE' and preparation_input == 0:
        kind = 'BS_CLEAR'
    line = data['factory']['models'][model]['line']
    path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
    target = settings[day]['targets']
    s = settings[day]
    phase, owner = 'NORMAL', line
    if kind == 'IDLE':
        flow = {w: (0, 0) for w in data['factory']['workshops']}
        phase = 'STOP'
    elif kind in ('PREPARE', 'BS_CLEAR'):
        reserve = {**(target if kind == 'PREPARE' else settings[control['clear_end']]['targets']),
                   line: 0, 'WBS': target['WBS'] if kind == 'PREPARE' else 0,
                   'PS': target['PS'] if kind == 'PREPARE' else control['clear_target']}
        if kind == 'BS_CLEAR':
            reserve.update(control.get('drain_levels', {}))
        if kind == 'PREPARE':
            reserve.update(control.get('hold', {}))
            reserve.update(control.get('early_levels', {}))
        amount = min(preparation_input, s['caps'][line]) if kind == 'PREPARE' else 0
        flow = _flows(data, stock, line, s, reserves=reserve, weld_input=amount,
                      drain=kind == 'BS_CLEAR', ps_exception=True)
        phase = 'NORMAL' if kind == 'PREPARE' else 'PS_PRE_STOP+BS_CLEAR'
    elif kind == 'CHANGEOVER':
        # C16：旧线连续出车；在给定换型日期之前清空，期间不可零流后重启。
        amount = min(s['caps'][line], max(1, sum(stock[line].values())
                     - control['future_weld_capacity']))
        reserve = {**target, line: 0}
        if control.get('drain_wbs'):
            reserve['WBS'] = 0
        # §5 合并规则：换型补满与停前目标同时成立，不能用降库覆盖 B13。
        if 'pre_stop' in control and not replenishing:
            reserve['PS'] = control['pre_stop']
            reserve.update(control.get('stop_levels', {}))
        flow = _flows(data, stock, line, s, reserves=reserve,
                      upper_overrides={'PS': control['pre_stop']} if 'pre_stop' in control and not replenishing else None,
                      weld_input=0, weld_output=amount, drain=True)
        phase = 'CHANGEOVER'
    else:
        other = next((v['line'] for v in data['factory']['models'].values()
                      if v['line'] != line and sum(stock[v['line']].values())), None)
        if other is not None:
            flow = _flows(data, stock, other, s, reserves={**target, other: 0},
                          weld_input=0, drain=True)
            phase, owner = 'INITIAL_DRAIN', other
        else:
            refill = any(sum(stock[n].values()) < target[n] for n in path
                         if n not in control.get('early_levels', {}))
            first = not any(stock[n][model] for n in path)
            reserve = dict(target)
            reserve.update(control.get('hold', {}))
            reserve.update(control.get('early_levels', {}))
            upper = {}
            if 'pre_stop' in control and not (refill or replenishing):
                reserve['PS'] = control['pre_stop']
                reserve.update(control.get('stop_levels', {}))
                upper = {'PS': reserve['PS']} if control['retain_water'] else {**target, 'PS': reserve['PS']}
                upper.update(control.get('stop_levels', {}))
                phase = 'PS_PRE_STOP'
            elif refill:
                phase = 'FIRST_START' if first else 'REFILL'
            elif control.get('month_last') and not control['retain_water'] and not control.get('hold'):
                upper = dict(target)
            # C6/C14/C15/C17：尾差时可消化期初超上限，但有出车的
            # 普通车间仍须有正投入；直接上游在目标水位时可随之少投。
            if control.get('month_last') and control.get('finish_limit', 0) > 0:
                for w in (line, 'PS', 'AS_MAIN', 'AS_FIN'):
                    physical = data['factory']['workshops'][w].get('cap_max', target[w])
                    before = sum(stock[w].values())
                    if sum(data['initial']['wip'].get(w, {}).values()) > physical and before > physical:
                        upper[w] = max(physical, before + 1 - control['finish_limit'])
            flow = _flows(data, stock, line, s, reserves=reserve, upper_overrides=upper,
                finish_limit=control.get('finish_limit'), ps_exception='pre_stop' in control,
                drain_nodes=tuple(control.get('drain_levels', {})),
                weld_input=control.get('weld_input'),
                tail_limit=(control.get('finish_limit') if not control['retain_water'] else None))
    row = _row(data, day, stock, flow, s, phase, owner)
    if control.get('hold') and phase in ('NORMAL', 'PS_PRE_STOP', 'REFILL', 'FIRST_START'):
        # C14/C15 rev 202：只核对主动蓄车日；水位被抬高不等于减投已有合法依据。
        downstream = {line: 'WBS', 'PS': 'PBS', 'AS_MAIN': 'AS_FIN'}
        upstream = {'PS': 'WBS', 'AS_MAIN': 'PBS', 'AS_FIN': 'AS_MAIN'}
        lowering = control.get('early_levels', {})
        assembly_drain = set()
        if 'PBS' in lowering or 'AS_MAIN' in lowering:
            assembly_drain.add('AS_MAIN')
        if 'AS_FIN' in lowering or 'AS_MAIN' in assembly_drain:
            assembly_drain.add('AS_FIN')
        for w in (line, 'PS', 'AS_MAIN', 'AS_FIN'):
            if w in assembly_drain:
                continue  # rev 205：由 _applicable 按真实降库起点和能做尽做公式核对。
            if (not any(flow[w]) or flow[w][0] >= s['caps'][w]
                    or kind == 'PREPARE' and w == line):
                continue
            below, above = downstream.get(w), upstream.get(w)
            full = False
            if below is not None:
                eod = sum(stock[below].values())
                if below in data['factory']['buffers']:
                    full = eod >= data['factory']['buffers'][below]['cap_max']
                elif 'cap_max' in data['factory']['workshops'][below]:
                    full = eod >= data['factory']['workshops'][below]['cap_max']
                else:
                    full = (max(sum(row['bod'][below].values()), eod) > target[below]
                        or eod >= target[below] and (below in s['fixed']
                            or flow[below][1] >= s['caps'][below] > 0))
            mirror = above is not None and sum(stock[above].values()) == target[above]
            if not (full or mirror):
                raise ValueError(f"{day} {w}：蓄车减投没有 C15 受限依据")
    return row


def _preparation(data, stock, control, settings, schedule, previous_weld=None):
    """§5 BS 清线/rev 199：枚举准备日投入，按唯一日转移核对整个段尾。

    焊装较慢时，准备日下游不能凭完成线能力虚增出车。终态、紧贴停线、
    每日能做尽做与不满后不再满产同时满足的最大投入才是此表项。
    """
    day, end = control['preparation_date'], control['clear_end']
    line = data['factory']['models'][control['model']]['line']
    path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
    final = {**settings[end]['targets'], **schedule[end].get('stop_levels', {}),
             line: 0, 'WBS': 0, 'PS': control['clear_target']}
    least = max(0, settings[day]['caps'][line] - sum(stock[line].values()))
    for amount in reversed(range(least, settings[day]['caps'][line] + 1)):
        water, partial, valid = {n: dict(v) for n, v in stock.items()}, set(), True
        cleared, clear_start, tail_out, gap = None, None, 0, False
        previous, reducible = previous_weld, None
        for d in _days(day, end):
            c = schedule[d]
            row = _step(data, water, c, settings, d, amount)
            weld = {'date': d, 'in': sum(row['workshops'][line]['in'].values()),
                    'out': sum(row['workshops'][line]['out'].values()),
                    'bod': sum(row['bod'][line].values())}
            if clear_start is None and weld['in'] == 0 and weld['out'] > 0:
                clear_start = d
                pre = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
                if previous is not None and previous['date'] == pre:
                    reducible = previous['in'] - max(0, previous['out'] - previous['bod'])
            previous = weld
            if clear_start is None and any(sum(water[n].values()) < settings[d]['targets'][n]
                                          for n in ('PBS', 'AS_MAIN', 'AS_FIN')
                                          if n not in c.get('early_levels', {})):
                # §5 rev 205：只有已进入人工水位降库的节点可先低于正常目标。
                valid = False
                break
            if c['kind'] == 'PREPARE' and amount:
                if (sum(row['workshops'][line]['out'].values()) != settings[d]['caps'][line]
                        or any(sum(water[n].values()) < settings[d]['targets'][n]
                               for n in path if n != line and n not in c.get('early_levels', {}))):
                    valid = False
                    break
                continue
            if not any(settings[d]['caps'].values()):
                continue
            # TODO(边界): 人工停前水位高于降库入口时不升库，该候选按原筛选流程淘汰。
            if any(not final[n] <= sum(water[n].values()) <= sum(row['bod'][n].values())
                   for n in c.get('drain_levels', {})):
                valid = False
            # §5 PS 停前降库：投入和出车都能做尽做，不靠下游留车反压 PS。
            ps_in = sum(row['workshops']['PS']['in'].values())
            weld_out = sum(sum(row['workshops'][w]['out'].values())
                           for w in {v['line'] for v in data['factory']['models'].values()})
            if ps_in != min(settings[d]['caps']['PS'], sum(row['bod']['WBS'].values()) + weld_out):
                valid = False
            room = (data['factory']['buffers']['WBS']['cap_max'] - sum(row['bod']['WBS'].values())
                    + ps_in - (weld_out - weld['out']))
            if weld['out'] != min(settings[d]['caps'][line], weld['bod'], room):
                valid = False
            for w in ('PS', 'AS_MAIN', 'AS_FIN'):
                actual = sum(row['workshops'][w]['out'].values())
                available = min(settings[d]['caps'][w], max(0,
                    sum(row['bod'][w].values()) + sum(row['workshops'][w]['in'].values()) - final[w]))
                if actual != available or w in partial and actual == settings[d]['caps'][w] > 0:
                    valid = False
                if actual < settings[d]['caps'][w]:
                    partial.add(w)
            # rev 200/203：空档按焊装工作日判，尾量合计包含清空后所有日期。
            if cleared is not None:
                tail_out += sum(row['workshops']['PS']['out'].values())
                if settings[d]['caps'][line] and (ps_in or sum(row['workshops']['PS']['out'].values())):
                    gap = True
                    if ps_in:
                        valid = False
            elif sum(water[line].values()) + water['WBS'][control['model']] == 0:
                cleared = d
        # TODO(边界): 零投入准备日若跨回放片段缺少清线前日流量，不采用需该证据的尾日候选。
        if (valid and (not gap or reducible is not None and tail_out > reducible)
                and all(sum(water[n].values()) == final[n] for n in path)):
            return amount
    # TODO(边界): 当前入口及准备日期没有合法段尾时，由候选层换日期，不证明输入无解。
    raise ValueError(f"{day}..{end}：未找到 §5 紧贴停线且能做尽做的清线模板")


def prepare_fast(data, segments):
    """§10：一次准备能力与理论产量前缀和；事件表只存真实入口的精确转移。

    表项直接比较日期、控制和完整按车型水位；不使用摘要或近似匹配。
    表不持久化，在同一逐日班制表的日期候选中复用；其他授权组合另准备。
    未见过的入口计算一次。
    """
    modes = {d: dict(v) for s in segments for d, v in s.get('modes', {}).items()}
    settings = _settings(data, modes)
    prefixes, rates = {}, {}
    for m, info in data['factory']['models'].items():
        total, prefixes[m], rates[m] = 0, {}, {}
        for d, s in settings.items():
            q = min(s['caps'][w] for w in (info['line'], 'PS', 'AS_MAIN', 'AS_FIN'))
            rates[m][d] = q
            total += q
            prefixes[m][d] = total
    return {'settings': settings, 'modes': modes, 'prefixes': prefixes, 'prebuild': prebuild(data),
            'stop_days': stop_days(data),
            'rates': rates, 'events': {}}


def replay_template(data, entry, first, last, modes, controls, *, prepared=None, fast=False, schedule=None,
                    fok_limits=None):
    """S1 记账契约：入口状态 + 日期 + 逐日班制 + 阶段/停点控制 → 一份流量。

    返回 days(IN/OUT/BOD/EOD/FOK)、production、exit、events、L3a/L3b、
    monthly_fok。所有数量只从这次转移累加；累计 FOK 不参与日转移。
    fast 的稳态段用理论前缀和，事件按精确入口查表；其余日执行同一转移。
    """
    settings = prepared['settings'] if prepared is not None else _settings(data, modes)
    schedule = (_schedule(data, controls, settings, level_days=prepared['stop_days'] if prepared is not None else None)
                if schedule is None else schedule)
    settings = _level_settings(data, settings, schedule)
    state = deepcopy(entry)
    stock, rows, events = state['stock'], [], []
    calendar = {r['date']: r['is_working_capable'] for r in data['calendar']}
    l3a = l3b = steady = table_hits = 0
    monthly = {}
    prep_input = 0
    model = controls[0]['model']
    previous_clear = 'BS_CLEAR' in state['phase']
    previous_date = next((d for d in reversed(settings) if d < first), None)
    # 逐日物理转移只有这一条链；计算月界不重置状态或 C14 段。
    for day in _days(first, last):
        c = schedule.get(day, {'model': model, 'kind': 'IDLE', 'segment': None})
        model = c['model']
        line = data['factory']['models'][model]['line']
        pending = state['pending_phases']
        # §5：阶段属于触发它的车型，换车型或计算月界均不结束未完成补线。
        if c['kind'] == 'CHANGEOVER' and sum(stock[line].values()) and not any(
                p['type'] == 'CHANGEOVER' and p['from'] == model for p in pending):
            pending.append({'type': 'CHANGEOVER', 'from': model, 'model': None})
        if c['kind'] == 'NORMAL':
            for p in pending:
                if settings[day]['caps'][line] and p['type'] == 'REFILL':
                    p.pop('waiting', None)
                if p['type'] == 'CHANGEOVER' and p['model'] is None and p['from'] != model:
                    p['model'] = model
            if state['current_model'] is None and not pending and any(
                    sum(stock[n].values()) < settings[day]['targets'][n]
                    for n in (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
                    if n not in c.get('early_levels', {})):
                pending.append({'type': 'REFILL', 'model': model})
        replenishing = any(not p.get('waiting', False) for p in pending)
        if c['kind'] == 'PREPARE' and day == c['preparation_date']:
            # §10 段尾查表：相同真实入口不重复枚举准备日；失败也只指这个表项。
            previous_weld = ({'date': rows[-1]['date'],
                'in': sum(rows[-1]['workshops'][line]['in'].values()),
                'out': sum(rows[-1]['workshops'][line]['out'].values()),
                'bod': sum(rows[-1]['bod'][line].values())} if rows else None)
            signature = {'date': day, 'stock': stock, 'control': c, 'previous_weld': previous_weld}
            saved = next((v for v in prepared.get('preparations', []) if v['entry'] == signature), None) if fast else None
            if saved is not None:
                if saved['amount'] is None:
                    raise ValueError(saved['error'])
                prep_input = saved['amount']
            else:
                try:
                    prep_input = _preparation(data, stock, c, settings, schedule, previous_weld)
                except ValueError as exc:
                    if fast:
                        prepared.setdefault('preparations', []).append({'entry': deepcopy(signature), 'amount': None, 'error': str(exc)})
                    raise
                if fast:
                    prepared.setdefault('preparations', []).append({'entry': deepcopy(signature), 'amount': prep_input})
        target = settings[day]['targets']
        path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
        eligible = (c['kind'] == 'NORMAL' and 'pre_stop' not in c
            and 'finish_limit' not in c and not settings[day]['fixed']
            and 'weld_input' not in c
            and 'hold' not in c
            and 'early_levels' not in c
            and not any(x['type'] == 'WIP_TARGET' and x['start'] <= day <= x['end'] for x in data['conditions'])
            and all(settings[day]['caps'][a] <= settings[day]['caps'][b]
                    for a, b in zip((line, 'PS', 'AS_MAIN'), ('PS', 'AS_MAIN', 'AS_FIN')))
            and all(sum(stock[n].values()) == target[n] and stock[n][model] == target[n] for n in path)
            and not any(stock[v['line']][m] for m, v in data['factory']['models'].items() if m != model))
        # 非正常中段水位组合很多，线性扫事件表比直接做一次日转移更慢；
        # 只有清线/换型的重复事件入口使用既有查表，稳态不复制签名。
        tabulated = fast and not eligible and c['kind'] in ('PREPARE', 'BS_CLEAR', 'CHANGEOVER')
        signature = ({'date': day, 'stock': deepcopy(stock), 'control': c,
                      'replenishing': replenishing, 'preparation_input': prep_input}
                     if tabulated else None)
        found = next((e for e in prepared['events'].get(day, []) if e['entry'] == signature), None) if tabulated else None
        if fast and eligible:
            q = prepared['prefixes'][model][day] - (prepared['prefixes'][model][previous_date] if previous_date else 0)
            flow = {w: (q, q) for w in (line, 'PS', 'AS_MAIN', 'AS_FIN')}
            row = _row(data, day, stock, flow, settings[day], 'NORMAL', line)
            steady += 1
        elif found is not None:
            row = deepcopy(found['row'])
            stock = deepcopy(row['eod'])
            state['stock'] = stock
            table_hits += 1
        else:
            row = _step(data, stock, c, settings, day, prep_input, replenishing)
            if tabulated:
                prepared['events'].setdefault(day, []).append({'entry': signature, 'row': deepcopy(row)})
        # §5：短停后 PS 从停前目标回升不算复线；已有历史的车型重启不算首次启动。
        if row['phase'] == 'REFILL' and not replenishing and not state['refilling'] and state['current_model'] is not None and sum(row['bod'][line].values()):
            row['phase'] = 'NORMAL'
        if row['phase'] == 'FIRST_START' and model in (state['current_model'], state['previous_model']):
            row['phase'] = 'REFILL'
        if c['kind'] not in ('PREPARE', 'BS_CLEAR'):
            phases = set(row['phase'].split('+')) | {p['type'] for p in pending if not p.get('waiting', False)}
            if replenishing:
                phases.discard('NORMAL')
            row['phase'] = '+'.join(p for p in ('NORMAL', 'PS_PRE_STOP', 'STOP', 'BS_CLEAR',
                'REFILL', 'FIRST_START', 'CHANGEOVER', 'MODEL_EXIT', 'INITIAL_DRAIN') if p in phases)
        # §5：全链达标才结束；旧车型未补满的线不能被新车型的水位代替。
        pending[:] = [p for p in pending if (day < p['end'] if p['type'] == 'STOP_DRAIN' else
            p['model'] is None or not (
            all(sum(stock[n].values()) >= target[n] for n in (
                data['factory']['models'][p['model']]['line'], 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN'))
            and (p['type'] != 'CHANGEOVER' or not sum(stock[data['factory']['models'][p['from']]['line']].values()))))]
        stop_end = (c['clear_end'] if c['kind'] in ('PREPARE', 'BS_CLEAR') else c.get('level_end'))
        if (stop_end is not None and stop_end > last
                and (day == c.get('preparation_date') or day == c.get('level_start'))
                and not any(p['type'] == 'STOP_DRAIN' and p['end'] == stop_end for p in pending)):
            # §5：跨月只切记账，不切同一次停前降库；沿用现有 pending_phases 传递段尾。
            end_control = schedule[stop_end]
            tail = deepcopy(controls[c['segment']]['tail'])
            tail.update(type='PLAN_END', preparation_date=end_control['preparation_date'],
                clear_start=end_control['clear_start'],
                stop_window={'pre_stop': stop_end, 'restart': end_control['clear_restart']})
            pending.append({'type': 'STOP_DRAIN', 'model': model, 'waiting': True, 'end': stop_end,
                'modes': {d: dict(settings[d]['modes']) for d in settings if day <= d <= stop_end},
                'tail': tail})
        if c['kind'] == 'BS_CLEAR' and day == c['clear_end']:
            # §5：清空后的保持日仍属停线，复工当天才开始补线。
            pending.append({'type': 'REFILL', 'model': model, 'waiting': True,
                'stop_window': {'pre_stop': day, 'restart': c['clear_restart']}})
        for m, info in data['factory']['models'].items():
            if sum(row['workshops'][info['line']]['in'].values()) and m not in state['started_models']:
                state['started_models'].append(m)
        actual_model = next((m for m, v in data['factory']['models'].items()
            if any(sum(row['workshops'][v['line']][k].values()) for k in ('in', 'out'))), None)
        if actual_model is not None and state['current_model'] != actual_model:
            if state['current_model'] is not None:
                events.append({'date': day, 'type': 'CHANGEOVER', 'from': state['current_model'], 'to': actual_model})
            state['previous_model'], state['current_model'] = state['current_model'], actual_model
        if 'BS_CLEAR' in row['phase'] and not previous_clear:
            events.append({'date': day, 'type': 'BS_CLEAR', 'model': model})
        if 'pre_stop' in c and any(sum(row['workshops']['PS'][k].values()) for k in ('in', 'out')):
            events.append({'date': day, 'type': 'PS_PRE_STOP', 'target': c['pre_stop']})
        if row['phase'] in ('REFILL', 'FIRST_START') and not state['refilling']:
            events.append({'date': day, 'type': row['phase'], 'model': model})
        if c['kind'] != 'IDLE':
            state['refilling'] = any(not p.get('waiting', False) for p in pending)
        state['phase'] = row['phase']
        previous_clear = 'BS_CLEAR' in row['phase']
        # C7 的等价批次账；只保存尚未进 PS 的焊出批次，不合并焊出日期。
        for m, info in data['factory']['models'].items():
            quantity = row['workshops'][info['line']]['out'].get(m, 0)
            if quantity:
                state['wbs_batches'].append({'date': day, 'model': m, 'quantity': quantity})
            used = row['workshops']['PS']['in'].get(m, 0)
            for batch in state['wbs_batches']:
                if batch['model'] == m:
                    amount = min(used, batch['quantity'])
                    batch['quantity'] -= amount
                    used -= amount
            state['fok'][m] += row['fok'][m]
            state['net'][m] += row['fok'][m] - data['demand']['WS_daily'].get(m, {}).get(day, 0)
            monthly.setdefault(day[:7], {v: 0 for v in data['factory']['models']})[m] += row['fok'][m]
        if fok_limits is not None and any(state['fok'][m] > upper
                for m, (_, upper) in fok_limits[day[:7]].items()):
            # C12：累计 FOK 不会下降，已超过本月上限就不再预演后面的降库日。
            raise ValueError(f'{day}：累计 FOK 超过月度带上限')
        state['wbs_batches'] = [b for b in state['wbs_batches'] if b['quantity']]
        row['fin'] = {m: max(0, v) for m, v in state['net'].items()}
        row['bl'] = {m: max(0, -v) for m, v in state['net'].items()}
        for shop in row['workshops'].values():
            l3a += int(not calendar[day] and shop['mode'] != 'OFF')
            l3b += int(shop['mode'] not in ('OFF', data['factory']['default_mode']))
        row['segment'] = c['segment']
        rows.append(row)
        previous_date = day
    state['stock'] = stock
    return {'days': rows, 'production': {m: state['fok'][m] - entry['fok'][m] for m in state['fok']},
            'exit': state, 'events': events, 'L3a': l3a, 'L3b': l3b,
            'monthly_fok': monthly, 'fast_stats': {'steady_days': steady, 'event_hits': table_hits,
                'single_days': len(rows) - steady - table_hits}}


def expand_segments(data, segments, *, replay=None):
    """S1 全年只调用一次模板；已给 replay 时直接使用同一份流量。"""
    if replay is None:
        modes = {d: dict(v) for s in segments for d, v in s.get('modes', {}).items()}
        replay = replay_template(data, initial_state(data), data['horizon']['start'],
                                 data['horizon']['end'], modes, segments)
    days = deepcopy(replay['days'])
    settings = _settings(data, {})
    stops, begin = [], None
    for i in range(len(days) + 1):
        row = days[i] if i < len(days) else None
        active = row is not None and (any(sum(row['workshops'][w][k].values())
            for w in (*[v['line'] for v in data['factory']['models'].values()], 'PS') for k in ('in', 'out'))
            or row['phase'] in ('REFILL', 'FIRST_START') and any(settings[row['date']]['caps'].values()))
        if row is not None and not active:
            if begin is None:
                begin = i
            continue
        if begin is None:
            continue
        end = (date.fromisoformat(_resume(data)) - timedelta(days=1)).isoformat() if row is None else days[i - 1]['date']
        length = (date.fromisoformat(end) - date.fromisoformat(days[begin]['date'])).days + 1
        if length >= data['rules']['ps_stop_min_days']:
            pre = days[begin - 1]['date'] if begin else None
            target, source = _stop_target(data, settings, pre, length) if pre else (None, 'DEFAULT')
            stops.append({'start': days[begin]['date'], 'end': end, 'length': length,
                          'pre_stop_date': pre, 'target': target, 'source': source})
            for r in days[begin:i]:
                r['phase'] = 'STOP'
        begin = None
    for row in days:
        row.pop('segment')
    return {'schema': 'aps-core/plan/v1', 'status': 'UNKNOWN', 'days': days,
            'stop_list': stops, 'objective': {'levels': []},
            'findings': prebuild_findings(data, days)}
