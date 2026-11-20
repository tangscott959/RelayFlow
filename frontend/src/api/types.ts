export type Tenant = {
  id: string
  name: string
  api_key_prefix: string
  created_at: string
}

export type TenantCreateResponse = Tenant & {
  api_key: string
}

export type EndpointStatus = 'active' | 'paused' | 'disabled'

export type Endpoint = {
  id: string
  tenant_id: string
  target_url: string
  secret_key: string
  rate_limit_per_sec: number
  subscribed_events: string[]
  status: EndpointStatus
  created_at: string
}

export type IngestResult = {
  event_id: string
  status: 'accepted' | 'duplicate'
  attempt_count: number
  attempt_ids: string[]
}

export type DeliveryStatus = 'pending' | 'delivered' | 'failed' | 'retrying'

export type DeliveryAttempt = {
  id: string
  event_id: string
  endpoint_id: string
  attempt_number: number
  http_status: number | null
  response_headers: Record<string, unknown> | null
  response_body: string | null
  duration_ms: number | null
  status: DeliveryStatus
  next_retry_at: string | null
  created_at: string
}

export type PaginatedDeliveries = {
  items: DeliveryAttempt[]
  total: number
  page: number
  page_size: number
}
