// Phase 3B — pure visual mapping for the daily effective-status projection.
// No business semantics live here: this only maps backend-owned mode/effect
// values to labels/colors/symbols for rendering.

export type ModeVisual = {
  label: string
  className: string
  color: string
}

const MODE_VISUAL: Record<string, ModeVisual> = {
  SHIFT_8H: { label: '8h', className: 'mode-shift-8h', color: '#1677ff' },
  SHIFT_8_PLUS_2: { label: '8+2', className: 'mode-shift-8p2', color: '#fa8c16' },
  SHIFT_8_PLUS_3: { label: '8+3', className: 'mode-shift-8p3', color: '#eb2f96' },
  DOUBLE_SHIFT: { label: '双班', className: 'mode-double-shift', color: '#722ed1' },
  NO_PRODUCTION: { label: '停产', className: 'mode-no-production', color: '#8c8c8c' },
}

export function modeVisual(mode: string): ModeVisual {
  return MODE_VISUAL[mode] ?? { label: mode, className: 'mode-unknown', color: '#8c8c8c' }
}

const EFFECT_LABEL: Record<string, string> = {
  LINE_REFILL: '复线',
  RAMP_UP: '爬坡',
  CLEARING: '清线',
  CAPACITY_LOSS: '降容',
}

const EFFECT_SYMBOL: Record<string, string> = {
  LINE_REFILL: '↺',
  RAMP_UP: '↗',
  CLEARING: '清',
  CAPACITY_LOSS: '↓',
}

export function effectLabel(type: string): string {
  return EFFECT_LABEL[type] ?? type
}

export function effectSymbol(type: string): string {
  return EFFECT_SYMBOL[type] ?? '·'
}

export const MODE_LEGEND = [
  { mode: 'SHIFT_8H', label: '8h', color: '#1677ff' },
  { mode: 'SHIFT_8_PLUS_2', label: '8+2', color: '#fa8c16' },
  { mode: 'SHIFT_8_PLUS_3', label: '8+3', color: '#eb2f96' },
  { mode: 'DOUBLE_SHIFT', label: '双班', color: '#722ed1' },
  { mode: 'NO_PRODUCTION', label: '停产', color: '#8c8c8c' },
]

export const EFFECT_LEGEND = [
  { type: 'LINE_REFILL', label: '复线', symbol: '↺' },
  { type: 'RAMP_UP', label: '爬坡', symbol: '↗' },
  { type: 'CLEARING', label: '清线', symbol: '清' },
  { type: 'CAPACITY_LOSS', label: '降容', symbol: '↓' },
]
