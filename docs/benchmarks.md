# Worker-scale benchmarks

RelayFlow decouples ingest from delivery so subscriber latency does not block `POST /api/v1/events`. Horizontal Celery workers then drain the Redis queue in parallel. This document measures that claim with an injected HTTP delay.

Each worker process uses `--concurrency 1`. Throughput should rise roughly in proportion to replica count while the sink holds each POST for `SINK_DELAY_MS`.

Ideal deliveries/sec ≈ `worker_replicas / (delay_ms / 1000)` if the only cost were the sink sleep. Real drain includes Celery dequeue, HMAC signing, and PostgreSQL writes, so measured throughput is lower than the ideal but should still scale with replicas.

## How to run

The delayed sink is a Compose profile (`bench`). It is not started by a default `docker compose up`.

```bash
docker compose --profile bench up --build -d --scale worker=1
python -m benchmarks.run --workers 1 --events 30 --delay-ms 200

docker compose --profile bench up -d --scale worker=3
python -m benchmarks.run --workers 3 --events 30 --delay-ms 200
```

The runner talks to the API on the host (`http://localhost:8000`) and registers an endpoint whose `target_url` is the Docker DNS name `http://sink:8089/hooks`. Set `rate_limit_per_sec` high (the runner defaults to 1000) so the outbound token bucket is not the bottleneck.

## Recorded run

Environment: Docker Desktop on Windows (2026-11-20), Compose stack on this machine, `SINK_DELAY_MS=200`, 30 events, ingest concurrency 10, endpoint `rate_limit_per_sec=1000`.

| Workers | Ingest time | Drain time | Deliveries/sec | Ideal ≈ | HTTP POST p50 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.648 s | 9.716 s | 3.088 | 5.0 | 224 ms |
| 3 | 0.196 s | 3.296 s | 9.101 | 15.0 | 224 ms |

Drain time dropped by **2.95×** when replicas went from 1 to 3. HTTP p50 stayed near the injected 200 ms delay, so the extra workers are overlapping subscriber latency rather than making each POST faster. Ingest stayed under a second in both runs: slow subscribers did not block `202 Accepted`.
