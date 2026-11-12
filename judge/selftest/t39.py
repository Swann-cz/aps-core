"""T-39-N：rev 206 停前上限、供给下限与短停后的补线延续（合成输入）。"""
from datetime import date, timedelta

from judge.constraints import check_level_drain, check_pre_stop
from judge.core import Judge
from judge.model import InputModel

from .t36 import _build, _judge, _make_input


def _input():
    raw = _make_input()
    raw['horizon'] = {'start': '2026-04-01', 'end': '2026-04-08'}
    raw['calendar'] = [
        {'date': (date(2026, 4, 1) + timedelta(days=i)).isoformat(),
         'is_working_capable': i not in (3, 4, 5)} for i in range(8)]
    raw['demand'] = {'PR': {'A': {'2026-04': 2000}}, 'WS_daily': {'A': {}}}
    return raw


def run_t39_cases():
    failures, total = [], 0

    def check(name, ok, detail):
        nonlocal total
        total += 1
        if not ok:
            failures.append(name)
        print(f"[{'PASS' if ok else 'FAIL'}] T-39-N {name}")
        print(f'   {detail}\n')

    raw = _input()
    raw['factory']['workshops']['BS1']['jph'] = 2.5
    raw['initial']['wip']['PS'] = {}
    # 停线内正常目标降低不能提前结束补线；人工停前目标仍优先取 131。
    raw['conditions'] = [
        {'id': 'LOW', 'type': 'WIP_TARGET', 'node': 'PS', 'start': '2026-04-04',
         'end': '2026-04-06', 'target': 30},
        {'id': 'PRE', 'type': 'PRE_STOP_TARGET', 'pre_stop_date': '2026-04-03', 'target': 131}]
    inp = InputModel(raw)
    flows = {d: {'BS1': 20, 'PS': (20, 0)}
             for d in ('2026-04-01', '2026-04-02', '2026-04-03', '2026-04-07', '2026-04-08')}
    plan = _build(inp, flows)
    j = _judge(inp, plan)
    check('a 补线遇短停，停前 PS 60、无出车 → ACCEPT',
          j.node_eod_total('2026-04-03', 'PS') == 60 and not j.hard_errors,
          f'硬错误 = {[(e.rule, e.date, e.detail) for e in j.hard_errors]}')
    check('e 复工 PS 80 < tgt，仍为 REFILL、不报 C8；停线日不算补线日',
          'REFILL' in j.phases['2026-04-07'].split('+')
          and all('REFILL' not in j.phases[d].split('+')
                  for d in ('2026-04-04', '2026-04-05', '2026-04-06'))
          and not any(e.rule == 'C8' and e.date == '2026-04-07' for e in j.hard_errors),
          f'阶段 = {j.phases}')
    # 同一流量也覆盖清线后补线的独立识别入口。
    after = Judge(inp, plan)
    after.recompute_inventory()
    after.compute_phases()
    after.phases = {d: '+'.join(p for p in ph.split('+') if p != 'REFILL') or 'NORMAL'
                    for d, ph in after.phases.items()}
    after._add_refill_after('BS1', date(2026, 3, 1), date(2026, 3, 31))
    check('清线后补线入口同样跨短停延续',
          'REFILL' in after.phases['2026-04-07'].split('+')
          and 'REFILL' not in after.phases['2026-04-04'].split('+'),
          f'阶段 = {after.phases}')

    def pre_stop(ps_eod, pbs=None, available=None):
        raw = _input()
        raw['horizon']['start'] = '2026-04-03'
        raw['calendar'] = [r for r in raw['calendar'] if r['date'] >= '2026-04-03']
        if pbs is not None:
            raw['wip_targets']['PBS'] = 45
            raw['initial']['wip']['PBS'] = {'A': pbs}
            raw['conditions'] = [{'id': 'PBS', 'type': 'WIP_TARGET', 'node': 'PBS',
                                  'start': '2026-04-04', 'end': '2026-04-06', 'target': 50}]
        if available is not None:
            raw['initial']['wip']['PS'] = {'A': available}
        inp = InputModel(raw)
        supply = raw['initial']['wip']['PS']['A']
        out = supply - ps_eod
        plan = _build(inp, {'2026-04-03': {'PS': (0, out), 'AS_MAIN': out, 'AS_FIN': out},
                            '2026-04-07': {'BS1': 80, 'PS': 80, 'AS_MAIN': 80, 'AS_FIN': 80},
                            '2026-04-08': {'BS1': 80, 'PS': 80, 'AS_MAIN': 80, 'AS_FIN': 80}})
        j = Judge(inp, plan)
        j.recompute_inventory()
        j.compute_phases()
        check_pre_stop(j)
        return j

    for name, value, pbs, error in (
            ('b PBS 正常 45、停前水位 50，EOD 47 合规', 131, 47, False),
            ('c PS 132 > 131 仍报 PS_PRE_STOP', 132, None, True),
            ('d 供给充足时 PS 125 < 131 仍报 PS_PRE_STOP', 125, None, True)):
        j = pre_stop(value, pbs)
        check(name, bool(j.hard_errors) == error,
              f'停前错误 = {[(e.node, e.detail) for e in j.hard_errors]}')

    j = pre_stop(60, available=61)
    check('车不足时仍须全部保留，供给 61 却只留 60 → PS_PRE_STOP',
          any(e.rule == 'PS_PRE_STOP' and e.node == 'PS' for e in j.hard_errors),
          f'停前错误 = {[(e.node, e.detail) for e in j.hard_errors]}')

    def higher_pbs(main_input):
        raw = _input()
        raw['wip_targets']['PBS'] = 45
        raw['initial']['wip']['PBS'] = {'A': 65}
        raw['factory']['workshops']['AS_MAIN']['jph'] = 13.75
        raw['conditions'] = [
            {'id': 'PBS', 'type': 'WIP_TARGET', 'node': 'PBS', 'start': '2026-04-04',
             'end': '2026-04-06', 'target': 50},
            {'id': 'MAIN', 'type': 'WIP_TARGET', 'node': 'AS_MAIN', 'start': '2026-04-04',
             'end': '2026-04-06', 'target': 0}]
        inp = InputModel(raw)
        flows = {d: {'BS1': 80, 'PS': 80, 'AS_MAIN': (inn, 110), 'AS_FIN': 110}
                 for d, inn in (('2026-04-01', main_input), ('2026-04-02', 80),
                                ('2026-04-03', 80), ('2026-04-07', 80), ('2026-04-08', 80))}
        j = Judge(inp, _build(inp, flows))
        j.recompute_inventory()
        j.compute_phases()
        check_level_drain(j)
        return [e for e in j.hard_errors if e.rule == 'PS_PRE_STOP'
                and e.date == '2026-04-01' and e.node == 'AS_MAIN']

    for amount, error in ((95, False), (100, True)):
        errors = higher_pbs(amount)
        check(f'PBS 正常 45、停前水位 50：主线投 {amount}，PS_PRE_STOP={error}',
              bool(errors) == error, f'提前降库错误 = {[e.detail for e in errors]}')

    print(f'== T-39-N 结果：{total - len(failures)}/{total} ==')
    return total, len(failures)


if __name__ == '__main__':
    raise SystemExit(bool(run_t39_cases()[1]))
