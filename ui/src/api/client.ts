const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

function scalarMessage(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function apiErrorMessage(status: number, detail: unknown): string {
  const direct = scalarMessage(detail)
  if (direct) return direct
  if (typeof detail !== 'object' || detail === null) return `HTTP ${status}`

  const payload = detail as Record<string, unknown>
  const nested = payload.detail
  const nestedDirect = scalarMessage(nested)
  if (nestedDirect) return nestedDirect
  if (typeof nested === 'object' && nested !== null) {
    const nestedMessage = scalarMessage((nested as Record<string, unknown>).message)
    if (nestedMessage) return nestedMessage
  }

  const message = scalarMessage(payload.message)
  return message || `HTTP ${status}`
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(apiErrorMessage(status, detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      detail = await response.json()
    } catch {
      detail = response.statusText
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export async function requestFile(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { Accept: '*/*' } })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      detail = await response.json()
    } catch {
      detail = response.statusText
    }
    throw new ApiError(response.status, detail)
  }
  const disposition = response.headers.get('Content-Disposition') || ''
  const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  let filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'aps-export'
  if (encodedFilename) {
    try {
      filename = decodeURIComponent(encodedFilename)
    } catch {
      // Keep the ASCII fallback supplied by Content-Disposition.
    }
  }
  return { blob: await response.blob(), filename }
}

export { request }
