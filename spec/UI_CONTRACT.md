# aps-core 界面接口约定（薄后端 ↔ 前端）

> 本文由 Claude 维护，2026-10-25 首版（方案 B，Swann 确认）；rev 7（2026-10-26）新增 §9 缺口与建议；rev 8 采纳后只重判、不重跑；rev 9 缺口只认月度带下限与全期欠产、加班逐档升级、EXHAUSTED；rev 10 运行带热启动与安全网（T-26，Swann 选 A）；rev 11 新建排产后先到“排产条件”一步（§8.3）；rev 12（2026-10-29）新增 §10 排产向导，主流程收进向导页，全局放大字号和按钮。只规定界面层的目录、接口和显示口径；
> 计划、判定的文件格式以 `spec/IO_CONTRACT.md` 为准，业务规则以 `spec/CORE_MODEL.md` 为准。
> 界面只显示、不计算：页面上的每个数都由后端按本文口径从 input / plan / verdict 算出。

## 1. 范围

本阶段界面只有三页，其余旧页面在导航和路由里隐藏（文件保留、不删）：

| 页面 | 路由 | 做什么 |
| --- | --- | --- |
| 年度总览 | `/annual-overview` | 看一份方案的全年计划：年度日历、月度事实、车型年度 PR / FOK / 缺口、判定结论 |
| 月度 Filling | `/monthly-filling?month=YYYY-MM` | 看一个月逐日、逐车间、逐车型的流量和在制 |
| 排产条件 | `/planning-conditions` | 增删改本方案的条件（IO_CONTRACT §2.1 七种），保存后点“运行”重算 |
| 新建排产 | `/new-plan` | rev 5：上传销售计划（及可选的期初在制、生产行事历）建新方案，见 §8 |
| 正式版本 | `/formal` | rev 5：已定稿的计划列表，只读查看，见 §8 |

三页共用顶栏：方案选择、方案状态（见 §4 `state`）、“运行”按钮、“另存为新方案”按钮。默认路由 `/` 进年度总览。
没有登录、没有多用户、没有锁定 / 实绩 / 滚动（第二阶段再接）。

## 2. 目录与启动

| 目录 | 内容 | 谁写 |
| --- | --- | --- |
| `server/` | 薄后端，Python 包，FastAPI + uvicorn（已装，允许使用） | Codex |
| `ui/` | 前端，由 Claude 从旧版 V6.1.4 前端整体复制而来（React + antd + vite） | Codex 在其上修改 |
| `workspace/` | 运行数据（方案目录），不进 git | 后端运行时写 |

```text
python -m server                     # 后端，监听 127.0.0.1:8765，工作目录 = 仓库根
cd ui && npm run dev                 # 前端，5173，/api 代理到 127.0.0.1:8765
python tools/seed_workspace.py       # Claude 维护：用 1d-annual-feedback 三组输入和第一阶段终版计划建三个方案
```

后端**不得 import** `engine` 或 `judge`，只用子进程调用 IO_CONTRACT §1 的命令行，与两者通过文件交互。

## 3. 方案目录 `workspace/scenarios/<id>/`

| 文件 | 内容 |
| --- | --- |
| `meta.json` | 见下 |
| `input.json` | IO_CONTRACT §2 输入；改条件只改其中 `conditions` |
| `plan.json` | 最近一次成功运行的计划（可不存在） |
| `verdict.json` | 与 `plan.json` 配对的判定（可不存在） |
| `run.log` | 最近一次运行的生成器和判定器标准输出 + 标准错误 |

```jsonc
// meta.json
{
  "id": "gap-sat",                    // 目录名；新建时用 "s-" + YYYYMMDD-HHMMSS
  "name": "gap 加三个周六",
  "created_at": "2026-10-25T10:00:00",
  "input_rev": 3,                     // 每次保存条件 +1
  "plan_input_rev": 3,                // 当前 plan.json 是用哪个 input_rev 算的；无计划为 null
  "run": { "state": "IDLE", "started_at": null, "finished_at": null, "seconds": null, "error": null }
                                      // state：IDLE / RUNNING / FAILED；error 一句话
}
```

## 4. 接口（前缀 `/api`，JSON）

| 方法 + 路径 | 请求 | 返回 |
| --- | --- | --- |
| `GET /api/scenarios` | — | `[ScenarioSummary]`，按 `created_at` 倒序 |
| `POST /api/scenarios` | `{ "from_id", "name" }` | 新方案的 `ScenarioSummary`；复制 `input.json`，不复制计划 |
| `GET /api/scenarios/{id}/conditions` | — | `ConditionsView` |
| `PUT /api/scenarios/{id}/conditions` | `{ "conditions": [...] }` | `ScenarioSummary`；整表替换 `input.json` 的 `conditions`，`input_rev` +1 |
| `POST /api/scenarios/{id}/run` | — | `ScenarioSummary`（`state` = `RUNNING`）；后台运行，见 §5 |
| `GET /api/scenarios/{id}/annual` | — | `AnnualView`；无计划返回 404 |
| `GET /api/scenarios/{id}/monthly?month=YYYY-MM` | — | `MonthlyView`；无计划或月份不在计划期返回 404 |

错误：方案不存在 404；该方案或任何方案正在运行时再点运行、或运行中改条件 409；返回体 `{ "detail": "<中文一句话>" }`。

```jsonc
// ScenarioSummary
{
  "id", "name", "created_at",
  "state": "NO_PLAN",                 // 下表五选一，前端顶栏按它显示
  "run": { ...meta.run },
  "plan_status": "FEASIBLE",          // plan.json 的 status；无计划 null
  "verdict": "ACCEPT",                // verdict.json 的 verdict；无判定 null
  "hard_error_count": 0,
  "objective": { "L1a": 0, ... }      // 取 verdict.json 的 objective；无判定 null
}
```

| state | 条件 | 顶栏显示 |
| --- | --- | --- |
| `RUNNING` | `run.state` = RUNNING | 运行中（已用秒数，前端每 3 秒刷新列表） |
| `FAILED` | `run.state` = FAILED | 运行失败 + `run.error` |
| `NO_PLAN` | 无 `plan.json` | 尚未运行 |
| `STALE` | `plan_input_rev` ≠ `input_rev` | 条件已改，计划未重算（仍显示旧计划） |
| `READY` | 其余 | 显示 `verdict` 与 `plan_status` |

## 5. 运行

1. 置 `run.state` = RUNNING，记 `started_at`。同一时刻全局只允许一个运行。
2. 子进程 `python -m engine <input.json> <plan.next.json>`，cwd = 仓库根，输出追加到 `run.log`。
3. 退出码 0 且 `plan.next.json` 的 `status` 为 `FEASIBLE` 或 `UNKNOWN`：再跑 `python -m judge <input.json> <plan.next.json> <verdict.next.json>`。
4. 成功（生成器退出码 0，且需要判定时判定器退出码 0）：`plan.next.json` → `plan.json`，`verdict.next.json` → `verdict.json`（没跑判定则删除旧 `verdict.json`），`plan_input_rev` = 运行开始时的 `input_rev`，`run.state` = IDLE。
   生成器状态为 `INPUT_INVALID` / `PROVEN_INFEASIBLE` / `EXECUTION_ERROR` 也算“成功写出”，照样替换，界面显示该状态和 findings。
4a. 热启动与安全网（rev 10）：已有 `plan.json` 且其 status 为 FEASIBLE/UNKNOWN、days 非空时，第 2 步加 `--warm-start <plan.json>`，`meta.run.warm_start` = true。新计划判定完后，再用新 input 判定旧 `plan.json`（→ `verdict.prev.json`）：旧计划 ACCEPT，且新计划不是 ACCEPT 或旧计划 objective 按字典序（L1a…L6）严格更好时，保留旧 `plan.json`、`verdict.json` 换成旧计划的新判定，`meta.run.kept_previous` = true，页面在运行状态旁显示灰字“新结果没有更好，沿用上一版计划（已按新条件重新判定）”。代价：同样的条件可能因上一版不同而得到不同计划。
5. 任何一步退出码非 0：`run.state` = FAILED，`error` = “生成器异常退出”或“判定器异常退出”，旧 `plan.json` / `verdict.json` 不动。
6. 后端启动时把残留的 RUNNING 改成 FAILED（`error` = “后端重启，运行中断”）。

## 6. 显示口径（后端计算）

记号：月份 mo 取计划期内的自然月；“累计”一律从 horizon.start 起算；车型集合 = `demand.PR` 的键；
`ratio` = `rules.monthly_band_ratio`；节点合计 = 该节点各车型之和。阶段以 `verdict.phases` 为准，无判定时用 plan 的 `phase`。

日的**主模式** `mode_summary`：当天五个车间里 `factory.modes` 小时数最大的模式；全部 OFF 则为 `OFF`。
日的**条件** `conditions`：覆盖当天的条件 `[ { "id", "type" } ]`；有 `date` 的按单日，有 `start`/`end` 的按区间，`PRE_STOP_TARGET` 按 `pre_stop_date`。

```jsonc
// AnnualView
{
  "scenario": ScenarioSummary,
  "horizon": { "start", "end" },
  "totals": {
    "annual_pr": 0, "annual_fok": 0, "annual_gap": 0,     // Σ车型；gap = Σ车型 max(0, PR 全年 − FOK 全年)
    "production_days": 0,                                 // 任一车间非 OFF 的天数
    "saturday_days": 0,                                   // 非 is_working_capable 但有车间非 OFF 的天数
    "overtime_days": 0                                    // 有车间模式 ∉ {OFF, default_mode} 的天数
  },
  "models": [ { "model": "A", "annual_pr", "annual_fok", "annual_gap",
                "months": { "2026-03": { "pr", "fok", "cum_gap", "band_short" } } } ],
       // cum_gap = max(0, 累计 PR − 累计 FOK)，到月末；band_short = max(0, 累计 PR − ratio × PR(m,mo) − 累计 FOK)
  "months": [ { "month": "2026-03",
                "pr", "fok", "ws",                        // 当月合计（ws = 当月 WS_daily 之和）
                "cum_gap", "band_short",                  // Σ车型
                "fin_eom",                                // 月末日成品库存合计（fin）
                "wip_eom": { "BS1": 0, ..., "AS_FIN": 0 },// 月末日 eod 节点合计
                "weld_days": { "BS1": 0, "BS2": 0 },      // 当月该线 in 或 out > 0 的天数
                "saturday_days", "overtime_days",         // 口径同 totals，限当月
                "phases": ["CHANGEOVER"] } ],              // 当月出现过的非 NORMAL 阶段（拆开 +，按 IO_CONTRACT §6 顺序）
  "days": [ { "date", "is_working_capable", "fok",        // fok 合计
              "mode_summary", "phase", "conditions" } ],
  "stop_list": [ ... ],                                   // plan.json 原样
  "findings": [ ... ],                                    // plan.json 原样
  "hard_errors": [ ... ]                                  // verdict.json 原样，最多前 50 条；无判定 []
}
```

```jsonc
// MonthlyView
{
  "scenario": ScenarioSummary,
  "month": "2026-03",
  "models": ["A", "B"],
  "targets": { "BS1": 69, ... },                          // input.wip_targets 原样（基础目标，不含 WIP_TARGET 条件）
  "days": [ {
    "date", "is_working_capable", "phase", "conditions",
    "mode_summary", "hours_max",                         // rev 3：主模式（口径同年度视图）、五个车间小时数最大值
    "workshops": {                                        // BS1、BS2、PS、AS_MAIN、AS_FIN
      "BS1": { "mode", "hours", "jph",                    // jph = factory.workshops 原样
               "bod", "in", "out", "eod",                 // 合计
               "in_cum", "out_cum",                       // 合计，累计
               "by_model": { "A": { "bod", "in", "out", "eod" } } } },
    "buffers": {                                          // WBS、PBS
      "WBS": { "bod", "in", "out", "eod",                 // in = 上游车间 out 之和；out = 下游车间 in
               "by_model": { "A": { "bod", "in", "out", "eod" } } } },
    "fin": { "fok", "fok_cum", "ws", "ws_cum", "eod", "bl",   // 合计；eod = fin，bl = 累计欠交
             "by_model": { "A": { "fok", "ws", "eod", "bl" } } }
  } ]
}
```

`by_model` 里每个车型都列出（0 也写），`models` 顺序 = 车型名排序。

## 7. 前端显示要求

- **年度总览**：沿用旧版布局。左侧年度日历按 `mode_summary` 着色（OFF / 默认模式 / 其他加班模式三档，非可生产日（`is_working_capable` = false）但当天有生产的日子另加“加”角标；普通周六不加标记）；rev 4：阶段 ≠ NORMAL 的日子在格子里加阶段短标签（停线、清线、复线、停前、换型、首启、退出、排空，与月度 Filling 列头同色同字），多个阶段时按 IO_CONTRACT §6 顺序取前两个；图例补上这些标签；
  点日期弹抽屉：阶段（中文名，见下表）、当天条件、当天所在的停线窗口（来自 `stop_list`）、“打开当月 Filling”。
  右侧摘要用 `totals`；下方按月趋势图（PR / FOK / WS）、月末成品库存柱图、月度事实表（`months`）、车型年度表（`models`，可展开 12 个月）。
  顶部：判定结论（ACCEPT 绿 / REJECT 红 + 硬错误数，可展开 `hard_errors` 前 50 条）、目标八级数值表、`findings` 列表。
  旧版的“锁定状态”“计划健康度”“产能余量”“WIP 偏差”不显示。
- **月度 Filling**（rev 3：按旧版 V6.1.4 的 Filling 样式，求“一屏能读”）：月份可前后切换；行 = 指标，列 = 日期，右侧固定一列“月度合计”（只对 IN / OUT / FOK / 交付类行求和，其余行显示 —；这是界面唯一允许的计算：把当月各日显示值相加）。
  - **左侧两列标签**：第一列“区段”（同组合并单元格），第二列“指标”。
  - **列头**：日期（MM/DD）+ 星期；阶段 ≠ NORMAL 时加阶段中文短标签（停线、清线、复线、换型、停前、首启、退出、排空），当天有条件加条件标签（类型中文名，超过两个显示 +N，悬停看全部）。阶段和条件不再占行。
  - **区段与行**（默认 33 行左右）：
    | 区段 | 指标行 |
    | --- | --- |
    | 生产参数 | 模式（`mode_summary` 中文名）、小时（`hours_max`） |
    | 焊装 Body Shop | BS1 投入、BS1 投入累计、BS1 产出、BS1 产出累计、BS2 同四行 |
    | WBS 缓冲区 | 日初、投入、产出、日末（目标 N） |
    | 涂装 Paint Shop | 日初、投入、产出、日末（目标 N） |
    | PBS 缓冲区 | 日初、投入、产出、日末（目标 N） |
    | 总装主线 | 日初、投入、产出、日末（目标 N） |
    | 总装完成线 | 日初、投入、FOK（产出）、日末（目标 N） |
    | 在制与成品 | BS1 日末（目标 N）、BS2 日末（目标 N）、交付（WS）、成品库存、欠交 |
  - **按车型子行**：WBS 至总装完成线各组的投入、产出、日末行可展开车型子行，默认收起。
  - **分组显示条**（表格上方）：每个区段一个开关按钮，加“展开全部”“收起全部”，同旧版。
  - **底色**：非可生产日列灰底；阶段含 STOP 的列淡橙底；含 BS_CLEAR 的列淡蓝底；含 REFILL 的列淡绿底。
  - 不再显示每个车间各自的模式 / 小时 / JPH 行，不提供单元格编辑。
- **排产条件**：表格列出 `conditions`（编号、类型中文名、日期、车间 / 节点、数值、备注），新增 / 编辑用抽屉表单，字段按 IO_CONTRACT §2.1 表随类型切换，
  下拉选项来自 `ConditionsView`；删除需确认；“保存”调 PUT，保存后提示“已保存，点运行重算”。
  运行后生成器若返回 `INPUT_INVALID`，在本页顶部显示 `findings`。

```jsonc
// ConditionsView
{
  "scenario": ScenarioSummary,
  "conditions": [ ... ],                                   // input.json 原样
  "options": {
    "horizon": { "start", "end" },
    "workshops": ["BS1", "BS2", "PS", "AS_MAIN", "AS_FIN"],
    "nodes": ["BS1", "BS2", "WBS", "PS", "PBS", "AS_MAIN", "AS_FIN"],
    "auth_modes": ["SINGLE_8P2", "DOUBLE_SHIFT"]           // factory.modes 去掉 OFF 和 default_mode
  }
}
```

新增条件时的类型选择（rev 6，2026-10-26 Swann 确认）：新增抽屉第一步不再用下拉框，而是把 7 种类型平铺成 7 张可点的卡片（两列或三列），每张写类型中文名和一句用途；点一张卡片进入该类型的表单，表单顶部显示所选类型和“换一种”链接回到卡片。编辑已有条件时直接进表单，不显示卡片。用途文字：
- 周六授权：允许本来不上班的日子开线（默认全线，可只选部分车间）
- 加班模式授权：某些车间在一段时间内可以用加班班制（如 8+2、双班）
- 计划停线：某些车间在一段时间内必须停
- 产能损失：检修等原因，某些车间每天最多只能开几小时
- 人工目标在制：某段时间把某个节点的目标在制改成指定值
- 人工停前目标：指定某次停线前一天涂装降到多少
- 指定产量：某车间某天必须产出指定台数

条件类型中文名：SATURDAY_AUTH 周六授权、MODE_AUTH 加班模式授权、SHUTDOWN 计划停线、CAPACITY_LOSS 产能损失、WIP_TARGET 人工目标在制、PRE_STOP_TARGET 人工停前目标、FIXED_OUTPUT 指定产量。

阶段中文名：NORMAL 正常、PS_PRE_STOP 停前降库、STOP 停线、BS_CLEAR 焊装清线、REFILL 复线补库、FIRST_START 首次启动、CHANGEOVER 换型、MODEL_EXIT 车型退出、INITIAL_DRAIN 期初排空。

模式中文名：OFF 停、SINGLE_8H 单班 8h、SINGLE_8P2 单班 8+2h、DOUBLE_SHIFT 双班；不在此表的模式显示原名。

## 8. 新建排产与正式版本（rev 5，2026-10-26，Swann 选“轻量版”）

### 8.1 新建排产

页面 `/new-plan`（左侧导航“新建排产”，放在第一位）。一页表单，自上而下：

| 项 | 必填 | 说明 |
| --- | --- | --- |
| 方案名称 | 是 | |
| 工厂设置来自 | 是 | 下拉选一个已有方案；新方案的 `factory`、`wip_targets`、`wbs_hi`、`rules` 原样复制自它（本阶段没有基础数据编辑页） |
| 计划期 | 是 | 起止日期，默认所选年份 01-01 至 12-31 |
| 销售计划 | 是 | 上传 xlsx，格式见下表 |
| 期初在制 | 否 | 上传 xlsx；不传则复制“工厂设置来自”那个方案的 `initial` |
| 生产行事历 | 否 | 上传 xlsx；不传则按“工厂设置来自”方案的 `calendar` 中同月同日的 `is_working_capable`，找不到的日子按周一至周五可生产、周六日不可生产 |

每个上传项旁有“下载模板”按钮。表单下方“预检”按钮：后端解析三份文件，返回汇总（每车型全年 PR、WS 合计、期初在制合计、可生产日数）和错误清单；无错误时“创建方案”按钮可用，创建后选中新方案并跳到排产条件页（`NO_PLAN`，见 §8.3；rev 11 起不再直接跳年度总览）。

**Excel 格式**（只认第一个工作表，第一行为表头，表头按名称找列，列序不限；空行跳过）：

| 文件 | 表头 | 规则 |
| --- | --- | --- |
| 销售计划 | 月份、车型类别、PR、WS | 月份 `YYYY-MM`（单元格是日期也接受，取年月）；车型类别必须在工厂设置的 `models` 里；PR、WS 为 ≥ 0 整数，空 = 0。计划期内每月每车型都要有 PR，缺的月份按 0 补。 |
| 期初在制 | 输入项、车型类别、数量 | 输入项取值：成品库存、BS在制、WBS缓冲、PS在制、PBS缓冲、AS主线在制、AS终线在制；分别对应 `initial.fin`、该车型所绑焊装线（`models[m].line`）、WBS、PS、PBS、AS_MAIN、AS_FIN。数量 ≥ 0 整数，同一格重复出现报错。 |
| 生产行事历 | 日期、是否具备生产能力、原因 | 日期 `YYYY-MM-DD`；是否具备生产能力填 是/否（也接受 1/0、true/false、Y/N）；只覆盖表里列出的日子，其余按上表默认。原因只显示，不进输入。 |

转换口径：
- `demand.PR[m][mo]` = 销售计划 PR。
- `demand.WS_daily[m]`：每月 WS 落在该月计划期内**最后一个可生产日**（`is_working_capable` = true）；该月没有可生产日则落在该月计划期内最后一天。
- `calendar` 覆盖计划期每一天，另外追加计划期结束后 14 天（按同一默认规则），供期末停线长度推算。
- `conditions` 为空。

预检错误（任一条即不能创建，逐条中文列出所在文件、行号、内容）：缺表头、月份格式错或不在计划期、车型类别不存在、数量非整数或为负、同月同车型重复、期初同一输入项同车型重复、日期格式错或不在计划期（行事历允许计划期后 14 天内的日子）。

接口：

| 方法 + 路径 | 请求 | 返回 |
| --- | --- | --- |
| `GET /api/templates/{kind}` | kind = `sales` / `initial` / `calendar`；`?base_id=` 方案 id、`?year=` | xlsx 文件下载。销售模板预填 12 个月 × 该方案车型、PR/WS 空；期初模板预填 7 个输入项 × 车型，数量填该方案当前期初值；行事历模板预填该年每一天和默认可生产标记 |
| `POST /api/new-plan/preview` | multipart：`base_id`、`start`、`end`、`sales`（文件）、`initial`（可选文件）、`calendar`（可选文件） | `{ "ok": bool, "errors": [ { "file", "row", "message" } ], "summary": { "models": { "A": { "pr", "ws", "initial_wip" } }, "working_days": n, "fin0": { ... } } }` |
| `POST /api/new-plan` | 同上 + `name` | 预检通过返回新方案 `ScenarioSummary`（`input_rev` = 1，无计划）；不通过返回 422 `{ "detail": "预检未通过", "errors": [...] }` |

### 8.3 首次排产的“排产条件”一步（rev 11，2026-10-26，Swann 选 A）

流程：导入 → 检查 → **排产条件** → 运行 → 补缺口 → 定稿。排产条件这一步可以跳过。

- 两种导入方式（一键导入、分文件导入）“创建方案”成功后，都跳到 `/planning-conditions`（新方案已选中）。
- 排产条件页在方案状态为 `NO_PLAN`（从没运行过）且不是正式版本时，页顶显示步骤卡“新建排产 · 第 3 步：排产条件”：
  - 步骤条：导入 ✓ → 检查 ✓ → **排产条件** → 运行 → 补缺口 → 定稿。
  - 说明：“已从导入文件带入 N 条条件。需要周六上班、加班、计划停线、产能损失等，点‘新增条件’添加；不需要可以直接运行。”N = 已保存的条件数，N 为 0 时写“导入文件里没有条件”。
  - 主按钮：有未保存修改时为“保存并运行”（先保存，成功后运行）；没有未保存修改时为“运行”。
  - 次按钮：“跳过，直接运行”，只在有未保存修改时出现；先确认“未保存的修改会丢弃”，再按已保存的条件运行。
  - 运行开始后跳到年度总览。
- 状态不是 `NO_PLAN` 时不显示步骤卡，页面和现在一样。

### 8.2 正式版本（定稿）

- 顶栏在 `state` = READY 且 `verdict` = ACCEPT 时显示“定为正式版”按钮；点后填备注（可空），确认后调用 `POST /api/scenarios/{id}/finalize { "note" }`。
- 后端把该方案目录整体复制为新方案 `f-YYYYMMDD-HHMMSS`，`meta.json` 加 `"formal": { "source_id", "confirmed_at", "note" }`，名称 = 原名称 + “（正式 YYYY-MM-DD）”。原方案不变，可继续改。
- 正式方案只读：对它 PUT conditions、run、finalize 一律 409“正式版本只读”；仍可“另存为新方案”（复制出的新方案不是正式版）。
- `ScenarioSummary` 增加 `"formal": null | { "source_id", "confirmed_at", "note" }`。
- 页面 `/formal`（左侧导航“正式版本”）：表格列出所有正式方案，按 `confirmed_at` 倒序：名称、定稿时间、备注、来源方案、判定、L1a、L1c、L2、L3a、L5；点一行即选中该方案并跳到年度总览。
- 顶栏方案下拉里正式方案带“正式”标签；选中正式方案时“运行”按钮隐藏，排产条件页只读（不显示新增 / 编辑 / 删除 / 保存）。
- 本阶段不做正式版之间的比较、作废、滚动。

## 9. 缺口与建议（rev 7，2026-10-26，Swann 选方案 B）

目的：计划欠产时，告诉排产员“下一步该加哪些周六或加班”。做法是先把候选周六和加班一次性加成“候选授权”，运行一次，由生成器挑用量最少的；跑完显示实际用到哪些，一键删掉没用到的。引擎不改：周六授权、模式授权本来就由排产员给出，生成器在 L1 缺口最小的前提下按 L3 尽量少用（先平日加班、后周六，CORE_MODEL §6 已确认）。

### 9.1 缺口口径

取年度总览同一口径（§6 `annual` 的 `models[].months`）：某月任一车型 `band_short` > 0（低于月度带下限，计入 L1c），或计划期最后一个月任一车型 `cum_gap` > 0（全期欠产，L1a），即为**缺口月**（rev 9）。月末累计缺口在月度带以内是 C12 允许的，不算缺口，`gaps` 不列。没有计划、或 `state` ≠ READY（含 STALE）时不算缺口，面板提示“先运行一次，才能看缺口”。

### 9.2 候选授权池（后端按规则生成，不求解）

- 窗口：每个缺口月 M 取 M 的前一个月和 M 本月，并起来去重，截到计划期内。
- 候选周六：窗口内每个周六 d，同时满足——日历不可生产（`is_working_capable` = false）；前一天（周五）日历可生产（排除长假里的周六）；d 不落在当前计划 `stop_list` 的任一窗口内，也不落在任何 `SHUTDOWN` 条件范围内；已有覆盖 d 的非候选 `SATURDAY_AUTH` 时跳过。每个周六一条：`{ "id": "CAND-SAT-YYYYMMDD", "type": "SATURDAY_AUTH", "date": d, "reason": "候选（缺口建议）" }`，不写 workshops（= 五个车间）。
- 候选加班：模式按工时从低到高逐档升级（rev 9）。`meta.suggest_tried` 记录每次**采纳**过的 `{ "mode", "months": [...] }`（撤销不记）。本次取 `factory.modes` 中工时高于默认模式的各档里，工时最小、且本次窗口月份**不全在**同档已试记录里的那一档（现输入依次为 SINGLE_8P2 → SINGLE_8P3 → DOUBLE_SHIFT）；只为不在该档已试记录里的窗口月份生成。没有这样的档、也没有新的候选周六时，不能生成（stage = EXHAUSTED）。窗口内每个月一条：`{ "id": "CAND-OT-YYYYMM", "type": "MODE_AUTH", "mode", "start": 该月计划期内首日, "end": 末日, "workshops": 五个车间, "reason": "候选（缺口建议）" }`。
- id 以 `CAND-` 开头的条件就是候选；条件表里这些行带“候选”标签。
- 生成时在 `meta.json` 记 `"suggest": { "baseline": { "L1a", "L1b", "L1c", "L3a", "L3b" }, "created_rev": 生成后的 input_rev }`，baseline 取生成前 verdict 的 objective。

### 9.3 使用情况（跑完后）

只在条件里有候选、且 `state` = READY 时计算：
- 候选周六“用到”= 计划当天任一车间 mode ≠ OFF。
- 候选加班“用到的日子”= 范围内、`workshops` 中任一车间当天 mode = 该候选的 mode；同时记下每天用到的车间。
- 缺口对比：baseline 与当前 verdict 的 L1a、L1c、L3a、L3b。

### 9.4 采纳与撤销

- **采纳**（只在 9.3 能计算时可用）：删掉没用到的候选；用到的候选周六改 id 为 `SAT-YYYYMMDD`，reason 改为“补缺口（建议采纳）”；用到的候选加班按“连续用到的日子”切成段（五个车间全天 OFF 的日子跳过、不算断开；某天有车间开工却没用这个模式就断开），每段一条 `MODE_AUTH`：id `OT-<起始YYYYMMDD>`，start/end = 段首尾，workshops = 段内用到过的车间并集，mode 不变，reason 同上。id 冲突时末尾加 `-2`、`-3`。整表保存，`input_rev` +1，删除 `meta.suggest`，并把本次候选加班的 `{ mode, months }` 追加到 `meta.suggest_tried`。现有计划只用到了保留下来的授权，对新条件依然成立：采纳后**不重跑生成器**，只用新的 input 对现有 `plan.json` 重跑一次判定器（几秒）；判定 ACCEPT 则写回 `verdict.json`、`plan_input_rev` = 新 `input_rev`（状态 READY，计划不变）；判定不是 ACCEPT 则撤回这次采纳（条件和 meta 恢复原样），返回 409“采纳后判定未通过：<首条错误>”。
- **撤销**：删掉全部 `CAND-` 条件，删除 `meta.suggest`，`input_rev` +1。
- 条件里已有候选时不能再生成（409“已有候选授权，先采纳或撤销”）。正式方案三个写接口一律 409。运行中 409。

### 9.5 接口

| 方法 + 路径 | 请求 | 返回 |
| --- | --- | --- |
| `GET /api/scenarios/{id}/suggest` | — | `SuggestView` |
| `POST /api/scenarios/{id}/suggest/candidates` | — | `SuggestView`；无缺口或无可用候选时 409，detail 说明原因 |
| `POST /api/scenarios/{id}/suggest/apply` | — | `SuggestView` |
| `POST /api/scenarios/{id}/suggest/discard` | — | `SuggestView` |

```jsonc
// SuggestView
{
  "stage": "NEED_RUN",        // NEED_RUN（无计划或非 READY 且无候选）/ NO_GAP / HAS_GAP / EXHAUSTED（有缺口但按 9.2 已没有新候选可加）/ CANDIDATES_PENDING（有候选、还没用当前条件跑过）/ CANDIDATES_DONE（有候选、已跑完）
  "next_mode": "SINGLE_8P2",  // HAS_GAP 时本次将用的加班档；其余 stage 为 null
  "gaps": [ { "month": "2026-03", "model": "A", "cum_gap": 422, "band_short": 239 } ],   // 当前计划的缺口月（按月、车型），stage 为 NEED_RUN / CANDIDATES_PENDING 时为 []
  "candidates": { "saturdays": ["2026-02-07", ...], "overtime": [ { "id", "mode", "start", "end" } ] },  // 无候选时两个空列表
  "usage": null | {           // 仅 CANDIDATES_DONE
    "saturdays_used": ["2026-03-07"], "saturdays_unused": ["2026-02-07", ...],
    "overtime_used": [ { "id": "CAND-OT-202603", "mode": "SINGLE_8P2", "days": [ { "date": "2026-03-12", "workshops": ["BS1","PS"] } ] } ],
    "overtime_unused_ids": ["CAND-OT-202602"]
  },
  "baseline": null | { "L1a", "L1b", "L1c", "L3a", "L3b" },
  "current": null | { "L1a", "L1b", "L1c", "L3a", "L3b" }    // 当前 verdict；无判定为 null
}
```

### 9.6 页面

排产条件页顶部，条件表上方一张卡片“缺口与建议”，按 stage 显示：
- NEED_RUN：一句“先运行一次，才能看缺口”。
- NO_GAP：绿色一句“当前条件下没有欠产，不需要加周六或加班”。
- HAS_GAP：缺口表（月份、车型、月末累计缺口、低于月度带下限）+ 主按钮“生成候选授权（周六 + <next_mode 中文名>加班）”；若已有采纳记录，按钮上方灰字“上一轮已采纳，这次升一档加班再试”+ 一句说明“会把欠产月及其前一个月的可用周六、加班一次性加为候选，运行后生成器只挑最少的用”。
- CANDIDATES_PENDING：“已加 N 个候选周六、M 段候选加班，请点顶栏‘运行’”+ 次按钮“撤销候选”。
- CANDIDATES_DONE：上排对比“欠产 82 → 0 台，月度带下限缺口 522 → 0 台”（baseline → current 的 L1a、L1c）；下排两列：用到的周六（日期标签）、用到的加班（每段：日期范围、天数、车间中文名）；灰字“没用到：周六 N 个、加班 M 段”。主按钮“采纳：删掉没用到的候选”，次按钮“全部撤销”。若 current.L1a > 0，再加黄字“候选用满仍欠产 X 台，需要更高的加班模式或更早的周六，请手工补条件”。
- EXHAUSTED：缺口表 + 黄字“欠产月附近可用的周六和各档加班都已让生成器挑过，剩余缺口要人工处理（例如调整销售计划、停线安排，或手工加更早的授权）”，无生成按钮。
- 采纳成功后，卡片顶部绿条“已采纳：只保留用到的授权，计划不变，判定已按新条件更新”一直显示到下一次生成 / 撤销 / 运行或切换方案。用到的加班里车间名按 焊装1、焊装2、涂装、总装主线、总装完成线 的顺序列。
- 采纳、撤销、生成后刷新条件表和顶栏状态。条件表中 `CAND-` 行显示“候选”标签；CANDIDATES_DONE 时再标“用到 / 没用到”。正式方案只显示信息，不显示按钮。

## 10. 排产向导（rev 12，2026-10-29，Swann 选“向导式流程”）

背景：同事试用反馈“按钮太小、流程不清晰”。导入、预检、创建、运行、补缺口、定稿分散在新建排产页、顶栏和排产条件页，用户不知道下一步点哪里。本节把主流程收进一个向导页；其余页面保留，作为“查看明细”的工具页。后端接口不变，向导只调用 §4、§8、§9 已有接口。

### 10.1 导航与路由

- 新页面 `/wizard`，左侧导航第一项“排产向导”，默认路由 `/` 和未知路由都进 `/wizard`。
- 导航“新建排产”去掉（`/new-plan` 路由保留，向导第 1 步复用它的导入组件）。
- “月度 Filling”改名“月度明细”（导航和页面标题），路由不变。
- 导航顺序：排产向导、年度总览、月度明细、排产条件、正式版本。

### 10.2 步骤与当前步

步骤条固定六步，与 §8.3 一致：**导入 → 检查 → 排产条件 → 运行 → 补缺口 → 定稿**。“检查”在第 1 步上传后自动完成，步骤条上仍单列，打勾表示预检通过。

当前步由所选方案的状态决定（界面不另存状态）：

| 方案状态 | 当前步 |
| --- | --- |
| 没有选中方案，或用户点了“新建一份排产” | 1 导入 |
| `NO_PLAN`，非正式 | 3 排产条件 |
| `run.state` = RUNNING | 4 运行 |
| `FAILED`，或 READY 但 `no_plan` = true（没排出计划） | 4 运行（显示失败原因） |
| `STALE` | 3 排产条件（提示“条件已改，需要重新运行”） |
| READY、有计划，`suggest.stage` ∈ HAS_GAP / CANDIDATES_PENDING / CANDIDATES_DONE / EXHAUSTED | 5 补缺口 |
| READY、有计划、`suggest.stage` = NO_GAP，非正式 | 6 定稿 |
| 正式方案 | 全部完成（显示“已定为正式版”和只读提示） |

用户可以点步骤条上已完成的步骤回看；跳回第 3 步改条件后，按状态表自然回到相应步骤。

### 10.3 每一步的内容

每一步一张卡片：一句话说明这一步做什么，一个**主按钮**（大号，见 10.4），最多两个次按钮。不显示 L1a 等级别代号。

1. **导入**：年份 → “下载模板”（可选预填来源方案）→ 拖放区上传填好的 xlsx。**选好文件即自动预检**，不再单独点“预检”。预检通过：显示汇总（每车型全年需求、交付、期初在制、可生产天数、带入的条件数），主按钮“创建方案，下一步”；不通过：逐条列出错误（表名、行号、说明），主按钮变为“重新选择文件”。“分文件导入”（三份老格式文件）收进页面底部折叠区“其他导入方式”，默认收起。
2. **检查**：并入第 1 步，不单独成卡片。
3. **排产条件**：显示已带入的条件数和条件清单（只读简表：类型中文名、日期、车间、数值），次按钮“去排产条件页修改”（跳 `/planning-conditions`，改完回向导）；主按钮“开始排产”。STALE 时上方黄条“条件已改，需要重新运行”。
4. **运行**：运行中显示大号计时“已用 N 秒”和一句“一般 1–3 分钟，期间可以离开本页”，不可点主按钮；运行结束自动进入下一步。失败或没排出计划：红色结论“没有排出计划”+ `findings` 逐条列出，主按钮“回到排产条件”，次按钮“重新运行”。
5. **补缺口**：顶部**结论卡**（见 10.5），下方复用 §9.6 的“缺口与建议”卡片内容和按钮（生成候选、运行、采纳、撤销）。EXHAUSTED 时次按钮“仍然定为正式版”（进入第 6 步）。
6. **定稿**：结论卡 + 备注输入框 + 主按钮“定为正式版”；次按钮“查看年度总览”“查看月度明细”。定稿成功后选中新的正式方案，显示“已定为正式版”。

第 4 步之后的每一步都在结论卡下放两个链接按钮“查看年度总览”“查看月度明细”。

### 10.4 尺寸与文字

- 全局字号 15px（主题 `fontSize`），控件高度 40px（`controlHeight`）。
- 向导里的主按钮：高 48px、字号 17px、宽度不小于 200px；每步只有一个主按钮。
- 顶栏按钮同步放大到 40px 高，“运行”“定为正式版”保留在顶栏，供工具页使用。
- 页面上不出现开发用语：L1a 等级别代号只在年度总览的目标表里作为灰色小字放在中文名后；“Filling”“FEASIBLE”“ACCEPT”这类英文不直接显示（用 §7 已有的中文名）。

### 10.5 结论卡

一张卡片，大字一句结论 + 一行关键数字，全部取自 `ScenarioSummary.objective` 和 `verdict`：
- 有计划且判定接受：绿色“排出来了”；关键数字：全年缺口 L1a 台、月度带缺口 L1c 台、换型与清线 L2 次、周六 L3a 车间·日、加班 L3b 车间·日、用时 `solver.seconds` 秒。
- 判定拒绝：红色“计划没通过校验，硬错误 N 条”，链接到年度总览的硬错误明细。
- 没排出计划：红色“没有排出计划”+ `findings` 第一条。

### 10.7 方案下拉框（2026-10-29，Swann 确认）

- 顶栏和向导顶部“当前方案”都用同一个下拉框：显示完整名称（宽 380px 起，向导里 460px），名称后跟状态标签：正式版（蓝）、排产中、未运行、没排出（红）、条件已改（橙）、未通过校验（红）、已排出（绿）。按创建时间倒序，可输入名称搜索。
- 顶栏不再单独显示“接受 · 可行”这类状态标签，只在运行中显示计时、运行失败时显示原因。
- 发布包只带一个示例方案，名称为“示例方案（可作模板预填来源）”。
- 页面本身（index.html）不缓存，换新版后刷新即可看到新界面。

### 10.6 不做

不改后端接口，不改年度总览、月度明细、排产条件、正式版本各页的内容（只改名和字号）；不做多方案比较。
