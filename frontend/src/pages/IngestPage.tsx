import { type FormEvent, useState } from 'react'

import { ApiError, ingestEvent } from '../api/client'
import type { IngestResult } from '../api/types'
import { useAuth } from '../auth/AuthContext'

function newIdempotencyKey(): string {
  return `evt-${crypto.randomUUID()}`
}

export function IngestPage() {
  const { session } = useAuth()
  const [eventType, setEventType] = useState('agent.completed')
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey)
  const [payloadText, setPayloadText] = useState('{\n  "ok": true\n}')
  const [result, setResult] = useState<IngestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!session) {
    return null
  }
  const apiKey = session.apiKey

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    let payload: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(payloadText)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Payload must be a JSON object.')
      }
      payload = parsed as Record<string, unknown>
    } catch (err: unknown) {
      setBusy(false)
      setError(err instanceof Error ? err.message : 'Payload must be valid JSON.')
      return
    }
    try {
      const body = await ingestEvent(apiKey, {
        event_type: eventType.trim(),
        idempotency_key: idempotencyKey.trim(),
        payload,
      })
      setResult(body)
      setIdempotencyKey(newIdempotencyKey())
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        const retry = err.retryAfter ? ` Retry after ${err.retryAfter}s.` : ''
        setError(`${err.message}.${retry}`)
      } else {
        setError('Ingest failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <header className="page-head">
        <div>
          <h1>Ingest</h1>
          <p className="muted">POST an event. Matching active endpoints are queued for delivery (202).</p>
        </div>
      </header>
      {error ? (
        <div className="banner danger" role="alert">
          {error}
        </div>
      ) : null}
      {result ? (
        <div className="banner ok" role="status">
          {result.status === 'duplicate' ? 'Duplicate' : 'Accepted'} — event {result.event_id},{' '}
          {result.attempt_count} attempt{result.attempt_count === 1 ? '' : 's'}.
        </div>
      ) : null}
      <form className="panel stack" onSubmit={onSubmit}>
        <label>
          Event type
          <input value={eventType} onChange={(e) => setEventType(e.target.value)} required />
        </label>
        <label>
          Idempotency key
          <input
            value={idempotencyKey}
            onChange={(e) => setIdempotencyKey(e.target.value)}
            spellCheck={false}
            required
          />
        </label>
        <label>
          Payload JSON
          <textarea value={payloadText} onChange={(e) => setPayloadText(e.target.value)} rows={8} spellCheck={false} />
        </label>
        <button type="submit" disabled={busy}>
          Send event
        </button>
      </form>
    </section>
  )
}
