"""CP-SAT generator for S1a through S1d functional cases."""
from __future__ import annotations

from calendar import SATURDAY
from copy import deepcopy
from datetime import date, timedelta
from fractions import Fraction
from math import ceil, floor
from threading import Event, Thread
from time import perf_counter

from ortools.sat.python import cp_model

from .monthly import monthly_plan, prebuild, prebuild_findings
from .conditions import prepare, stop_days, stop_level
from .templates import clear_rows, refill_rows

# CP-SAT deterministic seconds; computational budgets, not business parameters.
# Annual L1a uses the block seed; L1c/L5 use monthly neighborhoods below.
# Do not repeat full-horizon searches after these passes. Zero budgets retain
# the incumbent and leave nonzero levels explicitly unproven.
LEVEL_BUDGETS = {
    "L1a": 0.0, "L1b": 1.0, "L1c": 0.0, "L2": 0.0,
    "L3a": 0.0, "L3b": 1.0, "L4": 1.0, "L5": 0.0, "L6": 0.0,
}
SMALL_LEVEL_BUDGETS = {level: 300.0 for level in LEVEL_BUDGETS}
SMALL_MODEL_VARIABLES = 10000
INITIAL_SOLUTION_BUDGET = 75.0
# S4b computational budgets, not business parameters. The old fixed-plan check
# and L4/L5/L6 solves each allowed 2.0 deterministic seconds: 4 * 2.0 = 8.0
# bounds their combined budget; this is a budget-derived bound, not a measurement.
SEGMENT_REFINE_DETERMINISTIC = 2.0
SEGMENT_REFINE_DETERMINISTIC_TOTAL = 8.0
SEGMENT_REFINE_SAFETY_SECONDS = 120.0


def hint_all(search, source, size):
    """Copy the same ordered hint in bulk instead of querying each variable."""
    search.clear_hints()
    search.proto.solution_hint.vars.extend(range(size))
    search.proto.solution_hint.values.extend(list(source.response_proto.solution)[:size])


def result(status: str, findings: list[str]) -> dict:
    return {
        "schema": "aps-core/plan/v1", "status": status, "days": [],
        "stop_list": [], "objective": {"levels": []}, "findings": findings,
    }


def clearing_input_findings(data, days, available, allowed_modes, effective_hours, targets, manual):
    """Quantify the fixed-throughput clearing conflict using input stock bounds."""
    factory = data["factory"]
    workshops = list(factory["workshops"])
    lines = {settings["line"] for settings in factory["models"].values()}
    findings = []

    def capacity(w, i, mode):
        return floor(Fraction(str(effective_hours[w, i][mode]))
                     * Fraction(str(factory["workshops"][w]["jph"])))

    off = [not any(available[w, i] for w in workshops) for i in range(len(days))]
    for begin in range(1, len(days)):
        if not off[begin] or off[begin - 1]:
            continue
        end = begin
        while end + 1 < len(days) and off[end + 1]:
            end += 1
        length = end - begin + 1
        if length < max(settings["glue_age_max"] for settings in factory["models"].values()):
            continue
        if length < data["rules"]["ps_long_stop_days"]:
            continue
        if len(lines) > 1 and any(sum(data["initial"]["wip"].get(line, {}).values())
                                  > sum(available[line, i] for i in range(begin)) for line in lines):
            continue
        pre = begin - 1
        rates = {capacity("AS_FIN", i, k) for i in range(begin) for k in allowed_modes["AS_FIN", i]}
        rates.discard(0)
        if len(rates) != 1:
            continue
        rate = rates.pop()
        limits = {n: max(settings["cap_max"], sum(data["initial"]["wip"].get(n, {}).values()))
                  for n, settings in factory["buffers"].items()}
        limits.update({w: max([settings.get("cap_max", targets[w, i]) for i in range(begin)]
                             + [sum(data["initial"]["wip"].get(w, {}).values())])
                       for w, settings in factory["workshops"].items()})
        weld_caps = {line: max(capacity(line, i, k) for i in range(begin)
                              for k in allowed_modes[line, i]) for line in sorted(lines)}
        level = stop_level(data, "PS", days[begin], days[end])
        stop_targets = {manual[pre]["target"] if pre in manual else
                        level[0] if level is not None else data["rules"]["ps_pre_stop_target_long"]}
        levels = {n: stop_level(data, n, days[begin], days[end]) for n in ("PBS", "AS_MAIN", "AS_FIN")}
        downstream = sum(levels[n][0] if levels[n] is not None else targets[n, pre]
                         for n in ("PBS", "AS_MAIN", "AS_FIN"))
        shared_limit = sum(limits[n] for n in ("WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"))
        total_days = max((shared_limit + limits[line] + weld_caps[line] - downstream - target) // rate
                         for line in lines for target in stop_targets)
        work = [i for i in range(begin) if available["AS_FIN", i]]
        recent = work[-total_days:]
        if not recent or any(targets[n, i] != targets[n, pre] for i in recent
                             for n in ("WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")):
            continue
        if any({capacity(w, i, k) for k in allowed_modes[w, i]} != {0, rate}
               for i in recent for w in ("PS", "AS_MAIN", "AS_FIN")):
            continue
        cases = []
        for target in sorted(stop_targets, reverse=True):
            released = targets["WBS", pre] + targets["PS", pre] - target
            # PS OUT equals the maximum AS_MAIN IN throughout clearing and
            # its preceding day, so PBS cannot fall from above its final target.
            # A changeover empties the old BS line before starting the new line.
            refined = {line: shared_limit - limits["PBS"] + targets["PBS", pre]
                       + limits[line] + weld_caps[line] - downstream - target for line in sorted(lines)}
            if released <= rate or any((clearing_days + 1) * rate <= bound
                                       for clearing_days in range(2, total_days) for bound in refined.values()):
                break
            explanation = (f"PS 停前目标 {target} 台时，单个清线生产日至少释放 {released} 台，"
                           f"当日最多 {rate} 台，差至少 {released - rate} 台")
            for clearing_days in range(2, total_days):
                required = (clearing_days + 1) * rate
                bounds = "、".join(f"{line} 最多 {bound} 台（差 {required - bound} 台）"
                                  for line, bound in refined.items())
                explanation += f"；{clearing_days} 个清线生产日连同前一天需 {required} 台，{bounds}"
            cases.append(explanation)
        else:
            findings.append(f"【停前出清输入核算】CORE_MODEL §5 BS 清线及清线前一天、C4、C6："
                            f"{days[begin]} 至 {days[end]} 连续全线停线 {length} 天；"
                            + "；".join(cases)
                            + f"；全链物理上限还将清线及前一天限制为至多 {total_days} 个生产日。"
                            "上述为停前出清必要条件的输入数量冲突，不据此把求解状态改为不可行证明。")
    return findings


def solve(data: dict, warm_start: dict | None = None) -> dict:
    cold = _solve(data, seed_with_targets=True)
    if warm_start is None:
        return cold
    warm = _solve(data, warm_start)
    if warm is None or not warm["days"]:
        return cold
    if not cold["days"]:
        return warm
    cold_values = tuple(row["value"] for row in cold["objective"]["levels"])
    warm_values = tuple(row["value"] for row in warm["objective"]["levels"])
    return warm if warm_values < cold_values else cold


def refine_segment(data: dict, plan: dict) -> dict:
    started = perf_counter()
    deterministic_used = 0.0
    active_solver = None
    finished = Event()
    timed_out = Event()

    def stop_on_timeout():
        if finished.wait(max(0, started + SEGMENT_REFINE_SAFETY_SECONDS - perf_counter())):
            return
        timed_out.set()
        print(f"segment_refine=retained; reason=wall_clock_safety; "
              f"limit_seconds={SEGMENT_REFINE_SAFETY_SECONDS}; 已停止库存细调，沿用段级排产结果。", flush=True)
        # Repeat until refinement exits, including a timeout just before Solve starts.
        while not finished.is_set():
            solver = active_solver
            if solver is not None:
                solver.stop_search()
            finished.wait(0.1)

    def refine_solve(solver, search):
        nonlocal deterministic_used, active_solver
        remaining = SEGMENT_REFINE_DETERMINISTIC_TOTAL - deterministic_used
        if timed_out.is_set() or remaining <= 0:
            return cp_model.UNKNOWN
        solver.parameters.max_deterministic_time = min(SEGMENT_REFINE_DETERMINISTIC, remaining)
        active_solver = solver
        status = solver.solve(search)
        active_solver = None
        deterministic_used += solver.deterministic_time
        if timed_out.is_set() or deterministic_used > SEGMENT_REFINE_DETERMINISTIC_TOTAL:
            return cp_model.UNKNOWN
        return status

    # 仅实际用到 rev 206 停前范围的候选增加范围变量；普通候选沿用原细调模型。
    stop_ranges = False
    rows = {r['date']: r for r in plan['days']}
    for sw in plan['stop_list']:
        pre = sw['pre_stop_date']
        if pre is None:
            continue
        row = rows[pre]
        for n in ('PS', 'PBS', 'AS_MAIN', 'AS_FIN'):
            level = stop_level(data, n, sw['start'], sw['end'])
            target = sw['target'] if n == 'PS' else level[0] if level else None
            if target is None and 'BS_CLEAR' in row['phase']:
                target = data['wip_targets'][n]
                for c in data['conditions']:
                    if c['type'] == 'WIP_TARGET' and c['node'] == n and c['start'] <= pre <= c['end']:
                        target = c['target']
            if target is not None and sum(row['eod'].get(n, {}).values()) != target:
                stop_ranges = True
    watchdog = Thread(target=stop_on_timeout, daemon=True)
    watchdog.start()
    try:
        answer = _solve(data, plan, refine_solve=refine_solve, stop_ranges=stop_ranges)
    finally:
        finished.set()
        watchdog.join()
    seconds = perf_counter() - started
    print(f"segment_refine_seconds={seconds:.6f}; "
          f"segment_refine_deterministic={deterministic_used:.6f}/{SEGMENT_REFINE_DETERMINISTIC_TOTAL}", flush=True)
    if timed_out.is_set():
        answer = None
    if answer is None or not answer['days']:
        plan['findings'].extend(answer['findings'] if answer is not None else [
            '库存细调（WBS 越带、高于目标在制）没有完成，已沿用段级排产结果；缺口、换型、加班等主要结果不受影响。'])
        return plan
    return answer


def _solve(data: dict, warm_start: dict | None = None, *, seed_with_targets: bool = False,
           refine_solve=None, stop_ranges: bool = True) -> dict | None:
    factory = data["factory"]
    vehicles = list(factory["models"])
    if "WS_daily" not in data["demand"]:
        return result("UNKNOWN", ["IO_CONTRACT section 2 does not define monthly WS fields."])
    workshops = list(factory["workshops"])
    buffers = list(factory["buffers"])
    nodes = workshops + buffers
    edges = [edge.split(">") for edge in factory["flow"]]
    parents = {n: [a for a, b in edges if b == n] for n in nodes}
    children = {n: [b for a, b in edges if a == n] for n in nodes}
    welding = [w for w in workshops if not parents[w]]
    lines = {m: factory["models"][m]["line"] for m in vehicles}
    start = date.fromisoformat(data["horizon"]["start"])
    end = date.fromisoformat(data["horizon"]["end"])
    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d.isoformat() for d in dates]
    count = len(days)
    working_by_date = {d["date"]: d["is_working_capable"] for d in data["calendar"]}
    working = [working_by_date[d] for d in days]
    errors, available, allowed_modes, effective_hours, daily_targets, fixed, manual = prepare(data, days)
    if errors:
        return result("INPUT_INVALID", errors)
    early = prebuild(data)
    level_days = stop_days(data)
    if seed_with_targets and any("cap_max" in settings for settings in factory["workshops"].values()):
        seed_data = deepcopy(data)
        for settings in seed_data["factory"]["workshops"].values():
            settings.pop("cap_max", None)
        seed = _solve(seed_data)
        if seed["days"]:
            # The target-cap seed must pass the original model's fixed-plan
            # check below: C15 exemptions can change with physical caps.
            warm_start = seed
    production_days = [any(available[w, i] for w in workshops) for i in range(count)]
    months = sorted({d[:7] for d in days})
    pr = data["demand"]["PR"]
    ws = data["demand"]["WS_daily"]
    initial = {(n, m): data["initial"]["wip"].get(n, {}).get(m, 0)
               for n in nodes for m in vehicles}
    targets = data["wip_targets"]
    occupied = [w for w in welding if sum(initial[w, m] for m in vehicles)]
    dual_initial = len(occupied) > 1
    inactive = set(welding) - set(lines.values())
    initial_refill = any(
        sum(initial[n, m] for m in vehicles) < daily_targets[n, 0]
        for n in nodes if n not in welding or n in occupied
    )
    resume_date = end + timedelta(days=1)
    while not working_by_date.get(
        resume_date.isoformat(),
        resume_date.weekday() < 5 and (resume_date.month, resume_date.day) != (1, 1),
    ):
        resume_date += timedelta(days=1)
    tail_days = (resume_date - end).days - 1

    model = cp_model.CpModel()

    def ge(expression, bound, name):
        bit = model.new_bool_var(name)
        model.add(expression >= bound).only_enforce_if(bit)
        model.add(expression < bound).only_enforce_if(bit.Not())
        return bit

    def eq(expression, bound, name):
        bit = model.new_bool_var(name)
        model.add(expression == bound).only_enforce_if(bit)
        model.add(expression != bound).only_enforce_if(bit.Not())
        return bit

    def conjunction(bits, name):
        bit = model.new_bool_var(name)
        model.add_bool_and(bits).only_enforce_if(bit)
        model.add_bool_or([b.Not() for b in bits]).only_enforce_if(bit.Not())
        return bit

    modes, inputs, outputs, active, full, model_active = {}, {}, {}, {}, {}, {}
    total_in, total_out = {}, {}
    default = factory["default_mode"]
    capacities = {
        w: {k: floor(Fraction(str(hours)) * Fraction(str(factory["workshops"][w]["jph"])))
            for k, hours in factory["modes"].items()} for w in workshops
    }
    daily_capacities = {
        (w, i): {k: floor(Fraction(str(h)) * Fraction(str(factory["workshops"][w]["jph"])))
                 for k, h in effective_hours[w, i].items()}
        for w in workshops for i in range(count)
    }
    for i, day in enumerate(days):
        for w in workshops:
            key = (w, i)
            allowed = allowed_modes[key] if w not in inactive else ["OFF"]
            modes[key] = {k: model.new_bool_var(f"mode:{w}:{day}:{k}") for k in factory["modes"]}
            model.add_exactly_one(modes[key].values())
            for k, bit in modes[key].items():
                if k not in allowed:
                    model.add(bit == 0)
            capacity = sum(daily_capacities[key][k] * bit for k, bit in modes[key].items())
            upper = max(daily_capacities[key][k] for k in allowed)
            for m in vehicles:
                limit = 0 if w in welding and w != lines[m] else upper
                inputs[w, m, i] = model.new_int_var(0, limit, f"in:{w}:{m}:{day}")
                outputs[w, m, i] = model.new_int_var(0, limit, f"out:{w}:{m}:{day}")
                model_active[w, m, i] = ge(inputs[w, m, i] + outputs[w, m, i], 1, f"active:{w}:{m}:{day}")
            total_in[key] = sum(inputs[w, m, i] for m in vehicles)
            total_out[key] = sum(outputs[w, m, i] for m in vehicles)
            model.add(total_in[key] <= capacity)
            model.add(total_out[key] <= capacity)
            if key in fixed:
                model.add(total_out[key] == fixed[key])
            active[key] = ge(total_in[key] + total_out[key], 1, f"active:{w}:{day}")
            model.add(modes[key]["OFF"] + active[key] == 1)
            full[key] = conjunction([eq(total_in[key], capacity, f"at_capacity:{w}:{day}"), active[key]], f"full:{w}:{day}")
        model.add(sum(active[w, i] for w in welding) <= 1)  # C4, including drain/refill.

    inflow, outflow = dict(inputs), dict(outputs)
    for i in range(count):
        for m in vehicles:
            for n in buffers:
                inflow[n, m, i] = sum(outputs[w, m, i] for w in parents[n])
                outflow[n, m, i] = sum(inputs[w, m, i] for w in children[n])
            for source, dest in edges:
                if source in workshops and dest in workshops:
                    model.add(outputs[source, m, i] == inputs[dest, m, i])

    stocks, totals, finished, backlog = {}, {}, {}, {}
    cumulative_bs, cumulative_ps, cumulative_fok = {}, {}, {}
    excesses, weighted_excesses, band_days = [], [], []
    # IO_CONTRACT L6 weights are the number of flow edges remaining to FIN.
    downstream_weights = {"FIN": 0}
    for n in ("AS_FIN", "AS_MAIN", "PBS", "PS", "WBS", *welding):
        downstream_weights[n] = 1 + max(downstream_weights[b] for a, b in edges if a == n)
    stock_bound = sum(initial.values()) + sum(max(daily_capacities[w, i][k] for k in allowed_modes[w, i]) for w in welding for i in range(count))
    for i, day in enumerate(days):
        for n in nodes:
            for m in vehicles:
                before = initial[n, m] if i == 0 else stocks[n, m, i - 1]
                stocks[n, m, i] = model.new_int_var(0, stock_bound, f"stock:{n}:{m}:{day}")
                model.add(stocks[n, m, i] == before + inflow[n, m, i] - outflow[n, m, i])
            totals[n, i] = sum(stocks[n, m, i] for m in vehicles)
            if n in buffers:
                model.add(totals[n, i] <= factory["buffers"][n]["cap_max"])
            else:
                initial_total = sum(initial[n, m] for m in vehicles)
                physical_cap = factory["workshops"][n].get("cap_max", daily_targets[n, i])
                if initial_total > physical_cap:
                    before = totals[n, i - 1] if i else initial_total
                    limit = model.new_int_var(physical_cap, initial_total, f"physical_limit:{n}:{day}")
                    model.add_max_equality(limit, [physical_cap, before])
                    model.add(totals[n, i] <= limit)
                else:
                    model.add(totals[n, i] <= physical_cap)
            if n in inactive:
                model.add(totals[n, i] == 0)
            excess = model.new_int_var(0, stock_bound, f"excess:{n}:{day}")
            model.add_max_equality(excess, [0, totals[n, i] - daily_targets[n, i]])
            excesses.append(excess)
            weighted_excesses.append(downstream_weights[n] * excess)
        for m in vehicles:
            for cumulative, flow, label in (
                (cumulative_bs, outputs, lines[m]),
                (cumulative_ps, inputs, "PS"),
                (cumulative_fok, outputs, "AS_FIN"),
            ):
                cumulative[m, i] = model.new_int_var(
                    0, sum(max(daily_capacities[label, t][k] for k in allowed_modes[label, t]) for t in range(i + 1)),
                    f"cumulative:{label}:{m}:{day}",
                )
                model.add(cumulative[m, i] == (cumulative[m, i - 1] if i else 0) + flow[label, m, i])
            deliveries = ws.get(m, {})
            initial_fin = data["initial"]["fin"].get(m, 0)
            before_net = initial_fin if i == 0 else finished[m, i - 1] - backlog[m, i - 1]
            net = before_net + outputs["AS_FIN", m, i] - deliveries.get(day, 0)
            finished[m, i] = model.new_int_var(0, stock_bound + initial_fin, f"fin:{m}:{day}")
            backlog[m, i] = model.new_int_var(0, sum(deliveries.values()), f"bl:{m}:{day}")
            model.add_max_equality(finished[m, i], [0, net])
            model.add_max_equality(backlog[m, i], [0, -net])
            age = factory["models"][m]["glue_age_max"]
            due = initial["WBS", m] if i >= age - 1 else 0
            due += cumulative_bs[m, i - age] if i >= age else 0
            model.add(due <= cumulative_ps[m, i])

    false = model.new_constant(0)
    true = model.new_constant(1)

    def zero_windows(activity, label, threshold):
        # Saturated lengths preserve threshold tests with O(D) variables.
        prefix, suffix = {}, {}
        for i in range(count):
            prefix[i] = model.new_int_var(0, threshold, f"{label}:prefix:{i}")
            model.add_min_equality(prefix[i], [
                (prefix[i - 1] if i else 0) + 1, threshold * (1 - activity[i]),
            ])
        for i in reversed(range(count)):
            suffix[i] = model.new_int_var(0, threshold, f"{label}:suffix:{i}")
            model.add_min_equality(suffix[i], [
                (suffix[i + 1] if i + 1 < count else tail_days) + 1, threshold * (1 - activity[i]),
            ])
        return prefix, suffix

    # Long welding stops exclude gaps occupied by the other welding line.
    # TODO(边界): 焊装零流窗口触及期首且达到胶龄时视为期初前已清线，不追究清线。
    # TODO(边界): WBS 期末在制在计划期之后进入 PS 的胶龄本阶段不检查。
    bs_clear, bs_hold, clear_start, bs_resume_line = {}, {}, {}, {}
    clear_starts = []
    for m, line in lines.items():
        age = factory["models"][m]["glue_age_max"]
        prefix, suffix = zero_windows({i: active[line, i] for i in range(count)}, line, age)
        other_gap = {}
        for i in reversed(range(count)):
            other = ge(sum(active[w, i] for w in welding if w != line)
                       + (other_gap[i + 1] if i + 1 < count else 0), 1, f"other_gap_any:{line}:{i}")
            other_gap[i] = conjunction([active[line, i].Not(), other], f"other_gap:{line}:{i}")
        other_prefix = {}
        for i in range(count):
            other = ge(sum(active[w, i] for w in welding if w != line)
                       + (other_prefix[i - 1] if i else 0), 1, f"other_prefix_any:{line}:{i}")
            other_prefix[i] = conjunction([active[line, i].Not(), other], f"other_prefix:{line}:{i}")
        long_idle, window_start = {}, {}
        for i in range(count):
            length = prefix[i] + suffix[i] - 1
            long_idle[i] = conjunction([
                active[line, i].Not(), ge(length, age, f"long_length:{line}:{i}"),
                other_gap[i].Not(), other_prefix[i].Not(),
            ], f"long_idle:{line}:{i}")
            window_start[i] = conjunction([
                active[line, i - 1] if i else false, long_idle[i],
            ], f"bs_window_start:{line}:{i}")
        for i, day in enumerate(days):
            previous = bs_hold[line, i - 1] if i else false
            resume = conjunction([previous, active[line, i], long_idle[i - 1] if i else false], f"bs_resume:{line}:{i}")
            bs_resume_line[line, i] = resume
            start_clear = model.new_bool_var(f"clear_start:{line}:{day}")
            clear_start[line, i] = start_clear
            clear_starts.append(start_clear)
            model.add_implication(start_clear, previous.Not())
            model.add(total_in[line, i] == 0).only_enforce_if(start_clear)
            model.add(total_out[line, i] > 0).only_enforce_if(start_clear)
            # While draining, positive OUT is not a restart.
            model.add(total_in[line, i] > 0).only_enforce_if(resume)
            bs_hold[line, i] = model.new_bool_var(f"bs_hold:{line}:{day}")
            # A restart is allowed only after a qualifying zero-flow gap.
            if i:
                model.add_implication(resume, long_idle[i - 1])
            else:
                model.add(resume == 0)
            model.add(bs_hold[line, i] == previous + start_clear - resume)
            model.add(total_in[line, i] == 0).only_enforce_if(bs_hold[line, i])
            before_empty = eq(
                (stocks[line, m, i - 1] + stocks["WBS", m, i - 1]) if i
                else initial[line, m] + initial["WBS", m],
                0, f"clear_before_empty:{line}:{day}",
            )
            model.add_implication(resume, before_empty)
            bs_clear[line, i] = conjunction([bs_hold[line, i], before_empty.Not()], f"bs_clear:{line}:{day}")
            if available[line, i]:
                model.add_bool_or([bs_hold[line, i].Not(), before_empty.Not(), long_idle[i]])
            if i:
                model.add_implication(window_start[i], bs_hold[line, i - 1])
                model.add(stocks[line, m, i - 1] == 0).only_enforce_if(window_start[i])
        model.add_implication(bs_hold[line, count - 1], long_idle[count - 1])
        model.add(stocks["WBS", m, count - 1] == 0).only_enforce_if(bs_hold[line, count - 1])
        model.add(sum(clear_start[line, i] for i in range(count)) == sum(window_start.values()))
    clearing, clearing_node = {}, {}
    for i, day in enumerate(days):
        clearing[i] = ge(sum(bs_clear[line, i] for line in lines.values()), 1, f"clearing:{day}")
        for n in nodes:
            clearing_node[n, i] = (clearing[i] if n == "WBS" else
                                   bs_clear[n, i] if n in lines.values() else false)
    bs_resume = {i: ge(sum(bs_resume_line[line, i] for line in lines.values()), 1, f"bs_resume:{i}")
                 for i in range(count)}
    # The owner remembers the last active welding line across idle days.
    owner, switches = {}, {}
    initial_owner = {line: (model.new_constant(int(line == occupied[0])) if occupied and not dual_initial
                           else model.new_bool_var(f"initial_owner:{line}")) for line in lines.values()}
    model.add_exactly_one(initial_owner.values())
    initial_drain, sequence_started = {}, {}
    drain_done = false
    if dual_initial:
        # initial_owner denotes the retained line; the other line drains.
        eligible = [line for line in lines.values()
                    if all(initial[line, m] <= sum(pr[m].values()) for m in vehicles)]
        if not eligible:
            return result("INPUT_INVALID", [
                "期初双线排空：任一排空线的期初在制均超过对应车型全期 PR，排入成品会超产。"])
        for line in lines.values():
            if line not in eligible:
                model.add(initial_owner[line] == 1)
    switched = false
    for i, day in enumerate(days):
        before_switch = switched
        if dual_initial:
            begun = any(production_days[:i + 1])
            initial_drain[i] = drain_done.Not() if begun else false
            ready_lines = []
            for line in lines.values():
                retained_ready = ge(totals[line, i], daily_targets[line, i], f"initial_retained_ready:{line}:{i}")
                drained = eq(totals[line, i], 0, f"initial_empty:{line}:{i}")
                ready_lines.append(ge(retained_ready + initial_owner[line].Not(), 1, f"initial_retained:{line}:{i}"))
                ready_lines.append(ge(drained + initial_owner[line], 1, f"initial_drained:{line}:{i}"))
            ready_shared = [ge(totals[n, i], daily_targets[n, i], f"initial_ready:{n}:{i}")
                            for n in nodes if n not in welding]
            finished_drain = conjunction([initial_drain[i]] + ready_lines + ready_shared, f"initial_finished:{i}")
            drain_done = ge(drain_done + finished_drain, 1, f"initial_done:{i}")
        else:
            initial_drain[i] = false
        for line in lines.values():
            previous = owner[line, i - 1] if i else initial_owner[line]
            switch_gates = [active[line, i], previous.Not()]
            if dual_initial:
                switch_gates.append(initial_drain[i].Not())
            switches[line, i] = conjunction(switch_gates, f"switch:{line}:{i}")
            owner[line, i] = model.new_bool_var(f"owner:{line}:{i}")
            ownership_gates = [initial_drain[i].Not()] if dual_initial else []
            model.add(owner[line, i] == 1).only_enforce_if([active[line, i]] + ownership_gates)
            for other in lines.values():
                if other != line:
                    model.add(owner[line, i] == 0).only_enforce_if([active[other, i]] + ownership_gates)
                    if i:
                        model.add(totals[other, i - 1] == 0).only_enforce_if(switches[line, i])
            no_welding = conjunction([active[w, i].Not() for w in lines.values()], f"no_welding:{line}:{i}")
            model.add(owner[line, i] == previous).only_enforce_if(no_welding)
            if dual_initial:
                model.add(owner[line, i] == initial_owner[line]).only_enforce_if(initial_drain[i])
                if begun:
                    model.add(totals[line, i] == 0).only_enforce_if([owner[line, i].Not(), initial_drain[i].Not()])
                model.add(total_in[line, i] == 0).only_enforce_if(initial_drain[i])
                model.add(total_out[line, i] == 0).only_enforce_if([initial_drain[i], initial_owner[line]])
                model.add(clear_start[line, i] == 0).only_enforce_if(initial_drain[i])
                before = totals[line, i - 1] if i else sum(initial[line, m] for m in vehicles)
                if available[line, i]:
                    model.add(total_out[line, i] > 0).only_enforce_if([
                        initial_drain[i], initial_owner[line].Not(),
                        ge(before, 1, f"initial_drain_remaining:{line}:{i}")])
            else:
                model.add(totals[line, i] == 0).only_enforce_if(owner[line, i].Not())
        switched = ge(before_switch + sum(switches[line, i] for line in lines.values()), 1, f"switched:{i}")
        sequence_started[i] = switched

    # C16: each welding ownership change reverses the old/new order.
    # Initial cars have no cross-model order, but all precede newly welded cars.
    sequence_constraints = []
    for n in nodes:
        if n in welding or len(vehicles) == 1:
            continue
        upstream = {n}
        pending = list(parents[n])
        while pending:
            parent = pending.pop()
            if parent not in upstream:
                upstream.add(parent)
                pending.extend(parents[parent])
        initial_through = {m: sum(initial[p, m] for p in upstream) for m in vehicles}
        cumulative_out = {}
        for i in range(count):
            for m in vehicles:
                # Conservation gives cumulative node OUT from welding OUT and
                # the remaining shared-node stock on the intervening path.
                shared_path = [p for p in nodes if p in upstream and p not in welding]
                cumulative_out[m, i] = (cumulative_bs[m, i]
                    + sum(initial[p, m] - stocks[p, m, i] for p in shared_path))
            for new in vehicles:
                for old in vehicles:
                    if old == new or not initial_through[old]:
                        continue
                    new_cars = ge(cumulative_out[new, i], initial_through[new] + 1,
                                  f"initial_sequence:{n}:{new}:{i}")
                    constraint = model.add(cumulative_out[old, i] >= initial_through[old])
                    constraint.only_enforce_if(new_cars)
                    sequence_constraints.append(constraint.index)
    for i in range(count):
        for new, line in lines.items():
            new_owner = owner[line, i]
            for old in vehicles:
                if old == new:
                    continue
                for n in nodes:
                    if n in welding:
                        continue
                    positive = ge(outflow[n, new, i], 1, f"sequence_out:{n}:{new}:{i}")
                    constraint = model.add(stocks[n, old, i] == 0)
                    constraint.only_enforce_if([sequence_started[i], new_owner, positive])
                    sequence_constraints.append(constraint.index)

    ps_restart = {i: model.new_bool_var(f"ps_restart:{i}") for i in range(count)}
    rules = data["rules"]
    ps_prefix, ps_suffix = zero_windows(ps_restart, "PS", max(rules["ps_stop_min_days"], rules["ps_long_stop_days"]))
    stop, pre_stop, stop_starts = {}, {}, {}
    for i, day in enumerate(days):
        stop[i] = conjunction([ps_restart[i].Not(),
            ge(ps_prefix[i] + ps_suffix[i] - 1, rules["ps_stop_min_days"], f"stop_length:{i}")], f"stop:{day}")
        stop_starts[i] = conjunction([stop[i], ps_restart[i - 1] if i else true], f"stop_start:{i}")
        pre_stop[i] = false
    level_nodes = ("PS", "PBS", "AS_MAIN", "AS_FIN")
    stop_levels, level_used = {}, {}
    target_bound = max([rules["ps_pre_stop_target_long"], rules["ps_pre_stop_target_short"]]
                       + list(daily_targets.values()) + [c["target"] for c in manual.values()])
    def stop_floor(n, i, target, name):
        before = totals[n, i - 1] if i else sum(initial[n, m] for m in vehicles)
        incoming = total_out["PS", i] if n == "PBS" else total_in[n, i]
        lower = model.new_int_var(0, stock_bound, name)
        model.add_min_equality(lower, [target, daily_targets[n, i], before + incoming])
        return lower

    def require_stop(n, i, target, gates, name):
        if stop_ranges:
            lower = stop_floor(n, i, target, name)
            model.add(totals[n, i] >= lower).only_enforce_if(gates)
            model.add(totals[n, i] <= target).only_enforce_if(gates)
        else:
            model.add(totals[n, i] == target).only_enforce_if(gates)

    eligible_indices = [i for i, d in enumerate(days) if d in level_days]
    for i, day in enumerate(days):
        long_stop = false
        if i + 1 < count:
            pre_stop[i] = conjunction([active["PS", i], stop_starts[i + 1]], f"pre_stop:{day}")
            long_stop = ge(ps_suffix[i + 1], rules["ps_long_stop_days"], f"ps_long:{i}")
        first = next((t for t in eligible_indices if t > i), None)
        for n in level_nodes:
            stop_levels[n, i] = model.new_int_var(0, target_bound, f"stop_level:{n}:{i}")
            matches = []
            for c in data["conditions"]:
                if (c["type"] != "WIP_TARGET" or c["node"] != n
                        or n == "PS" and i in manual):
                    continue
                alternatives = []
                if first is not None and c["start"] <= days[first] <= c["end"]:
                    # rev 204：条件盖住窗口内全部可生产日。
                    outside = next((t for t in eligible_indices if days[t] > c["end"]), None)
                    covered = [eq(sum(ps_restart[t] for t in range(i + 1, first + 1)),
                                  0, f"level_first:{n}:{i}:{c['id']}")]
                    if outside is not None:
                        covered.append(ge(sum(ps_restart[t] for t in range(i + 1, outside + 1)),
                                          1, f"level_end:{n}:{i}:{c['id']}"))
                    alternatives.append(conjunction(covered, f"level_covers:{n}:{i}:{c['id']}"))
                if day < c["start"]:
                    # rev 205：整条条件落在同一次零流窗口内，接受提前自建空闲。
                    alternatives.append(eq(sum(ps_restart[t] for t in range(i + 1, days.index(c["end"]) + 1)),
                                           0, f"level_inside:{n}:{i}:{c['id']}"))
                if not alternatives:
                    continue
                covered = ge(sum(alternatives), 1, f"level_covered:{n}:{i}:{c['id']}")
                match = conjunction([pre_stop[i], covered, *[bit.Not() for bit in matches]],
                                    f"level_match:{n}:{i}:{c['id']}")
                model.add(stop_levels[n, i] == c["target"]).only_enforce_if(match)
                matches.append(match)
            level_used[n, i] = ge(sum(matches), 1, f"level_used:{n}:{i}")
            if n != "PS":
                model.add(stop_levels[n, i] == daily_targets[n, i]).only_enforce_if(level_used[n, i].Not())
                require_stop(n, i, stop_levels[n, i], [level_used[n, i]], f"stop_floor:{n}:{i}")
            elif i in manual:
                model.add(stop_levels[n, i] == manual[i]["target"])
            else:
                model.add(stop_levels[n, i] == rules["ps_pre_stop_target_long"]).only_enforce_if([level_used[n, i].Not(), long_stop])
                model.add(stop_levels[n, i] == rules["ps_pre_stop_target_short"]).only_enforce_if([level_used[n, i].Not(), long_stop.Not()])
        require_stop("PS", i, stop_levels["PS", i], [pre_stop[i]], f"stop_floor:PS:{i}")

    # Carry the coming pre-stop target backwards to the BS clearing start.
    clear_requirements = []

    def require_clear(expression, target, gates, i, node):
        constraint = model.add(expression == target)
        constraint.only_enforce_if(gates)
        clear_requirements.append((constraint.index, expression, target, gates, i, node))

    lowering, coming_pre_stop, lowering_target = {}, {}, {}
    carried_levels, carried_manual, level_drain = {}, {}, {}
    for i in reversed(range(count)):
        coming_pre_stop[i] = ge(pre_stop[i] + (
            conjunction([stop[i].Not(), coming_pre_stop[i + 1]], f"coming_pre_stop:{i}")
            if i + 1 < count else false), 1, f"has_pre_stop:{i}")
        for n in level_nodes:
            carried_levels[n, i] = model.new_int_var(0, target_bound, f"carried_level:{n}:{i}")
            carried_manual[n, i] = model.new_bool_var(f"carried_manual:{n}:{i}")
            model.add(carried_levels[n, i] == stop_levels[n, i]).only_enforce_if(pre_stop[i])
            model.add(carried_manual[n, i] == level_used[n, i]).only_enforce_if(pre_stop[i])
            model.add(carried_levels[n, i] == (carried_levels[n, i + 1] if i + 1 < count else 0)).only_enforce_if(pre_stop[i].Not())
            model.add(carried_manual[n, i] == (carried_manual[n, i + 1] if i + 1 < count else false)).only_enforce_if(pre_stop[i].Not())
        lowering_target[i] = carried_levels["PS", i]
        held = ge(sum(bs_hold[line, i] for line in lines.values()), 1, f"lowering_hold:{i}")
        lowering[i] = conjunction([held, coming_pre_stop[i], stop[i].Not()], f"ps_lowering:{i}")
        for n in level_nodes:
            # TODO(边界): legacy 尚未接入 rev 205 提前降库及其总装 C14 豁免，本轮不作为验收路线。
            # TODO(边界): 没有 BS 清线时仅停前日允许降库，达不到停前允许范围即排除该候选，不增加模板。
            level_drain[n, i] = conjunction([carried_manual[n, i],
                ge(lowering[i] + pre_stop[i], 1, f"level_period:{n}:{i}")], f"level_drain:{n}:{i}")
            before = totals[n, i - 1] if i else sum(initial[n, m] for m in vehicles)
            if stop_ranges:
                lower = stop_floor(n, i, carried_levels[n, i], f"drain_floor:{n}:{i}")
                model.add(totals[n, i] >= lower).only_enforce_if(level_drain[n, i])
            else:
                model.add(totals[n, i] <= before).only_enforce_if(level_drain[n, i])
                model.add(totals[n, i] >= carried_levels[n, i]).only_enforce_if(level_drain[n, i])
        capacity = sum(daily_capacities["PS", i][k] * bit for k, bit in modes["PS", i].items())
        wbs_before = totals["WBS", i - 1] if i else sum(initial["WBS", m] for m in vehicles)
        ps_before = totals["PS", i - 1] if i else sum(initial["PS", m] for m in vehicles)
        supply = wbs_before + sum(total_out[line, i] for line in welding)
        possible_in = model.new_int_var(0, stock_bound, f"lowering_in:{i}")
        possible_out = model.new_int_var(0 if stop_ranges else -target_bound, stock_bound, f"lowering_out:{i}")
        model.add_min_equality(possible_in, [capacity, supply])
        if stop_ranges:
            available_out = model.new_int_var(0, stock_bound, f"lowering_available:{i}")
            model.add_max_equality(available_out, [0, ps_before + total_in["PS", i] - lowering_target[i]])
            model.add_min_equality(possible_out, [capacity, available_out])
        else:
            model.add_min_equality(possible_out, [capacity, ps_before + total_in["PS", i] - lowering_target[i]])
        model.add(total_in["PS", i] == possible_in).only_enforce_if(lowering[i])
        model.add(total_out["PS", i] == possible_out).only_enforce_if(lowering[i])
        lower = (stop_floor("PS", i, lowering_target[i], f"lowering_floor:{i}")
                 if stop_ranges else lowering_target[i])
        model.add(totals["PS", i] >= lower).only_enforce_if(lowering[i])
        if any(c['type'] == 'WIP_TARGET' and c['node'] == 'PBS' for c in data['conditions']):
            # PBS 降往人工水位时按该水位保留，包括高于正常目标的水位。
            capacity = sum(daily_capacities['AS_MAIN', i][k] * bit for k, bit in modes['AS_MAIN', i].items())
            before = totals['PBS', i - 1] if i else sum(initial['PBS', m] for m in vehicles)
            available_main = model.new_int_var(0, stock_bound, f"level_main_available:{i}")
            possible_main = model.new_int_var(0, stock_bound, f"level_main_in:{i}")
            model.add_max_equality(available_main, [0, before + total_out['PS', i] - carried_levels['PBS', i]])
            model.add_min_equality(possible_main, [capacity, available_main])
            model.add(total_in['AS_MAIN', i] == possible_main).only_enforce_if(level_drain['PBS', i])
        for w in ("AS_MAIN", "AS_FIN"):
            capacity = sum(daily_capacities[w, i][k] * bit for k, bit in modes[w, i].items())
            before = totals[w, i - 1] if i else sum(initial[w, m] for m in vehicles)
            possible = model.new_int_var(0 if stop_ranges else -target_bound, stock_bound, f"lowering_out:{w}:{i}")
            if stop_ranges:
                available_out = model.new_int_var(0, stock_bound, f"lowering_available:{w}:{i}")
                model.add_max_equality(available_out, [0, before + total_in[w, i] - carried_levels[w, i]])
                model.add_min_equality(possible, [capacity, available_out])
            else:
                model.add_min_equality(possible, [capacity, before + total_in[w, i] - carried_levels[w, i]])
            period = ge(lowering[i] + level_drain[w, i], 1, f"assembly_lowering:{w}:{i}")
            require_clear(total_out[w, i], possible, [period], i, f"{w} OUT")
        for n in ("WBS", "PBS", "AS_MAIN", "AS_FIN"):
            if n == "WBS":
                require_clear(totals[n, i], 0, [lowering[i], pre_stop[i]], i, f"{n} EOD")
            elif stop_ranges:
                require_stop(n, i, carried_levels[n, i], [lowering[i], pre_stop[i]], f"clear_stop_floor:{n}:{i}")
            else:
                require_clear(totals[n, i], carried_levels[n, i], [lowering[i], pre_stop[i]], i, f"{n} EOD")
        for line in lines.values():
            require_clear(totals[line, i], 0, [bs_hold[line, i], pre_stop[i]], i, f"{line} EOD")
            # Rev 188: same-day PS intake releases physical WBS space.
            line_before = totals[line, i - 1] if i else sum(initial[line, m] for m in vehicles)
            line_capacity = sum(daily_capacities[line, i][k] * bit for k, bit in modes[line, i].items())
            possible_weld = model.new_int_var(-stock_bound, stock_bound, f"lowering_weld:{line}:{i}")
            model.add_min_equality(possible_weld, [line_capacity, line_before,
                factory["buffers"]["WBS"]["cap_max"] - wbs_before + total_in["PS", i]])
            model.add(total_out[line, i] == possible_weld).only_enforce_if([lowering[i], bs_hold[line, i]])

    # rev 199：清线期出现不满后不再回到满产；休息日 OFF 的零能力不算不满。
    held_levels = {}
    for i in range(count):
        for n in level_nodes:
            held_levels[n, i] = conjunction([stop[i], ge(
                (held_levels[n, i - 1] + level_used[n, i - 1] if i else false),
                1, f"stop_level_pending:{n}:{i}")], f"stop_level_held:{n}:{i}")
            model.add(sum(inflow[n, m, i] for m in vehicles) == 0).only_enforce_if(held_levels[n, i])
            model.add(sum(outflow[n, m, i] for m in vehicles) == 0).only_enforce_if(held_levels[n, i])
    for w in ("PS", "AS_MAIN", "AS_FIN"):
        partial = false
        for i in range(count):
            capacity = sum(daily_capacities[w, i][k] * bit for k, bit in modes[w, i].items())
            model.add(total_out[w, i] < capacity).only_enforce_if([
                lowering[i], partial, ge(capacity, 1, f"clear_positive_cap:{w}:{i}")])
            partial = conjunction([lowering[i], ge(partial + ge(capacity - total_out[w, i], 1,
                f"clear_partial_today:{w}:{i}"), 1, f"clear_partial_seen:{w}:{i}")], f"clear_partial:{w}:{i}")

    # The remainder is absorbed only on the calendar day before clearing.
    clear_remainder = {}
    for line in lines.values():
        for i in range(count):
            clear_remainder[line, i] = clear_start[line, i + 1] if i + 1 < count else false
            capacity = sum(daily_capacities[line, i][k] * bit for k, bit in modes[line, i].items())
            require_clear(total_out[line, i], capacity, [clear_remainder[line, i]], i, f"{line} OUT")
            for w in ("PS", "AS_MAIN", "AS_FIN"):
                capacity = sum(daily_capacities[w, i][k] * bit for k, bit in modes[w, i].items())
                require_clear(total_out[w, i], capacity, [clear_remainder[line, i]], i, f"{w} OUT")

    ready = {}
    for i in range(count):
        ready_nodes = []
        for n in nodes:
            if n in inactive:
                continue
            at_target = ge(totals[n, i], daily_targets[n, i], f"ready:{n}:{i}")
            if n in lines.values():
                at_target = ge(at_target + owner[n, i].Not(), 1, f"owner_ready:{n}:{i}")
            ready_nodes.append(at_target)
        ready[i] = conjunction(ready_nodes, f"ready:{i}")

    change, change_done, draining, starts = {}, {}, {}, []
    refill, refill_done, first_start = {}, {}, {}
    first_active, first_done, seen, seen_output = {}, {}, {}, {}
    for i, day in enumerate(days):
        previous_change = conjunction([change[i - 1], change_done[i - 1].Not()], f"change_continuing:{i}") if i else false
        switch = ge(sum(switches[line, i] for line in lines.values()), 1, f"switch_any:{i}")
        today_starts = []
        for line in lines.values():
            previous_owner = owner[line, i - 1] if i else initial_owner[line]
            start_change = conjunction([
                previous_change.Not(), previous_owner, bs_hold[line, i].Not(),
                *([initial_drain[i].Not()] if dual_initial else []),
                eq(total_in[line, i], 0, f"change_no_in:{line}:{i}"), active[line, i],
            ], f"start_change:{line}:{i}") if len(vehicles) > 1 else false
            starts.append(start_change)
            today_starts.append(start_change)
            previous_drain = draining[line, i - 1] if i else false
            draining[line, i] = conjunction([
                ge(previous_drain + start_change, 1, f"drain_pending:{line}:{i}"), switch.Not()
            ], f"draining:{line}:{i}")
            model.add(total_in[line, i] == 0).only_enforce_if(draining[line, i])
            model.add_implication(switch, previous_change)
            for other in lines.values():
                if other != line:
                    model.add_implication(switches[other, i], previous_drain)
        change[i] = ge(previous_change + sum(today_starts) + switch, 1, f"change:{i}")
        not_draining = [draining[line, i].Not() for line in lines.values()]
        change_done[i] = conjunction([change[i], ready[i]] + not_draining, f"change_done:{i}")
        continuing = conjunction([refill[i - 1], refill_done[i - 1].Not()], f"refill_continuing:{i}") if i else false
        initial_begin = int(initial_refill and not dual_initial and production_days[i] and not any(production_days[:i]))
        refill[i] = ge(continuing + bs_resume[i] + initial_begin, 1, f"refill:{i}")
        refill_done[i] = (conjunction([ready[i], stop[i].Not(),
                                     true if production_days[i] else false], f"refill_done:{i}")
                          if stop_ranges else ready[i])
        for m in vehicles:
            if sum(initial[n, m] for n in nodes):
                first_active[m, i] = false
                continue
            previous_seen = seen[m, i - 1] if i else false
            began = conjunction([previous_seen.Not(), ge(inputs[lines[m], m, i], 1, f"first_input:{m}:{i}")], f"first_begin:{m}:{i}")
            seen[m, i] = ge(previous_seen + began, 1, f"seen:{m}:{i}")
            continuing_first = conjunction([first_active[m, i - 1], first_done[m, i - 1].Not()], f"first_continue:{m}:{i}") if i else false
            first_active[m, i] = ge(began + continuing_first, 1, f"first_active:{m}:{i}")
            first_done[m, i] = ready[i]
            positive_out = ge(outputs[lines[m], m, i], 1, f"first_positive_out:{m}:{i}")
            previous_output = seen_output[m, i - 1] if i else false
            model.add(totals[lines[m], i] >= daily_targets[lines[m], i]).only_enforce_if([positive_out, previous_output.Not()])
            seen_output[m, i] = ge(previous_output + positive_out, 1, f"seen_output:{m}:{i}")
        first_start[i] = ge(sum(first_active[m, i] for m in vehicles), 1, f"first_start:{i}")
        replenishing = ge(change[i] + refill[i] + first_start[i], 1, f"replenishing:{i}")
        # Only waiting after the new line starts is replenishment waiting.
        # An idle gap while the old line is still draining is an actual stop.
        changed_line_wait = conjunction([change[i]] + not_draining, f"changed_line_wait:{i}")
        waiting = ge(refill[i] + first_start[i] + changed_line_wait, 1, f"ps_waiting:{i}")
        model.add_max_equality(ps_restart[i], [active["PS", i], waiting if (production_days[i] if stop_ranges else working[i]) else false]
                               + [active[line, i] for line in lines.values()])
        for n in nodes:
            if n in inactive:
                continue
            supplies = ge(sum(outflow[n, m, i] for m in vehicles), 1, f"supplies:{n}:{i}")
            gates = [replenishing, supplies]
            if n in lines.values():
                gates.extend([draining[n, i].Not(), bs_hold[n, i].Not()])
            elif n == "WBS":
                gates.append(clearing[i].Not())
            model.add(totals[n, i] >= daily_targets[n, i]).only_enforce_if(gates)
            if (available[n, i] if n in workshops else production_days[i]):
                node_stop = conjunction([stop[i], eq(sum(inflow[n, m, i] + outflow[n, m, i] for m in vehicles), 0, f"node_idle:{n}:{i}")], f"node_stop:{n}:{i}")
                normal = [node_stop.Not(), replenishing.Not(), clearing_node[n, i].Not()]
                if n in workshops and not working[i]:
                    normal.append(active[n, i])
                if dual_initial:
                    normal.append(initial_drain[i].Not())
                if n in lines.values():
                    normal.extend([bs_hold[n, i].Not(), owner[n, i]])
                    normal.append(clear_remainder[n, i].Not())
                if n == "PS":
                    normal.append(pre_stop[i].Not())
                    normal.append(lowering[i].Not())
                elif n in ("PBS", "AS_MAIN", "AS_FIN"):
                    normal.append(level_drain[n, i].Not())
                model.add(totals[n, i] >= daily_targets[n, i]).only_enforce_if(normal)
        if data["wbs_hi"] is not None:
            hi = data["wbs_hi"]
            band_days.append(ge(totals["WBS", i], hi + 1, f"band:{day}"))
            blocked = eq(totals["WBS", i], factory["buffers"]["WBS"]["cap_max"], f"wbs_at_cap:{day}")
            for line in welding:
                model.add(totals["WBS", i] <= hi).only_enforce_if([*([initial_drain[i].Not()] if dual_initial else []), replenishing.Not(), stop[i].Not(), clearing[i].Not(), full[line, i], full["PS", i], blocked.Not()])
    model.add(sum(starts) == sum(switches.values()))

    ratio = Fraction(str(data["rules"]["monthly_band_ratio"]))
    monthly_shortfalls, shortages = [], []
    for m in vehicles:
        total_pr = sum(pr[m][month] for month in months)
        total_fok = cumulative_fok[m, count - 1]
        model.add(total_fok <= total_pr)
        shortages.append(total_pr - total_fok)
        for pos, month in enumerate(months):
            cum_pr = sum(pr[m][mo] for mo in months[:pos + 1])
            cum_fok = cumulative_fok[m, max(i for i, day in enumerate(days) if day[:7] == month)]
            shortfall = model.new_int_var(0, ratio.denominator * total_pr, f"monthly_shortfall:{m}:{month}")
            model.add_max_equality(shortfall, [0, ratio.denominator * (cum_pr - cum_fok) - ratio.numerator * pr[m][month]])
            monthly_shortfalls.append(shortfall)
            if pos == len(months) - 1:
                model.add(cum_fok <= cum_pr)
            else:
                model.add(ratio.denominator * (cum_fok - cum_pr) <= max(
                    ratio.numerator * pr[m][months[pos + 1]], ratio.denominator * early[m][month]))

    # C14: activity suffix, reset by CHANGEOVER, STOP, REFILL and node clearing.
    # Month boundaries and weekends do not reset it. A tail requires no later
    # activity for this workshop/model in the same segment.
    later_segment = {}
    for w in workshops:
        for m in vehicles:
            for i in reversed(range(count)):
                if i == count - 1:
                    later_segment[w, m, i] = false
                else:
                    future = ge(model_active[w, m, i + 1] + later_segment[w, m, i + 1], 1, f"future:{w}:{m}:{i}")
                    later_segment[w, m, i] = conjunction([*([initial_drain[i + 1].Not()] if dual_initial else []), change[i + 1].Not(), stop[i + 1].Not(), refill[i + 1].Not(), first_start[i + 1].Not(), clearing_node[w, i + 1].Not(), future], f"later_segment:{w}:{m}:{i}")
    for i, day in enumerate(days):
        if not production_days[i]:
            continue
        later_month = [t for t in range(i + 1, count) if days[t][:7] == day[:7]]
        last_model = {
            m: eq(sum(model_active[w, m, t] for w in workshops for t in later_month), 0, f"last_model:{m}:{day}")
            for m in vehicles
        }
        for w in workshops:
            if w in inactive or not available[w, i]:
                continue
            normal_idle = [change[i].Not(), refill[i].Not(), first_start[i].Not(), active[w, i].Not()]
            if dual_initial:
                normal_idle.append(initial_drain[i].Not())
            if w in lines.values():
                normal_idle.append(bs_hold[w, i].Not())
            if w in welding:
                normal_idle.extend(active[line, i].Not() for line in welding if line != w)
            relevant = [m for m in vehicles if w not in welding or lines[m] == w]
            if not working[i]:
                normal_idle.append(active[w, i])  # Rev 190: unused authorization is a rest day.
            for m in relevant:
                previous_fok = cumulative_fok[m, i - 1] if i else 0
                cum_pr = sum(pr[m][mo] for mo in months if mo <= day[:7])
                model.add(previous_fok >= cum_pr).only_enforce_if(normal_idle)
            for t in later_month:
                model.add(active[w, t] == 0).only_enforce_if(normal_idle)
            exceptions = [stop[i], clearing_node[w, i], full[w, i]]
            no_input_gates = [eq(total_in[w, i], 0, f"no_input:{w}:{day}")]
            if w in lines.values():
                exceptions.extend([draining[w, i], switches[w, i]])
                exceptions.append(clear_remainder[w, i])
                no_input_gates.extend([bs_clear[w, i].Not(), draining[w, i].Not()])
                if dual_initial:
                    drain_line = conjunction([initial_drain[i], initial_owner[w].Not()], f"drain_line:{w}:{i}")
                    no_input_gates.append(drain_line.Not())
            if w == "PS":
                no_input_gates.append(pre_stop[i].Not())
                no_input_gates.append(lowering[i].Not())
            elif w in ("AS_MAIN", "AS_FIN"):
                no_input_gates.extend([lowering[i].Not(), level_drain[w, i].Not()])
            model.add(total_out[w, i] == 0).only_enforce_if(no_input_gates)
            if dual_initial:
                exceptions.append(initial_drain[i])
            for n in children[w]:
                if n in nodes:
                    if n not in buffers and "cap_max" not in factory["workshops"][n]:
                        # C6/C15 rev 202：(a) 超目标；(b) 自己满产；(c) 指定产量。
                        target = daily_targets[n, i]
                        limit = target + 1
                        exceptions.append(ge(totals[n, i], limit, f"downstream_full:{w}:{day}"))
                        if i:
                            exceptions.append(ge(totals[n, i - 1], limit, f"downstream_draining:{w}:{day}"))
                        elif sum(initial[n, v] for v in vehicles) >= limit:
                            draining_bit = model.new_bool_var(f"downstream_draining:{w}:{day}")
                            model.add(draining_bit == 1)
                            exceptions.append(draining_bit)
                        at_target = ge(totals[n, i], target, f"downstream_target:{w}:{day}")
                        if (n, i) in fixed:
                            exceptions.append(at_target)
                        else:
                            capacity = sum(daily_capacities[n, i][k] * bit for k, bit in modes[n, i].items())
                            exceptions.append(conjunction([at_target,
                                ge(total_out[n, i], capacity, f"downstream_output_full:{w}:{day}"),
                                ge(capacity, 1, f"downstream_capacity_positive:{w}:{day}")],
                                f"downstream_limited:{w}:{day}"))
                    else:
                        limit = (factory["buffers"][n]["cap_max"] if n in buffers else
                                 factory["workshops"][n]["cap_max"])
                        exceptions.append(ge(totals[n, i], limit, f"downstream_full:{w}:{day}"))
            for n in parents[w]:
                exceptions.append(eq(totals[n, i], daily_targets[n, i], f"upstream_target:{w}:{day}"))
                exceptions.append(conjunction([clearing_node[n, i], lowering[i].Not()], f"upstream_clearing:{w}:{i}")
                                  if w == "PS" else clearing_node[n, i])
            if w == "PS":
                exceptions.append(lowering[i])  # Section 5 fixes both flows during drawdown.
            elif w in ("AS_MAIN", "AS_FIN"):
                exceptions.extend([lowering[i], level_drain[w, i]])
            for m in relevant:
                tail = (later_segment[w, m, i].Not() if w in welding or len(vehicles) == 1 else
                        conjunction([later_segment[w, v, i].Not() for v in vehicles], f"shared_tail:{w}:{m}:{i}"))
                tail = conjunction([tail, change[i].Not(), refill[i].Not(), first_start[i].Not()], f"production_tail:{w}:{m}:{i}")
                model.add_bool_or(exceptions + [model_active[w, m, i].Not(), last_model[m], tail])

    objectives = [
        ("L1a", sum(shortages)), ("L1b", sum(backlog.values())),
        ("L1c", sum(monthly_shortfalls)), ("L2", sum(starts) + sum(clear_starts) + int(dual_initial)),
        ("L3a", sum(1 - modes[w, i]["OFF"] for w in workshops for i in range(count) if not working[i])),
        ("L3b", sum(bit for mode in modes.values() for k, bit in mode.items() if k not in ("OFF", default))),
        ("L4", sum(band_days)), ("L5", sum(excesses)), ("L6", sum(weighted_excesses)),
    ]
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 0
    solver.parameters.num_workers = 8
    solver.parameters.interleave_search = True
    solver.parameters.interleave_batch_size = 8
    model.add_decision_strategy(starts, cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)
    model.add_decision_strategy(
        [flow[w, m, i] for i in range(count) for w in workshops
         for m in vehicles for flow in (inputs, outputs)],
        cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE,
    )
    levels = []
    incumbent = None
    search_parameters = solver.parameters
    warm_feasible = False
    if warm_start is not None:
        reason = None
        if warm_start["status"] not in ("FEASIBLE", "OPTIMAL", "UNKNOWN"):
            reason = "status=" + warm_start["status"]
        elif not warm_start["days"]:
            reason = "empty_days"
        elif [row["date"] for row in warm_start["days"]] != days:
            reason = "calendar_mismatch"
        elif any(set(row["fok"]) != set(vehicles) or any(
            set(shop[direction]) - set(vehicles)
            for shop in row["workshops"].values() for direction in ("in", "out"))
            for row in warm_start["days"]):
            reason = "models_mismatch"
        else:
            warm_model = model.clone()
            for i, row in enumerate(warm_start["days"]):
                for w in workshops:
                    shop = row["workshops"][w]
                    for k, bit in modes[w, i].items():
                        warm_model.add(bit == int(k == shop["mode"]))
                    for m in vehicles:
                        warm_model.add(inputs[w, m, i] == shop["in"].get(m, 0))
                        warm_model.add(outputs[w, m, i] == shop["out"].get(m, 0))
            warm = cp_model.CpSolver()
            warm.parameters.copy_from(search_parameters)
            warm.parameters.max_deterministic_time = INITIAL_SOLUTION_BUDGET
            if refine_solve is not None:
                warm.parameters.num_workers = 1
                warm.parameters.interleave_search = False
            warm.parameters.stop_after_first_solution = True
            warm_status = warm.solve(warm_model) if refine_solve is None else refine_solve(warm, warm_model)
            if warm_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                incumbent = warm
                warm_feasible = True
                hint_all(model, warm, len(model.proto.variables))
                warm_levels = {label: warm.value(expr) / ratio.denominator
                               if label == "L1c" else warm.value(expr)
                               for label, expr in objectives}
                print(f"warm_start=feasible; levels={warm_levels}", flush=True)
            else:
                reason = "fixed_plan_" + warm.status_name(warm_status)
        if reason is not None:
            print(f"warm_start=ignored; reason={reason}", flush=True)
            if refine_solve is not None:
                return result('UNKNOWN', ['库存细调（WBS 越带、高于目标在制）没有完成，已沿用段级排产结果；缺口、换型、加班等主要结果不受影响。'])
            if not seed_with_targets:
                return None

    def warm_not_worse(source):
        return not warm_feasible or tuple(source.value(expr) for _, expr in objectives) <= tuple(
            incumbent.value(expr) for _, expr in objectives)

    if refine_solve is not None:
        # T-31 S4b / SEGMENT_PLAN §7: freeze verified high levels and true
        # changeover/clearing dates; no monthly seed or legacy cold search.
        verified = {r['level']: r['value'] for r in warm_start['objective']['levels']}
        for label, expression in objectives[:6]:
            expected = int(Fraction(str(verified[label])) * (ratio.denominator if label == 'L1c' else 1))
            if incumbent.value(expression) != expected:
                print(f"segment_refine=retained; reason={label}_verification_mismatch", flush=True)
                return None
            model.add(expression == expected)
            levels.append({'level': label, 'value': verified[label], 'proven_optimal': False})
        for table in (switches, clear_start, bs_clear, draining, pre_stop, stop):
            for bit in table.values():
                model.add(bit == incumbent.value(bit))
        for label, objective in objectives[6:]:
            model.minimize(objective)
            candidate = cp_model.CpSolver()
            candidate.parameters.random_seed = 0
            candidate.parameters.num_workers = 1
            before = incumbent.value(objective)
            if before == 0:
                status = cp_model.OPTIMAL
            else:
                status = refine_solve(candidate, model)
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and warm_not_worse(candidate):
                    incumbent = candidate
            value = incumbent.value(objective)
            print(f"segment_refine {label}: before={before}; after={value}; status={candidate.status_name(status)}", flush=True)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return result('UNKNOWN', ['库存细调（WBS 越带、高于目标在制）没有完成，已沿用段级排产结果；缺口、换型、加班等主要结果不受影响。'])
            levels.append({'level': label, 'value': value, 'proven_optimal': status == cp_model.OPTIMAL})
            model.add(objective == value)
            hint_all(model, incumbent, len(model.proto.variables))
        objectives = []

    budgets = SMALL_LEVEL_BUDGETS if refine_solve is not None or len(model.proto.variables) <= SMALL_MODEL_VARIABLES else LEVEL_BUDGETS
    coarse_bound = None
    has_overtime = any(c["type"] == "MODE_AUTH" for c in data["conditions"])
    authorization_pool = (has_overtime
        or sum(not working[i] and production_days[i] for i in range(count)) > len(months))
    if budgets is LEVEL_BUDGETS:
        guide_capacities = {w: dict(row) for w, row in capacities.items()}
        if data["conditions"] and not has_overtime:
            for w in workshops:
                guide_capacities[w][default] = max(daily_capacities[w, i][k]
                    for i in range(count) for k in allowed_modes[w, i])
        coarse_bound, coarse_rows, coarse_switches = monthly_plan(data, days, production_days, guide_capacities)

    idle_months = []
    idle_windows = {}
    if budgets is LEVEL_BUDGETS:
        cumulative = {m: 0 for m in vehicles}
        coarse_gaps = {}
        for mo in months:
            for m in vehicles:
                row = next(r for r in coarse_rows if r['month'] == mo and r['model'] == m)
                cumulative[m] += row['planned_fok']
                coarse_gaps[m, mo] = max(0, row['lower'] - cumulative[m])
        for pos, mo in enumerate(months):
            affected = months[pos:pos + 3]
            gaps = [(m, t, coarse_gaps[m, t]) for t in affected for m in vehicles if coarse_gaps[m, t] > 0]
            if not gaps:
                idle_months.append(mo)
            print(f'monthly_idle month={mo}; enabled={not gaps}; coarse_shortfalls={gaps}', flush=True)

    def guide_monthly_idle(search, control_months=(), scope=None, selected_months=None):
        # Rev 164: stop each completed model, independently of the other
        # model's advance-production allowance. Windows still use section 5.
        selected = idle_months if selected_months is None else selected_months
        for i in range(count):
            if not production_days[i]:
                continue
            for m in vehicles:
                mo = days[i][:7]
                if mo not in selected or (scope is not None and mo not in scope):
                    continue
                required = sum(pr[m][month] for month in months if month <= mo)
                done = search.new_bool_var(f'month_done:{m}:{i}')
                previous = cumulative_fok[m, i - 1] if i else 0
                search.add(previous >= required).only_enforce_if(done)
                search.add(previous < required).only_enforce_if(done.Not())
                # Keep the last PS production day adjacent to a guided whole-line
                # stop; startup/refill/clearing retain their own waiting rules.
                search.add_implication(active[lines[m], i], active['PS', i]).only_enforce_if(
                    [done, change[i].Not(), refill[i].Not(), first_start[i].Not(), clearing[i].Not()])
                no_completion = search.new_bool_var(f'no_completion:{m}:{i}')
                search.add(outputs['AS_FIN', m, i] == 0).only_enforce_if(no_completion)
                search.add(outputs['AS_FIN', m, i] > 0).only_enforce_if(no_completion.Not())
                for w in workshops:
                    before = sum(initial[w, v] for v in vehicles) if i == 0 else totals[w, i - 1]
                    missing = search.new_int_var(0, daily_targets[w, i], f'missing:{w}:{m}:{i}')
                    search.add_max_equality(missing, [0, daily_targets[w, i] - before])
                    if mo in control_months:
                        search.add(inputs[w, m, i] <= outputs[w, m, i] + missing).only_enforce_if(done)
                    # Once FOK stops, allow only target replenishment, while
                    # existing cars may still drain for a stop or changeover.
                    search.add(inputs[w, m, i] <= missing).only_enforce_if([done, no_completion])

    template_uses = set()

    def templates(source, search=None):
        # A template is fixed only when it reproduces the incumbent's flows.
        # Thus the incumbent remains feasible, with every objective unchanged;
        # the ordinary model is retained for fallback and subsequent searches.
        records = []
        limits = {n: factory["buffers"][n]["cap_max"] for n in buffers}
        limits.update({w: settings["cap_max"] for w, settings in factory["workshops"].items()
                       if "cap_max" in settings})
        for m, line in lines.items():
            events = []
            for i in range(count):
                if source.value(clear_start[line, i]):
                    pre = next(t for t in range(i, count) if source.value(pre_stop[t]))
                    events.append(("清线", i - 1, pre, source.value(lowering_target[i])))
                if source.value(bs_resume_line[line, i]):
                    pre = max(t for t in range(i) if source.value(pre_stop[t]))
                    events.append(("复线", i, count - 1, source.value(totals["PS", pre])))
            if initial_refill and not dual_initial and sum(initial[n, m] for n in nodes):
                begin = next((i for i in range(count) if source.value(refill[i])), None)
                if begin is not None and not any(source.value(bs_resume_line[line, i]) for i in range(begin + 1)):
                    events.append(("复线", begin, count - 1, sum(initial["PS", v] for v in vehicles)))
            for kind, begin, end_index, stop_target in events:
                reason = ""
                path = (line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")
                expected = {n: daily_targets[n, max(0, begin)] for n in path}
                before = {n: source.value(totals[n, begin - 1]) if begin > 0 else sum(initial[n, v] for v in vehicles) for n in path}
                standard = expected if kind == "清线" else {**expected, line: 0, "WBS": 0, "PS": stop_target}
                if begin < 0 or before != standard:
                    reason = "日初不是标准摆线" if kind == "清线" else "复工日初不是标准停线水位"
                elif any((source.value(stocks[n, v, begin - 1]) if begin else initial[n, v])
                         for n in nodes for v in vehicles if v != m):
                    reason = "存在其他车型在制"
                caps = [{w: daily_capacities[w, t][default] for w in (line, "PS", "AS_MAIN", "AS_FIN")}
                        for t in range(max(0, begin), end_index + 1)]
                rows = None
                if not reason:
                    rows = (clear_rows(line, caps, expected, stop_target, limits,
                                stop_levels={n: source.value(carried_levels[n, end_index])
                                             for n in ('PBS', 'AS_MAIN', 'AS_FIN')},
                                stop_ranges=stop_ranges) if kind == "清线" else
                            refill_rows(line, caps, expected, stop_target, limits))
                    if rows is None:
                        reason = "产能与目标无法形成标准逐日模板"
                if rows is not None:
                    finish = begin + len(rows) - 1
                    hit = [c["id"] for c in data["conditions"]
                           if c.get("pre_stop_date", c.get("date", c.get("start"))) <= days[finish]
                           and c.get("pre_stop_date", c.get("date", c.get("end"))) >= days[begin]]
                    if hit:
                        reason = "条件命中：" + "、".join(hit)
                    elif not all(working[t] for t in range(begin, finish + 1)):
                        reason = "模板段含不可生产日"
                    elif any(source.value(flow[w, v, begin + offset]) != (pair[k] if v == m else 0)
                             for offset, row in enumerate(rows) for w, pair in row.items()
                             for v in vehicles for k, flow in enumerate((inputs, outputs))):
                        reason = "模板流量与当前解不同，未证各级目标不变"
                    else:
                        # Identical dated FOK also preserves every monthly upper
                        # bound, including a template crossing a month boundary.
                        if search is not None:
                            for offset, row in enumerate(rows):
                                for w, pair in row.items():
                                    for v in vehicles:
                                        for k, flow in enumerate((inputs, outputs)):
                                            search.add(flow[w, v, begin + offset] == (pair[k] if v == m else 0))
                            template_uses.add((kind, line, begin))
                records.append((kind, line, begin, end_index, reason))
        return records

    for label, objective in objectives:
        # Every level is nonnegative; a feasible zero already proves its optimum.
        if incumbent is not None and incumbent.value(objective) == 0:
            levels.append({"level": label, "value": 0, "proven_optimal": True})
            model.add(objective == 0)
            print(f"{label} solve_seconds=0.000000; deterministic_seconds=0.000000; status=OPTIMAL; feasible_zero_meets_lower_bound", flush=True)
            continue
        candidate = cp_model.CpSolver()
        candidate.parameters.copy_from(search_parameters)
        candidate.parameters.max_deterministic_time = budgets[label]
        if budgets is LEVEL_BUDGETS:
            candidate.parameters.cp_model_probing_level = 0
            candidate.parameters.interleave_batch_size = 8
            candidate.parameters.use_lns_only = True
            if label != "L1a":
                candidate.parameters.num_workers = 1
                candidate.parameters.interleave_search = False
                candidate.parameters.use_lns_only = False
            if label == "L5":
                candidate.parameters.num_workers = 8
                candidate.parameters.interleave_search = True
                candidate.parameters.use_lns_only = True
        if budgets is SMALL_LEVEL_BUDGETS and label in ("L1b", "L5") and not warm_feasible:
            model.clear_hints()
        model.minimize(objective)
        started = perf_counter()
        if budgets is SMALL_LEVEL_BUDGETS and label == "L1a" and not dual_initial and not warm_feasible:
            seed_model = model.clone()
            transition_ranges = []
            workdays = [i for i in range(count) if production_days[i]]
            current = next((m for m in vehicles if lines[m] in occupied), vehicles[0])
            for mo in months:
                sequence = [m for m in vehicles if m != current and pr[m][mo]]
                for m in sequence:
                    past_pr = sum(pr[m][prior] for prior in months if prior < mo)
                    month_work = [i for i, day in enumerate(days) if day[:7] == mo and production_days[i]]
                    due_dates = [i for i in month_work if ws.get(m, {}).get(days[i], 0)]
                    due = due_dates[0] if due_dates else month_work[-1]
                    required = sum(v for day, v in ws.get(m, {}).items() if day <= days[due]) - past_pr if due_dates else pr[m][mo]
                    existing = max(0, sum(initial[n, m] for n in nodes) - past_pr)
                    reserve = targets[lines[m]] + sum(targets[n] for n in nodes if n not in welding)
                    need = ceil(max(0, required + reserve - existing) / capacities[lines[m]][default])
                    next_month = months[months.index(mo) + 1] if mo != months[-1] else None
                    drain_days = (ceil(targets[lines[m]] / capacities[lines[m]][default])
                                  if next_month is not None and not pr[m][next_month]
                                  and any(pr[v][next_month] for v in vehicles if v != m) else 0)
                    begin = month_work[max(0, month_work.index(due) - max(1, need) - drain_days + 1)]
                    if not transition_ranges:
                        seed_model.add(switches[lines[m], begin] == 1)
                    position = workdays.index(begin)
                    old_drain = ceil(targets[lines[current]] / capacities[lines[current]][default])
                    fill = ceil(targets[lines[m]] / capacities[lines[m]][default])
                    transition_ranges.append((workdays[max(0, position - old_drain)],
                                              workdays[min(len(workdays) - 1, position + fill - 1)]))
                if sequence:
                    current = sequence[-1]
            # Later switches can precede a month boundary to build next month's
            # supply. Only anchor the first block; retain the guide's count.
            seed_model.add(sum(switches.values()) == len(transition_ranges))
            for i in range(count):
                if any(begin <= i <= finish for begin, finish in transition_ranges[:1]):
                    seed_model.add(change[i] == 1)
            # The block seed need not have zero monthly-band shortage; L1c
            # still optimizes that shortage after annual output and delivery.
            for _, service_objective in objectives[:2]:
                seed_model.add(service_objective == 0)
            seed = cp_model.CpSolver()
            seed.parameters.copy_from(search_parameters)
            seed.parameters.max_deterministic_time = 10.0
            seed.parameters.stop_after_first_solution = True
            seed_status = seed.solve(seed_model)
            print(f"small_seed solve_seconds={perf_counter() - started:.6f}; status={seed.status_name(seed_status)}", flush=True)
            if seed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                templates(seed, seed_model)
                seed_status = seed.solve(seed_model)
                incumbent = seed
                hint_all(model, seed, len(model.proto.variables))
            started = perf_counter()

        if budgets is LEVEL_BUDGETS and label == "L1a" and not warm_feasible:
            # Keep the compact default-mode seed when it closes annual demand.
            # Otherwise search the actual authorized workshop-day capacities.
            for use_authorized_modes in ((False, True) if has_overtime else (False,)):
                seed = cp_model.CpSolver()
                seed.parameters.copy_from(search_parameters)
                seed.parameters.cp_model_probing_level = 0
                seed.parameters.max_deterministic_time = INITIAL_SOLUTION_BUDGET
                seed.parameters.stop_after_first_solution = True
                skeleton = model.clone()
                skeleton.minimize(objective)
                if not use_authorized_modes:
                    for (w, i), row in modes.items():
                        for k, bit in row.items():
                            if k not in ("OFF", default) and k in allowed_modes[w, i]:
                                skeleton.add(bit == 0)
                workdays = [i for i in range(count) if production_days[i]]
                transition_ranges = []
                switch_dates = {}
                current_model = next((m for m in vehicles if lines[m] in occupied), vehicles[0])
                monthly_owner = {}
                for mo in months:
                    for switch_month, m in coarse_switches:
                        if switch_month != mo:
                            continue
                        line, old_line = lines[m], lines[current_model]
                        month_days = [i for i in workdays if days[i][:7] == mo]
                        needed = next(row["welding_days"] for row in coarse_rows if row["month"] == mo and row["model"] == current_model)
                        drain_days = ceil(targets[old_line] / capacities[old_line][default])
                        switch_day = month_days[min(len(month_days) - 1, needed + drain_days)]
                        position = workdays.index(switch_day)
                        fill_days = ceil(targets[line] / capacities[line][default])
                        begin = workdays[position - drain_days]
                        finish = workdays[position + fill_days - 1]
                        switch_dates[line, switch_day] = 1
                        transition_ranges.append((begin, finish))
                        print(f"monthly_block model={m}; drain={days[begin]}; start={days[switch_day]}; ready={days[finish]}", flush=True)
                        current_model = m
                    monthly_owner[mo] = current_model
                # C16 block guide: a month's last model follows the preceding
                # models at every node when it reaches the completion line.
                for mo, current in monthly_owner.items():
                    last = max(i for i, day in enumerate(days) if day[:7] == mo)
                    if any(row['month'] == mo and row['model'] == current and row['planned_fok']
                           for row in coarse_rows):
                        for m in vehicles:
                            if m != current:
                                for n in nodes:
                                    skeleton.add(stocks[n, m, last] == 0)
                clear_dates = {}
                hold_ranges = {line: [] for line in lines.values()}
                for i in workdays:
                    after = i + 1
                    while after < count and not production_days[after]:
                        after += 1
                    m = monthly_owner[days[i][:7]]
                    line = lines[m]
                    if after - i - 1 < factory["models"][m]["glue_age_max"]:
                        continue
                    pre_target = rules["ps_pre_stop_target_long" if after - i - 1 >= rules["ps_long_stop_days"] else "ps_pre_stop_target_short"]
                    if i in manual:
                        pre_target = manual[i]["target"]
                    else:
                        level = stop_level(data, "PS", days[i + 1], days[after - 1], days=level_days)
                        if level is not None:
                            pre_target = level[0]
                    clear_days = (targets[line] + targets["WBS"] + max(0, targets["PS"] - pre_target)) // capacities["PS"][default]
                    begin = workdays[workdays.index(i) - clear_days + 1]
                    clear_dates[line, begin] = 1
                    hold_ranges[line].append((begin, after))
                for i in range(count):
                    skeleton.add(change[i] == int(any(begin <= i <= finish for begin, finish in transition_ranges)))
                    for line in lines.values():
                        skeleton.add(switches[line, i] == switch_dates.get((line, i), 0))
                        skeleton.add(clear_start[line, i] == clear_dates.get((line, i), 0))
                        skeleton.add(bs_hold[line, i] == int(any(begin <= i < finish for begin, finish in hold_ranges[line])))
                guide_monthly_idle(skeleton, months)
                if use_authorized_modes and incumbent is not None:
                    hint_all(skeleton, incumbent, len(skeleton.proto.variables))
                if sequence_constraints:
                    # This candidate supplies hints only; the incumbent below must
                    # come from solving the skeleton with all C16 constraints.
                    relaxed = skeleton.clone()
                    for index in sequence_constraints:
                        relaxed.proto.constraints[index].clear_linear()
                        relaxed.proto.constraints[index].enforcement_literal.clear()
                    # First find the attainable shortage, then select its seed with
                    # deterministic first-solution interleaving before fixing flows.
                    seed.parameters.stop_after_first_solution = False
                    relaxed_status = seed.solve(relaxed)
                    used_budget = seed.response_proto.deterministic_time
                    if relaxed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                        relaxed.add(objective == seed.value(objective))
                        seed.parameters.stop_after_first_solution = True
                        seed.parameters.max_deterministic_time = max(0.0, INITIAL_SOLUTION_BUDGET - used_budget)
                        relaxed_status = seed.solve(relaxed)
                        used_budget += seed.response_proto.deterministic_time
                    print(f"L1a sequence_hint_seconds={perf_counter() - started:.6f}; deterministic_seconds={used_budget:.6f}; status={seed.status_name(relaxed_status)}; value={seed.value(objective) if relaxed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'UNKNOWN'}", flush=True)
                    if relaxed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                        first_month = coarse_switches[0][0] if coarse_switches else months[0]
                        if dual_initial or any(initial[n, m] for n in nodes for m in vehicles
                                               if lines[m] not in occupied):
                            first_month = months[0]
                        hint_all(skeleton, seed, len(skeleton.proto.variables))
                        templates(seed, skeleton)
                        for i, day in enumerate(days):
                            if day[:7] < first_month:
                                for w in workshops:
                                    for m in vehicles:
                                        for flow in (inputs, outputs):
                                            skeleton.add(flow[w, m, i] == seed.value(flow[w, m, i]))
                    seed.parameters.max_deterministic_time = max(0.0, INITIAL_SOLUTION_BUDGET - used_budget)
                seed.parameters.stop_after_first_solution = False
                seed_status = seed.solve(skeleton)
                if seed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    skeleton.add(objective == seed.value(objective))
                    seed.parameters.stop_after_first_solution = True
                    seed_status = seed.solve(skeleton)
                print(f"L1a initial_solve_seconds={perf_counter() - started:.6f}; deterministic_seconds={seed.response_proto.deterministic_time:.6f}; status={seed.status_name(seed_status)}; value={seed.value(objective) if seed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'UNKNOWN'}", flush=True)
                if seed_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    if incumbent is None or seed.value(objective) < incumbent.value(objective):
                        incumbent = seed
                if incumbent is not None and incumbent.value(objective) == 0:
                    break
            if incumbent is not None:
                hint_all(model, incumbent, len(model.proto.variables))
            started = perf_counter()
        if budgets is LEVEL_BUDGETS and (label in ("L1c", "L5", "L6") or authorization_pool and label in ("L3a", "L3b")):
            # Optimize monthly flows, retaining other months' flows and all
            # preceding objective values. Carry stocks remain free to change.
            visits = [(mo, False) for mo in (months if label == "L1c" else reversed(months))]
            if label == "L3a" and has_overtime:
                visits += [(mo, True) for mo in reversed(months)]
            for mo, release_authorization in visits:
                pos = months.index(mo)
                window = months[:pos + 2] if label == "L1c" else months[pos:pos + 2]
                if label == "L5" and mo in idle_windows:
                    window = idle_windows[mo]
                if label in ("L3a", "L3b") and not any(
                    incumbent.value(bit) for (w, i), row in modes.items() if days[i][:7] in window
                    for k, bit in row.items() if (label == "L3a" and not working[i] and k != "OFF"
                        or label == "L3b" and k not in ("OFF", default))):
                    continue
                if label == "L1c":
                    last = max(i for i, day in enumerate(days) if day[:7] == mo)
                    if all(incumbent.value(cumulative_fok[m, last]) >= sum(pr[m][t] for t in months[:pos + 1]) - ratio * pr[m][mo] for m in vehicles):
                        continue
                    # Keep this pass local; a full-horizon neighborhood repeats
                    # the annual search instead of refining a monthly window.
                    if window == months:
                        continue
                elif mo == months[-1] and any(incumbent.value(gap) for gap in shortages):
                    # With an annual shortage, spend this budget on the next
                    # two-month window, which also covers the final month.
                    continue
                neighborhood = model.clone()
                if label == "L5":
                    guide_monthly_idle(neighborhood, window, window)
                    for gap in monthly_shortfalls:
                        neighborhood.add(gap <= incumbent.value(gap))
                if release_authorization:
                    neighborhood.add(sum(active[w, i] for w in workshops for i, day in enumerate(days)
                        if day[:7] in window and not working[i]) == 0)
                    for table in (switches, clear_start, bs_hold, change):
                        for key, bit in table.items():
                            i = key[-1] if isinstance(key, tuple) else key
                            if days[i][:7] not in window:
                                neighborhood.add(bit == incumbent.value(bit))
                elif label != "L5" or mo != months[-1]:
                    for bit in list(switches.values()) + list(clear_start.values()) + list(bs_hold.values()) + list(change.values()):
                        neighborhood.add(bit == incumbent.value(bit))
                neighborhood.add(objective <= incumbent.value(objective))
                if label in ("L3a", "L3b"):
                    preferred = sorted(
                        [i for i, day in enumerate(days) if day[:7] in window],
                        key=lambda i: (any(incumbent.value(stop[t]) for t in
                            range(max(0, i - 1), min(count, i + 2))), -dates[i].day, i))
                    ranked = [(rank, bit) for rank, i in enumerate(preferred)
                        for w in workshops for k, bit in modes[w, i].items()
                        if (label == "L3a" and not working[i] and k != "OFF"
                            or label == "L3b" and k not in ("OFF", default))
                        and k in allowed_modes[w, i]]
                    date_preference = sum(rank * bit for rank, bit in ranked)
                templates(incumbent, neighborhood)
                for i, day in enumerate(days):
                    if day[:7] not in window:
                        for w in workshops:
                            for m in vehicles:
                                for flow in (inputs, outputs):
                                    neighborhood.add(flow[w, m, i] == incumbent.value(flow[w, m, i]))
                if authorization_pool:
                    for (w, i), row in modes.items():
                        if days[i][:7] not in window or has_overtime and label in ("L5", "L6"):
                            for bit in row.values():
                                neighborhood.add(bit == incumbent.value(bit))
                neighborhood.clear_hints()
                if label in ("L1c", "L3a", "L3b") or authorization_pool:
                    hint_all(neighborhood, incumbent, len(model.proto.variables))
                neighborhood.proto.search_strategy.clear()
                neighborhood.add_decision_strategy(
                    [stocks[n, m, i] for n in (nodes if label == "L5" and mo == months[-1] else reversed(nodes)) for i, day in enumerate(days)
                     if day[:7] in window for m in vehicles],
                    cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE,
                )
                polish = cp_model.CpSolver()
                polish.parameters.random_seed = 0
                polish.parameters.num_workers = 1
                polish.parameters.cp_model_probing_level = 0
                polish.parameters.search_branching = cp_model.AUTOMATIC_SEARCH if label in ("L1c", "L3a", "L3b") else cp_model.FIXED_SEARCH
                has_transition = any(incumbent.value(switches[line, i]) or incumbent.value(clear_start[line, i]) for line in lines.values() for i, day in enumerate(days) if day[:7] in window)
                polish.parameters.max_deterministic_time = (3.0 if release_authorization else
                    1.0 if label in ("L3a", "L3b") else
                    3.0 if authorization_pool and not has_overtime and label == "L5" else
                    5.0 if label == "L5" and mo == months[-1] else
                    0.75 if label == "L1c" else
                    3.0 if mo in idle_windows or has_transition else 1.0)
                local_start = perf_counter()
                local_status = polish.solve(neighborhood)
                print(f"{label} month={mo};{' release_authorization;' if release_authorization else ''} before={incumbent.value(objective)}; after={polish.value(objective) if local_status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'UNKNOWN'}; solve_seconds={perf_counter() - local_start:.6f}; deterministic_seconds={polish.response_proto.deterministic_time:.6f}; status={polish.status_name(local_status)}", flush=True)
                if local_status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and warm_not_worse(polish):
                    if polish.value(objective) < incumbent.value(objective) or (label == "L5" and polish.value(objective) == incumbent.value(objective)) or (
                        label in ("L3a", "L3b") and polish.value(objective) == incumbent.value(objective)
                        and polish.value(date_preference) < incumbent.value(date_preference)):
                        incumbent = polish
            hint_all(model, incumbent, len(model.proto.variables))
            started = perf_counter()
        retained_only = False
        if incumbent is not None and incumbent.value(objective) == 0:
            candidate = incumbent
            status = cp_model.OPTIMAL
        elif budgets is SMALL_LEVEL_BUDGETS:
            status = candidate.solve(model)
        elif (budgets[label] == 0 or authorization_pool and label == "L3b") and incumbent is not None:
            candidate = incumbent
            status = cp_model.FEASIBLE
            retained_only = True
        else:
            search = model.clone()
            guide_monthly_idle(search)
            status = candidate.solve(search)
        if retained_only:
            print(f"{label} solve_seconds=0.000000; deterministic_seconds=0.000000; status=FEASIBLE; retained_incumbent", flush=True)
        else:
            print(f"{label} solve_seconds={perf_counter() - started:.6f}; deterministic_seconds={candidate.response_proto.deterministic_time:.6f}; status={candidate.status_name(status)}", flush=True)
        print(f"{label} bound={0 if retained_only or incumbent is not None and incumbent.value(objective) == 0 else candidate.best_objective_bound}", flush=True)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if incumbent is None or candidate.value(objective) <= incumbent.value(objective) and warm_not_worse(candidate):
                incumbent = candidate
        elif (status != cp_model.UNKNOWN or incumbent is None) and not warm_feasible:
            answer = result("UNKNOWN", [
                f"{label}：求解器在时限内没找到可行计划，不能证明输入不可行；"
                f"当前模型 CP-SAT {candidate.status_name(status)}，"
                f"本阶段确定性用时 {candidate.response_proto.deterministic_time:.6f} 秒。"])
            answer["objective"]["levels"] = levels
            input_findings = clearing_input_findings(
                data, days, available, allowed_modes, effective_hours, daily_targets, manual)
            answer["findings"].extend(input_findings)
            # Diagnose quantities only; this model never supplies a plan or a
            # FEASIBLE status. The production model keeps every hard rule.
            diagnosis = model.clone()
            differences = []
            for index, expression, target, gates, i, node in clear_requirements:
                diagnosis.proto.constraints[index].clear_linear()
                diagnosis.proto.constraints[index].enforcement_literal.clear()
                difference = diagnosis.new_int_var(0, stock_bound + target_bound, f"clear_difference:{index}")
                diagnosis.add(difference >= expression - target).only_enforce_if(gates)
                diagnosis.add(difference >= target - expression).only_enforce_if(gates)
                differences.append(difference)
            diagnosis.minimize(sum(differences))
            diagnostic = cp_model.CpSolver()
            diagnostic.parameters.random_seed = 0
            diagnostic.parameters.num_workers = 1
            diagnostic.parameters.max_deterministic_time = 5.0
            diagnostic_status = diagnostic.solve(diagnosis)
            if diagnostic_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                for _, expression, target, gates, i, node in clear_requirements:
                    if not all(diagnostic.boolean_value(gate) for gate in gates):
                        continue
                    actual, required = diagnostic.value(expression), diagnostic.value(target)
                    if actual == required:
                        continue
                    pre = next((t for t in range(i, count) if diagnostic.boolean_value(pre_stop[t])), None)
                    stop_date = days[pre + 1] if pre is not None and pre + 1 < count else "UNKNOWN"
                    answer["findings"].append(f"【停前出清诊断】停线 {stop_date}，{days[i]} {node}：要求 {required} 台，诊断值 {actual} 台，相差 {abs(actual - required)} 台；仅为放开出清等式后的诊断差额，不是可行计划或不可行证明。")
            else:
                if input_findings:
                    answer["findings"].append(f"【停前出清求解诊断】{diagnostic.status_name(diagnostic_status)}；"
                                              "未找到放开出清等式后的诊断解；上方台数差额来自输入必要条件核算。")
                else:
                    answer["findings"].append(f"【停前出清诊断】{diagnostic.status_name(diagnostic_status)}；未找到可量化差额的诊断解，停线归因及差额 UNKNOWN。")
            return answer
        if budgets is LEVEL_BUDGETS and label == "L1c" and budgets[label] > 0:
            for mo in months:
                if mo in idle_months:
                    continue
                conflicts = []
                for i, day in enumerate(days):
                    if day[:7] != mo or not production_days[i]:
                        continue
                    for m in vehicles:
                        required = sum(pr[m][t] for t in months if t <= mo)
                        previous = incumbent.value(cumulative_fok[m, i - 1]) if i else 0
                        if previous < required:
                            continue
                        for w in workshops:
                            before = sum(initial[w, v] for v in vehicles) if i == 0 else incumbent.value(totals[w, i - 1])
                            missing = max(0, daily_targets[w, i] - before)
                            out = incumbent.value(outputs[w, m, i])
                            limit = missing if incumbent.value(outputs['AS_FIN', m, i]) == 0 else out + missing
                            if incumbent.value(inputs[w, m, i]) > limit:
                                conflicts.append((day, w, m))
                if not conflicts:
                    continue
                month_indices = [i for i, day in enumerate(days) if day[:7] == mo]
                last_completion = max(i for i in month_indices if incumbent.value(total_out['AS_FIN', i]) > 0)
                tail = [i for i in month_indices if i > last_completion]
                if not any(production_days[i] for i in tail):
                    continue
                forced = model.clone()
                guide_monthly_idle(forced, [mo], [mo], [mo])
                for i in tail:
                    for w in workshops:
                        forced.add(total_in[w, i] == 0)
                        forced.add(total_out[w, i] == 0)
                for bit in list(switches.values()) + list(clear_start.values()) + list(bs_hold.values()) + list(change.values()):
                    forced.add(bit == incumbent.value(bit))
                affected_models = {m for _, _, m in conflicts}
                last_gap = max([months.index(mo)] + [pos for m in affected_models for pos, t in enumerate(months)
                    if incumbent.value(monthly_shortfalls[vehicles.index(m) * len(months) + pos]) > 0])
                window = months[months.index(mo):last_gap + 3]
                for i, day in enumerate(days):
                    if day[:7] not in window:
                        for w in workshops:
                            for m in vehicles:
                                for flow in (inputs, outputs):
                                    forced.add(flow[w, m, i] == incumbent.value(flow[w, m, i]))
                forced.clear_hints()
                forced.proto.search_strategy.clear()
                check = cp_model.CpSolver()
                check.parameters.random_seed = 0
                check.parameters.num_workers = 1
                check.parameters.cp_model_probing_level = 0
                check.parameters.max_deterministic_time = 3.0
                probe_start = perf_counter()
                probe_status = check.solve(forced)
                changes = []
                if probe_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    for m in vehicles:
                        for t in months:
                            gap = monthly_shortfalls[vehicles.index(m) * len(months) + months.index(t)]
                            delta = (check.value(gap) - incumbent.value(gap)) / ratio.denominator
                            if delta:
                                changes.append((m, t, delta))
                    if all(delta <= 0 for _, _, delta in changes) and (check.value(objective) < incumbent.value(objective) or check.value(sum(excesses)) <= incumbent.value(sum(excesses))) and warm_not_worse(check):
                        idle_months.append(mo)
                        idle_windows[mo] = window
                        incumbent = check
                print(f"monthly_idle_test month={mo}; stop_start={days[tail[0]]}; enabled={mo in idle_months}; status={check.status_name(probe_status)}; L1c_changes={changes}; L5_current={incumbent.value(sum(excesses))}; L5_forced={check.value(sum(excesses)) if probe_status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'UNKNOWN'}; bound={check.best_objective_bound / ratio.denominator}; solve_seconds={perf_counter() - probe_start:.6f}", flush=True)
        solver = incumbent
        value = int(solver.value(objective))
        reported = Fraction(value, ratio.denominator) if label == "L1c" else Fraction(value)
        levels.append({"level": label, "value": int(reported) if reported.denominator == 1 else float(reported), "proven_optimal": status == cp_model.OPTIMAL and (budgets is SMALL_LEVEL_BUDGETS or value == 0)})
        model.add(objective == value)
        model.clear_hints()
        if label != "L6":
            hint_all(model, solver, len(model.proto.variables))

    solver = incumbent
    answer = result("FEASIBLE", [])
    answer["objective"]["levels"] = levels
    annual_gaps = {m: int(solver.value(shortage)) for m, shortage in zip(vehicles, shortages)}
    monthly_gaps = {}
    for m in vehicles:
        if annual_gaps[m]:
            answer["findings"].append(f"【年度缺口】车型 {m}：全期需求减累计完工，欠 {annual_gaps[m]} 台。")
    for m in vehicles:
        for pos, month in enumerate(months):
            last = max(i for i, day in enumerate(days) if day[:7] == month)
            cumulative_pr = sum(pr[m][t] for t in months[:pos + 1])
            produced = int(solver.value(cumulative_fok[m, last]))
            gap = max(0, cumulative_pr - produced)
            monthly_gaps[m, month] = gap
            below_band = max(Fraction(0), cumulative_pr - ratio * pr[m][month] - produced)
            if gap and any(annual_gaps.values()):
                answer["findings"].append(f"【月末累计缺口】车型 {m}，{month} 月末：累计需求 {cumulative_pr} 台，累计完工 {produced} 台，累计缺口 {gap} 台。")
            if below_band and any(annual_gaps.values()):
                answer["findings"].append(f"【月末累计缺口】车型 {m}，{month} 月末：低于月度带下限 {float(below_band):g} 台（计入月度带下限缺口目标，与累计缺口分列）。")
    for m in vehicles:
        i = 0
        while i < count:
            if not solver.value(backlog[m, i]):
                i += 1
                continue
            first = i
            peak = 0
            while i < count and solver.value(backlog[m, i]):
                peak = max(peak, int(solver.value(backlog[m, i])))
                i += 1
            answer["findings"].append(f"【交付欠交】车型 {m}：{days[first]} 至 {days[i - 1]}，最大欠交 {peak} 台。")
    if any(annual_gaps.values()):
        for m in vehicles:
            if not annual_gaps[m]:
                continue
            line = lines[m]
            capacity = capacities[line][default]
            answer["findings"].append(f"【加班 / 周六建议】车型 {m}，焊装线 {line}：年度需补约 {annual_gaps[m]} 台 ≈ 该线 {annual_gaps[m] / capacity:.2f} 个单班（每班 {capacity} 台，按输入默认模式产能算；整班估算需 {ceil(Fraction(annual_gaps[m], capacity))} 个）。")
            deadlines = [month for month in months if monthly_gaps[m, month]]
            for month in deadlines:
                gap = monthly_gaps[m, month]
                answer["findings"].append(f"【加班 / 周六建议】{line} 截至 {month} 月末累计需补约 {gap} 台，折合 {ceil(Fraction(gap, capacity))} 个默认单班；各月为累计快照，不相加。")
            overtime = [f"{mode}（{hours:g} 小时，每班 {capacities[line][mode]} 台，较默认增加 {capacities[line][mode] - capacity} 台）"
                        for mode, hours in factory["modes"].items() if hours > factory["modes"][default]]
            for month in months:
                if month > deadlines[-1]:
                    continue
                deadline_month = next(t for t in deadlines if t >= month)
                deadline = max(d for d in days if d[:7] == deadline_month)
                saturdays = [day for i, day in enumerate(days) if day[:7] == month
                             and dates[i].weekday() == SATURDAY and not working[i] and not available[line, i]
                             and not any(c["type"] == "SHUTDOWN" and c["start"] <= day <= c["end"] and line in c.get("workshops", workshops) for c in data["conditions"])
                             and solver.value(owner[line, i]) and solver.value(totals[line, i]) > 0
                             and day < deadline]
                weekdays = [day for i, day in enumerate(days) if day[:7] == month
                            and working[i] and solver.value(full[line, i])
                            and day < deadline]
                if saturdays:
                    answer["findings"].append(f"【加班 / 周六建议】{line}，{month} 可补授权的周六候选（用于 {deadline_month} 月末及以后缺口）：{'、'.join(saturdays)}。")
                if weekdays and overtime:
                    answer["findings"].append(f"【加班 / 周六建议】{line}，{month} 满产工作日候选（用于 {deadline_month} 月末及以后缺口）：{'、'.join(weekdays)}；可申请模式：{'；'.join(overtime)}。")
        answer["findings"].append("【加班 / 周六建议】以上仅为焊装产能估算；候选日期须早于拟补缺口的月末，下游车间同日也需授权，实际补产量以重算为准。请排产员补加班 / 周六授权条件后重算")
    if coarse_bound is not None:
        answer["findings"].append(f"【求解状态】年度缺口目标（L1a）当前 {sum(annual_gaps.values())} 台，下界 {coarse_bound} 台；下界来源：月度产能松弛模型。")
    for level in levels:
        if not level["proven_optimal"] and refine_solve is None:
            answer["findings"].append(f"【求解状态】{level['level']} 未证最优，当前值 {level['value']}。")
    answer["stop_list"] = []
    for i in range(count):
        if solver.value(stop_starts[i]):
            after = i
            while after < count and not solver.value(ps_restart[after]):
                after += 1
            length = after - i + (tail_days if after == count else 0)
            target = rules["ps_pre_stop_target_long" if length >= rules["ps_long_stop_days"] else "ps_pre_stop_target_short"]
            override = manual.get(i - 1) if i and solver.value(pre_stop[i - 1]) else None
            if override:
                target = override["target"]
            source = f"MANUAL:{override['id']}" if override else "DEFAULT"
            level = stop_level(data, "PS", days[i], (dates[i] + timedelta(days=length - 1)).isoformat(), days=level_days)
            if not override and level is not None:
                target, source = level[0], f"WIP_TARGET:{level[1]}"
            answer["stop_list"].append({
                "start": days[i], "end": (dates[i] + timedelta(days=length - 1)).isoformat(),
                "length": length, "pre_stop_date": days[i - 1] if i else None,
                "target": target if i else None, "source": source,
            })
    for i, condition in manual.items():
        if not solver.value(pre_stop[i]):
            answer["findings"].append(f"未匹配的人工停前目标：{condition['id']}，{days[i]}，target={condition['target']}。")
    template_records = templates(solver)
    for entry in answer["stop_list"]:
        pre = days.index(entry["pre_stop_date"]) if entry["pre_stop_date"] else -1
        clears = [r for r in template_records if r[0] == "清线" and r[3] == pre]
        if not clears:
            continue
        clear = clears[0]
        resumes = [r for r in template_records if r[0] == "复线" and r[1] == clear[1] and days[r[2]] > entry["end"]]
        resume = min(resumes, key=lambda r: r[2]) if resumes else None
        def template_label(record):
            if record is None:
                return "求解（复工不在计划期内）"
            kind, line, begin, _, reason = record
            if not reason and (kind, line, begin) in template_uses:
                return "模板"
            return "求解（" + (reason or "本次搜索未固定模板") + "）"
        answer["findings"].append(f"{entry['start']} 至 {entry['end']} 清线：{template_label(clear)}；复线：{template_label(resume)}")
    for i, day in enumerate(days):
        row = {"date": day, "workshops": {}, "bod": {}, "eod": {}}
        for w in workshops:
            selected = next(k for k, bit in modes[w, i].items() if solver.value(bit))
            row["workshops"][w] = {
                "mode": selected, "hours": effective_hours[w, i][selected],
                "in": {m: int(solver.value(inputs[w, m, i])) for m in vehicles},
                "out": {m: int(solver.value(outputs[w, m, i])) for m in vehicles},
            }
        for n in nodes:
            row["bod"][n] = {m: initial[n, m] if i == 0 else int(solver.value(stocks[n, m, i - 1])) for m in vehicles}
            row["eod"][n] = {m: int(solver.value(stocks[n, m, i])) for m in vehicles}
        row["fok"] = {m: int(solver.value(outputs["AS_FIN", m, i])) for m in vehicles}
        row["fin"] = {m: int(solver.value(finished[m, i])) for m in vehicles}
        row["bl"] = {m: int(solver.value(backlog[m, i])) for m in vehicles}
        phases = [name for name, bit in (
            ("PS_PRE_STOP", pre_stop[i]), ("STOP", stop[i]),
            ("BS_CLEAR", clearing[i]),
            ("REFILL", refill[i]), ("FIRST_START", first_start[i]), ("CHANGEOVER", change[i]),
            ("INITIAL_DRAIN", initial_drain[i]),
        ) if solver.value(bit) and (name in ("PS_PRE_STOP", "STOP") or production_days[i])]
        if solver.value(lowering[i]) and "PS_PRE_STOP" not in phases:
            phases.insert(0, "PS_PRE_STOP")
        row["phase"] = "+".join(phases) if phases else "NORMAL"
        answer["days"].append(row)
    answer["findings"].extend(prebuild_findings(data, answer["days"]))
    return answer
