"""Arithmetic long-stop flow templates; all quantities come from the request."""


def clear_rows(line, capacities, targets, stop_target, buffer_limits):
    """Include the reduced-input day, followed by zero-input clearing days."""
    stock = dict(targets)
    stopped = {**targets, line: 0, "WBS": 0, "PS": stop_target}
    release = sum(targets.values()) - sum(stopped.values())
    first_input = sum(cap["AS_FIN"] for cap in capacities) - release
    if not 0 <= first_input <= capacities[0][line]:
        return None
    rows = []
    for pos, cap in enumerate(capacities):
        weld_in = first_input if pos == 0 else 0
        weld_out = cap[line] if pos == 0 else min(
            cap[line], stock[line], buffer_limits["WBS"] - stock["WBS"] + cap["PS"])
        ps_in = min(cap["PS"], stock["WBS"] + weld_out)
        ps_out = cap["PS"]
        main_in = min(cap["AS_MAIN"], stock["PBS"] + ps_out - targets["PBS"])
        main_out = cap["AS_MAIN"]
        fin_in, fin_out = main_out, cap["AS_FIN"]
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
                or any(stock[n] < 0 or stock[n] > buffer_limits.get(n, targets[n]) for n in stock)
                or stock["PS"] < stop_target
                or any(stock[n] < targets[n] for n in ("PBS", "AS_MAIN", "AS_FIN"))):
            return None
        rows.append(flow)
    return rows if stock == stopped else None


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
