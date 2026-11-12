"""判定核心：从 input 与计划的逐日 IN/OUT 独立重算库存、阶段，并对账、查硬约束。

设计原则（T-01 B 部分 / AGENTS.md）：
- 不采信计划自报的 bod/eod/fok/fin/phase/objective；全部重算后对账，不一致记硬错误。
- 阶段从输入与逐日流量推导（B21）。
- 目标 L1–L5 按 IO_CONTRACT §5 重算。
"""
from __future__ import annotations

from datetime import date, timedelta
from math import ceil

from .model import InputModel, parse_date

# 七节点 = 五个车间 + 两个缓冲；按 IO_CONTRACT flow 的拓扑取输入。
# 判定器从输入读节点集合，不在代码里写死数字，但节点名是规格(§1)固定的。
NODES = ("BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN")
WORKSHOPS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")

# L6 节点权重（CORE_MODEL §6 目标表第 5 行 / IO_CONTRACT §5 L6 行，rev 185）：
# 超目标在制尽量靠下游，权重越大越靠近上游。AS_FIN 1、AS_MAIN 2、PBS 3、PS 4、
# WBS 5、BS1/BS2 6。是度量口径的系数，规格唯一来源，不在 input.json 中登记。
NODE_L6_WEIGHT = {"AS_FIN": 1, "AS_MAIN": 2, "PBS": 3, "PS": 4,
                  "WBS": 5, "BS1": 6, "BS2": 6}


class HardError:
    __slots__ = ("rule", "date", "node", "model", "detail")

    def __init__(self, rule: str, date: str, node: str | None, model: str | None, detail: str):
        self.rule = rule
        self.date = date
        self.node = node
        self.model = model
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "date": self.date,
            "node": self.node,
            "model": self.model,
            "detail": self.detail,
        }


class Judge:
    def __init__(self, inp: InputModel, plan: dict):
        self.inp = inp
        self.plan = plan
        self.hard_errors: list[HardError] = []
        self.reports: list[dict] = []
        # 重算得到的逐日数据，键为 ISO 日期字符串
        self._days = {d["date"]: d for d in plan.get("days", [])}
        # 重算的库存 eod：{date_str: {node: {model: qty}}}
        self.eod: dict[str, dict[str, dict[str, int]]] = {}
        self.bod: dict[str, dict[str, dict[str, int]]] = {}
        self.fok: dict[str, dict[str, int]] = {}
        self.fin: dict[str, dict[str, int]] = {}
        self.bl: dict[str, dict[str, int]] = {}
        self._g: dict[str, dict[str, int]] = {}
        self.phases: dict[str, str] = {}
        self.objective: dict[str, float] = {}
        # 换型信息（compute_phases 从逐日流量重算后填入）。T-06 起支持多次换型，
        # 故为列表；每项 {old_line, new_line, start, end}（ISO 字符串）。无换型则 []。
        self.changeovers: list[dict] = []
        # 兼容旧字段：最后一次换型（供少量仍用单换型语义的查询）
        self.changeover: dict | None = None
        # S1c：PS 停线窗口（≥ ps_stop_min_days 的全厂零流窗口）与各停前日目标。
        # 每项 {start, end, length, pre_stop_date, target, source}；end 与 length
        # 可能延伸到计划期之后（尾停推算，rev 159）。
        self.stop_windows: list[dict] = []
        self.pre_stop_targets: dict[str, int] = {}
        # S1c 长停：BS 清线事件（每项 {line, model, start, end, zero_start, zero_end}，
        # start/end 为清线期首末自然日 ISO；zero_start/zero_end 为该线停线窗口首末）。
        self.bs_clear_events: list[dict] = []
        # S1c 长停未清线（评审退回）：零流窗口 ≥ Lg 但无清线日、窗口前最后一天该线或
        # 该车型 WBS EOD 不为 0。每项 {line, model, date, zero_start, zero_end, length}。
        self.bs_clear_violations: list[dict] = []
        # S1c 长停：补线周期（每项 {start, end}，清线后的停线复工、或期初补线触发）。
        self.refill_periods: list[dict] = []
        # S1d：首次启动事件（每项 {model, line, start, end}）；START/END 为 ISO 日期。
        self.first_starts: list[dict] = []
        # T-12：期初排空独立于换型，C16 不按换型检查。
        self.initial_drain: dict | None = None
        # T-17：PS 停前降库期（有 BS 清线的停线）。每项 {start, end, target}，ISO 日期
        # （含首尾），从首个 BS 清线日到 PS 停前日。期间 PS 不查 C8（放宽），投入/出车
        # 必须符合「能做尽做」公式，由 constraints.check_ps_clear_down 查。
        self.ps_clear_down_periods: list[dict] = []

    # ---------- 通用取值 ----------

    def _models(self) -> list[str]:
        return list(self.inp.models.keys())

    def _day(self, ds: str) -> dict:
        d = self._days.get(ds)
        if d is None:
            # 计划缺某天：记为硬错误，其余检查跳过
            return {}
        return d

    def _wq(self, ds: str, w: str, model: str, key: str) -> int:
        """车间 w 车型 model 当日 in/out 数量，缺失记 0。"""
        day = self._days.get(ds, {})
        ws = day.get("workshops", {}).get(w, {})
        return int(ws.get(key, {}).get(model, 0))

    def _mode(self, ds: str, w: str) -> str | None:
        day = self._days.get(ds, {})
        ws = day.get("workshops", {}).get(w, {})
        return ws.get("mode")

    def node_eod_total(self, ds: str, node: str) -> int:
        """节点（含车间与缓冲）当日 EOD 的全车型合计。"""
        return sum(self.eod[ds].get(node, {}).values())

    def workshop_total(self, ds: str, w: str, key: str) -> int:
        """车间 w 当日全车型 in/out 合计。"""
        return sum(self._wq(ds, w, m, key) for m in self._models())

    def workshop_on(self, ds: str, w: str) -> bool:
        """C4：on(w,d)=1 当且仅当当日有正 IN 或正 OUT。"""
        return self.workshop_total(ds, w, "in") > 0 or self.workshop_total(ds, w, "out") > 0

    def is_production_day(self, w: str, d: date) -> bool:
        """rev 190：未用的周六授权按车间视同休息日；C3 仍检查原始授权。"""
        return self.inp.is_available(w, d) and (
            self.inp.is_working(d) or self.workshop_on(d.isoformat(), w))

    # ---------- C1 守恒重算 ----------

    def recompute_inventory(self):
        """逐日重算七个节点的 BOD/EOD，fok、fin 也从重算值推出。"""
        models = self._models()
        dates = self.inp.dates
        prev: dict[str, dict[str, int]] = {}

        # 上个自然日的 EOD；第一天之前用 inv0（C1：inv(s-1) = inv0）
        def node_eod_before(ds: str, node: str, model: str) -> int:
            # 找该日期之前最近一个已重算的 EOD
            d = parse_date(ds)
            if d <= self.inp.start:
                return self.inp.inv0.get(node, {}).get(model, 0)
            prev_ds = (d - timedelta(days=1)).isoformat()
            return self.eod.get(prev_ds, {}).get(node, {}).get(model, 0)

        # 上游 OUT → 下游 IN（缓冲）映射，来自 flow
        # WBS.in = BS1.out + BS2.out；PS.in = WBS.out；PBS.in = PS.out；AS_MAIN.in = PBS.out；AS_FIN.in = AS_MAIN.out
        # 这里按 flow 的 "X>Y" 边推导：Y 是缓冲时，Y.in 累积所有上游 X.out；Y 是车间时，Y.in = X.out
        downstream_in: dict[str, list[str]] = {}  # node -> list of upstream edges source
        for e in self.inp.flow:
            src, dst = e.split(">")
            if dst == "FIN":
                continue
            downstream_in.setdefault(dst, []).append(src)

        for i, d in enumerate(dates):
            ds = d.isoformat()
            day = self._days.get(ds)
            eod_day: dict[str, dict[str, int]] = {}
            bod_day: dict[str, dict[str, int]] = {}

            for node in NODES:
                eod_day[node] = {}
                bod_day[node] = {}
                for m in models:
                    bod = node_eod_before(ds, node, m)
                    bod_day[node][m] = bod

                    # 当日 IN / OUT
                    if node in WORKSHOPS:
                        inn = self._wq(ds, node, m, "in")
                        out = self._wq(ds, node, m, "out")
                    else:
                        # 缓冲区：IN = 上游车间 OUT 合计；OUT = 下游车间 IN
                        sources = downstream_in.get(node, [])
                        inn = sum(self._wq(ds, s, m, "out") for s in sources)
                        # OUT = 缓冲下游车间的 IN
                        out = 0
                        for e in self.inp.flow:
                            s2, d2 = e.split(">")
                            if s2 == node and d2 != "FIN":
                                out += self._wq(ds, d2, m, "in")
                    eod_day[node][m] = bod + inn - out

            self.bod[ds] = bod_day
            self.eod[ds] = eod_day

            # fok = AS_FIN.out；fin / bl 按 C11（2026-10-24）递推
            fok_day = {m: self._wq(ds, "AS_FIN", m, "out") for m in models}
            self.fok[ds] = fok_day
            ws_m = {m: self.inp.ws_daily.get(m, {}).get(ds, 0) for m in models}
            # g = fin − bl 是守恒量：g(d) = g(d−1) + fok(d) − WS(d)，g(期初) = fin0
            if ds == self.inp.start.isoformat():
                g_before = {m: self.inp.fin0.get(m, 0) for m in models}
            else:
                g_before = self._g.get((d - timedelta(days=1)).isoformat(), {})
                g_before = {m: g_before.get(m, 0) for m in models}
            g_day = {m: g_before[m] + fok_day[m] - ws_m[m] for m in models}
            self._g[ds] = g_day
            # fin ≥ 0、bl ≥ 0、两者不同时为正（有车先补交）
            self.fin[ds] = {m: max(0, g_day[m]) for m in models}
            self.bl[ds] = {m: max(0, -g_day[m]) for m in models}

    # ---------- 对账（计划自报 vs 重算） ----------

    def reconcile(self):
        models = self._models()
        for d in self.inp.dates:
            ds = d.isoformat()
            day = self._days.get(ds, {})
            if not day:
                self._err("C1", ds, None, None, f"计划缺少 {ds} 当日记录")
                continue
            # bod / eod 对账
            for key, recomputed in (("bod", self.bod[ds]), ("eod", self.eod[ds])):
                claimed = day.get(key, {})
                for node in NODES:
                    for m in models:
                        got = recomputed.get(node, {}).get(m, 0)
                        want = claimed.get(node, {}).get(m, 0)
                        if got != want:
                            self._err(
                                "C1", ds, node, m,
                                f"{key.upper()} 计划自报 {want} ≠ 重算 {got}",
                            )
            # fok 对账
            claimed_fok = day.get("fok", {})
            for m in models:
                if self.fok[ds].get(m, 0) != claimed_fok.get(m, 0):
                    self._err("C1", ds, "AS_FIN", m,
                              f"FOK 计划自报 {claimed_fok.get(m,0)} ≠ 重算 {self.fok[ds].get(m,0)}")
            # fin 对账
            claimed_fin = day.get("fin", {})
            for m in models:
                if self.fin[ds].get(m, 0) != claimed_fin.get(m, 0):
                    self._err("C11", ds, "FIN", m,
                              f"成品 计划自报 {claimed_fin.get(m,0)} ≠ 重算 {self.fin[ds].get(m,0)}")
            # bl 对账：计划自报的累计欠交须与 C11 递推重算一致
            claimed_bl = day.get("bl", {})
            for m in models:
                if self.bl[ds].get(m, 0) != claimed_bl.get(m, 0):
                    self._err("C11", ds, "FIN", m,
                              f"欠交 计划自报 {claimed_bl.get(m,0)} ≠ 重算 {self.bl[ds].get(m,0)}")

    def _err(self, rule, ds, node, model, detail):
        self.hard_errors.append(HardError(rule, ds, node, model, detail))

    # ---------- 阶段重算（1a：NORMAL；1b 换型；1c 停线/清线/补线；1d 期初补线/首尾停线/首次启动/多次换型） ----------

    def compute_phases(self):
        """从输入与逐日流量独立重算阶段（B21）。T-06 起支持多次换型、期初补线、
        计划期首尾停线（含尾停长度推算）、首次启动。

        检测顺序：
          1. 换型（多次）：共享班组在两线间来回转移，每次识别旧线清线日 → 结束日。
          2. 全厂停线窗口：连续全厂零流自然日；触计划期尾则推算长度到复工前一日。
          3. BS 长停清线：停线跨度 ≥ Lg 的线清线（换型旧线/闲置线不算，rev 161）。
          4. 补线：清过线的停线复工、或期初低于目标（期初补线）。
          5. 首次启动：期初无在制、无历史车型的第一次投入 → 全链补满。
        """
        for d in self.inp.dates:
            self.phases[d.isoformat()] = "NORMAL"

        self._detect_initial_drain()
        self._detect_changeovers()
        self._detect_stops()
        self._detect_bs_clear()
        self._detect_ps_clear_down()
        self._detect_level_drain()
        self._detect_initial_refill()
        self._detect_first_starts()
        matched = {sw["pre_stop_date"] for sw in self.stop_windows}
        for c in self.inp.valid_conditions:
            if c["type"] == "PRE_STOP_TARGET" and c["pre_stop_date"] not in matched:
                self.reports.append({"rule": "PS_PRE_STOP", "date": c["pre_stop_date"],
                                     "node": "PS", "model": None,
                                     "detail": f"未匹配的人工停前目标：条件 {c['id']}，target={c['target']}"})

    # ---------- 1. 多次换型检测 ----------

    def _welding_lines(self) -> list[str]:
        """有车型绑定的焊装线，按 input 顺序去重。"""
        seen: list[str] = []
        for m in self._models():
            l = self.inp.line_of[m]
            if l not in seen:
                seen.append(l)
        return seen

    def _detect_initial_drain(self) -> None:
        lines = ("BS1", "BS2")
        if not all(sum(self.inp.inv0.get(l, {}).values()) > 0 for l in lines):
            return
        first = next((d for d in self.inp.dates
                      if any(self.is_production_day(l, d) for l in lines)), None)
        if first is None:
            return
        # 净出车识别排空，仍投入的违规计划也须识别后报 INITIAL_DRAIN。
        candidate = next(((d, l) for d in self.inp.dates for l in lines
                          if self.workshop_total(d.isoformat(), l, "out")
                          > self.workshop_total(d.isoformat(), l, "in")), None)
        if candidate is None:
            self._err("INITIAL_DRAIN", first.isoformat(), None, None,
                      "期初双线有在制，但未开始排空")
            return
        start, line = candidate
        other = next(l for l in lines if l != line)
        chain = [n for n in NODES if n != line]
        end = next((d for d in self.inp.dates if d >= start
                    and self.node_eod_total(d.isoformat(), line) == 0
                    and all(self.node_eod_total(d.isoformat(), n) >= self.inp.node_target(n, d)
                            for n in chain)), None)
        self.initial_drain = {"line": line, "other_line": other,
                              "start": start.isoformat(),
                              "end": (end or self.inp.end).isoformat()}
        if start != first:
            self._err("INITIAL_DRAIN", start.isoformat(), line, None,
                      f"期初排空从 {start} 开始，须从首个可生产日 {first} 开始")
        if end is None:
            self._err("INITIAL_DRAIN", self.inp.end.isoformat(), line, None,
                      "期初排空至期末仍未满足排空线为零、其余节点达到目标的结束条件")
        for d in self.inp.dates:
            if start <= d <= (end or self.inp.end):
                self._merge_phase(d.isoformat(), "INITIAL_DRAIN")

    def _detect_changeovers(self) -> None:
        """识别共享班组在两线之间来回转移的每次换型。

        换型 = 活跃线（当前占用班组的线）切换到另一条线。每对 (old, new)：
          start = 旧线清线日（旧线在换型前最近一次 IN=0、OUT>0 的日子）；
          end   = 旧线 EOD=0、新线 EOD≥tgt、全链共享节点 EOD≥tgt 的当天（含）。
        """
        lines = self._welding_lines()
        if len(lines) < 2:
            return

        # 换型序列：扫描每日，记录活跃线切换（on 判定见 workshop_on）。
        switches: list[tuple[str, str, date]] = []  # (old, new, new 线首次 on 的日期)
        active: str | None = None
        for d in self.inp.dates:
            ds = d.isoformat()
            if self.initial_drain and self.initial_drain["start"] <= ds <= self.initial_drain["end"]:
                active = self.initial_drain["other_line"]
                continue
            on = [l for l in lines if self.workshop_on(ds, l)]
            if not on:
                continue
            line = on[0]  # C4 同日两线同流由 check_c4 报错，这里取一条
            if active is None:
                active = line
            elif line != active:
                switches.append((active, line, d))
                active = line

        for old, new, _new_first_day in switches:
            # 清线日 = 旧线在最后一次「仍投入」（IN>0）之后，首个 IN=0、OUT>0 的日子。
            # 从旧线最后一次 IN>0 的日子之后向后找首个 OUT>0（旧线清线可能跨周末，
            # 但首个清线日即 IN=0 且 OUT>0 的那天）。
            clear_day: date | None = None
            # 旧线最后一次 IN>0 的日子（早于新线首次 on）
            last_in = None
            for d in self.inp.dates:
                if d >= _new_first_day:
                    break
                if self.workshop_total(d.isoformat(), old, "in") > 0:
                    last_in = d
            # 从 last_in 之后找首个 OUT>0 的日子
            start_from = last_in + timedelta(days=1) if last_in else self.inp.start
            for d in self.inp.dates:
                if d < start_from or d >= _new_first_day:
                    continue
                if self.workshop_total(d.isoformat(), old, "out") > 0:
                    clear_day = d
                    break
            if clear_day is None:
                # 无清线日（旧线一直在投入，违规）：退化到旧线最后一次 OUT>0 的日子。
                for d in reversed(self.inp.dates):
                    if d >= _new_first_day:
                        continue
                    ds = d.isoformat()
                    if self.workshop_total(ds, old, "out") > 0:
                        clear_day = d
                        break
            if clear_day is None:
                continue

            shared = [n for n in NODES if n not in ("BS1", "BS2")]
            end: date | None = None
            for d in self.inp.dates:
                if d < clear_day:
                    continue
                ds = d.isoformat()
                new_full = self.node_eod_total(ds, new) >= self.inp.node_target(new, parse_date(ds)) if new else False
                shared_ok = all(self.node_eod_total(ds, n) >= self.inp.node_target(n, parse_date(ds)) for n in shared)
                if new_full and shared_ok:
                    end = d
                    break
            if end is None:
                end = self.inp.dates[-1]

            co = {
                "old_line": old, "new_line": new,
                "start": clear_day.isoformat(), "end": end.isoformat(),
            }
            self.changeovers.append(co)
            for d in self.inp.dates:
                if clear_day <= d <= end:
                    self._merge_phase(d.isoformat(), "CHANGEOVER")

        # 兼容旧字段：最后一次换型。
        self.changeover = self.changeovers[-1] if self.changeovers else None

    def _changeover_on(self, ds: str) -> dict | None:
        """当天命中的换型（若有）；同一时刻至多一次。"""
        d = parse_date(ds)
        for co in self.changeovers:
            if parse_date(co["start"]) <= d <= parse_date(co["end"]):
                return co
        return None

    # ---------- 2. 全厂停线窗口检测（含首尾推算） ----------

    def _extrapolate_stop_end(self, s: date) -> date:
        """推算触及计划期尾的停线窗口最后一天（含，可能在计划期之后）。

        复工日 = horizon.end 之后首个工作日：输入 calendar 带了下一年日历时以日历为准
        （顺延到首个 is_working_capable=true 的日子；日历给完仍未遇到，按默认规则继续），
        否则默认 1 月 1 日放假、遇周六周日顺延（rev 159）。
        """
        d = self.inp.end + timedelta(days=1)
        while True:
            if d in self.inp.working:
                if self.inp.working[d]:
                    return d - timedelta(days=1)
                d += timedelta(days=1)
                continue
            # 日历未覆盖：默认规则
            if (d.month == 1 and d.day == 1) or d.weekday() >= 5:
                d += timedelta(days=1)
                continue
            return d - timedelta(days=1)

    def _zero_flow_windows(self, w: str) -> list[tuple[date, date, date]]:
        """车间 w 的零流窗口（当日全车型 IN=OUT=0 的连续自然日段，horizon 内）。
        相邻零流自然日自动合并。返回 [(s, e_horizon, stop_end)]，其中 stop_end 为
        触及计划期尾时按 rev 159 推算的窗口最后一天（可能超过 horizon.end）。"""
        windows: list[tuple[date, date]] = []
        cur_start: date | None = None
        for d in self.inp.dates:
            if (self.workshop_total(d.isoformat(), w, "in") == 0
                    and self.workshop_total(d.isoformat(), w, "out") == 0):
                if cur_start is None:
                    cur_start = d
            else:
                if cur_start is not None:
                    windows.append((cur_start, d - timedelta(days=1)))
                    cur_start = None
        if cur_start is not None:
            windows.append((cur_start, self.inp.dates[-1]))

        out: list[tuple[date, date, date]] = []
        for s, e in windows:
            stop_end = self._extrapolate_stop_end(s) if e >= self.inp.end else e
            out.append((s, e, stop_end))
        return out

    def _detect_stops(self) -> None:
        """识别 ≥ ps_stop_min_days 的 PS 停线窗口，标记 STOP / PS_PRE_STOP，并填
        stop_windows（长度可延伸到计划期之后）。

        停线窗口按 PS 实际流量识别（rev 161）：PS 当日 IN=OUT=0 的连续自然日（日历假期、
        周末、计划自建空闲都算，相邻的合并计长度）≥ ps_stop_min_days 即为停线窗口。
        换型、补线、首次启动期间 PS 因上游缺车而空的日子不计入停线：零流窗口内从任一
        焊装线复工（当日 IN 或 OUT > 0）那天起不再算停线，窗口截断到复工前一日（rev 163，
        2026-10-24 裁决）；截断后长度仍 ≥ ps_stop_min_days 才是停线窗口。之后 PS 等上游
        来车的空闲属于补线、换型或首次启动。
        尾停（窗口延续到计划期末，且期末无焊装复工）按 rev 159 推算长度至复工前一日。
        """
        ps_stop_min = self.inp.rules.get("ps_stop_min_days")
        if ps_stop_min is None:
            return  # 缺字段由 INPUT 硬错误另行报告

        ps_long_stop = self.inp.rules.get("ps_long_stop_days")
        tgt_long = self.inp.rules.get("ps_pre_stop_target_long")
        tgt_short = self.inp.rules.get("ps_pre_stop_target_short")

        for s, e, stop_end in self._zero_flow_windows("PS"):
            # rev 163：零流窗口内首个任一焊装线复工日 r，把窗口截断到 r-1（复工日不算停线）。
            # 停线后 PS 仍零流、但焊装已复工的日子属于补线/换型/首次启动，不计入停线窗口。
            r = None
            cur = s
            while cur <= e:
                if any(self.workshop_on(cur.isoformat(), l) for l in self._welding_lines()):
                    r = cur
                    break
                cur += timedelta(days=1)
            if r is not None:
                stop_end = min(stop_end, r - timedelta(days=1))
                e = min(e, r - timedelta(days=1))

            length = (stop_end - s).days + 1
            if length < ps_stop_min:
                continue  # 普通周末 / 短空闲 / 截断后不足停线

            # 停前日 = 窗口前最后一个 PS 生产日（PS 有流的日子）。窗口是最大 PS 零流段，
            # 故 s-1（若在 horizon 内）必为 PS 生产日；窗口从计划期首开始则无停前日。
            pre_stop: date | None = None
            if s > self.inp.start:
                pre_stop = s - timedelta(days=1)

            target = tgt_long if (ps_long_stop is not None and length >= ps_long_stop) else tgt_short

            source = "DEFAULT"
            if pre_stop is not None:
                for c in self.inp.conditions_on("PRE_STOP_TARGET", pre_stop):
                    target = c["target"]
                    source = f"MANUAL:{c['id']}"
                # rev 204：盖住整次停线的人工目标在制 = 停前水位（人工停前目标优先）。
                lv = self.inp.stop_level("PS", s, stop_end)
                if source == "DEFAULT" and lv is not None:
                    target, source = lv[0], f"WIP_TARGET:{lv[1]}"
            levels = {}
            for node in ("PBS", "AS_MAIN", "AS_FIN"):
                lv = self.inp.stop_level(node, s, stop_end)
                if lv is not None:
                    levels[node] = lv[0]

            self.stop_windows.append({
                "start": s.isoformat(),
                "end": stop_end.isoformat(),
                "length": length,
                "pre_stop_date": pre_stop.isoformat() if pre_stop else None,
                "target": target if pre_stop else None,
                "source": source,
                "levels": levels,
            })

            # STOP 阶段（只标 horizon 内的自然日）
            d = s
            while d <= e:
                self._merge_phase(d.isoformat(), "STOP")
                d += timedelta(days=1)

            # PS_PRE_STOP（窗口前最后一个 PS 生产日；计划期首在停线则无停前日，rev 159）
            if pre_stop is not None:
                self._merge_phase(pre_stop.isoformat(), "PS_PRE_STOP")
                if target is not None:
                    self.pre_stop_targets[pre_stop.isoformat()] = target

    # ---------- 3. BS 长停清线检测 ----------

    def _stop_is_long(self, sw: dict, line: str, lg: int) -> tuple[bool, int | None]:
        """该停线窗口对该焊装线是否按长停处理（§5 BS 清线行，rev 196）。

        长停有两类：
        - 零流窗口长度 W ≥ 胶龄 Lg（原口径）；
        - rev 196 胶龄逼清：窗口虽短于 Lg，但 W + k > Lg(m)，其中
          k = ⌈WBS 当日目标 ÷ 该线停前最后生产日的焊装产能⌉，此时按长停处理
          （照本行清线、WBS 清空、PS 停前降库、停后补线、切分 C14 生产段）。

        返回 (是否按长停, k)；k 仅在胶龄逼清起效时为计算值，否则为 None。
        """
        length = sw["length"]
        if length >= lg:
            return True, None
        k = self._glue_forced_k(sw, line)
        if k is None or k <= 0:
            return False, None
        return (length + k) > lg, k

    def _glue_forced_k(self, sw: dict, line: str) -> int | None:
        """rev 196 胶龄逼清判定里的 k = ⌈WBS 当日目标 ÷ 该线停前最后生产日的焊装产能⌉。

        「停前最后生产日」= 停线窗口前该线最后一次投入（IN>0）的日子；WBS 当日目标取
        该日的有效目标。该线停前无生产日（如计划期首已在停线）则返回 None（无从逼清）。
        """
        ws = parse_date(sw["start"])
        last_in = None
        for d in self.inp.dates:
            if d >= ws:
                break
            if self.workshop_total(d.isoformat(), line, "in") > 0:
                last_in = d
        if last_in is None:
            return None
        cap = self.inp.cap_for_mode(line, self._mode(last_in.isoformat(), line) or "OFF", last_in)
        if cap <= 0:
            return None
        wbs_target = self.inp.node_target("WBS", last_in)
        return ceil(wbs_target / cap)

    def _detect_bs_clear(self) -> None:
        """从输入与逐日流量独立识别 BS 清线事件，标记 BS_CLEAR / REFILL 阶段。

        清线依据（§5 BS 清线行）：焊装线自身零流窗口长度 ≥ 该车型胶龄 Lg（长停）；
        或窗口短于 Lg 但胶龄逼清（W + k > Lg，rev 196），同样按长停清线。
        换型旧线与换型留下的闲置线不算长停（rev 161）。清线/补线在停线前后有逐级延迟：
        焊装线比 PS 早停（清线日 IN=0）、早复（补线日 BS 先填），故焊装线的零流结束日
        （复工日）与 PS 停线窗口结束日可能差一天，需按该线实际流量单独识别复工日。
        清线期结束（WBS 清到 0）以 PS 停线窗口开始日为界（WBS 靠 PS 排空，紧贴停线）。
        """
        for m, cfg in self.inp.models.items():
            line = cfg["line"]
            lg = cfg["glue_age_max"]

            for sw in self.stop_windows:
                length = sw["length"]
                is_long, forced_k = self._stop_is_long(sw, line, lg)
                if not is_long:
                    continue  # 短停且无胶龄逼清，不给该线触发清线
                ws = parse_date(sw["start"])
                # 清线期开始：清线日 = 该线最后一次「仍投入」（IN>0）之后首个 OUT>0 的日子。
                last_in = None
                for d in self.inp.dates:
                    if d >= ws:
                        break
                    if self.workshop_total(d.isoformat(), line, "in") > 0:
                        last_in = d
                clear_start = None
                start_from = last_in + timedelta(days=1) if last_in else self.inp.start
                for d in self.inp.dates:
                    if d < start_from or d >= ws:
                        continue
                    if self.workshop_total(d.isoformat(), line, "out") > 0:
                        clear_start = d
                        break
                if clear_start is None:
                    # 无清线日：窗口前最后一天该线 EOD 或该车型 WBS EOD 不为 0 → 未清线违规。
                    # 窗口若从计划期首开始（期初即在长停），视为期初前已清线（TODO(边界)）。
                    if sw["start"] == self.inp.start.isoformat():
                        self.reports.append({
                            "rule": "PHASE", "date": sw["start"], "node": line, "model": m,
                            "detail": (f"{line} 停线窗口 {sw['start']}..{sw['end']} 长 {length} 天 ≥ 胶龄，"
                                       "但计划期首日已在停线，视为期初前已清线（TODO(边界)）"),
                        })
                        continue
                    prev = ws - timedelta(days=1)
                    ds_prev = prev.isoformat()
                    line_eod = self.node_eod_total(ds_prev, line)
                    wbs_eod = self.eod[ds_prev].get("WBS", {}).get(m, 0)
                    if line_eod != 0 or wbs_eod != 0:
                        self.bs_clear_violations.append({
                            "line": line, "model": m, "date": ds_prev,
                            "zero_start": sw["start"], "zero_end": sw["end"],
                            "length": length, "forced_k": forced_k,
                        })
                    continue

                # 换型旧线的清线属于这次换型，不另计 BS 清线（rev 161，L2 不另计）。只跳过
                # 清线日落在换型区间内的旧线清线；换型区间之外的旧线长停清线（该线其后另有
                # ≥ Lg 的停线、独立清线）仍按长停清线计。
                if any(co["old_line"] == line
                       and parse_date(co["start"]) <= clear_start <= parse_date(co["end"])
                       for co in self.changeovers):
                    continue
                if (self.initial_drain and self.initial_drain["line"] == line
                        and self.initial_drain["start"] <= clear_start.isoformat() <= self.initial_drain["end"]):
                    continue

                # 清线期结束：该线 EOD=0 且该车型 WBS EOD=0 的当天（含）。查找截至停线开始日。
                clear_end = None
                cur = clear_start
                while cur <= ws:
                    ds = cur.isoformat()
                    line_eod = self.node_eod_total(ds, line)
                    wbs_eod = self.eod[ds].get("WBS", {}).get(m, 0)
                    if line_eod == 0 and wbs_eod == 0:
                        clear_end = cur
                        break
                    cur += timedelta(days=1)
                if clear_end is None:
                    clear_end = ws  # 未清到 0，由 check_bs_clear 报错

                # 该线复工日 = 清线结束后首个有流的日子（可能早于 PS 复工，逐级补线延迟）。
                resume: date | None = None
                cur = clear_end + timedelta(days=1)
                while cur <= self.inp.end:
                    if (self.workshop_total(cur.isoformat(), line, "in") > 0
                            or self.workshop_total(cur.isoformat(), line, "out") > 0):
                        resume = cur
                        break
                    cur += timedelta(days=1)
                # 零流结束日 = 复工前一日；期末仍未复工则取停线窗口推算的结束日。
                zero_end = (resume - timedelta(days=1)) if resume else parse_date(sw["end"])

                self.bs_clear_events.append({
                    "line": line, "model": m,
                    "start": clear_start.isoformat(), "end": clear_end.isoformat(),
                    "zero_start": sw["start"], "zero_end": zero_end.isoformat(),
                })

                d = clear_start
                while d <= clear_end:
                    # 清线是生产活动：只标可生产日（周末/节假日 NORMAL），与预期 phases 一致。
                    if self.is_production_day(line, d):
                        self._merge_phase(d.isoformat(), "BS_CLEAR")
                    d += timedelta(days=1)

                # 清线后补线（REFILL）：该线复工日起，到全链每节点 ≥ tgt 当天。
                self._add_refill_after(line, ws, zero_end)

    def _add_refill_after(self, line: str, ws: date, we: date) -> None:
        """清过线的停线复工后补线：从 we 之后首个生产日起，到全链节点 ≥ tgt 止。
        若 we 超出计划期（尾停），则不产生补线（计划期结束无复工）。"""
        chain = [line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
        resume = we + timedelta(days=1)
        if resume < self.inp.start:
            resume = self.inp.start
        while resume <= self.inp.end:
            ds = resume.isoformat()
            if (self.workshop_total(ds, line, "in") > 0
                    or self.workshop_total(ds, line, "out") > 0):
                break
            resume += timedelta(days=1)
        if resume > self.inp.end:
            return  # 期末未复工，无补线
        refill_end = None
        cur = resume
        while cur <= self.inp.end:
            ds = cur.isoformat()
            if ("STOP" not in self.phases[ds].split("+")
                    and any(self.is_production_day(w, cur) for w in WORKSHOPS)
                    and all(self.node_eod_total(ds, n) >= self.inp.node_target(n, cur) for n in chain)):
                refill_end = cur
                break
            cur += timedelta(days=1)
        if refill_end is None:
            refill_end = self.inp.dates[-1]  # TODO(边界)：补线到期末仍未全链达标
        self.refill_periods.append({"start": resume.isoformat(), "end": refill_end.isoformat()})
        d = resume
        while d <= refill_end:
            if ("STOP" not in self.phases[d.isoformat()].split("+")
                    and any(self.is_production_day(w, d) for w in WORKSHOPS)):
                self._merge_phase(d.isoformat(), "REFILL")
            d += timedelta(days=1)

    # ---------- 3b. PS 停前降库期检测（T-17 / rev 185） ----------

    def _detect_ps_clear_down(self) -> None:
        """识别 PS 停前降库期：对每个有停前日、且首个 BS 清线日落在该停线窗口内的停线
        窗口，从首个 BS 清线日到 PS 停前日（含首尾）为降库期。

        rev 185 裁决：有 BS 清线时，从首个 BS 清线日起 PS 进入停前降库——期间 PS 不查 C8，
        投入/出车必须「能做尽做」（投入 = min(PS 当日产能, WBS 日初 + 当日焊装出车)，
        出车 = min(PS 当日产能, PS 日初 + 投入 − 停前目标)），公式核对在
        constraints.check_ps_clear_down。降库期天数标记 PS_PRE_STOP 阶段（使 PS 免 C8/C14，
        由公式替代这两条——见 check_c8 / check_c14 的阶段放宽）。
        """
        clear_by_stop: dict[str, list[dict]] = {}
        for ev in self.bs_clear_events:
            clear_by_stop.setdefault(ev["zero_start"], []).append(ev)

        for sw in self.stop_windows:
            pre = sw.get("pre_stop_date")
            target = sw.get("target")
            if pre is None or target is None:
                continue
            evs = clear_by_stop.get(sw["start"], [])
            if not evs:
                continue
            clear_start = min(ev["start"] for ev in evs)
            self.ps_clear_down_periods.append({
                "start": clear_start,
                "end": pre,
                "target": target,
            })
            d = parse_date(clear_start)
            end = parse_date(pre)
            while d <= end:
                self._merge_phase(d.isoformat(), "PS_PRE_STOP")
                d += timedelta(days=1)

    def _detect_level_drain(self) -> None:
        """rev 205：有停前水位的节点的降库起点 sw["drain_from"][node]——停前日之前该节点日末
        连续低于正常目标那段日子的第一天，不晚于首个 BS 清线日（没有清线时为停前日）。"""
        for sw in self.stop_windows:
            pre = sw.get("pre_stop_date")
            sw["drain_from"] = {}
            if pre is None:
                continue
            clear = next((p["start"] for p in self.ps_clear_down_periods if p["end"] == pre), pre)
            for node in sw.get("levels", {}):
                start = parse_date(pre)
                d = start - timedelta(days=1)
                while d >= self.inp.start and self.node_eod_total(d.isoformat(), node) < self.inp.node_target(node, d):
                    start = d
                    d -= timedelta(days=1)
                sw["drain_from"][node] = min(start.isoformat(), clear)

    # ---------- 4. 期初补线检测 ----------

    def _detect_initial_refill(self) -> None:
        """期初任一非闲置节点（共享节点按两车型合计）低于 tgt → 从首个生产日起进入
        REFILL，到全链每个在产节点 ≥ tgt 当天（含）止。

        闲置焊装线 = 期初该线自身在制合计为 0 的线（换型前/首启前闲置，不参与补线判定；
        CORE_MODEL §5 补线行「闲置焊装线除外」，rev 159）。共享节点（WBS/PS/PBS/AS_MAIN/
        AS_FIN）按两车型合计比对，始终参与。
        """
        if all(sum(self.inp.inv0.get(l, {}).values()) > 0 for l in ("BS1", "BS2")):
            return  # 双线期初在制按 INITIAL_DRAIN 处理，不能用 REFILL 遮蔽迟排空。
        # 闲置焊装线：期初该线自身 in0 合计为 0。
        def line_idle(line: str) -> bool:
            return sum(self.inp.inv0.get(line, {}).values()) == 0

        def node_below(node: str) -> bool:
            init = sum(self.inp.inv0.get(node, {}).get(m, 0) for m in self._models())
            return init < self.inp.node_target(node, self.inp.start)

        below = False
        for n in NODES:
            if n in ("BS1", "BS2"):
                if line_idle(n):
                    continue  # 闲置焊装线不判
            if node_below(n):
                below = True
                break
        if not below:
            return

        # 首个生产日（is_working_capable）
        start = None
        for d in self.inp.dates:
            if any(self.is_production_day(w, d) for w in WORKSHOPS):
                start = d
                break
        if start is None:
            return
        # 补线链 = 在产焊装线（期初自身有在制的线，取首个）→ WBS → PS → PBS → AS_MAIN → AS_FIN
        first_line = None
        for m in self._models():
            l = self.inp.line_of[m]
            if not line_idle(l):
                first_line = l
                break
        chain = [n for n in [first_line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"] if n]
        refill_end = None
        cur = start
        while cur <= self.inp.end:
            ds = cur.isoformat()
            if ("STOP" not in self.phases[ds].split("+")
                    and any(self.is_production_day(w, cur) for w in WORKSHOPS)
                    and all(self.node_eod_total(ds, n) >= self.inp.node_target(n, cur) for n in chain)):
                refill_end = cur
                break
            cur += timedelta(days=1)
        if refill_end is None:
            refill_end = self.inp.dates[-1]
        self.refill_periods.append({"start": start.isoformat(), "end": refill_end.isoformat()})
        d = start
        while d <= refill_end:
            if ("STOP" not in self.phases[d.isoformat()].split("+")
                    and any(self.is_production_day(w, d) for w in WORKSHOPS)):
                self._merge_phase(d.isoformat(), "REFILL")
            d += timedelta(days=1)

    # ---------- 5. 首次启动检测 ----------

    def _detect_first_starts(self) -> None:
        """期初无在制、无历史的车型第一次投入 → 首次启动。阶段从该车型首次投入日
        到全链补满日（含）。首次正 OUT 当天焊装线 EOD ≥ tgt 由 check_first_start 查。"""
        for m, cfg in self.inp.models.items():
            line = cfg["line"]
            has_init = any(self.inp.inv0.get(n, {}).get(m, 0) > 0 for n in NODES)
            if has_init:
                continue
            # 首次投入日（该车型 IN>0 或 OUT>0 的首日）
            first_day = None
            for d in self.inp.dates:
                ds = d.isoformat()
                if (self._wq(ds, line, m, "in") > 0 or self._wq(ds, line, m, "out") > 0
                        or self._wq(ds, "PS", m, "in") > 0 or self._wq(ds, "AS_FIN", m, "out") > 0):
                    first_day = d
                    break
            if first_day is None:
                continue
            # 结束 = 全链补满（同补线）
            chain = [line, "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"]
            end = None
            cur = first_day
            while cur <= self.inp.end:
                ds = cur.isoformat()
                if all(self.node_eod_total(ds, n) >= self.inp.node_target(n, parse_date(ds)) for n in chain):
                    end = cur
                    break
                cur += timedelta(days=1)
            if end is None:
                end = self.inp.dates[-1]
            self.first_starts.append({
                "model": m, "line": line,
                "start": first_day.isoformat(), "end": end.isoformat(),
            })
            d = first_day
            while d <= end:
                self._merge_phase(d.isoformat(), "FIRST_START")
                d += timedelta(days=1)

    # ---------- 阶段合并（IO_CONTRACT §6：一天命中多阶段用 + 连接，按固定顺序） ----------

    _PHASE_ORDER = ("PS_PRE_STOP", "STOP", "BS_CLEAR", "REFILL",
                    "FIRST_START", "CHANGEOVER", "MODEL_EXIT", "INITIAL_DRAIN")

    def _merge_phase(self, ds: str, phase: str) -> None:
        cur = self.phases.get(ds, "NORMAL")
        if cur == "NORMAL":
            self.phases[ds] = phase
            return
        parts = cur.split("+")
        if phase in parts:
            return
        parts.append(phase)
        parts.sort(key=lambda p: self._PHASE_ORDER.index(p) if p in self._PHASE_ORDER else 99)
        self.phases[ds] = "+".join(parts)

    # ---------- 目标 L1–L5 重算 ----------

    def compute_objective(self):
        models = self._models()
        # L1a 全期 PR 缺口（台）= Σ max(0, ΣPR - Σfok)
        l1a = 0
        for m in models:
            pr_total = sum(self.inp.pr.get(m, {}).values())
            fok_total = sum(self.fok[ds].get(m, 0) for ds in self.eod)
            l1a += max(0, pr_total - fok_total)
        # L1b 欠交台·天 = Σ_d Σ_m bl(m,d)
        l1b = 0
        for ds in self.eod:
            for m in models:
                l1b += self.bl[ds].get(m, 0)
        # L1c 月度带下限缺口（台）= Σ_m Σ_mo max(0, cumPR(m,mo) - ratio·PR(m,mo) - cumFOK(m,mo))
        band = self.inp.rules.get("monthly_band_ratio") or 0
        l1c = 0.0
        months = self.inp.months_in_horizon()
        for m in models:
            cum_pr = 0
            cum_fok = 0
            for mo in months:
                pr_mo = self.inp.pr.get(m, {}).get(mo, 0)
                cum_pr += pr_mo
                for d in self.inp.dates:
                    if self.inp.month_of(d) == mo:
                        cum_fok += self.fok[d.isoformat()].get(m, 0)
                u = cum_pr - band * pr_mo - cum_fok
                # L1c 取精确值、不取整（IO_CONTRACT §5，2026-10-24 定）。band·PR 最多一位
                # 小数，cumPR/cumFOK 为整数，故 u 最多一位小数；round(…,10) 只消二进制浮点尾巴。
                if u > 0:
                    l1c += round(u, 10)
        # L2 换型+清线次数：换型事件数 + BS 清线事件数；换型里旧线的清线属于这次换型，
        # 不另计清线（_detect_bs_clear 对换型旧线不记录事件）。
        l2 = len(self.changeovers) + len(self.bs_clear_events) + int(self.initial_drain is not None)
        # L3a 周六使用量：非日历可生产日采用非 OFF 的车间·日数
        l3a = 0
        for d in self.inp.dates:
            ds = d.isoformat()
            if self.inp.is_working(d):
                continue
            day = self._days.get(ds, {})
            for w in WORKSHOPS:
                mode = day.get("workshops", {}).get(w, {}).get("mode", "OFF")
                if mode != "OFF":
                    l3a += 1
        # L3b 非默认模式使用量：OFF 与 default_mode 之外
        l3b = 0
        default = self.inp.default_mode
        for d in self.inp.dates:
            ds = d.isoformat()
            day = self._days.get(ds, {})
            for w in WORKSHOPS:
                mode = day.get("workshops", {}).get(w, {}).get("mode", "OFF")
                if mode not in ("OFF", default):
                    l3b += 1
        # L4 WBS 越出经验带天数
        l4 = 0
        if self.inp.wbs_hi is not None:
            for d in self.inp.dates:
                ds = d.isoformat()
                total = sum(self.eod[ds].get("WBS", {}).values())
                if total > self.inp.wbs_hi:
                    l4 += 1
        # L5 高于目标的在制总量
        l5 = 0
        for d in self.inp.dates:
            ds = d.isoformat()
            for node in NODES:
                total_eod = sum(self.eod[ds].get(node, {}).values())
                tgt = self.inp.node_target(node, parse_date(ds))
                l5 += max(0, total_eod - tgt)
        # L6 超目标在制尽量靠下游（rev 185）：Σ_d Σ_n w(n)·max(0, EOD−tgt)，权重见
        # NODE_L6_WEIGHT；其余口径同 L5。
        l6 = 0
        for d in self.inp.dates:
            ds = d.isoformat()
            for node in NODES:
                total_eod = sum(self.eod[ds].get(node, {}).values())
                tgt = self.inp.node_target(node, parse_date(ds))
                l6 += NODE_L6_WEIGHT[node] * max(0, total_eod - tgt)

        self.objective = {"L1a": l1a, "L1b": l1b, "L1c": l1c, "L2": l2,
                          "L3a": l3a, "L3b": l3b, "L4": l4, "L5": l5, "L6": l6}
