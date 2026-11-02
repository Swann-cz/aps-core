export const phaseLabels: Record<string, string> = { STOP: '停线', BS_CLEAR: '清线', REFILL: '复线', CHANGEOVER: '换型', PS_PRE_STOP: '停前', FIRST_START: '首启', MODEL_EXIT: '退出', INITIAL_DRAIN: '排空' }
export const phaseBadge = (phase: string) => phase === 'STOP' ? 'day-shutdown-badge' : phase === 'BS_CLEAR' ? 'day-clear-badge' : phase === 'REFILL' ? 'day-restart-badge' : 'day-boundary-badge'
