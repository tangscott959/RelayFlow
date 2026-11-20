# RelayFlow operator console

Vite + React + TypeScript UI for tenant endpoints, event ingest, delivery logs, and DLQ resend.

The browser talks only to FastAPI `/api` (proxied by Vite). It never opens PostgreSQL or Celery.

```bash
cd frontend
npm install
npm run dev
```

With the API on `http://localhost:8000`, open `http://localhost:5173`. Compose starts this app as the `frontend` service (`API_PROXY_TARGET=http://web:8000`).
