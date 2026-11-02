import { useState } from 'react'
import { Alert, Button, Card, Space, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/planning'
import type { AnnualCalendar, StartSessionRequest, WorkbenchState } from '../../types/api'
import { isCurrentPreflight, validatedActualScope, validatedBaseDays, validatedPreflight } from './preflightAuthority'
import type {
  ChangeSource,
  NewRoundCommandProgress,
  PreflightEnvelope,
} from './types'
import { startUncertainMarkerKey } from './types'

type CompareTarget = { left: string; right: string }

export function GenerateCompareStep({
  inputs,
  inputsIdentity,
  preflight,
  fetching,
  error,
  inputFetching,
  inputError,
  planningYear,
  intentIdentity,
  basePlanVersionId,
  baseProjection,
  baseFetching,
  baseError,
  source,
  commandProgress,
  onCommandProgress,
  onBack,
  onCompare,
}: {
  inputs: StartSessionRequest | null
  inputsIdentity: string | null
  preflight: PreflightEnvelope | undefined
  fetching: boolean
  error: boolean
  inputFetching: boolean
  inputError: boolean
  planningYear: number | null
  intentIdentity: string
  basePlanVersionId: string | null
  baseProjection: AnnualCalendar | undefined
  baseFetching: boolean
  baseError: boolean
  source: ChangeSource
  commandProgress: NewRoundCommandProgress
  onCommandProgress: (progress: NewRoundCommandProgress) => void
  onBack: () => void
  onCompare: (left: string, right: string) => void
}) {
  const queryClient = useQueryClient()
  const [reconciling, setReconciling] = useState(false)
  const needsActual = source === 'actual' || source === 'combined'
  const authorityFetching = inputFetching || fetching
  const authorityError = inputError || error
  const current = isCurrentPreflight(inputsIdentity, preflight, authorityFetching, authorityError)
  const currentPreflight = current ? validatedPreflight(preflight?.result) : null
  const scope = needsActual && planningYear !== null
    ? validatedActualScope(source, currentPreflight, planningYear)
    : null
  const baseCurrent = needsActual || (
    !baseFetching
    && !baseError
    && validatedBaseDays(baseProjection, basePlanVersionId, planningYear) !== null
  )
  const authorized = Boolean(
    inputs
    && currentPreflight?.outcome === 'PASS'
    && (!needsActual || scope)
    && baseCurrent,
  )
  const progressMatchesInputs = commandProgress.status === 'IDLE'
    || commandProgress.inputsIdentity === inputsIdentity

  const adoptWorkbench = (
    progress: NewRoundCommandProgress,
    workbench: WorkbenchState,
  ): CompareTarget | null => {
    const frozenBaseConfirmedId = progress.baseConfirmedPlanVersionId
    if (!frozenBaseConfirmedId || !progress.sessionId) return null
    if (workbench.session_id !== progress.sessionId) {
      onCommandProgress({ ...progress, status: 'BLOCKED', message: 'Workbench 已切换到其他 Session，禁止自动重放命令' })
      return null
    }
    if (workbench.base_confirmed_plan_version_id !== frozenBaseConfirmedId) {
      onCommandProgress({ ...progress, status: 'BLOCKED', message: 'Workbench Base 与命令冻结 Base 不一致' })
      return null
    }
    if (!workbench.current_plan_version_id) {
      if (progress.generatedPlanId) {
        onCommandProgress({ ...progress, status: 'REFRESH_FAILED', message: '命令已成功 / 状态刷新失败' })
      } else {
        onCommandProgress({ ...progress, status: 'GENERATE_RETRY_ALLOWED', message: '同一 Session 尚无 Plan，可以只重试 Generate' })
      }
      return null
    }
    if (progress.generatedPlanId && workbench.current_plan_version_id !== progress.generatedPlanId) {
      onCommandProgress({ ...progress, status: 'BLOCKED', message: 'Workbench head 与 Generate 结果不一致' })
      return null
    }
    queryClient.setQueryData<WorkbenchState>(['workbench-state'], workbench)
    onCommandProgress({
      ...progress,
      generatedPlanId: workbench.current_plan_version_id,
      status: 'GENERATED',
      message: null,
    })
    return { left: frozenBaseConfirmedId, right: workbench.current_plan_version_id }
  }

  const reconcileAfterGenerateUncertainty = async (
    progress: NewRoundCommandProgress,
  ): Promise<CompareTarget | null> => {
    try {
      const workbench = await api.workbenchState()
      return adoptWorkbench(progress, workbench)
    } catch {
      onCommandProgress({ ...progress, status: 'GENERATE_UNCERTAIN', message: 'Generate 响应不确定，对账失败；只能重新获取 Workbench' })
      return null
    }
  }

  const command = useMutation({
    mutationFn: async (): Promise<CompareTarget | null> => {
      if (!inputs || !inputsIdentity || !authorized || !progressMatchesInputs) {
        throw new Error('Preflight 未授权当前输入')
      }
      const baseConfirmedId = inputs.base_confirmed_plan_version_id
      if (!baseConfirmedId) throw new Error('API Gap：缺少 Confirmed Base')

      let sessionId = commandProgress.sessionId
      let planningRevision = commandProgress.planningRevision
      if (commandProgress.status === 'IDLE') {
        let started
        try {
          started = await api.startSession(inputs)
        } catch (startError) {
          try {
            window.sessionStorage.setItem(startUncertainMarkerKey(intentIdentity), '1')
          } catch {
            // Memory state below still fails closed for the current page.
          }
          onCommandProgress({
            inputsIdentity,
            baseConfirmedPlanVersionId: baseConfirmedId,
            sessionId: null,
            planningRevision: null,
            generatedPlanId: null,
            status: 'START_UNCERTAIN',
            message: 'Start 响应不确定；禁止再次 Start，只能对账',
          })
          throw startError
        }
        if (started.outcome !== 'SESSION_STARTED' || !started.session_id) {
          onCommandProgress({
            inputsIdentity,
            baseConfirmedPlanVersionId: baseConfirmedId,
            sessionId: null,
            planningRevision: null,
            generatedPlanId: null,
            status: 'BLOCKED',
            message: `启动会话失败: ${started.outcome}`,
          })
          throw new Error(`启动会话失败: ${started.outcome}`)
        }
        sessionId = started.session_id
        planningRevision = typeof started.planning_revision === 'number'
          ? started.planning_revision
          : null
        const startedProgress: NewRoundCommandProgress = {
          inputsIdentity,
          baseConfirmedPlanVersionId: baseConfirmedId,
          sessionId,
          planningRevision,
          generatedPlanId: null,
          status: planningRevision === null ? 'BLOCKED' : 'STARTED',
          message: planningRevision === null ? 'Start 已成功但缺少 planning_revision，禁止 Generate' : null,
        }
        onCommandProgress(startedProgress)
        if (planningRevision === null) throw new Error(startedProgress.message as string)
      }

      if (!sessionId || typeof planningRevision !== 'number') {
        throw new Error('已启动 Session 缺少可验证的 planning_revision')
      }
      const startedProgress: NewRoundCommandProgress = {
        inputsIdentity,
        baseConfirmedPlanVersionId: commandProgress.baseConfirmedPlanVersionId || baseConfirmedId,
        sessionId,
        planningRevision,
        generatedPlanId: null,
        status: 'STARTED',
        message: null,
      }
      let generated
      try {
        generated = await api.generatePlan(sessionId, { expected_planning_revision: planningRevision })
      } catch {
        return reconcileAfterGenerateUncertainty({
          ...startedProgress,
          status: 'GENERATE_UNCERTAIN',
          message: 'Generate 响应不确定，正在按 Workbench 对账',
        })
      }
      if (generated.outcome !== 'PLAN_CREATED') {
        onCommandProgress({ ...startedProgress, status: 'BLOCKED', message: `生成失败: ${generated.outcome}` })
        throw new Error(`生成失败: ${generated.outcome}`)
      }
      if (!generated.plan_version_id) {
        return reconcileAfterGenerateUncertainty({
          ...startedProgress,
          status: 'GENERATE_UNCERTAIN',
          message: 'Generate 缺少 plan_version_id，正在按 Workbench 对账',
        })
      }
      const generatedProgress: NewRoundCommandProgress = {
        ...startedProgress,
        generatedPlanId: generated.plan_version_id,
        status: 'GENERATED',
        message: null,
      }
      onCommandProgress(generatedProgress)
      try {
        const workbench = await api.workbenchState()
        return adoptWorkbench(generatedProgress, workbench)
      } catch {
        onCommandProgress({ ...generatedProgress, status: 'REFRESH_FAILED', message: '命令已成功 / 状态刷新失败' })
        return null
      }
    },
    onSuccess: (target) => {
      if (target) onCompare(target.left, target.right)
    },
    onError: (commandError) => message.error(commandError instanceof Error ? commandError.message : '生成失败'),
  })

  const reconcile = async () => {
    if (!commandProgress.sessionId && commandProgress.status === 'START_UNCERTAIN') {
      onCommandProgress({
        ...commandProgress,
        status: 'BLOCKED',
        message: '无法确认 Start 是否创建了新 Session',
      })
      return
    }
    setReconciling(true)
    try {
      const workbench = await api.workbenchState()
      const target = adoptWorkbench(commandProgress, workbench)
      if (target) onCompare(target.left, target.right)
    } catch {
      message.error('Workbench 对账失败，未重放任何命令')
    } finally {
      setReconciling(false)
    }
  }

  const showReconcile = ['START_UNCERTAIN', 'GENERATE_UNCERTAIN', 'GENERATED', 'REFRESH_FAILED'].includes(commandProgress.status)
  const canRunCommand = authorized
    && progressMatchesInputs
    && (commandProgress.status === 'IDLE' || commandProgress.status === 'GENERATE_RETRY_ALLOWED')

  return (
    <Card size="small" title="第 4 步 · 生成与比对">
      {!inputs && <Alert type="error" showIcon message="API Gap：无法构建后端输入身份" />}
      {inputFetching && <Alert type="info" showIcon message="正在刷新后端输入" />}
      {inputs && !inputFetching && fetching && <Alert type="info" showIcon message="正在检查当前输入" />}
      {inputs && !authorityFetching && authorityError && <Alert type="error" showIcon message="Preflight 或输入查询失败" />}
      {inputs && !authorityFetching && !authorityError && !currentPreflight && (
        <Alert type="error" showIcon message="API Gap：Preflight 响应无效" />
      )}
      {inputs && !authorityFetching && !authorityError && needsActual && (!current || !scope) && (
        <Alert type="error" showIcon message="API Gap：Preflight Actual scope 无效" />
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && baseFetching && (
        <Alert type="info" showIcon message="正在读取 Confirmed Base 范围" />
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && !baseFetching && (baseError || !baseCurrent) && (
        <Alert type="error" showIcon message="Confirmed Base 投影不可用" />
      )}
      {commandProgress.message && commandProgress.status !== 'BLOCKED' && (
        <Alert
          type="warning"
          showIcon
          message={commandProgress.message}
          style={{ marginTop: 10 }}
        />
      )}
      {inputs && !authorityFetching && !authorityError && currentPreflight && (!needsActual || scope) && baseCurrent && (
        <div style={{ marginTop: 10 }}>
          <div className="muted" style={{ marginBottom: 10 }}>
            Preflight：{currentPreflight.outcome === 'PASS' ? '✓ 通过' : `未通过（${currentPreflight.checks.filter((check) => !check.ok).length} 项）`}
          </div>
          <Space>
            <Button disabled={commandProgress.status !== 'IDLE' || command.isPending} onClick={onBack}>上一步：影响范围</Button>
            {commandProgress.status === 'BLOCKED' ? null : showReconcile ? (
              <Button type="primary" loading={reconciling} onClick={() => void reconcile()}>
                重新获取 Workbench
              </Button>
            ) : (
              <Button
                type="primary"
                disabled={!canRunCommand}
                loading={command.isPending}
                onClick={() => command.mutate()}
              >
                {commandProgress.status === 'GENERATE_RETRY_ALLOWED'
                  ? '重试 Generate（不重复 Start）'
                  : '生成新一轮并进入比对'}
              </Button>
            )}
          </Space>
        </div>
      )}
    </Card>
  )
}
