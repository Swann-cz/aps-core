export type V6BusinessMessage = {
  title: string
  description: string
  suggestion: string
}

const MESSAGES: Record<string, V6BusinessMessage> = {
  ACTUAL_OR_LOCK_CONFLICT: {
    title: '排产调整触及不可修改边界',
    description: '部分清线或补线窗口位于排产周期起点、终点，或与 Actual/锁定范围冲突，系统无法自动调整。',
    suggestion: '调整排产周期或锁定范围，或修改相关停线条件后重新排产。',
  },
  MONTH_CAPACITY_SHORTFALL: {
    title: '月度产能不足',
    description: '至少一个月份的生产需求超过当前日历、班制和 JPH 允许的最大产能。',
    suggestion: '增加工作日或工作模式、调整产能条件，或重新评估需求。',
  },
  TIMING_INVENTORY_SHORTFALL: {
    title: '销售时点库存不足',
    description: '当前生产节奏和期初库存无法在要求月份满足销售需求。',
    suggestion: '提前安排产量、调整销售节奏或补充期初库存。',
  },
  ANNUAL_CLOSURE_SHORTFALL: {
    title: '年度产量无法闭合',
    description: '年度计划产量低于年度 PR，当前候选无法完成全年需求。',
    suggestion: '增加可用产能、调整条件或重新评估年度需求。',
  },
  ROLLING_UNAVOIDABLE_ANNUAL_GAP: {
    title: 'Rolling 不可逆年度差额已由证书确认',
    description: '该车型的年度 PR、最终 FOK 与差额来自后端不可逆年度差额证书及其来源边界，可能表现为超产或欠产，不是前端推算结果。',
    suggestion: '查看证书中的来源类型、日期范围和计算边界；该警告不等于普通的可忽略错误。',
  },
  FLOW_CONSERVATION_VIOLATION: {
    title: '车间流量不守恒',
    description: '候选中的 IN、OUT 或 WIP 变化不满足物料流守恒。',
    suggestion: '检查期初 WIP、固定产量及清线/补线条件后重新排产。',
  },
  WIP_LIMIT_VIOLATION: {
    title: '缓冲区 WIP 超过物理上限',
    description: '指定日期的缓冲区全车型 WIP 合计超过基础数据配置的物理上限。',
    suggestion: '检查期初 WIP、缓冲区物理上限和上游进车节奏后重新排产。',
  },
  CLEARING_TARGET_UNREACHABLE: {
    title: '停线前清线目标不可达',
    description: '在可修改日期和现有产能范围内，无法在停线前达到要求的清线目标。',
    suggestion: '扩大可调整日期、减少锁定范围或调整停线安排。',
  },
  REFILL_TARGET_UNREACHABLE: {
    title: '复线补线目标不可达',
    description: '在假后可用日期和现有产能范围内，无法恢复要求的 WIP 水位。',
    suggestion: '扩大复线窗口、授权合适工作模式或调整补线目标。',
  },
  TERMINAL_TYPECLASS_WIP_NOT_DRAINED: {
    title: '停产车型仍有在制库存',
    description: '该车型在最后生产月份结束后，焊装、WBS、涂装、PBS 或总装仍有库存或继续发生流量。',
    suggestion: '查看问题中的截止日和各节点残量，释放必要的可排产日期或调整锁定事实后重新排产。该错误不能确认忽略。',
  },
  HOLIDAY_WINDOW_CHANGED: {
    title: '重排后识别到新的停线窗口',
    description: '局部修复改变了零流量窗口，最终窗口与首次扫描结果不同。',
    suggestion: '查看窗口证据后再次重排，或填写原因后保存当前候选。',
  },
  HARD_VALIDATION_FAILED: {
    title: '候选未通过硬校验',
    description: '当前候选存在不能忽略的物理或业务约束错误。',
    suggestion: '查看本页具体问题，增加或调整排产条件后重新排产。',
  },
  HARD_ERRORS: {
    title: '候选仍存在硬错误',
    description: '一个或多个硬错误尚未解决，因此不能保存为正式 PP。',
    suggestion: '根据具体硬错误调整条件并重新排产。',
  },
  UNSAFE_DEMO_FORMAL_SAVE: {
    title: '仅演示环境绕过硬校验',
    description: '当前候选仍有硬错误，本次保存仅用于隔离演示，生成的 FormalPP 不可信且不得用于生产或验收。',
    suggestion: '填写知晓原因；演示结束后关闭开关并使用通过硬校验的候选重新保存。',
  },
  OPEN_CONDITION_DRAFT: {
    title: '存在尚未应用的排产条件',
    description: '新增条件仍处于草案或预览状态，尚未进入当前候选。',
    suggestion: '合并全部新增条件，预览重排影响后应用并重排。',
  },
}

export function v6BusinessMessage(code: string): V6BusinessMessage {
  return MESSAGES[code] || {
    title: '未识别的系统问题',
    description: '系统返回了尚未配置业务说明的问题。',
    suggestion: '保留技术代码并联系系统维护人员核对。',
  }
}

export function v6MonthLabel(value: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(value)
  return match ? `${match[1]}年${Number(match[2])}月` : value || '未指定月份'
}
