import type { PreflightResult } from '../../types/api'

export type ChangeSource = 'actual' | 'sales' | 'conditions' | 'combined'
export type NewRoundTask = 'source' | 'inputs' | 'scope' | 'generate-compare'

export interface PreflightEnvelope {
  inputsIdentity: string
  result: PreflightResult
}

export type NewRoundCommandStatus =
  | 'IDLE'
  | 'STARTED'
  | 'START_UNCERTAIN'
  | 'GENERATE_RETRY_ALLOWED'
  | 'GENERATE_UNCERTAIN'
  | 'GENERATED'
  | 'REFRESH_FAILED'
  | 'BLOCKED'

export interface NewRoundCommandProgress {
  inputsIdentity: string | null
  baseConfirmedPlanVersionId: string | null
  sessionId: string | null
  planningRevision: number | null
  generatedPlanId: string | null
  status: NewRoundCommandStatus
  message: string | null
}

export const EMPTY_COMMAND_PROGRESS: NewRoundCommandProgress = {
  inputsIdentity: null,
  baseConfirmedPlanVersionId: null,
  sessionId: null,
  planningRevision: null,
  generatedPlanId: null,
  status: 'IDLE',
  message: null,
}

const START_UNCERTAIN_MARKER_PREFIX = 'aps:new-round:start-uncertain:'

export function startUncertainMarkerKey(inputsIdentity: string): string {
  return `${START_UNCERTAIN_MARKER_PREFIX}${inputsIdentity}`
}
