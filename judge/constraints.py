"""硬约束检查 C1–C15（S1b：两车型、一次换型）。

判据一律以 CORE_MODEL 条文为准；本阶段实现 T-02 共同范围列出的部分，
在 T-01/T-01b 基础上扩充：C4 单班焊装、闲置线保持 0、换型阶段放宽与逐级补满、
C13 合法原因扩充、C14 按段与按车型「当月最后生产日」、C15 镜像、L2 换型次数。
见各函数 docstring 的条款映射。
"""
from __future__ import annotations

from datetime import date, timedelta

from .core import Judge, WORKSHOPS, NODES
from .model import parse_date


# 本阶段判定器需要消费的规则常数（IO_CONTRACT §2 rules）。缺失时不写死默认值，
# 记 INPUT 硬错误（AGENTS.md 规则 6）。
REQUIRED_RULES = ("monthly_band_ratio", "ps_stop_min_days",
                  "ps_long_stop_days", "ps_pre_stop_target_short", "ps_pre_stop_target_long")

WELDING_LINES = ("BS1", "BS2")


def _has_phase(ph: str | None, target: str) -> bool:
    """阶段字符串（可能为 NORMAL / 单阶段 / 多阶段 + 连接）是否包含 target 子阶段。"""
    if ph is None:
        return False
    return target in ph.split("+")


def _stop_exempts(j: Judge, ds: str, node: str) -> bool:
    if not _has_phase(j.phases.get(ds), "STOP"):
        return False
    d = parse_date(ds)
    shutdowns = j.inp.conditions_on("SHUTDOWN", d)
    if not shutdowns:
        return True
    stopped = {w for c in shutdowns for w in c["workshops"]}
    # T-11：部分车间停线不豁免其余节点的正常生产约束。
    return node in stopped or stopped == set(j.inp.workshops)


def check_input(j: Judge):
    for detail in j.inp.condition_errors:
        j._err("INPUT", None, None, None, detail)
    for f in REQUIRED_RULES:
        if f not in j.inp.rules or j.inp.rules[f] is None:
            j._err("INPUT", None, None, None, f"rules 缺字段 {f}")


def check_all(j: Judge):
    check_input(j)
    check_c1_topology(j)
    check_c2(j)
    check_c3(j)
    check_c4(j)
    check_c5(j)
    check_c6(j)
    check_c7(j)
    check_c8(j)
    check_c9(j)
    check_c10(j)
    check_c11(j)
    check_c12(j)
    check_c13(j)
    check_c14(j)
    check_c17(j)
    check_seq(j)
    check_changeover(j)
    check_initial_drain(j)
    check_first_start(j)
    check_pre_stop(j)
    check_level_drain(j)
    check_bs_clear(j)
    check_refill(j)
    check_fixed_output(j)
    check_ps_clear_down(j)
    check_clear_remainder(j)


def check_seq(j: Judge):
    """C16 / SEQ-01：期初全链累计量与换型顺序分别检查。"""
    models = j._models()
    shared = ("WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")
    initial_totals = {}
    for node in shared:
        upstream = {node}
        pending = [node]
        while pending:
            target = pending.pop()
            for edge in j.inp.flow:
                src, dst = edge.split(">")
                if dst == target and src not in upstream:
                    upstream.add(src)
                    pending.append(src)
        initial_totals[node] = {
            m: sum(j.inp.inv0.get(n, {}).get(m, 0) for n in upstream)
            for m in models
        }
    cumulative = {n: {m: 0 for m in models} for n in shared}
    initial = [m for m in models
               if sum(j.inp.inv0.get(j.inp.line_of[m], {}).values()) > 0]
    current = None
    draining = None
    if len(initial) == 1:
        current = initial[0]
    elif initial:
        draining = next((m for m in initial if j.initial_drain
                         and j.inp.line_of[m] == j.initial_drain["line"]), None)
        current = next((m for m in initial if m != draining), None)
    else:
        # 两条焊装线均无期初在制：用计划中下一个正投入认定新车型。
        current = next((m for d in j.inp.dates for m in models
                        if j._wq(d.isoformat(), j.inp.line_of[m], m, "in") > 0), None)
    old_model = None  # 期初排空不是 C16 意义上的换型。

    for d in j.inp.dates:
        ds = d.isoformat()
        active = next((m for m in models
                       if j.workshop_on(ds, j.inp.line_of[m])), None)
        if _has_phase(j.phases.get(ds), "INITIAL_DRAIN"):
            active = None
        if active is not None:
            if draining is None or active != draining:
                if active != current:
                    old_model = current
                current = active
                draining = None
        for node in shared:
            workshop = j.inp.downstream[node] if node in j.inp.buffers else node
            key = "in" if node in j.inp.buffers else "out"
            outputs = {m: j._wq(ds, workshop, m, key) for m in models}
            for m in models:
                cumulative[node][m] += outputs[m]
            for m in models:
                if cumulative[node][m] <= initial_totals[node][m]:
                    continue
                for other in models:
                    if other != m and cumulative[node][other] < initial_totals[node][other]:
                        j._err("SEQ", ds, node, m,
                               f"{node} {ds} 车型 {m} 累计出车 {cumulative[node][m]} 台"
                               f"超过全链上游及本节点期初 {initial_totals[node][m]} 台，"
                               f"车型 {other} 累计出车 {cumulative[node][other]} 台"
                               f"未达期初 {initial_totals[node][other]} 台（SEQ-01）")
            if old_model is None:
                continue
            out = outputs[current]
            if out <= 0:
                continue
            for old in (old_model,):
                remaining = j.eod[ds][node][old]
                if remaining > 0:
                    j._err("SEQ", ds, node, current,
                           f"{node} {ds} 旧车型 {old} 日末在制 {remaining} 台，"
                           f"新车型 {current} 出车 {out} 台（SEQ-01）")


# ---------- C1 拓扑守恒（车间→车间直连边） ----------

def check_c1_topology(j: Judge):
    """C1 / TOP-03：车间→车间直连边（本链只有 AS_MAIN→AS_FIN）下游车间当日
    投入必须等于上游车间当日产出，逐车型核对；不一致记 C1（写明日期、车型、两个数）。

    缓冲区上、下游与车间之间的边（如 WBS→PS、PBS→AS_MAIN）在 recompute_inventory
    里由缓冲 OUT=下游 IN 推导，天然一致，无需另查；只有 AS_MAIN→AS_FIN 两个车间
    直连，两边都是决策变量，必须显式核对。
    """
    for e in j.inp.flow:
        if ">" not in e:
            continue
        src, dst = e.split(">")
        if dst == "FIN" or src not in WORKSHOPS or dst not in WORKSHOPS:
            continue
        for d in j.inp.dates:
            ds = d.isoformat()
            for m in j._models():
                up_out = j._wq(ds, src, m, "out")
                down_in = j._wq(ds, dst, m, "in")
                if down_in != up_out:
                    j._err("C1", ds, dst, m,
                           f"{dst} 投入 {down_in} ≠ 上游 {src} 产出 {up_out}")


# ---------- C2 产能 ----------

def _totals(j: Judge, ds: str, w: str):
    models = j._models()
    inn = sum(j._wq(ds, w, m, "in") for m in models)
    out = sum(j._wq(ds, w, m, "out") for m in models)
    return inn, out


def check_c2(j: Judge):
    for d in j.inp.dates:
        ds = d.isoformat()
        for w in WORKSHOPS:
            mode = j._mode(ds, w)
            if mode is None:
                continue
            cap = j.inp.cap_for_mode(w, mode, parse_date(ds))
            inn, out = _totals(j, ds, w)
            if inn > cap:
                j._err("C2", ds, w, None, f"{w} 投入合计 {inn} 超过能力 {cap}（mode={mode}）")
            if out > cap:
                j._err("C2", ds, w, None, f"{w} 产出合计 {out} 超过能力 {cap}（mode={mode}）")


# ---------- C3 日历与授权 ----------

def check_c3(j: Judge):
    for d in j.inp.dates:
        ds = d.isoformat()
        for w in WORKSHOPS:
            mode = j._mode(ds, w)
            if mode is None:
                continue
            inn, out = _totals(j, ds, w)
            if not j.inp.is_available(w, d):
                if mode != "OFF":
                    j._err("C3", ds, w, None, f"不可生产日 {w} 采用 {mode}，只能 OFF")
                if inn != 0 or out != 0:
                    j._err("C3", ds, w, None, f"不可生产日 {w} 有流 IN={inn} OUT={out}")
            else:
                if not j.inp.mode_allowed(w, d, mode):
                    j._err("C3", ds, w, None,
                           f"无授权 {w} 采用 {mode}，只允许 {j.inp.default_mode}/OFF")


# ---------- C4 单班焊装 ----------

def check_c4(j: Judge):
    """C4（B05）：on(BS1,d) + on(BS2,d) ≤ 1；任一线当日有正 IN 或正 OUT 即 on = 1。
    启动、清线、补线都不例外。缺一条线（单车型未绑定的线即便不存在流量也计 0），
    天然满足 on≤1，故只查「同一天两条线都有正流量」。
    """
    for d in j.inp.dates:
        ds = d.isoformat()
        on = [l for l in WELDING_LINES if j.workshop_on(ds, l)]
        if len(on) > 1:
            j._err("C4", ds, None, None,
                   f"单班焊装违反：{on} 同日同时有流量（on 数量 {len(on)} > 1）")


# ---------- C5 车型绑线 ----------

def check_c5(j: Judge):
    for m, cfg in j.inp.models.items():
        line = cfg["line"]
        for d in j.inp.dates:
            ds = d.isoformat()
            for w in ("BS1", "BS2"):
                inn = j._wq(ds, w, m, "in")
                if inn > 0 and w != line:
                    j._err("C5", ds, w, m, f"车型 {m} 在 {w} 投入 {inn}，绑定线为 {line}")


# ---------- C6 物理上限 ----------

def check_c6(j: Judge):
    draining = {w: sum(j.inp.inv0.get(w, {}).values()) > j.inp.node_cap(w, j.inp.start)
                for w in j.inp.workshops}
    for d in j.inp.dates:
        ds = d.isoformat()
        for buf, cap_max in j.inp.buffers.items():
            total = sum(j.eod[ds].get(buf, {}).values())
            if total > cap_max:
                j._err("C6", ds, buf, None, f"{buf} EOD 合计 {total} 超过物理上限 {cap_max}")
        for w in j.inp.workshops:
            cap_max = j.inp.node_cap(w, d)
            total = j.node_eod_total(ds, w)
            before = sum(j.bod[ds][w].values())
            limit = before if draining[w] else cap_max
            if total > limit:
                j._err("C6", ds, w, None,
                       f"{w} {ds} EOD 合计 {total}，物理上限 {cap_max}，"
                       f"当日允许上限 {limit}（日初 {before}）")
            if total <= cap_max:
                draining[w] = False


# ---------- C7 胶龄 FIFO ----------

def check_c7(j: Judge):
    """C7 累计量线性式（B17：期初 WBS 按计划开始前一天焊出计龄）：
    对每个 d：
      1[d >= s-1+Lg] * inv0(WBS,m) + sum_{t <= d-Lg} out(BS_line,m,t) <= sum_{t <= d} in(PS,m,t)
    # TODO(边界): 计划期末之后的胶龄（WBS 期末在制在下一年进 PS）不检查——本检查只覆盖
    # 计划期内的 d，下一年进 PS 的胶龄留给 Rolling/下一年计划。
    """
    s = j.inp.start
    for m, cfg in j.inp.models.items():
        lg = cfg["glue_age_max"]
        line = cfg["line"]
        inv0_wbs = j.inp.inv0.get("WBS", {}).get(m, 0)
        cum_ps_in = 0
        for d in j.inp.dates:
            ds = d.isoformat()
            cum_ps_in += j._wq(ds, "PS", m, "in")
            weld_day = d - timedelta(days=lg)
            cum_weld_out = 0
            for t in j.inp.dates:
                if t <= weld_day:
                    cum_weld_out += j._wq(t.isoformat(), line, m, "out")
            indicator = 1 if d >= s + timedelta(days=lg - 1) else 0
            lhs = indicator * inv0_wbs + cum_weld_out
            if lhs > cum_ps_in:
                j._err("C7", ds, "PS", m,
                       f"胶龄：累计需进 PS {lhs} 台，实际 {cum_ps_in} 台")


# ---------- C8 七节点硬下限（+ 闲置线保持 0） ----------

def _current_welding_line(j: Judge, ds: str) -> str | None:
    """焊装「当前在产」线。换型前为旧线、换型后为新线、换型期内为 None（C8 放宽）。

    支持多次换型：按日期落在哪段区间判。无换型时：若只有一条线绑定了车型，则该线为
    在产线；两条线都绑车型而无换型时，非生产日（两条线都 OFF）沿用最近一个生产日的
    在产线（CORE_MODEL §5 普通周末不切段、不改变当前在产线），计划期首日之前没有生产日
    则按期初在制 / 首次启动确定。闲置线（另一条有车型绑定的线）须保持 0（由 check_c8 查）。
    """
    lines = [j.inp.line_of[m] for m in j._models()]
    if not lines:
        return None
    d = parse_date(ds)
    # 依次查找覆盖 d 的换型区间
    for co in j.changeovers:
        start = parse_date(co["start"])
        end = parse_date(co["end"])
        if start <= d <= end:
            return None  # 换型期内 C8 放宽
    # 换型之间：落在某次换型结束后、下次换型前 → 该次的新线；否则最早换型前的旧线。
    # 用「最后一次在 d 之前结束的换型的新线」，否则「第一次换型的旧线」。
    if j.changeovers:
        new_line = None
        for co in j.changeovers:
            if parse_date(co["end"]) < d:
                new_line = co["new_line"]
            elif parse_date(co["start"]) > d:
                break
        if new_line is not None:
            return new_line
        return j.changeovers[0]["old_line"]
    if len(lines) == 1:
        return lines[0]
    if j.initial_drain and ds > j.initial_drain["end"]:
        return j.initial_drain["other_line"]
    # 当天有正流量的线优先（工作日）；两条线都 OFF（非生产日 / 停线）时沿用最近一个
    # 生产日的在产线，而非返回 None 把在产线误判成闲置线（T-34-J R05）。
    on = [l for l in WELDING_LINES if j.workshop_on(ds, l)]
    if len(on) == 1:
        return on[0]
    if len(on) > 1:
        return None  # 同日两线同流由 C4 报错，此处不臆断
    for d2 in reversed(j.inp.dates):
        if d2 > d:
            continue
        on2 = [l for l in WELDING_LINES if j.workshop_on(d2.isoformat(), l)]
        if len(on2) == 1:
            return on2[0]
        if len(on2) > 1:
            return None
    # 计划期首日之前没有生产日：按期初在制 / 首次启动确定在产线。
    with_init = [l for l in WELDING_LINES if sum(j.inp.inv0.get(l, {}).values()) > 0]
    if len(with_init) == 1:
        return with_init[0]
    if len(with_init) > 1:
        return None  # 双线期初在制由 INITIAL_DRAIN 处理
    return next((j.inp.line_of[m] for m in j._models()
                 if any(j._wq(d2.isoformat(), j.inp.line_of[m], m, "in") > 0
                        for d2 in j.inp.dates)), None)


def check_c8(j: Judge):
    """C8：正常生产日每个节点 EOD ≥ tgt；共享节点按两车型合计。
    焊装只约束「当前在产」线（EOD ≥ tgt），闲置线保持 0。
    换型期 / 停线日 / 补线日全链不查 C8；停前日只有 PS 免 C8（降到停前目标），
    其余节点仍查（暂定口径，见 tasks/T-04 与 cases/1c-short-stop/README）。
    BS 清线期只对该焊装线和 WBS 免 C8（阶段重叠第 1 条：按节点、按日），其余节点照查。
    """
    lines_with_model = set(j.inp.line_of.values())
    for d in j.inp.dates:
        ds = d.isoformat()
        ph = j.phases.get(ds)
        if (_has_phase(ph, "CHANGEOVER") or _has_phase(ph, "REFILL")
                or _has_phase(ph, "FIRST_START") or _has_phase(ph, "INITIAL_DRAIN")):
            continue  # 换型/停线/补线/首次启动期放宽：不查 C8
        for node in NODES:
            if _stop_exempts(j, ds, node):
                continue
            if node == "PS" and _has_phase(ph, "PS_PRE_STOP"):
                continue  # 停前日 PS 降到停前目标，免 C8（由 check_pre_stop 对账）
            if _drains_to_stop_level(j, ds, node):
                continue  # rev 204：降到人工停前水位途中免 C8（由 check_pre_stop 对账）
            # 清线期：只对该焊装线和 WBS 免 C8（按节点、按日）
            if _in_bs_clear(j, ds, node):
                continue
            if node in WELDING_LINES:
                if (j.initial_drain and ds < j.initial_drain["start"]
                        and not any(j.is_production_day(l, d) for l in WELDING_LINES)):
                    continue  # 期首停线尚未到排空工作日。
                if node not in lines_with_model:
                    continue  # 没有车型绑定的焊装线不查（保持 0 由 C1 守恒自然满足）
                cur = _current_welding_line(j, ds)
                total = j.node_eod_total(ds, node)
                if node == cur:
                    if _is_bs_clear_prequel(j, ds, node):
                        continue  # T-18 零头：清线前一天本线日末可低于 tgt（只此一天、只此节点）
                    tgt = j.inp.node_target(node, parse_date(ds))
                    if j.is_production_day(node, d) and total < tgt:
                        j._err("C8", ds, node, None, f"{node} EOD 合计 {total} < 目标 {tgt}")
                else:
                    # 闲置线：须保持 0
                    if total != 0:
                        j._err("C8", ds, node, None, f"闲置焊装线 {node} EOD 合计 {total} ≠ 0")
            else:
                if not (j.is_production_day(node, d) if node in j.inp.workshops
                        else any(j.is_production_day(w, d) for w in WORKSHOPS)):
                    continue
                total = j.node_eod_total(ds, node)
                tgt = j.inp.node_target(node, parse_date(ds))
                if total < tgt:
                    j._err("C8", ds, node, None, f"{node} EOD 合计 {total} < 目标 {tgt}")


# ---------- C9 WBS 经验带 ----------

def _drains_to_stop_level(j: Judge, ds: str, node: str) -> bool:
    """rev 204：node 当天是否在降往人工停前水位的途中（PS 停前降库期，没有清线时只有停前日）。"""
    for sw in j.stop_windows:
        pre = sw.get("pre_stop_date")
        if pre is None or node not in sw.get("levels", {}):
            continue
        if sw.get("drain_from", {}).get(node, pre) <= ds <= pre:
            return True
    return False


def _level_drain_day(j: Judge, ds: str, w: str) -> bool:
    """rev 205：总装车间 w 当天是否在提前降库期——w 自己或它上游的 PBS（总装主线）在降。"""
    if w == "AS_MAIN":
        return _drains_to_stop_level(j, ds, "AS_MAIN") or _drains_to_stop_level(j, ds, "PBS")
    if w == "AS_FIN":
        return _drains_to_stop_level(j, ds, "AS_FIN") or _level_drain_day(j, ds, "AS_MAIN")
    return False


def check_level_drain(j: Judge):
    """rev 205 总装提前降库：有停前水位的总装两段，从降库起点到首个 BS 清线日前一天（没有
    清线时到停前日）每天出车 = min(当日选定班制产能, 日初 + 投入 − 停前水位)；整个降库期
    （到停前日）不满产之后不得再满产。总装主线或 PBS 在降的日子（清线前），总装主线投入
    = min(当日产能, PBS 日初 + PS 出车 − PBS 保留量)，PBS 保留量在 PBS 降库时取停前水位，
    否则取正常目标（这几天总装免 C14，由本函数代替）。不符记 PS_PRE_STOP。清线段内的出车
    公式由 check_clear_remainder 查。"""
    for sw in j.stop_windows:
        pre = sw.get("pre_stop_date")
        if pre is None:
            continue
        clear = next((p["start"] for p in j.ps_clear_down_periods if p["end"] == pre), None)
        for d in j.inp.dates:
            ds = d.isoformat()
            if ds > pre or (clear is not None and ds >= clear) or not _level_drain_day(j, ds, "AS_MAIN"):
                continue
            if not any(_drains_to_stop_level(j, ds, n) and n in sw.get("levels", {}) for n in ("PBS", "AS_MAIN")):
                continue
            cap = j.inp.cap_for_mode("AS_MAIN", j._mode(ds, "AS_MAIN") or "OFF", d)
            pbs_bod = sum(j.bod[ds].get("PBS", {}).values())
            ps_out = j.workshop_total(ds, "PS", "out")
            keep = sw["levels"]["PBS"] if _drains_to_stop_level(j, ds, "PBS") else j.inp.node_target("PBS", d)
            want = min(cap, pbs_bod + ps_out - keep)
            inn = j.workshop_total(ds, "AS_MAIN", "in")
            if inn != want:
                j._err("PS_PRE_STOP", ds, "AS_MAIN", None,
                       f"提前降库总装主线投入 {inn} ≠ min(产能 {cap}, PBS 日初 {pbs_bod} + 涂装出车 {ps_out} "
                       f"− PBS 保留 {keep}) = {want}")
    for sw in j.stop_windows:
        pre = sw.get("pre_stop_date")
        if pre is None:
            continue
        clear = next((p["start"] for p in j.ps_clear_down_periods if p["end"] == pre), None)
        for w in ("AS_MAIN", "AS_FIN"):
            if w not in sw.get("levels", {}):
                continue
            level = sw["levels"][w]
            first_under = None
            d = parse_date(sw["drain_from"][w])
            while d <= parse_date(pre):
                ds = d.isoformat()
                cap = j.inp.cap_for_mode(w, j._mode(ds, w) or "OFF", d)
                bod = sum(j.bod[ds].get(w, {}).values())
                inn = j.workshop_total(ds, w, "in")
                out = j.workshop_total(ds, w, "out")
                want = min(cap, bod + inn - level)
                if (clear is None or ds < clear) and out < want:
                    j._err("PS_PRE_STOP", ds, w, None,
                           f"提前降库 {w} 出车 {out} < 能做尽做 {want}（产能 {cap}，日初 {bod} + 投入 {inn} − 停前水位 {level}）")
                if out < cap and first_under is None:
                    first_under = ds
                elif out >= cap > 0 and first_under is not None:
                    j._err("PS_PRE_STOP", ds, w, None,
                           f"降库期 {w} 不满产日 {first_under} 之后仍满产（不满应落在最后）")
                d += timedelta(days=1)


def check_c9(j: Judge):
    if j.inp.wbs_hi is None:
        return
    for d in j.inp.dates:
        ds = d.isoformat()
        if not j.is_production_day("PS", d):
            continue
        if _has_phase(j.phases.get(ds), "CHANGEOVER") or _stop_exempts(j, ds, "WBS") \
                or _has_phase(j.phases.get(ds), "REFILL") or _has_phase(j.phases.get(ds), "PS_PRE_STOP") \
                or _has_phase(j.phases.get(ds), "FIRST_START") \
                or _has_phase(j.phases.get(ds), "INITIAL_DRAIN"):
            continue  # 换型/停线/补线/停前日/首次启动日不查 C9
        if _in_bs_clear(j, ds, "WBS"):
            continue  # 清线期：WBS 免 C9（按节点、按日）
        total = sum(j.eod[ds].get("WBS", {}).values())
        if total > j.inp.wbs_hi:
            # C9 只在焊装与 PS 都满产日为硬约束；否则只报告
            weld_full = _welding_full(j, ds)
            ps_full = _totals(j, ds, "PS")[0] >= j.inp.cap_for_mode("PS", j._mode(ds, "PS") or "OFF", d)
            if weld_full and ps_full:
                j._err("C9", ds, "WBS", None, f"WBS EOD {total} > wbs_hi {j.inp.wbs_hi}")
            else:
                j.reports.append({
                    "rule": "C9", "date": ds, "node": "WBS", "model": None,
                    "detail": f"WBS EOD {total} > wbs_hi {j.inp.wbs_hi}（非满产日，仅报告）",
                })


def _welding_full(j: Judge, ds: str) -> bool:
    lines_in_use = {cfg["line"] for cfg in j.inp.models.values()}
    for w in ("BS1", "BS2"):
        if w not in lines_in_use:
            continue
        mode = j._mode(ds, w) or "OFF"
        if mode == "OFF":
            return False
        if _totals(j, ds, w)[0] < j.inp.cap_for_mode(w, mode, parse_date(ds)):
            return False
    return True


# ---------- C10 年度闭合 ----------

def check_c10(j: Judge):
    """C10（2026-10-24 裁决）：全期 FOK ≤ 全期 PR，只查超产；
    欠产计入 L1a，不是硬错误。"""
    for m in j._models():
        pr_total = sum(j.inp.pr.get(m, {}).values())
        fok_total = sum(j.fok[ds].get(m, 0) for ds in j.eod)
        if fok_total > pr_total:
            j._err("C10", j.inp.end.isoformat(), "AS_FIN", m,
                   f"FOK 合计 {fok_total} > PR 合计 {pr_total}（超产）")


# ---------- C11 交付时点 ----------

def check_c11(j: Judge):
    """C11（2026-10-24 裁决）：fin − bl 逐日守恒（由 fin0、fok、WS 推出），
    fin ≥ 0、bl ≥ 0、两者不同时为正（有车先补交）。bl 是累计欠交，期初 0。
    计划自报的 fin/bl 与判定器独立递推不一致时，由 reconcile 记 C11；此处只查
    三个不等式（重算值恒满足 fin−bl 守恒，故只可能违反 fin/bl 同正或负值，而
    bl = max(0,−g)、fin 重算值可使 fin 与 bl 同负的情况由守恒唯一推出，见返回）。"""
    for d in j.inp.dates:
        ds = d.isoformat()
        for m in j._models():
            fin = j.fin[ds].get(m, 0)
            b = j.bl[ds].get(m, 0)
            if fin < 0:
                j._err("C11", ds, "FIN", m, f"成品库存 {fin} < 0")
            if b < 0:
                j._err("C11", ds, "FIN", m, f"欠交 {b} < 0")
            if fin > 0 and b > 0:
                j._err("C11", ds, "FIN", m, f"成品 {fin} 与欠交 {b} 同时为正")


# ---------- C12 月度带 ----------

def check_c12(j: Judge):
    """C12（2026-10-24 裁决）：下限缺口计入 L1c，不再是硬错误；只查上限；
    末月改为 cumFOK ≤ cumPR（差额即 C10 缺口）。"""
    models = j._models()
    months = j.inp.months_in_horizon()
    cum_pr = {m: 0 for m in models}
    cum_fok = {m: 0 for m in models}
    band = j.inp.rules.get("monthly_band_ratio")
    early = j.inp.prebuild()  # rev 204 必须提前量
    for i, mo in enumerate(months):
        for m in models:
            cum_pr[m] += j.inp.pr.get(m, {}).get(mo, 0)
        for d in j.inp.dates:
            if j.inp.month_of(d) == mo:
                ds = d.isoformat()
                for m in models:
                    cum_fok[m] += j.fok[ds].get(m, 0)
        for m in models:
            if i == len(months) - 1:
                if cum_fok[m] > cum_pr[m]:
                    j._err("C12", mo, "AS_FIN", m,
                           f"末月 {mo} 累计 FOK {cum_fok[m]} > 累计 PR {cum_pr[m]}")
            else:
                if band is None:
                    # 缺 monthly_band_ratio 已由 INPUT 硬错误报告（check_input），此处不再兜底
                    continue
                nxt = months[i + 1]
                e = early[m][mo]
                hi = cum_pr[m] + max(band * j.inp.pr.get(m, {}).get(nxt, 0), e)
                if cum_fok[m] > hi + 1e-9:
                    j._err("C12", mo, "AS_FIN", m,
                           f"{mo} 累计 FOK {cum_fok[m]} 超过上限 {hi:.1f}"
                           + (f"（含后面月份做不完的必须提前量 {e}）" if e else ""))
                elif e > band * j.inp.pr.get(m, {}).get(nxt, 0) and cum_fok[m] > cum_pr[m]:
                    j.reports.append({"rule": "C12", "date": mo, "node": "AS_FIN", "model": m,
                                      "detail": f"{mo} 车型 {m} 因后面月份做不完提前生产 "
                                                f"{cum_fok[m] - cum_pr[m]} 台（必须提前量 {e}）"})


# ---------- C13 空闲许可 ----------

def _in_production_workshops(j: Judge) -> list[str]:
    """本阶段「在产车间」= 各车型绑定的焊装线 + PS + AS_MAIN + AS_FIN。

    闲置焊装线（没有车型绑定）不在此列，不查 C13/C14。
    """
    ws = {cfg["line"] for cfg in j.inp.models.values()}
    ws.update(("PS", "AS_MAIN", "AS_FIN"))
    return sorted(ws)


def _workshop_flow(j: Judge, ds: str, w: str, key: str) -> int:
    """车间 w 当日全车型 in/out 合计（本阶段共享车间按两车型合计）。"""
    return sum(j._wq(ds, w, m, key) for m in j._models())


def _cum_fok_to_day_start(j: Judge, m: str, d) -> int:
    """截至前一日（日初）的完成线累计 FOK：从计划期起点的完成线累计，到 d 的前一自然日为止。

    C13（2026-10-24 裁决）：「需求已排完」= 日初完成线 cumFOK ≥ 从计划期首月累计到当月的 cumPR。
    """
    total = 0
    for d2 in j.inp.dates:
        if d2 >= d:
            break
        total += j.fok[d2.isoformat()].get(m, 0)
    return total


def _cum_pr_to_month(j: Judge, m: str, d) -> int:
    """从计划期首月累计到 d 所属当月的 cumPR（含当月）。"""
    mo = j.inp.month_of(d)
    total = 0
    for mo2 in j.inp.months_in_horizon():
        total += j.inp.pr.get(m, {}).get(mo2, 0)
        if mo2 == mo:
            break
    return total


def _in_changeover(j: Judge, ds: str) -> bool:
    return _has_phase(j.phases.get(ds), "CHANGEOVER")


def check_c13(j: Judge):
    """C13 空闲许可（扩充）：可生产日任一车间全车型 IN=OUT=0，都要有合法原因。

    合法原因（tasks/T-02.md 共同范围）：
    - 「需求已排完」：截至前一日（日初）完成线 cumFOK ≥ 从计划期首月累计到当月的
      cumPR，且空闲只能在一整段连续生产结束后，不能在段中间空（段中间按同月判）；
      焊装线只看绑在该线上的车型（C13「只在**该车型**…时成立」），PS/PBS/总装等
      共享车间看当天所有车型（任一车型未排完都不算排完）；
    - 「另一条焊装线占用班组」：只有焊装线（BS1/BS2）适用——当天另一条线 on=1，本线空闲；
    - 「补线中」（换型期内）车间空闲合法（§5 换型放宽）。
    闲置焊装线（无车型绑定）不查。
    """
    for w in _in_production_workshops(j):
        for d in j.inp.dates:
            ds = d.isoformat()
            if not j.is_production_day(w, d):
                continue
            idle = all(
                j._wq(ds, w, m, "in") == 0 and j._wq(ds, w, m, "out") == 0
                for m in j._models()
            )
            if not idle:
                continue
            # 换型期 / 补线期 / 停线日 / 首次启动期车间空闲合法（「补线中」/「停线条件」）
            if _has_phase(j.phases.get(ds), "CHANGEOVER") or _has_phase(j.phases.get(ds), "REFILL") \
                    or _stop_exempts(j, ds, w) or _has_phase(j.phases.get(ds), "FIRST_START"):
                continue
            # 清线期该焊装线空闲合法（清线中 / 清线后保持，C13「清线后保持」）
            if _in_bs_clear(j, ds, w):
                continue
            # 焊装线：另一条线占用班组
            if w in WELDING_LINES:
                if _has_phase(j.phases.get(ds), "INITIAL_DRAIN"):
                    continue  # 排空占用班组，排空线清空后保持，另一线不开工。
                other = [l for l in WELDING_LINES if l != w]
                if any(j.workshop_on(ds, o) for o in other):
                    continue
            mo = j.inp.month_of(d)
            # C13「需求已排完」只在**该车型**截至前一日完成线 cumFOK ≥ 当月累计 cumPR 时成立：
            # 焊装线只看绑在这条线上的车型；PS、PBS、总装等共享车间看当天所有车型（任一车型
            # 未排完都不算排完）。
            if w in WELDING_LINES:
                bound = next((m for m, l in j.inp.line_of.items() if l == w), None)
                done = (bound is not None
                        and _cum_fok_to_day_start(j, bound, d) >= _cum_pr_to_month(j, bound, d))
            else:
                done = all(
                    _cum_fok_to_day_start(j, m, d) >= _cum_pr_to_month(j, m, d)
                    for m in j._models()
                )
            if done:
                later_flow = any(
                    (j.inp.month_of(d2) == mo)
                    and (_workshop_flow(j, d2.isoformat(), w, "in") > 0
                         or _workshop_flow(j, d2.isoformat(), w, "out") > 0)
                    for d2 in j.inp.dates if d2 > d and j.is_production_day(w, d2)
                )
                if later_flow:
                    j._err("C13", ds, w, None,
                           "需求已排完但在段中间空闲（其后同月仍有生产）")
            else:
                j._err("C13", ds, w, None,
                       "可生产日空闲但需求未排完（截至前一日完成线 cumFOK < 当月累计 cumPR）")


# ---------- C14 满负荷生产段（按换型切分 + 按车型当月最后生产日 + C15 镜像） ----------

def _direct_upstream_node(j: Judge, w: str) -> str | None:
    """车间 w 的直接上游节点名（缓冲或车间），由 input flow 推导；多上游或无则 None。

    用于 C15 镜像：上游节点 EOD 已等于 tgt → 下游车间不满产合法。
    """
    up = j.inp.upstream.get(w)
    # upstream 为 None 表示「多个上游」或「无上游」；WBS 的多上游（BS1/BS2）不适用于
    # 单车间镜像判定，返回 None。
    return up


def _upstream_at_target(j: Judge, ds: str, w: str) -> bool:
    """C15 镜像：车间 w 的直接上游节点（缓冲或车间）当日 EOD 已等于 tgt，
    即上游供不上 → 下游自然减产合法（2026-10-24 裁决，按原文：只判 EOD == tgt）。
    """
    up = _direct_upstream_node(j, w)
    if up is None:
        return False
    total = j.node_eod_total(ds, up)
    tgt = j.inp.node_target(up, parse_date(ds))
    return total == tgt


def _upstream_in_bs_clear(j: Judge, ds: str, w: str) -> bool:
    """C15 镜像扩展（rev 154）：车间 w 的直接上游节点当天处于 BS 清线期（正在清空），
    同样算上游供不上，下游不满产合法、不计 C14。
    """
    up = _direct_upstream_node(j, w)
    if up is None:
        return False
    return _in_bs_clear(j, ds, up)


def _ps_in_clear_down(j: Judge, ds: str) -> bool:
    """PS 当天是否处于停前降库期（T-17 / rev 185）。"""
    d = parse_date(ds)
    for pd_ in j.ps_clear_down_periods:
        if parse_date(pd_["start"]) <= d <= parse_date(pd_["end"]):
            return True
    return False


def check_c14(j: Judge):
    """C14：段内每个生产日按当日选定模式满产（按投入 IN 判）。

    生产段由真实换型 / 停线 / 补线切分（月界、普通周末不切分）；段内非末尾差日、
    非合法不满位置记硬错误。允许不满（不记 C14）：段末尾差日；该车间对应车型的
    「当月最后生产日」（按车型、按自然月判，见 `_is_model_month_last_prod`）；
    直接下游节点 EOD 到物理上限（C15）；上游节点 EOD 等于 tgt（C15 镜像）；
    直接上游节点处于 BS 清线期（C15 镜像扩展）；换型后新车型首日；
    清线期只对该焊装线和 WBS 免 C14（阶段重叠第 1 条：按节点、按日）；清线前一天该线可减量投入（CLR-07）。
    """
    for w in _in_production_workshops(j):
        prod_days = []
        for d in j.inp.dates:
            ds = d.isoformat()
            if not j.is_production_day(w, d):
                continue
            if _workshop_flow(j, ds, w, "in") > 0 or _workshop_flow(j, ds, w, "out") > 0:
                prod_days.append(ds)
        if not prod_days:
            continue
        # 按换型 / 停线 / 补线把生产日切成若干段（月界与周末不切分）
        segments = _split_segments(j, prod_days)
        for seg in segments:
            for idx, ds in enumerate(seg):
                if _has_phase(j.phases.get(ds), "INITIAL_DRAIN"):
                    continue  # 期初双线排空同清线。
                if _changeover_old_line(j, ds, w) or _changeover_first_day(j, ds, w):
                    continue
                if _in_bs_clear(j, ds, w):
                    continue  # 清线期：该焊装线 / WBS 免 C14（按节点、按日）
                if _is_bs_clear_prequel(j, ds, w):
                    continue  # 清线前一天该线可减量投入（CLR-07），不满产不记 C14
                if _level_drain_day(j, ds, w):
                    continue  # rev 205：提前降库期总装按能做尽做（check_level_drain），不按 C14
                mode = j._mode(ds, w) or "OFF"
                cap = j.inp.cap_for_mode(w, mode, parse_date(ds))
                inn = _workshop_flow(j, ds, w, "in")
                if inn >= cap:
                    continue  # 满产（按投入判）
                is_seg_last = (idx == len(seg) - 1)
                d = parse_date(ds)
                is_month_last = _is_model_month_last_prod(j, w, ds, prod_days)
                downstream_full = _downstream_full(j, ds, w)
                upstream_target = _upstream_at_target(j, ds, w)
                upstream_clear = _upstream_in_bs_clear(j, ds, w)
                # T-17 / rev 185：降库期 PS 不适用 C15 镜像「上游清线可少产」豁免。
                if w == "PS" and _ps_in_clear_down(j, ds):
                    upstream_clear = False
                if not (is_seg_last or is_month_last or downstream_full
                        or upstream_target or upstream_clear):
                    j._err("C14", ds, w, None, f"段内非段末不满产（投入 {inn} < 能力 {cap}）")


def _split_segments(j: Judge, prod_days: list[str]) -> list[list[str]]:
    """把生产日按换型 + 停线 + 补线边界切段。

    月界与普通周末不切分（prod_days 已只含工作日）。停前日（PS_PRE_STOP）是段末，
    其后首个生产日（补线日或正常日）开新段；补线和首次启动从开始日切段，
    补满后继续同一生产段，不能把补满日当作额外尾差日。
    """
    co_starts = {co["start"] for co in j.changeovers}
    segments: list[list[str]] = []
    cur: list[str] = []
    for ds in prod_days:
        ph = j.phases.get(ds, "NORMAL")
        if cur:
            prev_ph = j.phases.get(cur[-1], "NORMAL")
            if ((ds in co_starts)
                    or (_has_phase(ph, "REFILL") and not _has_phase(prev_ph, "REFILL"))
                    or (_has_phase(ph, "FIRST_START") and not _has_phase(prev_ph, "FIRST_START"))
                    or (_has_phase(ph, "INITIAL_DRAIN") != _has_phase(prev_ph, "INITIAL_DRAIN"))
                    or _has_phase(prev_ph, "PS_PRE_STOP")):
                segments.append(cur)
                cur = []
        cur.append(ds)
    if cur:
        segments.append(cur)
    return segments


def _changeover_old_line(j: Judge, ds: str, w: str) -> bool:
    return any(co["old_line"] == w and co["start"] <= ds <= co["end"]
               for co in j.changeovers)


def _changeover_first_day(j: Judge, ds: str, w: str) -> bool:
    """按车间的新车型首次有流日保留 C14 首日豁免。"""
    for co in j.changeovers:
        if not co["start"] <= ds <= co["end"]:
            continue
        for m, line in j.inp.line_of.items():
            if line != co["new_line"]:
                continue
            first = next((d.isoformat() for d in j.inp.dates
                          if co["start"] <= d.isoformat() <= co["end"]
                          and (j._wq(d.isoformat(), w, m, "in") > 0
                               or j._wq(d.isoformat(), w, m, "out") > 0)), None)
            if first == ds:
                return True
    return False


def check_c17(j: Judge):
    """C17：按车间全车型合计，无投入不得出车；清空例外按节点判断。"""
    for d in j.inp.dates:
        ds = d.isoformat()
        for w in j.inp.workshops:
            inn, out = _totals(j, ds, w)
            if inn != 0 or out == 0:
                continue
            if _in_bs_clear(j, ds, w) or _changeover_old_line(j, ds, w):
                continue
            if (j.initial_drain and j.initial_drain["line"] == w
                    and j.initial_drain["start"] <= ds <= j.initial_drain["end"]):
                continue
            if w == "PS" and ds in j.pre_stop_targets:
                continue
            # TODO(边界): 当前输入尚无车型退出标记；接入退出时按车型流经节点豁免。
            j._err("C17", ds, w, None,
                   f"{w} 投入合计 {inn}，产出合计 {out}，非清空例外日不得无投入出车")


def _is_model_month_last_prod(j: Judge, w: str, ds: str, prod_days: list[str]) -> bool:
    """「该车型当月最后生产日」（C14）按车型、按自然月判：车间 w 当天须是
    其任一相关车型在该自然月的最后一个生产日。

    车型按「焊装线绑车型」反查（line_of）：焊装线只绑一个车型；共享车间
    （PS / AS_MAIN / AS_FIN）同月走多个车型，以「该车间（任一车型）在此月
    最后有流的生产日」为准——本文段以此表达「该车型当月最后生产日」的放宽，
    不再按整个计划期判（2026-10-27 修正：03-31 是 A 在 3 月最后生产日，允许
    不满产，月界不切段）。
    """
    mo = j.inp.month_of(parse_date(ds))
    # 该月内车间 w 的所有生产日（按车型合计有流的工作日）
    month_days = [d for d in prod_days if j.inp.month_of(parse_date(d)) == mo]
    if not month_days:
        return False
    return ds == month_days[-1]


def _downstream_full(j: Judge, ds: str, w: str) -> bool:
    """C15：直接下游缓冲或车间 EOD 已到物理上限；FIN 不属于在制节点。

    rev 202：下游车间没填物理上限（上限随目标）时，日末到目标还须该车间自己受限才算：
    期初超量正在降回目标（日初或日末高于目标）；或当天自己已满产（含产能损失后的能力）；
    或当天产量由排产条件指定。只是跟着上游停在目标、自己也少产的，不算到上限。
    """
    node = j.inp.downstream[w]
    if node is None:
        return False
    if node not in j.inp.buffers and node not in j.inp.workshop_caps:
        d = parse_date(ds)
        tgt = j.inp.node_target(node, d)
        eod = j.node_eod_total(ds, node)
        if max(sum(j.bod.get(ds, {}).get(node, {}).values()), eod) > tgt:
            return True
        if eod < tgt:
            return False
        out = _workshop_flow(j, ds, node, "out")
        fixed = any(c["workshop"] == node for c in j.inp.conditions_on("FIXED_OUTPUT", d))
        return fixed or out >= j.inp.cap_for_mode(node, j._mode(ds, node) or "OFF", d) > 0
    cap_max = j.inp.node_cap(node, parse_date(ds))
    return j.node_eod_total(ds, node) >= cap_max


# ---------- CHANGEOVER（换型期约束，rule: "CHANGEOVER"） ----------

def _chain_refill_order(j: Judge, new_line: str) -> list[str]:
    """换型逐级补满顺序：新线 → WBS → PS → PBS → AS_MAIN → AS_FIN。"""
    order = [new_line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
    return [n for n in order if n is not None]


def _node_supplies_downstream(j: Judge, ds: str, node: str) -> bool:
    """节点当天是否向下游供车：车间看 OUT > 0；缓冲看下游车间当日 IN > 0。"""
    if node in WORKSHOPS:
        return j.workshop_total(ds, node, "out") > 0
    # 缓冲：下游车间 IN > 0
    dst = j.inp.downstream.get(node)
    if dst is not None and dst in WORKSHOPS:
        return j.workshop_total(ds, dst, "in") > 0
    return False


def check_initial_drain(j: Judge):
    drain = j.initial_drain
    if drain is None:
        return
    line = drain["line"]
    other = drain["other_line"]
    for d in j.inp.dates:
        ds = d.isoformat()
        if not (drain["start"] <= ds <= drain["end"]):
            continue
        for w in WELDING_LINES:
            inn = j.workshop_total(ds, w, "in")
            if inn > 0:
                j._err("INITIAL_DRAIN", ds, w, None,
                       f"期初排空期间 {w} 投入 {inn} 台，须为零")
        if j.workshop_total(ds, other, "out") > 0:
            j._err("INITIAL_DRAIN", ds, other, None,
                   f"期初排空占用班组，另一条线 {other} 不得出车")
        if (j.is_production_day(line, d) and sum(j.bod[ds][line].values()) > 0
                and j.workshop_total(ds, line, "out") == 0):
            j._err("INITIAL_DRAIN", ds, line, None, "期初排空未连续进行，排空线仍有在制但未出车")


def check_changeover(j: Judge):
    """换型期约束（rule: CHANGEOVER）。

    1. 期间：旧线 IN = 0（清线日后旧线不得再投入）。
    2. 逐级补满：换型期内，链上节点（新旧线外的 WBS/PS/PBS/AS_MAIN/AS_FIN，
       旧线清线不受此限）向下游供车时，该节点日末 EOD 必须 ≥ tgt；日末未达目标不得供车。
    """
    for co in j.changeovers:
        old_line = co["old_line"]
        new_line = co["new_line"]
        start = parse_date(co["start"])
        end = parse_date(co["end"])

        # 新线在换型期内首次 on 的日子（用于「旧线先清到 0」核对）
        new_first_on = None
        for d in j.inp.dates:
            if start <= d <= end and j.workshop_on(d.isoformat(), new_line):
                new_first_on = d
                break

        for d in j.inp.dates:
            if not (start <= d <= end):
                continue
            ds = d.isoformat()
            # 1) 期间旧线 IN = 0
            if j.workshop_total(ds, old_line, "in") > 0:
                j._err("CHANGEOVER", ds, old_line, None,
                       f"换型期旧线 {old_line} 仍有投入 {j.workshop_total(ds, old_line, 'in')} 台")
            # 2) 新线开工当天旧线须已清到 0
            if new_first_on is not None and d == new_first_on:
                old_eod = j.node_eod_total(ds, old_line)
                if old_eod > 0:
                    j._err("CHANGEOVER", ds, old_line, None,
                           f"新线 {new_line} 开工时旧线 {old_line} 未清到 0（EOD {old_eod}）")
            # 3) 逐级补满：节点供车时 EOD ≥ tgt（旧线清线除外）
            for node in _chain_refill_order(j, new_line):
                if node == old_line:
                    continue  # 旧线清线不受此限
                if _node_supplies_downstream(j, ds, node):
                    total = j.node_eod_total(ds, node)
                    tgt = j.inp.node_target(node, parse_date(ds))
                    if total < tgt:
                        j._err("CHANGEOVER", ds, node, None,
                               f"换型期 {node} 向下游供车但日末 EOD {total} < 目标 {tgt}")


# ---------- FIRST_START（首次启动，rule: "FIRST_START"） ----------

def check_first_start(j: Judge):
    """首次启动约束（rule: FIRST_START）。对每个首次启动车型：该车型焊装线首次正 OUT
    当天日末 EOD ≥ tgt（LIFE-02）；不达标记 FIRST_START。其余同补线（逐级补满由
    check_refill 覆盖；首次启动期 C8/C9/C14 已放宽）。"""
    for fs in j.first_starts:
        line = fs["line"]
        model = fs["model"]
        for d in j.inp.dates:
            ds = d.isoformat()
            if j._wq(ds, line, model, "out") > 0:
                total = j.node_eod_total(ds, line)
                tgt = j.inp.node_target(line, d)
                if total < tgt:
                    j._err("FIRST_START", ds, line, model,
                           f"首次启动 {model} 焊装线 {line} 首次出车当天日末 EOD {total} < 目标 {tgt}")
                break  # 只查首次正 OUT 当天


# ---------- PS 停前日（rule: PS_PRE_STOP） ----------

def _stop_bs_clear_events(j: Judge, sw: dict) -> list[dict]:
    """某停线窗口对应的 BS 清线事件（有 BS 清线的停线）；没有则空列表。"""
    return [e for e in j.bs_clear_events if e["zero_start"] == sw["start"]]


def check_pre_stop(j: Judge):
    """PS 停前日：窗口前最后一个 PS 生产日，PS 全车型合计日末 EOD 必须精确等于停前目标
    （人工目标优先，否则短停 ps_pre_stop_target_short / 长停 ps_pre_stop_target_long，
    停线窗口按 PS 实际流量识别）。不等于记 PS_PRE_STOP。目标缺失（对应规则常数未在输入
    登记）由 check_input 记 INPUT，此处跳过。

    T-18 / rev 187 停线前出清：有 BS 清线的停线，停前日日末全链高于目标的在制都要作为
    成品出掉——PBS、AS_MAIN、AS_FIN 必须回到目标（焊装、WBS = 0 由 BS 清线查，PS = 停前
    目标由本函数查）。高于目标记 PS_PRE_STOP。
    """
    for sw in j.stop_windows:
        pre = sw.get("pre_stop_date")
        target = sw.get("target")
        if pre is None or target is None:
            continue
        total = j.node_eod_total(pre, "PS")
        if total != target:
            j._err("PS_PRE_STOP", pre, "PS", None,
                   f"PS 停前日末 EOD {total} ≠ 停前目标 {target}")
        # T-18 停线前出清：仅对有 BS 清线的停线要求下游节点回到目标；
        # rev 204：人工目标在制盖住整次停线的节点，不论有无清线都要精确到停前水位。
        levels = sw.get("levels", {})
        cleared = bool(_stop_bs_clear_events(j, sw))
        for node in ("PBS", "AS_MAIN", "AS_FIN"):
            if node not in levels and not cleared:
                continue
            tgt = levels.get(node, j.inp.node_target(node, parse_date(pre)))
            total = j.node_eod_total(pre, node)
            if total != tgt:
                j._err("PS_PRE_STOP", pre, node, None,
                       f"停前日出清 {node} EOD {total} ≠ {'停前水位' if node in levels else '目标'} {tgt}")


# ---------- PS 停前降库（rule: PS_PRE_STOP，T-17 / rev 185） ----------

def check_ps_clear_down(j: Judge):
    """降库期 PS 投入/出车公式。降库期（首个 BS 清线日到 PS 停前日，含首尾）内，PS 须做
    能做尽：

    - 投入 = min(PS 当日产能, WBS 日初 + 当日焊装出车)
    - 出车 = min(PS 当日产能, PS 日初 + 投入 − 停前目标)

    不符记 PS_PRE_STOP（rev 185 裁决）。日末 ≥ 停前目标由出车公式蕴含；停前日日末精确
    等于停前目标由 check_pre_stop 查。「不满的那天自然落在最后」是公式的自然结果，不另查。
    """
    for pd_ in j.ps_clear_down_periods:
        start = parse_date(pd_["start"])
        end = parse_date(pd_["end"])
        target = pd_["target"]
        d = start
        while d <= end:
            ds = d.isoformat()
            cap = j.inp.cap_for_mode("PS", j._mode(ds, "PS") or "OFF", d)
            wbs_bod = sum(j.bod[ds].get("WBS", {}).values())
            weld_out = sum(j._wq(ds, l, m, "out")
                           for l in ("BS1", "BS2") for m in j._models())
            ps_bod = sum(j.bod[ds].get("PS", {}).values())
            inn = j.workshop_total(ds, "PS", "in")
            out = j.workshop_total(ds, "PS", "out")
            want_in = min(cap, wbs_bod + weld_out)
            want_out = min(cap, ps_bod + inn - target)
            if inn != want_in:
                j._err("PS_PRE_STOP", ds, "PS", None,
                       f"PS 停前降库期投入 {inn} ≠ min(产能 {cap}, WBS 日初 {wbs_bod} "
                       f"+ 焊装出车 {weld_out}) = {want_in}")
            if out != want_out:
                j._err("PS_PRE_STOP", ds, "PS", None,
                       f"PS 停前降库期出车 {out} ≠ min(产能 {cap}, PS 日初 {ps_bod} "
                       f"+ 投入 {inn} − 停前目标 {target}) = {want_out}")
            d += timedelta(days=1)


# ---------- 清线零头（rule: BS_CLEAR，T-18 / rev 187） ----------

def check_clear_remainder(j: Judge):
    """清线零头放在清线前一天（rev 187）+ 清线段 PS / 总装「能做尽做」（rev 197）。

    判据：
    - 清线段（首个 BS 清线日到 PS 停前日）焊装本线出尽出（rev 188）：出车 = min(产能,
      本线日初, WBS 物理上限允许量)；
    - 清线段 PS / 总装（AS_MAIN、AS_FIN）「能做尽做」（rev 197）：出车 = min(产能, 日初
      在制 + 投入 − 停前保留水位)——上游供不上时可少产（可出量 < 产能），有车却不满产
      （供得上却低于产能出车，且非停前保留水位所致）记 BS_CLEAR；不满产的那天必须落在
      清线段末尾，其后不得再满产；
    - 减量投入日（清线前一天）焊装本线出车满产。
    不符记 BS_CLEAR。满产以当日选定合法模式的产能为准（与 C14 口径一致）。
    """
    for ev in j.bs_clear_events:
        line = ev["line"]
        sw = next((s for s in j.stop_windows if s["start"] == ev["zero_start"]), None)
        if sw is None or sw.get("pre_stop_date") is None:
            continue
        clear_start = parse_date(ev["start"])
        pre = parse_date(sw["pre_stop_date"])
        # 1) 清线段焊装本线出尽出 + PS / 总装「能做尽做」（rev 197）。
        #    PS 停前保留水位 = 停前目标；AS_MAIN / AS_FIN = 停前日目标（停线前出清）。
        clear_ws = ("PS", "AS_MAIN", "AS_FIN")
        first_under: dict[str, str | None] = {w: None for w in clear_ws}  # 首个不满产日
        last_full: dict[str, str | None] = {w: None for w in clear_ws}    # 最后一个满产日
        d = clear_start
        while d <= pre:
            ds = d.isoformat()
            # rev 188：清线期本线能出尽出；WBS 按共享日末物理上限计算可接收量。
            cap = j.inp.cap_for_mode(line, j._mode(ds, line) or "OFF", d)
            bod = sum(j.bod[ds].get(line, {}).values())
            wbs_bod = sum(j.bod[ds].get("WBS", {}).values())
            other_out = sum(j.workshop_total(ds, other, "out")
                            for other in WELDING_LINES if other != line)
            room = (j.inp.buffers["WBS"] - wbs_bod
                    + j.workshop_total(ds, "PS", "in") - other_out)
            want_out = min(cap, bod, room)
            out = j.workshop_total(ds, line, "out")
            if out != want_out:
                j._err("BS_CLEAR", ds, line, ev["model"],
                       f"清线期 {line} 出车 {out} ≠ min(产能 {cap}, 本线日初 {bod}, "
                       f"WBS 物理上限允许量 {room}) = {want_out}")
            # rev 197「能做尽做」：出车 = min(产能, 日初 + 投入 − 停前保留水位)。
            # 有车却不满产（供得上却低于产能出车，且非停前保留水位所致）记 BS_CLEAR；
            # 上游供不上时（可出量 < 产能）可少产，但不满产的一天必须落在清线段末尾。
            for w in clear_ws:
                cap_w = j.inp.cap_for_mode(w, j._mode(ds, w) or "OFF", d)
                bod_w = sum(j.bod[ds].get(w, {}).values())
                inn_w = j.workshop_total(ds, w, "in")
                out_w = j.workshop_total(ds, w, "out")
                reserve_w = sw["target"] if w == "PS" else sw.get("levels", {}).get(w, j.inp.node_target(w, pre))
                want_w = min(cap_w, bod_w + inn_w - reserve_w)
                if out_w < want_w:
                    j._err("BS_CLEAR", ds, w, None,
                           f"清线段 {w} 出车 {out_w} < 能做尽做 {want_w}（产能 {cap_w}，"
                           f"日初 {bod_w} + 投入 {inn_w} − 停前保留 {reserve_w}）")
                if cap_w == 0:
                    pass  # 周末 / OFF 日不算满产也不算不满（清线段跨周末）
                elif out_w < cap_w:
                    if first_under[w] is None:
                        first_under[w] = ds
                else:
                    last_full[w] = ds
            d += timedelta(days=1)
        # 不满落最后（rev 197）：首个不满产日之后不得再有满产日。
        for w in clear_ws:
            fu = first_under[w]
            lf = last_full[w]
            if fu is not None and lf is not None and lf > fu:
                j._err("BS_CLEAR", lf, w, None,
                       f"清线段 {w} 不满产日 {fu} 之后仍有满产日 {lf}（不满应落在清线段末尾）")
        # 2) 减量投入日（清线前一天）焊装本线出车满产
        prequel = _prequel_day(j, line, clear_start)
        if prequel is None:
            continue
        ds_pre = prequel.isoformat()
        if j.workshop_total(ds_pre, line, "in") <= 0:
            continue
        cap = j.inp.cap_for_mode(line, j._mode(ds_pre, line) or "OFF", prequel)
        out = j.workshop_total(ds_pre, line, "out")
        if out < cap:
            j._err("BS_CLEAR", ds_pre, line, None,
                   f"减量投入日 {line} 出车 {out} < 满产 {cap}")


# ---------- 补线（rule: REFILL） ----------

def _refill_chain(j: Judge) -> list[str]:
    """补线逐级补满顺序：焊装线（本阶段单车型按绑定线）→ WBS → PS → PBS → AS_MAIN → AS_FIN。

    与换型逐级补满（新线在前）共用同一拓扑，但焊装起点取车型绑定线。
    """
    lines = [j.inp.line_of[m] for m in j._models()]
    first = lines[0] if lines else None
    order = [first, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
    return [n for n in order if n is not None]


def check_refill(j: Judge):
    """补线期约束（rule: REFILL）：只在清过线的长停之后触发（rev 153）。期间按
    BS→WBS→PS→PBS→AS 逐级补满：节点当天向下游供车时，日末 EOD 必须 ≥ tgt，否则记
    REFILL（不查 C8/C9、少出不计 C14，见相应 check 的阶段放宽）。

    短停（≥3 天 PS 零流但未清线）不触发补线，复工首日即为 NORMAL；补线周期由
    compute_phases 的 _detect_bs_clear 在清线事件后写入 refill_periods。
    """
    for rp in j.refill_periods:
        s = parse_date(rp["start"])
        e = parse_date(rp["end"])
        for d in j.inp.dates:
            if not (s <= d <= e):
                continue
            ds = d.isoformat()
            for node in _refill_chain(j):
                if not _node_supplies_downstream(j, ds, node):
                    continue
                total = j.node_eod_total(ds, node)
                tgt = j.inp.node_target(node, parse_date(ds))
                if total < tgt:
                    j._err("REFILL", ds, node, None,
                           f"补线期 {node} 向下游供车但日末 EOD {total} < 目标 {tgt}")


def _prequel_day(j: Judge, line: str, start: date) -> date | None:
    """清线前一天 = 清线开始日之前该线最后一个可生产日（隔着周末 / 假期时往前找，最多 14 天）。"""
    d = start - timedelta(days=1)
    while d >= j.inp.start and (start - d).days <= 14:
        if j.inp.is_available(line, d) and (j.inp.is_working(d) or j.workshop_on(d.isoformat(), line)):
            return d
        d -= timedelta(days=1)
    return None


def _is_bs_clear_prequel(j: Judge, ds: str, w: str) -> bool:
    """C14 / CLR-07：车间 w 当天是否是某 BS 长停清线期的「清线前一天」（清线开始前该线
    最后一个可生产日，隔着周末时为周五——见 _prequel_day），且该线当天有投入。该日是正常日，投入不满产不记 C14（只有清线前一天可减量
    投入）。换型旧线清线不算长停清线（`bs_clear_events` 已排除换型清线），不受此豁免。
    """
    d = parse_date(ds)
    for ev in j.bs_clear_events:
        if ev["line"] != w:
            continue
        if _prequel_day(j, w, parse_date(ev["start"])) == d:
            return j.workshop_total(ds, w, "in") > 0
    return False


def _is_clear_tail(j: Judge, ev: dict, ds: str) -> bool:
    """rev 203：清空日之后、停线之前，仍在 PS 停前降库期且 PS 当天不投入（只消化自身在制，
    出车公式由 check_ps_clear_down 核对）的日子属于清线期，不算清得太早。"""
    if not (ev["end"] < ds < ev["zero_start"]):
        return False
    if j.workshop_total(ds, "PS", "in") != 0:
        return False
    if not any(pd_["start"] <= ds <= pd_["end"] for pd_ in j.ps_clear_down_periods):
        return False
    # 只有清线前一天减量投入也消化不掉的尾巴才算（2026-10-26「零头放在清线前一天」仍有效）：
    # 尾日 PS 出车合计 > 清线前一天还能少投的量（投入 − 保住当天出车所需的最少投入）。
    line = ev["line"]
    pre_d = _prequel_day(j, line, parse_date(ev["start"]))
    if pre_d is None:
        return False
    pre = pre_d.isoformat()
    pre_in = j.workshop_total(pre, line, "in")
    pre_out = j.workshop_total(pre, line, "out")
    reducible = pre_in - max(0, pre_out - sum(j.bod[pre].get(line, {}).values()))
    tail = sum(j.workshop_total(t.isoformat(), "PS", "out") for t in j.inp.dates
               if ev["end"] < t.isoformat() < ev["zero_start"])
    return tail > reducible


def _in_bs_clear(j: Judge, ds: str, node: str) -> bool:
    """节点 node（焊装线或 WBS）当天是否处于 BS 清线期。

    清线期按节点、按日豁免：哪个阶段把哪个节点排除在正常生产之外，只免该节点该日。
    焊装线看其自身清线事件；WBS 看任一清线事件（本阶段单车型，WBS 清线即该车型 WBS）。
    """
    d = parse_date(ds)
    for ev in j.bs_clear_events:
        s = parse_date(ev["start"])
        e = parse_date(ev["end"])
        if not (s <= d <= e or _is_clear_tail(j, ev, ds)):
            continue
        if node == ev["line"]:
            return True
        if node == "WBS" and ev["model"] is not None:
            return True
    return False


def check_bs_clear(j: Judge):
    """BS 清线期约束（rule: BS_CLEAR）。对每个清线事件：

    1. 清线期内该线 IN=0（清线期仍投入 → BS_CLEAR）。
    2. 清空当天（清线期结束日）该线 EOD=0 且该车型 WBS EOD=0（没清到 0 → BS_CLEAR，
       由 compute_phases 只在两者均 0 时才记录事件，故此处主要核对清线期内逐日 WBS
       是否提前回升；保守起见核对结束日当天两者确实为 0）。
    3. 清空日之后到零流窗口结束，该线不得再生产（清空后重启 → BS_CLEAR），也不得有
       空档工作日（留空档 → BS_CLEAR）。rev 200：零流窗口由日历假期与自建空闲合并而成时，
       窗口内全厂都停的工作日算停线、不算清空后空档；只有清空后 PS 仍在生产（IN 或 OUT > 0）、
       本线却空着的工作日才算空档。rev 203：PS 停前降库期内 PS 当天不投入、只消化自身
       在制的工作日属于清线期，不算空档。

    清线前一天「可减量投入」（CLR-07）：清线日前一天该线减量投入（不满产）不记 C14，
    由 check_c14 的 `_is_bs_clear_prequel` 豁免；该日仍是正常日，C8/C9/C13 照常查。

    长停未清线（bs_clear_violations，评审退回）：零流窗口 ≥ Lg 但无清线日，窗口前
    最后一天该线 EOD 或该车型 WBS EOD 不为 0 → BS_CLEAR（写明日期/线/车型/剩余台数）。
    """
    for v in j.bs_clear_violations:
        line = v["line"]
        model = v["model"]
        ds = v["date"]
        line_eod = j.node_eod_total(ds, line)
        wbs_eod = j.eod[ds].get("WBS", {}).get(model, 0)
        forced_k = v.get("forced_k")
        if forced_k is not None:
            reason = (f"窗口长 {v['length']} 天、k={forced_k}，W+k={v['length'] + forced_k} > 胶龄"
                      "（rev 196 胶龄逼清，按长停）")
        else:
            reason = f"共 {v['length']} 天 ≥ 胶龄（长停）"
        j._err("BS_CLEAR", ds, line, model,
               f"{line} 零流窗口 {v['zero_start']}..{v['zero_end']}，{reason}，"
               f"但窗口前最后一天 {ds} 日末 {line} EOD {line_eod}、WBS {model} EOD {wbs_eod}，未清到 0 即进入停线")

    for ev in j.bs_clear_events:
        line = ev["line"]
        model = ev["model"]
        s = parse_date(ev["start"])
        e = parse_date(ev["end"])
        zs = parse_date(ev["zero_start"])
        ze = parse_date(ev["zero_end"])

        # 1) 清线期内该线 IN=0
        for d in j.inp.dates:
            if not (s <= d <= e):
                continue
            ds = d.isoformat()
            inn = j.workshop_total(ds, line, "in")
            if inn > 0:
                j._err("BS_CLEAR", ds, line, None,
                       f"清线期 {line} 仍投入 {inn} 台（须 IN=0）")

        # 2) 清空当天该线 EOD=0 且该车型 WBS EOD=0
        ds_e = e.isoformat()
        line_eod = j.node_eod_total(ds_e, line)
        wbs_eod = j.eod[ds_e].get("WBS", {}).get(model, 0)
        if line_eod != 0 or wbs_eod != 0:
            j._err("BS_CLEAR", ds_e, line, None,
                   f"清空当天 {line} EOD {line_eod}、WBS EOD {wbs_eod}，未清到 0")

        # 3) 清空日之后到零流窗口结束：不得再生产、不得有空档工作日
        d = e + timedelta(days=1)
        while d <= ze:
            ds = d.isoformat()
            inn = j.workshop_total(ds, line, "in")
            out = j.workshop_total(ds, line, "out")
            if inn > 0 or out > 0:
                j._err("BS_CLEAR", ds, line, None,
                       f"清空后 {line} 在 {ds} 又有生产（IN={inn} OUT={out}），清空后不得重启")
            # rev 200：清空后本线空着，只有当天 PS 仍在生产（IN 或 OUT > 0）才算空档；
            # 全厂都停的工作日（PS 也无流）属于停线，不算清空后空档。
            # rev 203：PS 停前降库期内 PS 不投入、只消化自身在制的尾日属于清线期（_is_clear_tail）。
            if j.is_production_day(line, d) and not _is_clear_tail(j, ev, ds)                     and (j.workshop_total(ds, "PS", "in") > 0 or j.workshop_total(ds, "PS", "out") > 0):
                j._err("BS_CLEAR", ds, line, None,
                       f"清空后 {line} 在 {ds} 空档（工作日未紧贴停线）")
            d += timedelta(days=1)


def check_fixed_output(j: Judge):
    for c in j.inp.valid_conditions:
        if c["type"] != "FIXED_OUTPUT":
            continue
        ds = c["date"]
        w = c["workshop"]
        actual = j.workshop_total(ds, w, "out")
        if actual != c["out"]:
            j._err("FIXED", ds, w, None,
                   f"条件 {c['id']}: {w} OUT 合计 {actual} ≠ 指定产量 {c['out']}")
