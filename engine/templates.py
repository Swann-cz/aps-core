"""Arithmetic long-stop flow templates; all quantities come from the request."""


def clear_rows(line, capacities, targets, stop_target, buffer_limits, *, stop_levels=None, stop_ranges=True):
    """Include the reduced-input day, followed by zero-input clearing days."""
    stock = dict(targets)
    stopped = {**targets, **(stop_levels or {}), line: 0, "WBS": 0, "PS": stop_target}
    release = sum((targets[n] - stopped[n] if n == "PBS" or not stop_ranges else
                   max(0, targets[n] - stopped[n])) for n in targets)
    first_input = sum(cap["AS_FIN"] for cap in capacities) - release
    if not 0 <= first_input <= capacities[0][line]:
        return None
    rows = []
    for pos, cap in enumerate(capacities):
        before = dict(stock)
        weld_in = first_input if pos == 0 else 0
        weld_out = cap[line] if pos == 0 else min(
            cap[line], stock[line], buffer_limits["WBS"] - stock["WBS"] + cap["PS"])
        ps_in = min(cap["PS"], stock["WBS"] + weld_out)
        ps_keep = targets["PS"] if pos == 0 else stop_target
        ps_out = min(cap["PS"], max(0, stock["PS"] + ps_in - ps_keep)) if stop_ranges else cap["PS"]
        pbs_keep = max(targets["PBS"], stopped["PBS"]) if pos == 0 else stopped["PBS"]
        main_in = min(cap["AS_MAIN"], max(0, stock["PBS"] + ps_out - pbs_keep))
        main_keep = targets["AS_MAIN"] if pos == 0 else stopped["AS_MAIN"]
        main_out = min(cap["AS_MAIN"], max(0, stock["AS_MAIN"] + main_in - main_keep)) if stop_ranges else cap["AS_MAIN"]
        fin_in = main_out
        fin_keep = targets["AS_FIN"] if pos == 0 else stopped["AS_FIN"]
        fin_out = min(cap["AS_FIN"], max(0, stock["AS_FIN"] + fin_in - fin_keep)) if stop_ranges else cap["AS_FIN"]
        flow = {line: (weld_in, weld_out), "PS": (ps_in, ps_out),
                "AS_MAIN": (main_in, main_out), "AS_FIN": (fin_in, fin_out)}
        stock[line] += weld_in - weld_out
        stock["WBS"] += weld_out - ps_in
        stock["PS"] += ps_in - ps_out
        stock["PBS"] += ps_out - main_in
        stock["AS_MAIN"] += main_in - main_out
        stock["AS_FIN"] += fin_in - fin_out
        if (any(value < 0 for pair in flow.values() for value in pair)
                or any(max(pair) > cap[w] for w, pair in flow.items())
                or any(stock[n] < 0 or stock[n] > buffer_limits.get(n, targets[n]) for n in stock)):
            return None
        if not stop_ranges and (stock["PS"] < stop_target
                or any(stock[n] < targets[n] for n in ("PBS", "AS_MAIN", "AS_FIN"))):
            return None
        rows.append(flow)
    if not stop_ranges:
        return rows if stock == stopped else None
    incoming = {"PS": ps_in, "PBS": ps_out, "AS_MAIN": main_in, "AS_FIN": fin_in}
    return rows if (stock[line] == stock["WBS"] == 0 and all(
        min(stopped[n], targets[n], before[n] + incoming[n]) <= stock[n] <= stopped[n]
        for n in incoming)) else None


def refill_rows(line, capacities, targets, stop_target, buffer_limits):
    stock = {**targets, line: 0, "WBS": 0, "PS": stop_target}
    rows = []
    for cap in capacities:
        weld_in = cap[line]
        weld_out = min(cap[line], max(0, stock[line] + weld_in - targets[line]))
        ps_in = min(cap["PS"], max(0, stock["WBS"] + weld_out - targets["WBS"]))
        ps_out = min(cap["PS"], max(0, stock["PS"] + ps_in - targets["PS"])) if ps_in else 0
        main_in = min(cap["AS_MAIN"], max(0, stock["PBS"] + ps_out - targets["PBS"]))
        main_out = min(cap["AS_MAIN"], max(0, stock["AS_MAIN"] + main_in - targets["AS_MAIN"])) if main_in else 0
        fin_in = main_out
        fin_out = min(cap["AS_FIN"], max(0, stock["AS_FIN"] + fin_in - targets["AS_FIN"])) if fin_in else 0
        flow = {line: (weld_in, weld_out), "PS": (ps_in, ps_out),
                "AS_MAIN": (main_in, main_out), "AS_FIN": (fin_in, fin_out)}
        stock[line] += weld_in - weld_out
        stock["WBS"] += weld_out - ps_in
        stock["PS"] += ps_in - ps_out
        stock["PBS"] += ps_out - main_in
        stock["AS_MAIN"] += main_in - main_out
        stock["AS_FIN"] += fin_in - fin_out
        if (any(max(pair) > cap[w] for w, pair in flow.items())
                or any(stock[n] > buffer_limits.get(n, targets[n]) for n in stock)):
            return None
        rows.append(flow)
        if stock == targets:
            return rows
    return None
