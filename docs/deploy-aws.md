# Deploying PlayUp on an AWS EC2 instance

One instance, Docker Compose, four containers: Caddy (TLS), nginx serving the
built frontend and proxying `/api/*`, the FastAPI backend, and PostgreSQL.
Nothing but Caddy is reachable from outside the Docker network.

```text
internet ──:80/:443──> caddy ──> frontend (nginx) ──/api/*──> backend:8000 ──> db:5432
```

Until a domain is configured Caddy serves plain HTTP on the instance IP.
Section 5 turns on HTTPS.

## 1. Instance

- Ubuntu 24.04 LTS, `t3.small` or larger (the Node build step needs ~1 GB free RAM; on a `t3.micro` add 1 GB of swap first).
- Security group inbound: **80** and **443** (TCP; UDP 443 too if you want HTTP/3) from anywhere, **22** from your IP only, or no SSH at all if you use SSM. Do not open 5432 or 8000. Port 80 must stay open after HTTPS is on: Let's Encrypt validates and browsers get redirected through it.
- Install Docker Engine + Compose plugin from Docker's repository (the Ubuntu `docker.io` package ships an old Compose):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker
docker compose version   # needs >= 2.20
```

## 2. First deploy

```bash
git clone https://github.com/eduardoccmelo/PlayUp.git
cd PlayUp
cp .env.example .env
# set POSTGRES_PASSWORD (openssl rand -base64 32); keep PLAYUP_ENVIRONMENT=production
nano .env

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps           # db, backend, frontend "healthy"; caddy "Up"
curl -s http://localhost/api/health   # {"status":"ok"} (plain HTTP until section 5)
```

The backend runs `alembic upgrade head` on every start, so the schema is
created on the first boot and upgraded on later ones. The database lives in
the `playup-db` named volume and survives `down`/`up`.

**Do not load `db/seed.sql` in production.** It creates demo users and groups
with placeholder credentials.

## 3. Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker image prune -f
```

Compose only recreates containers whose image or config changed. The
backend re-runs migrations on start.

## 4. Operating

| Task | Command |
|---|---|
| Logs | `docker compose logs -f backend` |
| Backup | `docker compose exec -T db pg_dump -U playup -Fc playup > playup-$(date +%F).dump` |
| Restore | `docker compose exec -T db pg_restore -U playup -d playup --clean < playup.dump` |
| psql | `docker compose exec db psql -U playup -d playup` |
| Stop | `docker compose -f docker-compose.yml -f docker-compose.prod.yml down` |

Container logs rotate at 10 MB x 3 files (set in `docker-compose.prod.yml`).
Put the backup command in cron and copy the dump off the instance (S3 via
`aws s3 cp`); a named volume on one EBS disk is not a backup.

## 5. Domain and HTTPS

The domain is registered at GoDaddy; DNS is served by Route 53; the
certificate comes from Let's Encrypt and is issued and renewed by the Caddy
container. No ACM certificate or load balancer is involved, so there is
nothing to pay for beyond the hosted zone (about USD 0.50 a month).

### 5.1 Give the instance a fixed address

EC2 console → **Elastic IPs** → *Allocate* → *Associate* with the instance.
Without it the public IP changes on every stop/start and DNS breaks.
An Elastic IP is free while attached to a running instance.

### 5.2 Route 53 hosted zone

Route 53 → **Hosted zones** → *Create hosted zone* → the bare domain
(`example.com`), type *Public*. Then create two records:

| Name | Type | Value | TTL |
|---|---|---|---|
| `example.com` (leave name empty) | A | the Elastic IP | 300 |
| `www` | A | the Elastic IP | 300 |

The zone shows an **NS** record with four name servers
(`ns-123.awsdns-45.com`, ...). Copy them.

### 5.3 Point GoDaddy at Route 53

GoDaddy → *My Products* → the domain → **DNS** → **Nameservers** → *Change* →
*I'll use my own nameservers* → paste the four Route 53 name servers
(without the trailing dot) → save.

This replaces GoDaddy's DNS entirely: any records that exist there today
(email MX, verification TXT) stop resolving and must be recreated in the
Route 53 zone first. Propagation usually takes minutes, up to 48 hours.

Check from any machine:

```bash
dig +short NS example.com        # the awsdns name servers
dig +short example.com           # the Elastic IP
dig +short www.example.com       # the Elastic IP
```

> Simpler alternative: leave the name servers at GoDaddy and add the two A
> records in GoDaddy's DNS editor instead. Everything below works the same.
> Use Route 53 only if you want DNS managed inside AWS.

### 5.4 Turn on HTTPS

Only after both `dig` lookups return the Elastic IP. Caddy asks Let's
Encrypt for a certificate on start, and Let's Encrypt validates by
connecting to the domain on port 80; if DNS is not there yet the attempt
fails (Caddy retries with backoff, but repeated failures are rate limited).

With the GitHub Actions deploy: repository → *Settings* → *Secrets and
variables* → *Actions* → **Variables** → add

```text
SITE_ADDRESS = example.com, www.example.com
```

and re-run the *Deploy* workflow. By hand on the instance: put the same
line in `/opt/playup/.env` and run the `docker compose ... up -d` command
from section 2.

Verify:

```bash
curl -sI http://example.com  | head -3      # 308 -> https://example.com/
curl -s  https://example.com/api/health     # {"status":"ok"}
docker compose logs caddy | grep -i "certificate obtained"
```

Renewal is automatic (about 30 days before expiry) as long as the
`caddy-data` volume is kept and ports 80/443 stay open. Never run
`docker compose down -v` on the server: it deletes the certificates and the
database.

### 5.5 If the certificate does not arrive

| Symptom in `docker compose logs caddy` | Cause |
|---|---|
| `no valid A records found` / `NXDOMAIN` | DNS not propagated, or record missing for one of the names in `SITE_ADDRESS` |
| `connection refused` / `timeout` during challenge | Security group does not allow 80/443, or the A record points at an old IP |
| `too many certificates` / `rateLimited` | Volume was wiped repeatedly; wait an hour (failed validations) or a week (duplicate certificates) |
| `CAA record ... prevents issuance` | A CAA record exists that does not include `letsencrypt.org`; add `0 issue "letsencrypt.org"` |

## 6. Things to know before real users

- **Sign-in has no mailer yet.** In production the access code is *not*
  returned by the API; it is written to the backend log
  (`docker compose logs backend | grep "Access code"`). Until a mailer exists,
  only someone with server access can complete a sign-in. Do **not** work
  around this with `PLAYUP_ENVIRONMENT=development` on a public host: that
  returns the code to whoever asks, so anyone could sign in as any email.
- **HTTPS is off until `SITE_ADDRESS` is set** (section 5). Do not let
  people sign in over plain HTTP.
- **No rate limiting** on `/v1/auth/*` or `/v1/groups/join` yet
  (`docs/backend-plan-python.md` §9). Add it in nginx (`limit_req`) or the
  app before the instance is public.
- **The frontend does not call the API yet.** `src/services/apiClient.ts`
  exists but nothing imports it; the UI still runs on `localStorage`. The
  deployed site is therefore the browser-only prototype plus a working API
  at `/api/v1/*` for the cut-over.
- **Single instance only.** Migrations run inside the backend container's
  start command; with more than one backend replica, run them once
  separately and drop them from the `CMD`.
