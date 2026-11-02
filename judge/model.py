"""数据模型：把 input.json 解析成便于判定的结构，并从逐日 IN/OUT 独立重算库存。

只依赖 CORE_MODEL §1/§2/§3 的集合定义；不 import engine。
"""
from __future__ import annotations

from datetime import date, timedelta
from math import floor

from .conditions import parse_conditions

# CORE_MODEL §1：七个 N 节点 = 车间 ∪ 缓冲区（成品 FIN 不在此列）
# IO_CONTRACT 里 flow 定死了这条链；判定器按 flow 从输入推导节点与流向，
# 不在代码里写死任何业务数字（AGENTS.md 规则 6）。
WORKSHOP_KEYS = ("BS1", "BS2", "PS", "AS_MAIN", "AS_FIN")
BUFFER_KEYS = ("WBS", "PBS")


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def all_dates_horizon(start: str, end: str) -> list[date]:
    d0, d1 = parse_date(start), parse_date(end)
    out, cur = [], d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


class InputModel:
    """解析后的输入，供判定器各处读取。"""

    def __init__(self, raw: dict):
        self.raw = raw
        self.start = parse_date(raw["horizon"]["start"])
        self.end = parse_date(raw["horizon"]["end"])
        self.dates: list[date] = all_dates_horizon(raw["horizon"]["start"], raw["horizon"]["end"])
        self.date_index = {d: i for i, d in enumerate(self.dates)}

        # 日历：D 中每天一条，is_working_capable 决定 Dᵂ
        self.working: dict[date, bool] = {}
        for c in raw["calendar"]:
            self.working[parse_date(c["date"])] = bool(c["is_working_capable"])

        f = raw["factory"]
        self.workshops: dict[str, int] = {k: v["jph"] for k, v in f["workshops"].items()}
        self.buffers: dict[str, int] = {k: v["cap_max"] for k, v in f["buffers"].items()}
        self.workshop_caps = {k: v["cap_max"] for k, v in f["workshops"].items() if "cap_max" in v}
        self.modes: dict[str, int] = dict(f["modes"])  # hrs(k)
        self.default_mode: str = f["default_mode"]
        self.models: dict[str, dict] = f["models"]  # {m: {line, glue_age_max}}
        self.flow: list[str] = f["flow"]
        self.shared_welding_jph_max = f.get("shared_welding_jph_max")

        # 由 flow 推出每个车间的上游节点（本阶段只有一条链，用于日后校验，当前够用）
        self.line_of = {m: v["line"] for m, v in self.models.items()}
        self.glue_age_max = {m: v["glue_age_max"] for m, v in self.models.items()}

        # 由 flow 推出的「下游节点」与「直接上游节点」映射（用于 C15 镜像 / 换型逐级补满）。
        # flow 边 "X>Y"：Y 的直接上游是 X；X 的直接下游是 Y。FIN 是成品，不在 N 中。
        self.downstream: dict[str, str | None] = {}   # node -> 直接下游（唯一，链式流），FIN 记 None
        self.upstream: dict[str, str | None] = {}     # node -> 直接上游；多上游节点（WBS 有 BS1/BS2）记 None 表示“多个”
        for e in self.flow:
            src, dst = e.split(">")
            if ">" not in e or dst == "FIN":
                # FIN 边不计入在制链
                self.downstream.setdefault(src, None)
                continue
            # 记为直接下游（链式流，每节点至多一个下游车间/缓冲）
            self.downstream.setdefault(src, dst)
            # 直接上游：若已存在且不同，记为多上游（WBS）
            prev = self.upstream.get(dst)
            if prev is None:
                self.upstream[dst] = src
            elif prev != src:
                self.upstream[dst] = None
        # 补上 FIN 边的下游记录已在上方 setdefault；确保每个节点都有下游键
        for w in self.workshops:
            self.downstream.setdefault(w, None)
        for b in self.buffers:
            self.downstream.setdefault(b, None)
            self.upstream.setdefault(b, None)

        self.pr: dict[str, dict[str, int]] = raw["demand"]["PR"]  # {model: {month: qty}}
        self.ws_daily: dict[str, dict[str, int]] = raw["demand"].get("WS_daily", {})

        init = raw["initial"]
        self.inv0: dict[str, dict[str, int]] = {}
        for node, per_model in init.get("wip", {}).items():
            self.inv0[node] = dict(per_model)
        self.fin0: dict[str, int] = dict(init.get("fin", {}))

        self.wip_targets: dict[str, int] = dict(raw.get("wip_targets", {}))
        self.wbs_hi = raw.get("wbs_hi")  # None => C9 不启用
        self.conditions: list = raw.get("conditions", [])
        self.rules: dict = raw.get("rules", {})
        self.valid_conditions, self.condition_errors = parse_conditions(self)

    # ---- 派生查询 ----

    def node_cap(self, node: str, d: date) -> int:
        """C6：显式物理上限固定，未填的车间跟随当日目标。"""
        if node in self.buffers:
            return self.buffers[node]
        if node in self.workshop_caps:
            return self.workshop_caps[node]
        return self.node_target(node, d)

    def node_target(self, node: str, d: date | None = None) -> int:
        """当日人工目标优先，否则取基础目标；共享节点目标按车型合计。"""
        for c in self.conditions_on("WIP_TARGET", d):
            if c["node"] == node:
                return c["target"]
        return self.wip_targets.get(node, 0)

    def stop_level(self, node: str, s: date, e: date) -> tuple[int, str] | None:
        """rev 204：盖住停线窗口 s..e 内全部可生产日的人工目标在制 → (停前水位, 条件 id)。
        rev 205：整条落在窗口内的人工目标在制也算（自建空闲与计划停线合并成更长的停线时，
        条件只写在计划停线那段）。"""
        days = [d for d in self.dates if s <= d <= e and any(self.is_available(w, d) or self.is_working(d)
                                                            for w in self.workshops)]
        for c in self.valid_conditions:
            if c["type"] == "WIP_TARGET" and c["node"] == node and (
                    (days and all(c["start_date"] <= d <= c["end_date"] for d in days))
                    or s <= c["start_date"] and c["end_date"] <= e):
                return c["target"], c["id"]
        return None

    def max_cap(self, w: str, d: date) -> int:
        """当天授权内最高班制产能（含产能损失）；停线或不可生产为 0。"""
        if not self.is_available(w, d):
            return 0
        return max(self.cap_for_mode(w, mode, d) for mode in self.modes if self.mode_allowed(w, d, mode))

    def prebuild(self) -> dict[str, dict[str, int]]:
        """C12 rev 204 必须提前量 E(m, mo)：之后月份按月度产能估算做不完、须在本月及以前做完的量。"""
        months = self.months_in_horizon()
        out: dict[str, dict[str, int]] = {}
        for m, line in self.line_of.items():
            cap = {mo: 0 for mo in months}
            for d in self.dates:
                cap[self.month_of(d)] += min(self.max_cap(w, d) for w in (line, "PS", "AS_MAIN", "AS_FIN"))
            pr = self.pr.get(m, {})
            out[m] = {}
            for k, mo in enumerate(months):
                need, best = 0, 0
                for j in months[k + 1:]:
                    need += pr.get(j, 0) - cap[j]
                    best = max(best, need)
                out[m][mo] = best
        return out

    def is_working(self, d: date) -> bool:
        return self.working.get(d, False)

    def month_of(self, d: date) -> str:
        return f"{d.year:04d}-{d.month:02d}"

    def months_in_horizon(self) -> list[str]:
        seen: list[str] = []
        for d in self.dates:
            mo = self.month_of(d)
            if mo not in seen:
                seen.append(mo)
        return seen

    def conditions_on(self, kind: str, d: date | None):
        return [c for c in self.valid_conditions if c["type"] == kind
                and d is not None and c["start_date"] <= d <= c["end_date"]]

    def is_shutdown(self, w: str, d: date) -> bool:
        return any(w in c["workshops"] for c in self.conditions_on("SHUTDOWN", d))

    def is_available(self, w: str, d: date) -> bool:
        return not self.is_shutdown(w, d) and (self.is_working(d) or any(
            w in c["workshops"] for c in self.conditions_on("SATURDAY_AUTH", d)))

    def mode_allowed(self, w: str, d: date, mode: str) -> bool:
        return mode in ("OFF", self.default_mode) or any(
            w in c["workshops"] and c["mode"] == mode
            for c in self.conditions_on("MODE_AUTH", d))

    def cap_for_mode(self, w: str, mode: str, d: date | None = None) -> int:
        """C2 / C14：按当日工时上限计算有效产能。"""
        hrs = self.modes.get(mode, 0)
        for c in self.conditions_on("CAPACITY_LOSS", d):
            if w in c["workshops"]:
                hrs = min(hrs, c["hours_max"])
        return floor(hrs * self.workshops[w])
