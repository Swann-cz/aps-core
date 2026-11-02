import { Alert, Button, Card, Descriptions, Space, Tag } from 'antd'
import type { AnnualCalendar, StartSessionRequest } from '../../types/api'
import { isCurrentPreflight, validatedActualScope, validatedBaseDays, validatedPreflight } from './preflightAuthority'
import type { ChangeSource, PreflightEnvelope } from './types'

export function ImpactScopeStep({
  source,
  inputs,
  inputsIdentity,
  preflight,
  fetching,
  error,
  inputFetching,
  inputError,
  planningYear,
  basePlanVersionId,
  baseProjection,
  baseFetching,
  baseError,
  baseInvalid,
  blocked,
  onRetry,
  onRetryBase,
  onBack,
  onNext,
}: {
  source: ChangeSource
  inputs: StartSessionRequest | null
  inputsIdentity: string | null
  preflight: PreflightEnvelope | undefined
  fetching: boolean
  error: boolean
  inputFetching: boolean
  inputError: boolean
  planningYear: number | null
  basePlanVersionId: string | null
  baseProjection: AnnualCalendar | undefined
  baseFetching: boolean
  baseError: boolean
  baseInvalid: boolean
  blocked: boolean
  onRetry: () => void
  onRetryBase: () => void
  onBack: () => void
  onNext: () => void
}) {
  const needsActual = source === 'actual' || source === 'combined'
  const authorityFetching = inputFetching || fetching
  const authorityError = inputError || error
  const current = isCurrentPreflight(inputsIdentity, preflight, authorityFetching, authorityError)
  const currentPreflight = current ? validatedPreflight(preflight?.result) : null
  const scope = needsActual && planningYear !== null
    ? validatedActualScope(source, currentPreflight, planningYear)
    : null
  const baseDays = !needsActual
    && !baseFetching
    && !baseError
    && !baseInvalid
    ? validatedBaseDays(baseProjection, basePlanVersionId, planningYear)
    : null
  const baseCurrent = baseDays !== null
  const protectedBaseDays = baseCurrent
    ? baseDays.filter((day) => day.lock_state !== 'MUTABLE')
    : []
  const mutableBaseDays = baseCurrent
    ? baseDays.filter((day) => day.lock_state === 'MUTABLE')
    : []
  const canContinue = Boolean(
    !blocked
    && inputs
    && currentPreflight?.outcome === 'PASS'
    && (needsActual ? scope : baseCurrent),
  )

  return (
    <Card size="small" title="第 3 步 · 影响范围">
      {!inputs && <Alert type="error" showIcon message="API Gap：无法构建后端输入身份" />}
      {inputFetching && <Alert type="info" showIcon message="正在刷新后端输入" />}
      {inputs && !inputFetching && fetching && <Alert type="info" showIcon message="正在检查当前输入" />}
      {inputs && !authorityFetching && authorityError && (
        <Alert type="error" showIcon message="Preflight 请求失败" action={<Button onClick={onRetry}>重试</Button>} />
      )}
      {inputs && !authorityFetching && !authorityError && !currentPreflight && (
        <Alert type="error" showIcon message="API Gap：Preflight 响应无效" />
      )}
      {inputs && !authorityFetching && !authorityError && needsActual && (!current || !scope) && (
        <Alert type="error" showIcon message="API Gap：Preflight Actual scope 无效" />
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && baseFetching && (
        <Alert type="info" showIcon message="正在读取 Confirmed Base 范围" />
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && !baseFetching && baseError && (
        <Alert type="error" showIcon message="Confirmed Base 投影请求失败" action={<Button onClick={onRetryBase}>重试</Button>} />
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && !baseFetching && !baseError && !baseCurrent && (
        <Alert type="error" showIcon message="API Gap：Confirmed Base 投影无效" />
      )}
      {inputs && !authorityFetching && !authorityError && needsActual && current && scope && (
        <>
          {scope.outcome !== 'PASS' && (
            <Alert
              type="warning"
              showIcon
              message="Preflight 未通过"
              description={scope.checks.filter((check) => !check.ok).map((check) => check.detail).join('；')}
              style={{ marginBottom: 12 }}
            />
          )}
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="受保护范围（后端 Actual scope）">
              {needsActual && scope.actual_locked_through ? (
                <Tag color="blue">实际锁定至：{scope.actual_locked_through}</Tag>
              ) : (
                <Tag>无 Actual 已锁定截止日</Tag>
              )}
              <div className="muted" style={{ marginTop: 6 }}>过去至该日期由后端标记为 ACTUALIZED，原样保留</div>
            </Descriptions.Item>
            <Descriptions.Item label="可重排范围（后端 Actual scope）">
              {scope.mutable_replan_start ? (
                <Tag color="green">可重排起点：{scope.mutable_replan_start}</Tag>
              ) : (
                <Tag>无可重排起点</Tag>
              )}
              <Tag>可调整日期：{scope.mutable_dates.length} 天</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="继续锁定的显式日期">
              {scope.explicit_locked_dates.length > 0
                ? scope.explicit_locked_dates.map((date) => <Tag key={date} color="gold">{date}</Tag>)
                : <Tag>无</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="后端保护区间">
              {scope.protected_dates.length > 0
                ? scope.protected_dates.map((range) => (
                  <Tag key={`${range.start_date}-${range.end_date}-${range.lock_source}`}>
                    {range.start_date} 至 {range.end_date} · {range.lock_state}
                  </Tag>
                ))
                : <Tag>无</Tag>}
            </Descriptions.Item>
          </Descriptions>
        </>
      )}
      {inputs && !authorityFetching && !authorityError && !needsActual && currentPreflight && baseCurrent && (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Confirmed Base 保护范围（后端 Annual 投影）">
            <Tag color="blue">Base 受保护日期：{protectedBaseDays.length} 天</Tag>
            <Tag color="green">Base 可调整日期：{mutableBaseDays.length} 天</Tag>
            <div style={{ marginTop: 6 }}>
              {protectedBaseDays.length > 0
                ? protectedBaseDays.map((day) => (
                  <Tag key={day.date} color="gold">
                    <code>{day.date}</code> · {day.lock_state} · {day.lock_source || '后端未标注来源'}
                  </Tag>
                ))
                : <Tag>无受保护日期</Tag>}
            </div>
          </Descriptions.Item>
        </Descriptions>
      )}
      <Space style={{ marginTop: 14 }}>
        <Button onClick={onBack}>上一步：更新输入</Button>
        <Button type="primary" disabled={!canContinue} onClick={onNext}>
          下一步：生成与比对
        </Button>
      </Space>
    </Card>
  )
}
