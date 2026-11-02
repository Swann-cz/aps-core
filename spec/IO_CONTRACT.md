# aps-core 接口约定（算例输入 / 计划输出 / 判定输出）

> 本文由 Claude 维护，只规定**文件格式和度量口径**，不规定业务规则；业务规则只以 `spec/CORE_MODEL.md` 为准。
> 两者冲突时以 CORE_MODEL 为准，并在回报里指出冲突。
> 第一阶段算例使用本文的扁平 JSON；S2 接入产品时再写 `PlanningRequest` / `PlanningResult` 适配层。

## 1. 命令行入口

两边各自是一个 Python 包，**彼此不得 import**，只通过文件交换数据。

```text
python -m engine <input.json> <plan.json>                 # 生成器：读输入，写计划
python -m judge  <input.json> <plan.json> <verdict.json>  # 判定器：读输入和任意一份计划，写判定
python tools/run_case.py cases/<case-dir>                # 跑算例：生成 → 判定 → 与 expected 比对
```

- 退出码：0 = 正常写出文件（无论结论是什么）；非 0 = 程序异常。
- 所有日期为 `YYYY-MM-DD` 字符串，所有数量为整数（台）。

## 2. 输入 `input.json`

```jsonc
{
  "schema": "aps-core/input/v1",
  "horizon": { "start": "2026-03-02", "end": "2026-03-11" },      // D，含首尾
  "calendar": [ { "date": "2026-03-02", "is_working_capable": true }, ... ],  // D 中每天一条；可以多带 horizon.end 之后的日子，只用来推算期末停线长度（CORE_MODEL §5 停线行，rev 159）
  "factory": {
    "workshops": { "BS1": { "jph": 10, "cap_max": 80 }, "BS2": { "jph": 8 }, "PS": { "jph": 10 },
                   "AS_MAIN": { "jph": 10 }, "AS_FIN": { "jph": 10 } },   // cap_max 选填（CORE_MODEL C6，rev 191）：车间物理上限；缺省 = 当天目标在制
    "buffers":   { "WBS": { "cap_max": 69 }, "PBS": { "cap_max": 150 } },  // capᴹ(n)
    "modes":     { "OFF": 0, "SINGLE_8H": 8, "SINGLE_8P2": 10, "DOUBLE_SHIFT": 16 },  // hrs(k)
    "default_mode": "SINGLE_8H",                                   // 无授权时唯一可用的非 OFF 模式
    "models":    { "A": { "line": "BS1", "glue_age_max": 14 } },   // line(m)、Lg(m)
    "flow": ["BS1>WBS", "BS2>WBS", "WBS>PS", "PS>PBS", "PBS>AS_MAIN", "AS_MAIN>AS_FIN", "AS_FIN>FIN"],
    "shared_welding_jph_max": 13
  },
  "demand": {
    "PR": { "A": { "2026-03": 600 } },                 // PR(m,mo)，计划期内每月每车型都有
    "WS_daily": { "A": { "2026-03-11": 600 } }         // WS(m,d)；未给逐日时由月度 WS 落到该月最后可生产日
  },
  "initial": {
    "wip": { "BS1": { "A": 69 }, "WBS": { "A": 37 }, ... },   // inv0(n,m)，缺省为 0
    "fin": { "A": 0 }                                       // fin0(m)
  },
  "wip_targets": { "BS1": 69, "BS2": 69, "WBS": 37, "PS": 147, "PBS": 80, "AS_MAIN": 100, "AS_FIN": 40 },  // tgt₀(n)
  "wbs_hi": null,                // 经验上限；null = 本请求不启用 C9
  "conditions": [],              // 排产员条件，格式见 §2.1；空列表 = 无条件
  "rules": {                     // 规则常数，代码里不得写死
    "ps_stop_min_days": 3,
    "ps_long_stop_days": 15,
    "ps_pre_stop_target_short": 131,
    "ps_pre_stop_target_long": 91,
    "monthly_band_ratio": 0.1
  }
}
```

### 2.1 条件 `conditions`（2026-10-25 定稿）

业务含义以 CORE_MODEL C3 后“条件的业务含义”为准；本节只定字段。每条一个对象：

```jsonc
{ "id": "C-001", "type": "SATURDAY_AUTH", ...各类型字段..., "reason": "可选，备注" }
```

- `id`：字符串，同一输入内不得重复；计划和判定按它引用（停线清单 `source: "MANUAL:<id>"`、findings、判定 detail）。
- 日期范围写 `start`、`end`（含首尾）；标注“或 `date`”的类型可只写单日 `date`。所有日期必须在 horizon 内。
- `workshops`：车间 id 列表（BS1、BS2、PS、AS_MAIN、AS_FIN）；标“可省略”的，省略 = 五个车间全部。
- `reason`：可选，任何类型都可带，不影响计算。

| type | 必填字段 | 可选字段 |
| --- | --- | --- |
| `SATURDAY_AUTH` | `start`+`end` 或 `date` | `workshops`（可省略） |
| `MODE_AUTH` | `mode`（须在 factory.modes 中，且不是 OFF / default_mode）、`start`、`end`、`workshops` | — |
| `SHUTDOWN` | `start`、`end` | `workshops`（可省略） |
| `CAPACITY_LOSS` | `start`、`end`、`workshops`、`hours_max`（整数，≥ 0） | — |
| `WIP_TARGET` | `node`（七个节点之一）、`start`、`end`、`target`（整数，≥ 0） | — |
| `PRE_STOP_TARGET` | `pre_stop_date`、`target`（整数，≥ 0） | — |
| `FIXED_OUTPUT` | `workshop`、`date`、`out`（整数，≥ 0） | — |

输入预检（生成器返回 `INPUT_INVALID`，判定器报 `INPUT`）：未知 type、缺必填字段、id 重复、日期出 horizon 或 start > end、车间 / 节点 / 模式不存在、同一节点同一天两条 `WIP_TARGET` 值不同、同一车间同一天两条 `FIXED_OUTPUT` 值不同、`FIXED_OUTPUT` 落在该车间停线日且 out > 0、`WIP_TARGET` 与全线 `SHUTDOWN`（不列 workshops 或列全五个车间）有重叠却没有盖住整段 `SHUTDOWN`（CORE_MODEL rev 204）。

示例（gap 组补两个周六，全线上班）：

```jsonc
"conditions": [
  { "id": "SAT-1", "type": "SATURDAY_AUTH", "date": "2026-10-03", "reason": "补 A 欠产" },
  { "id": "SAT-2", "type": "SATURDAY_AUTH", "date": "2026-10-10", "reason": "补 A 欠产" }
]
```

## 3. 计划 `plan.json`（生成器写）

```jsonc
{
  "schema": "aps-core/plan/v1",
  "status": "FEASIBLE",          // 生成器自己的结论：FEASIBLE / UNKNOWN / PROVEN_INFEASIBLE / INPUT_INVALID / EXECUTION_ERROR
  "solver": { "name": "segment", "seconds": 13.2 },   // 可选（2026-10-27，T-31 S4）：本次使用的找解路线 legacy / segment / best 及墙钟用时；判定器不读
  "days": [
    {
      "date": "2026-03-02",
      "workshops": {
        "BS1": { "mode": "SINGLE_8H", "hours": 8, "in": { "A": 80 }, "out": { "A": 80 } },
        "BS2": { "mode": "OFF", "hours": 0, "in": {}, "out": {} },   // 当日 IN=OUT=0 的车间记 OFF；有正流量时不得为 OFF
        ...                      // 五个车间都要有
      },
      "bod": { "BS1": { "A": 69 }, "WBS": { "A": 37 }, ... },   // 七个节点，按车型；0 可省略
      "eod": { "BS1": { "A": 69 }, "WBS": { "A": 37 }, ... },
      "fok": { "A": 80 },
      "fin": { "A": 80 },
      "bl": { "A": 0 },          // 累计欠交（CORE_MODEL C11），产能够时恒为 0
      "phase": "NORMAL",         // 生成器自报的阶段，仅供对照（B21：判定器自己重算）
      "phase_basis": "..."       // 可选，文字依据
    }
  ],
  "stop_list": [                 // ≥3 天 PS 零流窗口，按开始日排序；没有就是 []
    { "start": "2026-04-02", "end": "2026-04-05", "length": 4,        // 窗口首尾日（含），自然日数
      "pre_stop_date": "2026-04-01", "target": 131, "source": "DEFAULT" }   // 停前日、停前目标、来源 DEFAULT | MANUAL:<条件号>
  ],
  // 计划期首日已在停线：start = horizon.start，length 只数计划期内的天，pre_stop_date、target 为 null。
  // 计划期末日仍在停线：end 写推算出的复工前一天（可以在计划期之后），length 按推算长度。
  "objective": {
    "levels": [ { "level": "L1a", "value": 0, "proven_optimal": true }, ... ]
  },
  "findings": []                 // PR 缺口、违规、建议等说明
}
```

## 4. 判定 `verdict.json`（判定器写）

```jsonc
{
  "schema": "aps-core/verdict/v1",
  "verdict": "ACCEPT",           // ACCEPT = 零硬错误；REJECT = 至少一条硬错误
  "hard_errors": [ { "rule": "C6", "date": "2026-03-11", "node": "WBS", "model": null, "detail": "..." } ],   // rule：C1–C15、C17；SEQ（C16）；FIXED（指定产量不符）；§5 阶段新增约束的违规记阶段名（如 CHANGEOVER）；INPUT
  "reports": [],                 // 只报告、不算失败的事项（如 C9 不满产日越界）
  "phases": { "2026-03-02": "NORMAL", ... },   // 判定器从输入和逐日流量独立重算的阶段
  "objective": { "L1a": 0, "L1b": 0, "L1c": 0, "L2": 0, "L3a": 0, "L3b": 0, "L4": 0, "L5": 0, "L6": 0 }   // 判定器独立重算（L6 自 rev 185 起）
}
```

## 5. 目标各级的度量口径（CORE_MODEL §6 的落地）

除 L1c 外全部为整数，越小越好；L1c 按公式取精确值，不取整（monthly_band_ratio = 0.1 时最多一位小数，JSON 写成数字，如 142.3；2026-10-24 定），按 L1a → L1b → L1c → L2 → L3a → L3b → L4 → L5 → L6 分级优化。

| 级别 | 度量 | 计算 |
| --- | --- | --- |
| L1a | 全期 PR 缺口（台） | Σ_m max(0, Σ_mo PR(m,mo) − Σ_d fok(m,d)) |
| L1b | 欠交台·天 | Σ_d Σ_m bl(m,d)，bl 按 CORE_MODEL C11 由 fin0、fok、WS 逐日推出 |
| L1c | 月度带下限缺口（台） | Σ_m Σ_mo max(0, cumPR(m,mo) − monthly_band_ratio·PR(m,mo) − cumFOK(m,mo)) |
| L2 | 换型与清线次数 | 换型事件数 + BS 清线事件数；换型里旧线的清线属于这次换型，不另计清线；期初双线排空记 1 次换型（2026-10-25）（1a 恒为 0，1b 为 1） |
| L3a | 周六使用量 | 非日历可生产日上采用非 OFF 模式的“车间·日”数 |
| L3b | 非默认模式使用量 | 采用 OFF 和 default_mode 以外模式的“车间·日”数 |
| L4 | WBS 越出经验带天数 | wbs_hi 非 null 时，WBS 合计 EOD > wbs_hi 的天数；否则 0 |
| L5 | 高于目标的在制总量 | Σ_{d∈D} Σ_{n∈N} max(0, EOD(n,d) − tgt(n,d))；共享节点按车型合计，焊装线按各自线计 |
| L6 | 超目标在制尽量靠下游（rev 185） | Σ_{d∈D} Σ_{n∈N} w(n) · max(0, EOD(n,d) − tgt(n,d))，w：AS_FIN 1、AS_MAIN 2、PBS 3、PS 4、WBS 5、BS1 / BS2 6；其余口径同 L5 |

L3 拆成 3a/3b 是按“先平日加班、后周六”的确认：周六比平日加班更不希望用，因此先压周六。

## 6. 阶段名

`NORMAL`、`PS_PRE_STOP`、`STOP`、`BS_CLEAR`、`REFILL`、`FIRST_START`、`CHANGEOVER`、`MODEL_EXIT`、`INITIAL_DRAIN`。
一天命中多个阶段时，用 `+` 连接、按上面顺序排列（如 `PS_PRE_STOP+BS_CLEAR`、首次启动经由换型时的 `FIRST_START+CHANGEOVER`）。期初低于目标的补线记 `REFILL`。1a 只会出现 `NORMAL`。
