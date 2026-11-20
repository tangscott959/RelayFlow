import type {
  DeliveryAttempt,
  DeliveryStatus,
  Endpoint,
  EndpointStatus,
  IngestResult,
  PaginatedDeliveries,
  Tenant,
  TenantCreateResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  }
  return 'Request failed.'
}

async function request<T>(
  path: string,
  options: RequestInit & { apiKey?: string | null } = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (options.apiKey) {
    headers.set('Authorization', `Bearer ${options.apiKey}`)
  }
  const response = await fetch(`/api/v1${path}`, { ...options, headers })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = (body as { detail: unknown }).detail
      }
    } catch {
      /* non-JSON error body */
    }
    const retryRaw = response.headers.get('Retry-After')
    const retryAfter = retryRaw ? Number.parseInt(retryRaw, 10) : null
    throw new ApiError(response.status, formatDetail(detail), Number.isFinite(retryAfter) ? retryAfter : null)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export function createTenant(name: string): Promise<TenantCreateResponse> {
  return request<TenantCreateResponse>('/tenants', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function readMe(apiKey: string): Promise<Tenant> {
  return request<Tenant>('/tenants/me', { apiKey })
}

export function listEndpoints(apiKey: string, status?: EndpointStatus): Promise<Endpoint[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<Endpoint[]>(`/endpoints${query}`, { apiKey })
}

export function createEndpoint(
  apiKey: string,
  payload: {
    target_url: string
    subscribed_events: string[]
    rate_limit_per_sec: number
  },
): Promise<Endpoint> {
  return request<Endpoint>('/endpoints', {
    method: 'POST',
    apiKey,
    body: JSON.stringify(payload),
  })
}

export function patchEndpoint(
  apiKey: string,
  endpointId: string,
  payload: { status: EndpointStatus },
): Promise<Endpoint> {
  return request<Endpoint>(`/endpoints/${endpointId}`, {
    method: 'PATCH',
    apiKey,
    body: JSON.stringify(payload),
  })
}

export function ingestEvent(
  apiKey: string,
  payload: { event_type: string; idempotency_key: string; payload: Record<string, unknown> },
): Promise<IngestResult> {
  return request<IngestResult>('/events', {
    method: 'POST',
    apiKey,
    body: JSON.stringify(payload),
  })
}

export function listDeliveries(
  apiKey: string,
  endpointId: string,
  params: { page: number; page_size: number; status?: DeliveryStatus | '' },
): Promise<PaginatedDeliveries> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
  })
  if (params.status) {
    search.set('status', params.status)
  }
  return request<PaginatedDeliveries>(`/endpoints/${endpointId}/deliveries?${search.toString()}`, {
    apiKey,
  })
}

export function resendDelivery(apiKey: string, attemptId: string): Promise<DeliveryAttempt> {
  return request<DeliveryAttempt>(`/deliveries/${attemptId}/resend`, {
    method: 'POST',
    apiKey,
  })
}
