"""T-38：按输入水位、逐月 C12 预算预判相邻月份的停线候选。"""
from datetime import date, timedelta
from fractions import Fraction
from math import ceil

from .conditions import stop_level
from .segments import _stop_target, needs_clear


def predict_stop(data, entry, start, pre, restart, table, limits):
    """只缩小首轮候选域；合法性仍交给原模板，失败后由调用方完整枚举。"""
    month = start[:7]
    previous_month = (date.fromisoformat(pre[:7] + '-01') - timedelta(days=1)).strftime('%Y-%m')
    if month not in (pre[:7], previous_month):
        return None
    settings = table['settings']
    model = entry['current_model'] or max(data['factory']['models'],
        key=lambda m: sum(v[m] for v in entry['stock'].values()))
    line = data['factory']['models'][model]['line']
    work = [d for d in settings if start <= d <= pre
            and settings[d]['caps'][line] and settings[d]['caps']['PS']]
    if not work:
        return None
    stop_start = (date.fromisoformat(pre) + timedelta(days=1)).isoformat()
    stop_end = (date.fromisoformat(restart) - timedelta(days=1)).isoformat()
    levels = {n: stop_level(data, n, stop_start, stop_end, days=table['stop_days'])
              for n in ('PS', 'PBS', 'AS_MAIN', 'AS_FIN')}
    length = (date.fromisoformat(restart) - date.fromisoformat(pre)).days - 1
    clear = needs_clear(data, model, settings, pre, length)
    if not any(v is not None for v in levels.values()) and not clear:
        return None
    target, _ = _stop_target(data, settings, pre, length, days=table['stop_days'])
    reserve = {**settings[start]['targets'], 'PS': target}
    if clear:
        reserve.update({line: 0, 'WBS': 0})
    reserve.update({n: value[0] for n, value in levels.items() if value is not None and n != 'PS'})
    path = (line, 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN')
    release = {n: settings[start]['targets'][n] - reserve[n] for n in path}
    ps_out = sum(release[n] for n in path[:3])
    fin_out = sum(release.values())
    # TODO(边界): 降库天数按原停前日产能折算；期间目标或产能变化仍由精确回放及完整枚举处理。
    ps_cap = table['stop_default'][pre]['caps']['PS']
    extra = max(0, fin_out - ps_out)
    high = min(table['stop_high'][pre]['caps'][w] for w in ('AS_MAIN', 'AS_FIN'))
    difference = high - ps_cap
    # 差非正时不生成提前降库候选；原完整枚举仍由调用方保留。
    if ps_cap <= 0 or extra > 0 and difference <= 0:
        return {'before': [], 'release': release, 'ps_out': ps_out, 'fin_out': fin_out}
    paint_days = max(0, ceil(Fraction(ps_out, ps_cap)))
    advance_days = ceil(Fraction(extra, difference)) if extra else 0
    normal = [0]
    for d in work:
        normal.append(normal[-1] + table['rates'][model][d])
    # 第 7 轮：人工停前目标匹配自然停前日时固定日期，不参与提前停线预算搜索。
    fixed = settings[pre]['manual'] is not None
    before = [pre] if fixed else []
    if not fixed:
        for pos, d in enumerate(work):
            # 从本月入口累计 FOK 开始，跨月逐个使用该月上限；超支即止，
            # 不能借后一个月上涨的累计上限越过前一个月的超支日。
            count = max(0, pos + 1 - paint_days) if clear else pos + 1
            reducible = (min(settings[work[count - 1]]['caps'][line],
                             settings[work[count - 1]]['targets'][line]) if clear and count else 0)
            projected = entry['fok'][model] + normal[count] - reducible + fin_out
            if projected > limits[d[:7]][model][1]:
                break
            before.append(d)
        before = list(reversed(before[-2:]))
    starts, preparations = {}, {}
    for d in before:
        pos = work.index(d)
        drain = pos - max(1, advance_days) + 1
        starts[d] = ([work[i] for i in (drain + 1, drain, drain - 1) if 0 <= i <= pos]
                     if advance_days and clear else [])
        prep = pos - max(1, paint_days)
        preparations[d] = ([work[i] for i in (prep + 1, prep, prep - 1) if 0 <= i <= pos]
                           if clear else [])
    if month == previous_month:
        # 只有清线准备或提前降库确实落入本月，才生成跨月候选。
        before = [d for d in before if d[:7] == month or any(
            x[:7] == month for x in (*starts[d], *preparations[d]))]
        if not before:
            return None
    return {'before': before, 'starts': starts, 'preparations': preparations,
            'release': release, 'ps_out': ps_out, 'fin_out': fin_out,
            'paint_days': paint_days, 'advance_days': advance_days}
