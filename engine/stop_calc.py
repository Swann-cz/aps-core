"""STOP-1：SEGMENT_PLAN §12 的独立停线计算器，不接入候选图。"""
from datetime import date
from fractions import Fraction
from math import ceil

from .segment_plan import _limits
from .segments import _resume, needs_clear
from .stop_plan import _stop_release


def _span(data, entry, model, start, last, table, restart):
    """§12.1：理论产量前缀和及段头缺口；不展开日转移。"""
    line = data['factory']['models'][model]['line']
    path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
    settings = table['settings']
    work = [d for d in settings if start <= d <= last and table['rates'][model][d] > 0]
    if not work:
        return None
    target = settings[work[0]]['targets']
    stock = [sum(entry['stock'][n].values()) for n in path]
    losses = [0]
    for n, before in zip(path, stock):
        # 段头损失按链累计抵扣，下游多出的在制抵扣上游缺口。
        losses.append(max(0, losses[-1] + target[n] - before))
    prefix, full, total = [0], [], 0
    for d in work:
        total += table['rates'][model][d]
        prefix.append(total)
        bonus = 0
        if _classify(data, model, d, restart, table)[2] != 'NONE':
            event = _stop_release(data, model, work[0], d, restart, table)
            available = event['fin_out']
            draining = [d]
            if event['clear']:
                # 与 build_schedule 一样向前定位准备日；准备日仍保正常下游水位。
                release, capacity, prep = event['fin_out'], 0, work[0]
                for previous in reversed(work[:len(prefix) - 1]):
                    s = settings[previous]
                    reducible = min(s['caps'][line], s['targets'][line])
                    if previous < d and capacity >= max(0, release - reducible):
                        prep = previous
                        break
                    capacity += min(s['caps'][w] for w in ('PS', 'AS_MAIN', 'AS_FIN'))
                draining = [x for x in work if prep < x <= d]
                # 清线日不再投入，释放库存先补上这些日子的整链基准产量。
                available = max(0, available - sum(table['rates'][model][x] for x in draining))
            extra = sum(max(0, min(settings[x]['caps'][w] for w in ('PS', 'AS_MAIN', 'AS_FIN'))
                            - table['rates'][model][x]) for x in draining)
            bonus = min(available, extra)
        full.append(entry['fok'][model] + max(0, total - losses[-1]) + bonus)
    return {'work': work, 'prefix': prefix, 'full': full, 'losses': losses,
            'path': path, 'stock': stock}


def _classify(data, model, day, restart, table):
    """§12.2：窗口含自然日，胶龄逼清也记 LONG。"""
    s = table['settings'][day]
    line = data['factory']['models'][model]['line']
    W = (date.fromisoformat(restart) - date.fromisoformat(day)).days - 1
    k = ceil(Fraction(s['targets']['WBS'], s['caps'][line]))
    stop_class = ('NONE' if day == data['horizon']['end'] or W < data['rules']['ps_stop_min_days'] else
                  'LONG' if needs_clear(data, model, table['settings'], day, W) else 'SHORT')
    return W, k, stop_class


def _consume(batches, quantity):
    for batch in batches:
        taken = min(quantity, batch['quantity'])
        batch['quantity'] -= taken
        quantity -= taken
    return [b for b in batches if b['quantity']]


def _batches(entry, model, span, pos):
    """§12.4：从入口批次与满产累计焊出量、PS 投入量重建 FIFO。"""
    batches = [dict(b) for b in entry['wbs_batches']]
    prefix, losses = span['prefix'], span['losses']
    for i, d in enumerate(span['work'][:pos]):
        quantity = max(0, prefix[i + 1] - losses[1]) - max(0, prefix[i] - losses[1])
        if quantity:
            batches.append({'date': d, 'model': model, 'quantity': quantity})
    return _consume(batches, max(0, prefix[pos] - losses[2]))


def _tail_edges(data, path, before, s, reserve, tail, retain, stopping):
    """尾差的能力/水位差分约束：沿链求每条流边的最大可行量。"""
    caps = s['caps']
    bounds = [caps[path[0]], caps[path[0]], caps['PS'], caps['PS'],
              caps['AS_MAIN'], min(caps['AS_MAIN'], caps['AS_FIN']), caps['AS_FIN']]
    bounds = [min(q, tail) for q in bounds] if not retain else [*bounds[:-1], min(bounds[-1], tail)]
    physical = {**data['factory']['workshops'], **data['factory']['buffers']}
    upper = [physical[n].get('cap_max', s['targets'][n]) for n in path]
    if not retain:
        upper = [min(u, reserve[n]) for n, u in zip(path, upper)]
    elif stopping:
        upper[2] = min(upper[2], reserve['PS'])
    # 相邻边只受库存差约束；链上任意边的上界可直接传到另一边，无回放或迭代求解。
    edges = list(bounds)
    for source, bound in enumerate(bounds):
        q = bound
        for i in range(source, len(path)):
            q = max(0, q + before[i] - reserve[path[i]])
            edges[i + 1] = min(edges[i + 1], q)
        q = bound
        for i in reversed(range(source)):
            q = max(0, q + upper[i] - before[i])
            edges[i] = min(edges[i], q)
    water = [before[i] + edges[i] - edges[i + 1] for i in range(len(path))]
    if (edges[-1] != tail or edges[0] <= 0
            or any(not reserve[n] <= q <= u for n, q, u in zip(path, water, upper))
            or any(edges[i] == 0 and edges[i + 1] > 0 for i in (0, 4, 5))
            or not stopping and edges[2] == 0 and edges[3] > 0):
        return None
    return edges, water


def _candidate(data, entry, model, goal, lower, upper, restart, span, table, fixed=None, shape=None):
    """§12.1/12.4：一个 F 的停点、形态及供下月使用的出口水位。"""
    pos = next((i for i, f in enumerate(span['full']) if f >= goal), None)
    if pos is None or goal <= entry['fok'][model]:
        return None
    work, path = span['work'], span['path']
    day = work[pos]
    W, k, stop_class = _classify(data, model, day, restart, table)
    if stop_class == 'LONG':
        goal = span['full'][pos]
        if goal > upper:
            pos -= 1
            if pos < 0 or span['full'][pos] < lower:
                return None
            day, goal = work[pos], span['full'][pos]
            W, k, stop_class = _classify(data, model, day, restart, table)
    if fixed is not None and day != fixed:
        return None
    previous = entry['fok'][model] + max(0, span['prefix'][pos] - span['losses'][-1])
    tail = goal - previous
    s = table['settings'][day]
    full_tail = span['full'][pos] - previous
    if not lower <= goal <= upper or not 0 < tail <= full_tail:
        return None
    if span['prefix'][pos] < max(span['losses']):
        # TODO(边界): 停点仍在补线期内属于 §11 非正常清线，本计算器不展开。
        return None
    event = (_stop_release(data, model, work[0], day, restart, table)
             if stop_class != 'NONE' else None)
    reserve = {n: s['targets'][n] - (event['release'][n] if event else 0) for n in path}
    if stop_class == 'LONG':
        if shape == 'RETAIN':
            return None
        shape = 'SYNC'
        # TODO(边界): LONG 不使用 quantity/retain_water；非标准清线末日供给仍交回放核对。
        water, batches = [reserve[n] for n in path], []
    else:
        total = span['prefix'][pos]
        full_edges = [max(0, total - loss) for loss in span['losses']]
        before = [q + full_edges[i] - full_edges[i + 1] for i, q in enumerate(span['stock'])]
        batches = _batches(entry, model, span, pos)
        age = data['factory']['models'][model]['glue_age_max']
        physical = {**data['factory']['workshops'], **data['factory']['buffers']}
        space = sum(max(0, physical[n]['cap_max'] - s['targets'][n])
                    for n in path[3:] if 'cap_max' in physical[n])
        drop = event['release']['PS'] if event else 0
        for shape in (('SYNC', 'RETAIN') if shape is None else (shape,)):
            if shape == 'RETAIN' and tail <= drop and space < drop - tail + 1:
                continue
            result = _tail_edges(data, path, before, s, reserve, tail, shape == 'RETAIN', event is not None)
            if result is None:
                continue
            edges, water = result
            remaining = [dict(b) for b in batches]
            if edges[1]:
                remaining.append({'date': day, 'model': model, 'quantity': edges[1]})
            remaining = _consume(remaining, edges[2])
            if any((date.fromisoformat(restart) - date.fromisoformat(b['date'])).days > age
                   for b in remaining):
                continue
            batches = remaining
            break
        else:
            return None
    exit_entry = {**entry, 'stock': {n: dict(v) for n, v in entry['stock'].items()},
                  'fok': {**entry['fok'], model: goal}, 'wbs_batches': batches}
    for n, q in zip(path, water):
        exit_entry['stock'][n][model] = q
    candidate = {'fok': goal, 'date': day, 'tail': tail, 'full_tail': full_tail, 'W': W, 'k': k,
                 'stop_class': stop_class, 'shape': shape}
    return candidate, exit_entry


def _next_tail(data, entry, model, month, restart, table):
    """§12.5：只预检紧接的一个月，不递归生成候选。"""
    months = sorted(data['demand']['PR'][model])
    pos = months.index(month) + 1
    if pos == len(months):
        return True, None, None
    following = months[pos]
    lower, upper = _limits(data, following, table['prebuild'])[model]
    if entry['fok'][model] >= lower:
        return True, 0, None
    days = [d for d in table['settings'] if d[:7] == following]
    start = max(restart, days[0])
    if start > days[-1]:
        return False, None, None
    next_start = next((d for d in table['settings'] if d > days[-1]
                       and table['rates'][model][d] > 0), _resume(data))
    span = _span(data, entry, model, start, days[-1], table, next_start)
    if span is None:
        return False, None, None
    result = _candidate(data, entry, model, lower, lower, upper, next_start, span, table)
    if result is None:
        return False, None, None
    candidate, _ = result
    return True, candidate['tail'], candidate['shape']


def stop_candidates(data, entry, month, first, last, segment, table) -> list[dict]:
    """§12.3/12.5/12.7：按四类标签返回候选，同一 F 可保留两种尾差形态。"""
    model = segment['model']
    line = data['factory']['models'][model]['line']
    path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
    start = max(first, segment['start'])
    if (segment['tail']['type'] == 'CHANGEOVER' or segment['start'] > first
            or entry['current_model'] not in (None, model)
            or any(q for n in entry['stock'] for m, q in entry['stock'][n].items() if m != model)
            or any(p['type'] in ('CHANGEOVER', 'INITIAL_DRAIN') for p in entry['pending_phases'])):
        # TODO(边界): 换型片段、双换型和期初异车型排空不适用 §12 第一期。
        return []
    physical = {**data['factory']['workshops'], **data['factory']['buffers']}
    if (any(sum(entry['stock'][n].values()) > table['settings'][start]['targets'][n]
            and ('cap_max' not in physical[n]
                 or sum(entry['stock'][n].values()) > physical[n]['cap_max']) for n in path)
            or any(c['type'] in ('WIP_TARGET', 'FIXED_OUTPUT')
                   and c.get('start', c.get('date')) <= last
                   and c.get('end', c.get('date')) >= first for c in data['conditions'])
            or segment.get('anticipate_buffers') or segment['tail'].get('hold_buffers')
            or segment['tail'].get('level_drains')):
        # TODO(边界): 超目标且无物理上限或超物理上限、人工目标/固定产量和非标准蓄车交现有模板。
        return []
    window = segment['tail'].get('stop_window')
    fixed = window['pre_stop'] if window else None
    restart = window['restart'] if window else segment['next_start']
    span = _span(data, entry, model, start, min(last, fixed) if fixed else last, table, restart)
    if span is None:
        return []
    lower, upper = _limits(data, month, table['prebuild'])[model]
    goals = [('DEMAND', lower), ('UPPER', upper)]
    for label, stop_class in (('NO_CLEAR', 'SHORT'), ('NO_STOP', 'NONE')):
        day = next((d for d in span['work'] if (fixed is None or d == fixed)
                    and _classify(data, model, d, restart, table)[2] == stop_class), None)
        if day is not None:
            goals.append((label, span['full'][span['work'].index(day)]))
    candidates = []
    for label, goal in goals:
        if not lower <= goal <= upper:
            continue
        result = _candidate(data, entry, model, goal, lower, upper, restart, span, table, fixed)
        if result is None:
            continue
        candidate, exit_entry = result
        origin = candidate['fok']
        valid, next_tail, next_shape = _next_tail(data, exit_entry, model, month, restart, table)
        if not valid:
            # 距离相同先查较小 F；LONG 只接受本身就是满产累计的格点。
            for distance in range(1, max(origin - lower, upper - origin) + 1):
                for adjusted in (origin - distance, origin + distance):
                    if not lower <= adjusted <= upper:
                        continue
                    trial = _candidate(data, entry, model, adjusted, lower, upper, restart, span, table, fixed)
                    if trial is None or trial[0]['fok'] != adjusted:
                        continue
                    check = _next_tail(data, trial[1], model, month, restart, table)
                    if check[0]:
                        candidate, exit_entry = trial
                        valid, next_tail, next_shape = check
                        break
                if valid:
                    break
        if valid:
            variants = [(candidate, exit_entry)]
            if candidate['stop_class'] != 'LONG':
                other = 'RETAIN' if candidate['shape'] == 'SYNC' else 'SYNC'
                alternative = _candidate(data, entry, model, candidate['fok'], lower, upper,
                                         restart, span, table, fixed, shape=other)
                if alternative is not None and alternative[0]['fok'] == candidate['fok']:
                    variants.append(alternative)
            for variant, exit_entry in variants:
                check = _next_tail(data, exit_entry, model, month, restart, table)
                if check[0] and all((c['fok'], c['shape']) != (variant['fok'], variant['shape'])
                                    for c in candidates):
                    candidates.append({'label': label, **variant, 'next_tail': check[1],
                                       'next_shape': check[2], 'adjusted': variant['fok'] != origin})
    return candidates
