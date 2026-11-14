# Deployment

## Fastest public URL: Fly.io

`fly.toml` is included, pinned to the `jed` (Jeddah) region.

```bash
fly launch --no-deploy --name bayyinah     # accept the detected Dockerfile
fly volumes create bayyinah_data --size 1
fly secrets set BAYYYINAH_API_KEY=$(openssl rand -hex 24)
fly deploy
```

The volume is mounted at `/data`, so the SQLite database survives deploys. Use a
strong API key — once the URL is public, `/api/stats` and `/api/ingest` are the
only keyed routes, so treat the whole instance as semi-public until you add auth
to the question and contract endpoints too.

> **Residency caveat:** Fly gives you a region choice, not a PDPL guarantee. If
> you claim in-Kingdom hosting anywhere, check the provider's current region
> commitments first — a `jed` machine is not the same thing as an accredited
> in-Kingdom cloud.

## Docker (recommended for self-hosting)

```bash
docker compose up --build
# → http://localhost:8080
```

The database lives in a named volume (`/data`), so containers are disposable. First start ingests `corpora/raw` automatically; every restart is a no-op because ingestion is hash-idempotent.

### Without compose

```bash
docker build -t bayyinah .
docker run -d --name bayyinah -p 8080:8080 \
  -v bayyinah-data:/data \
  -e BAYYINAH_API_KEY=change-me \
  bayyinah
```

## Bare metal / VM

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install python-docx pypdf  # optional: Word export, PDF ingest

python -m bayyinah ingest corpora/raw
BAYYINAH_API_KEY=… python -m bayyinah serve --host 0.0.0.0 --port 8080
```

Run it under systemd (Linux) or NSSM/scheduled task (Windows). It is a plain threaded process with no external dependencies.

### systemd unit

```ini
[Unit]
Description=Bayyinah compliance copilot
After=network.target

[Service]
User=bayyinah
WorkingDirectory=/opt/bayyinah
Environment=BAYYINAH_API_KEY=…
Environment=BAYYINAH_DB_PATH=/var/lib/bayyinah/bayyinah.db
ExecStart=/opt/bayyinah/.venv/bin/python -m bayyinah serve --host 127.0.0.1 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

## TLS

Terminate TLS at a reverse proxy; the app speaks plain HTTP and should never be exposed directly to the internet.

```caddyfile
compliance.example.sa {
    reverse_proxy 127.0.0.1:8080
    encode gzip
}
```

Caddy provisions certificates automatically. nginx equivalent:

```nginx
server {
    listen 443 ssl http2;
    server_name compliance.example.sa;
    ssl_certificate     /etc/letsencrypt/live/…/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/…/privkey.pem;
    client_max_body_size 5m;   # match BAYYYINAH_MAX_UPLOAD_BYTES

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

## Data residency (KSA)

PDPL and NCA Cloud Controls make residency a procurement question, not a preference. Two supported shapes:

| Shape | Setup | Data leaves the Kingdom? |
|---|---|---|
| **Fully in-Kingdom, self-hosted model** | Host the VM in a KSA region; run `BAYYINAH_LLM_BASE_URL` against a self-hosted vLLM/Ollama serving ALLaM or another open model | No |
| **In-Kingdom app, hosted LLM** | Host the app in a KSA region; call a hosted API | **Yes** — contract text transits the provider. Only acceptable with a no-training / zero-retention clause, and not for government data |

The default configuration uses **no external calls at all** (extractive baseline), so the residency question has a clean answer until you deliberately change it.

See [pdpl-mapping.md](pdpl-mapping.md) for the control mapping and the pre-pilot checklist.

## Sizing

| Corpus | RAM | CPU | Notes |
|---|---|---|---|
| ≤ 5k chunks | 512 MB | 1 vCPU | comfortable |
| ≤ 50k chunks | 2 GB | 2 vCPU | vectors dominate memory |
| > 50k chunks | — | — | move to Postgres + pgvector |

Disk is small: 8 chunks ≈ 60 KB. A 500k-token legal corpus with vectors is roughly 50–100 MB.

## Backups

One file. Back it up; that is the whole system.

```bash
sqlite3 var/bayyinah.db ".backup '/backup/bayyinah-$(date +%F).db'"
```

Run daily, keep 14 days, verify by opening one restore. Contract reports and query history live in the same file.

## Upgrades

```bash
git pull
docker compose up -d --build      # or: pip install -e .
python -m bayyinah ingest corpora/raw   # idempotent; picks up changed files
python evals/run_eval.py                # confirm the gates are still green
```

The schema is created with `IF NOT EXISTS`; there are no migrations yet. Adding a column means writing one — do it before the first real pilot, not after.

## Health and monitoring

- `GET /api/health` — liveness plus corpus size. Wire it to your uptime check.
- `GET /api/stats` — query volume, refusal rate, average latency and cost.
- Container healthcheck is defined in the Dockerfile.

Alert on: corpus size dropping to zero, refusal rate spiking (a retrieval regression), p95 latency climbing, disk usage.
