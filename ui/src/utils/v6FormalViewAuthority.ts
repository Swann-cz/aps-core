import type { V6FormalPPVersion } from '../types/v6'

const STORAGE_KEY = 'aps.v6.formal-view-authority.v1'

export function readRecentFormalId(): string | null {
  return window.localStorage.getItem(STORAGE_KEY)
}

export function rememberFormalId(formalPpId: string): void {
  window.localStorage.setItem(STORAGE_KEY, formalPpId)
}

export function clearRecentFormalId(): void {
  window.localStorage.removeItem(STORAGE_KEY)
}

export function latestFormalVersion(
  versions: V6FormalPPVersion[],
): V6FormalPPVersion | null {
  return [...versions].sort((left, right) => (
    right.saved_at.localeCompare(left.saved_at)
    || right.formal_pp_id.localeCompare(left.formal_pp_id)
  ))[0] ?? null
}

export function isV6FormalReadOnlyPath(pathname: string): boolean {
  return pathname === '/annual-overview'
    || pathname === '/monthly-filling'
    || pathname === '/v6/formal-pp'
    || pathname === '/v6/formal-compare'
    || /^\/v6\/formal-pp\/[^/]+\/(annual|filling)$/.test(pathname)
}
