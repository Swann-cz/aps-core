export type StartTask = 'sales' | 'conditions' | 'preflight'

export type ConditionDraft = {
  draftId: string
  actionType: string
  params: Record<string, unknown>
  actionPayload: Record<string, unknown>
  planningConditions: Record<string, unknown>[]
}

export type StartPlanningDraft = {
  salesPlanVersionId: string | null
  conditionChanges: ConditionDraft[]
  baseConfirmedPlanVersionId: string | null
  planningYear: number
  workNote: string
}

export function createStartDraft(): StartPlanningDraft {
  return {
    salesPlanVersionId: null,
    conditionChanges: [],
    baseConfirmedPlanVersionId: null,
    planningYear: new Date().getFullYear(),
    workNote: '',
  }
}
