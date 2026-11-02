"""Monthly capacity relaxation and welding block guide for the daily search."""
from fractions import Fraction
from math import ceil, floor
from time import perf_counter

from ortools.sat.python import cp_model
from .conditions import prepare


def prebuild(data):
    """C12 rev 204：各车型独立按授权内日瓶颈产能计算必须提前量。"""
    days = sorted(r['date'] for r in data['calendar']
                  if data['horizon']['start'] <= r['date'] <= data['horizon']['end'])
    months = sorted({d[:7] for d in days})
    _, available, allowed, hours, *_ = prepare(data, days)
    factory = data['factory']
    max_cap = {(w, i): (max(floor(hours[w, i][mode] * factory['workshops'][w]['jph'])
                            for mode in allowed[w, i]) if available[w, i] else 0)
               for w in factory['workshops'] for i in range(len(days))}
    out = {}
    for m, info in factory['models'].items():
        cap = {mo: 0 for mo in months}
        for i, d in enumerate(days):
            cap[d[:7]] += min(max_cap[w, i] for w in (info['line'], 'PS', 'AS_MAIN', 'AS_FIN'))
        pr = data['demand']['PR'].get(m, {})
        out[m] = {}
        for k, mo in enumerate(months):
            need, best = 0, 0
            for j in months[k + 1:]:
                need += pr.get(j, 0) - cap[j]
                best = max(best, need)
            out[m][mo] = best
    return out


def prebuild_findings(data, days):
    """只说明实际发生、且超出普通月度浮动的提前生产。"""
    early = prebuild(data)
    months = sorted({r['date'][:7] for r in days})
    ratio = Fraction(str(data['rules']['monthly_band_ratio']))
    findings = []
    for m, pr in data['demand']['PR'].items():
        done = total = 0
        for k, mo in enumerate(months):
            done += sum(r['fok'].get(m, 0) for r in days if r['date'][:7] == mo)
            total += pr.get(mo, 0)
            following = pr.get(months[k + 1], 0) if k + 1 < len(months) else 0
            if done > total and early[m][mo] > ratio * following:
                findings.append(f"{mo} 车型 {m} 因后面月份做不完提前生产 {done - total} 台"
                                f"（必须提前量 {early[m][mo]} 台）")
    return findings


def monthly_plan(data, days, working, capacities):
    started = perf_counter()
    factory = data['factory']
    vehicles = list(factory['models'])
    months = sorted({day[:7] for day in days})
    pr = data['demand']['PR']
    ratio = Fraction(str(data['rules']['monthly_band_ratio']))
    early = prebuild(data)
    lines = {m: factory['models'][m]['line'] for m in vehicles}
    cap = {m: capacities[lines[m]][factory['default_mode']] for m in vehicles}
    available = {mo: sum(work for day, work in zip(days, working) if day[:7] == mo) for mo in months}
    initial = {m: sum(row.get(m, 0) for row in data['initial']['wip'].values()) for m in vehicles}
    bounds = {}
    coarse = cp_model.CpModel()
    quantity, weld_days, stock, used = {}, {}, {}, {}
    shortfalls = []
    for m in vehicles:
        cum = 0
        for p, mo in enumerate(months):
            cum += pr[m][mo]
            lower = cum - ratio * pr[m][mo]
            upper = floor(cum + max(ratio * pr[m][months[p + 1]], early[m][mo])) if p + 1 < len(months) else cum
            bounds[m, mo] = (lower, upper)
            quantity[m, mo] = coarse.new_int_var(0, upper, f'q:{m}:{mo}')
            weld_days[m, mo] = coarse.new_int_var(0, available[mo], f'd:{m}:{mo}')
            stock[m, mo] = coarse.new_int_var(0, cap[m] * sum(available.values()) + initial[m], f's:{m}:{mo}')
            weld_quantity = coarse.new_int_var(0, cap[m] * available[mo], f'in:{m}:{mo}')
            coarse.add(weld_quantity <= cap[m] * weld_days[m, mo])
            coarse.add(weld_quantity >= cap[m] * (weld_days[m, mo] - 1) + 1)
            before = stock[m, months[p - 1]] if p else initial[m]
            coarse.add(stock[m, mo] == before + weld_quantity - quantity[m, mo])
            cumulative = sum(quantity[m, t] for t in months[:p + 1])
            coarse.add(cumulative <= upper)
            gap = coarse.new_int_var(0, ratio.denominator * cum, f'gap:{m}:{mo}')
            coarse.add_max_equality(gap, [0, int(lower * ratio.denominator) - ratio.denominator * cumulative])
            shortfalls.append(gap)
        used[m] = coarse.new_bool_var(f'used:{m}')
        coarse.add(sum(weld_days[m, mo] for mo in months) > 0).only_enforce_if(used[m])
        coarse.add(sum(weld_days[m, mo] for mo in months) == 0).only_enforce_if(used[m].Not())
    for mo in months:
        coarse.add(sum(weld_days[m, mo] for m in vehicles) <= available[mo])
        coarse.add(sum(quantity[m, mo] for m in vehicles) <= capacities['AS_FIN'][factory['default_mode']] * available[mo])
    occupied = [m for m in vehicles if data['initial']['wip'].get(lines[m], {}).get(m, 0)]
    # Every newly used other line requires at least one old-line zero-IN drain
    # day. Other clearing/startup losses are relaxed to zero: a valid lower bound.
    minimum_drains = sum(used[m] for m in vehicles if occupied and m not in occupied)
    coarse.add(sum(weld_days.values()) + minimum_drains <= sum(available.values()))
    shortage = sum(sum(pr[m].values()) for m in vehicles) - sum(quantity.values())
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 0
    solver.parameters.num_workers = 1
    solver.parameters.max_deterministic_time = 1.0
    coarse.minimize(shortage)
    status = solver.solve(coarse)
    # The default-mode block guide does not bound an overtime-enabled model.
    lower_bound = (0 if any(c["type"] == "MODE_AUTH" for c in data["conditions"])
                   else ceil(solver.best_objective_bound))
    # The bound above is the relaxation. The block guide below reserves the
    # current line and shared WIP, and charges zero-IN drain days separately.
    order = occupied[0] if occupied else vehicles[0]
    guide_switches = []
    shared_target = sum(value for node, value in data['wip_targets'].items() if node not in lines.values())
    for mo in months:
        sequence = [order] + [m for m in vehicles if m != order and pr[m][mo]]
        for m in vehicles:
            if m not in sequence:
                coarse.add(weld_days[m, mo] == 0)
        losses = 0
        for m in sequence:
            if m != order:
                losses += ceil(data['wip_targets'][lines[order]] / cap[order])
                guide_switches.append((mo, m))
                order = m
        month_indices = [i for i, day in enumerate(days) if day[:7] == mo]
        for i in month_indices:
            if working[i] and i + 1 < len(days) and not working[i + 1]:
                after = i + 1
                while after < len(days) and not working[after]:
                    after += 1
                if after - i - 1 >= factory['models'][order]['glue_age_max']:
                    losses += ceil(data['wip_targets'][lines[order]] / cap[order])
        coarse.add(sum(weld_days[m, mo] for m in vehicles) <= max(0, available[mo] - losses))
        # C16: after the last model completes cars, shared WIP belongs to it;
        # preceding models cannot remain in those nodes as target reserve.
        coarse.add(stock[order, mo] >= shared_target + data['wip_targets'][lines[order]])
        physical_reserve = sum(
            factory['buffers'][n]['cap_max'] if n in factory['buffers'] else
            max(factory['workshops'][n].get('cap_max', target), sum(data['initial']['wip'].get(n, {}).values()))
            for n, target in data['wip_targets'].items()
            if n not in lines.values() or n == lines[order]
        )
        coarse.add(stock[order, mo] <= physical_reserve)
        for m in vehicles:
            if m != order:
                coarse.add(stock[m, mo] == 0)
        print(f'monthly_reserve month={mo}; drain_days={losses}; ending_owner={order}', flush=True)
    coarse.minimize(shortage)
    solver.solve(coarse)
    coarse.add(shortage == solver.value(shortage))
    coarse.minimize(sum(shortfalls))
    solver.solve(coarse)
    coarse.add(sum(shortfalls) == solver.value(sum(shortfalls)))
    coarse.minimize(sum(stock.values()))
    solver.solve(coarse)
    rows = []
    order = occupied[0] if occupied else vehicles[0]
    for mo in months:
        planned = {m: solver.value(quantity[m, mo]) for m in vehicles}
        # Carry the previous owner across the month boundary; each needed model
        # gets one block. Startup reserve is derived from its line target.
        sequence = [order] + [m for m in vehicles if m != order and planned[m]]
        sequence = [m for m in sequence if planned[m]]
        for m in sequence:
            rows.append({'month': mo, 'model': m, 'planned_fok': planned[m],
                         'welding_days': solver.value(weld_days[m, mo]),
                         'lower': float(bounds[m, mo][0]), 'upper': bounds[m, mo][1]})
        for m in vehicles:
            if m not in sequence:
                rows.append({'month': mo, 'model': m, 'planned_fok': planned[m],
                             'welding_days': solver.value(weld_days[m, mo]),
                             'lower': float(bounds[m, mo][0]), 'upper': bounds[m, mo][1]})
        if sequence:
            order = sequence[-1]
    print(f'monthly_seconds={perf_counter() - started:.6f}; L1a_lower_bound={lower_bound}; relaxation_status={solver.status_name(status)}', flush=True)
    for row in rows:
        print('monthly ' + ' '.join(f'{k}={v}' for k, v in row.items()), flush=True)
    print(f'monthly_switches={guide_switches}', flush=True)
    return lower_bound, rows, guide_switches
