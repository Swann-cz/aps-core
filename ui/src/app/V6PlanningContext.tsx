import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { v6Api } from '../api/v6'
import type { V6Session, V6Workbench } from '../types/v6'
import { isV6FormalReadOnlyPath } from '../utils/v6FormalViewAuthority'

interface V6PlanningContextValue {
  openSessions: V6Session[]
  activeSession: V6Session | null
  multipleOpenSessions: boolean
  workbench: V6Workbench | null
  loading: boolean
  fetching: boolean
  error: unknown
  refresh: () => Promise<void>
}

const V6PlanningContext = createContext<V6PlanningContextValue | null>(null)

export function V6PlanningProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const formalReadOnly = isV6FormalReadOnlyPath(location.pathname)
  const sessionsQuery = useQuery({
    queryKey: ['v6', 'sessions', 'OPEN'],
    queryFn: () => v6Api.sessions('OPEN'),
    staleTime: 10_000,
    enabled: !formalReadOnly,
  })
  const openSessions = sessionsQuery.data || []
  const activeSession = openSessions.length === 1 ? openSessions[0] : null
  const workbenchQuery = useQuery({
    queryKey: ['v6', 'workbench', activeSession?.session_id],
    queryFn: () => v6Api.workbench(activeSession!.session_id),
    enabled: !formalReadOnly && Boolean(activeSession),
    staleTime: 10_000,
  })

  const value = useMemo<V6PlanningContextValue>(() => ({
    openSessions,
    activeSession,
    multipleOpenSessions: openSessions.length > 1,
    workbench: workbenchQuery.data || null,
    loading: sessionsQuery.isLoading || (Boolean(activeSession) && workbenchQuery.isLoading),
    fetching: sessionsQuery.isFetching || workbenchQuery.isFetching,
    error: sessionsQuery.error || workbenchQuery.error,
    refresh: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['v6', 'sessions'] }),
        queryClient.invalidateQueries({ queryKey: ['v6', 'workbench'] }),
        queryClient.invalidateQueries({ queryKey: ['v6', 'formal'] }),
      ])
    },
  }), [activeSession, openSessions, queryClient, sessionsQuery.error, sessionsQuery.isFetching, sessionsQuery.isLoading, workbenchQuery.data, workbenchQuery.error, workbenchQuery.isFetching, workbenchQuery.isLoading])

  return <V6PlanningContext.Provider value={value}>{children}</V6PlanningContext.Provider>
}

export function useV6Planning() {
  const value = useContext(V6PlanningContext)
  if (!value) throw new Error('useV6Planning must be used within V6PlanningProvider')
  return value
}
