# SuccessfulSuccess — Meetings

[![Style](https://github.com/dobosevych/SuccessfulSuccess/actions/workflows/style.yml/badge.svg)](https://github.com/dobosevych/SuccessfulSuccess/actions/workflows/style.yml)

A small web app for today's meetings: see what is on today (name, description,
participants) and add a new one from the UI. Built to `SPEC.md`.

- **Frontend** — Next.js (App Router) + shadcn/ui, styled after Canva's visual language
- **Backend** — FastAPI + SQLAlchemy 2 (async) + Alembic
- **Database** — PostgreSQL 17

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

| What | URL |
|------|-----|
| App | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

The backend applies migrations on start.

### Sign-in (Cognito)

Every page except the login page, and every `/api/v1` endpoint, needs a
signed-in user, and each user sees only their own meetings. Sign-in is an AWS
Cognito user pool (`infra/auth.yml`): email + password, and Google when it is
configured. Even for local development the pool lives in AWS (it is free at
this scale):

```bash
make aws-deploy-auth   # create/update the user pool; allows http://localhost:$FRONTEND_PORT/
make aws-auth-env      # prints COGNITO_* lines: paste them into .env
docker compose up -d   # restart so the API and the frontend pick them up
```

**Google sign-in** (optional): in Google Cloud console create an OAuth client of
type *Web application*, put its id and secret in `.env` as `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET`, run `make aws-deploy-auth`, and add the redirect URI it
prints (`https://<prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse`)
to the client's *Authorized redirect URIs*. Without it the Google button says
Google sign-in is not enabled.

The first time someone signs in, the frontend sends their ID token to
`POST /api/v1/me/sync`, which stores their profile (email, name, picture,
provider, last login) in the `users` table. Meetings reference `users.id`, the
Cognito `sub`.

Demo data is per user: `make seed owner=<sub>` adds a few meetings for today to
that user (their `sub` is on the user's page in the Cognito console, or `id` in
`GET /api/v1/me`).

> **Ports already in use?** Every host port is configurable in `.env`
> (`FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`). If you change the frontend
> or backend port, update `CORS_ORIGINS` and `NEXT_PUBLIC_API_BASE_URL` to match —
> the browser talks to the published host port, not the compose service name.

## Common tasks

```bash
make up          # start the stack
make down        # stop it
make down-v      # stop it and drop the database volume
make test        # backend test suite (creates meetings_test automatically)
make lint        # ruff + eslint
make migrate     # alembic upgrade head
make seed owner=<sub>  # demo meetings for today for one user
make psql        # psql shell against the app database
make help        # everything else
```

## Windows

The same `make` targets work on Windows, with Docker Desktop (WSL 2 backend)
and [Git for Windows](https://git-scm.com/download/win) installed. There is no
need to install GNU make first: `make.cmd` in the repository root runs the
Makefile, and when `make.exe` is missing it offers to install it with winget
(`ezwinports.make`) and carries on.

```powershell
Copy-Item .env.example .env
.\make help        # PowerShell only runs scripts from the current folder with .\
.\make up-build
```

In `cmd.exe`, plain `make help` finds `make.cmd`; once make is installed,
`make help` works everywhere.

Every recipe runs in Git's bash (`C:/Program Files/Git` by default; pass
`GIT_HOME=...` if it is installed elsewhere), so `make test`, `make seed`, the
`aws-*` targets and the rest behave as on macOS and Linux. Inside WSL, plain
`make` works as on Linux.

Things that are already taken care of, and why:

- `.gitattributes` checks every file out with LF line endings. Git on Windows
  converts to CRLF by default, and a CRLF `entrypoint.sh` stops the backend
  container with `exec /app/entrypoint.sh: no such file or directory`. A clone
  made before `.gitattributes` existed keeps its CRLF files until you run
  `git rm --cached -r . && git reset --hard` (this discards local changes).
- File-change events from a Windows folder do not reach the containers, so hot
  reload polls: `WATCHPACK_POLLING` for Next.js, `WATCHFILES_FORCE_POLLING` for
  uvicorn. For faster reloads keep the clone inside WSL rather than on `C:\`.
- Git's bash rewrites arguments that look like paths (`/aws` becomes
  `C:/Program Files/Git/aws`); the Makefile turns that off with
  `MSYS_NO_PATHCONV`.
- Keep `.env` with LF line endings (copying `.env.example` does): `make` reads
  it directly, and a CRLF `.env` leaves a stray `\r` on every value.

## Deploy to AWS

`infra/` holds four CloudFormation templates: `auth.yml` (Cognito sign-in),
`ecr.yml` (image registry), `backend.yml` (API and database) and `frontend.yml`
(site). `make` reads `.env`,
so the `aws-*` targets pick up the credentials and settings from there; `.env` is
gitignored, so real keys never reach the repository. The AWS CLI runs in the
`amazon/aws-cli` container, so nothing has to be installed on the host besides
Docker (`AWS=aws make aws-deploy` uses a local CLI instead, which is noticeably
faster).

```
browser ──https──→ Lambda function URL (static Next.js + FastAPI) → private RDS PostgreSQL :5432
```

Every resource lives in `AWS_REGION`, **us-east-1** by default. There is no
CloudFront, API Gateway, public S3 bucket, or load balancer. The static frontend
and API share one HTTPS Lambda function URL and origin.

Every stack is tagged `PROJECT_NAME=<value of PROJECT_NAME>`, and every resource
that accepts tags also carries it explicitly in the templates. Filter by it in
Cost Explorer or Resource Groups to see everything the project owns.

### One command

```bash
make aws-whoami   # check the credentials work
make aws-deploy   # deploy Cognito, API and frontend on one HTTPS URL
```

`aws-deploy` creates Cognito, builds the frontend into the Lambda image, deploys
the API and frontend together, then updates Cognito with the function URL for
Google sign-in callbacks. `aws-deploy-frontend` repeats that combined build and
deploy when frontend code changes.

The backend Lambda sits in a VPC with no internet access, so it cannot download
the pool's signing keys itself; `aws-deploy-backend` fetches them
(`<issuer>/.well-known/jwks.json`) and passes them in as `COGNITO_JWKS`.
The frontend uses relative `/api/v1` URLs, so production requests stay on the
same HTTPS origin and need no separate CORS configuration.

Fill these in `.env` first:

```bash
AWS_ACCESS_KEY_ID=...        # an IAM user, not root access keys
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
PROJECT_NAME=successfulsuccess   # prefixes every resource name, and the PROJECT_NAME tag
AWS_DB_PASSWORD=...          # 8-41 chars, [A-Za-z0-9_-] only
AWS_CORS_ORIGINS=            # empty: use CORS_ORIGINS for local development
GOOGLE_CLIENT_ID=            # optional: Google sign-in (see "Sign-in" above)
GOOGLE_CLIENT_SECRET=
```

### GitHub Actions deployment

The `CI/CD` workflow runs backend Ruff checks and tests plus frontend ESLint on
pushes to `main`. Only after those checks pass does it build the combined
frontend/API Lambda image, push it to ECR tagged with the full commit SHA, and
update the Lambda stack through CloudFormation. Roll back to an earlier image
with `make aws-deploy-image IMAGE_TAG=<full-commit-sha>`; the ECR lifecycle rule
retains the five most recent images.

Bootstrap the deploy role once from PowerShell using the AWS credentials in
your local `.env`:

```powershell
.\make aws-deploy-github-actions
.\make aws-github-actions-role-arn
```

The bootstrap identity needs permission to create the GitHub OIDC provider and
IAM role. Copy the printed ARN into the GitHub repository's **Settings → Secrets
and variables → Actions → Variables** as `AWS_ROLE_ARN`. It is an identifier,
not a secret. The workflow needs no AWS access-key secrets.

The role's trust policy requires `aud=sts.amazonaws.com` and this exact `sub`:

```text
repo:KarinaMadiar@269516340/SuccessfulSuccess@1398660644:ref:refs/heads/main
```

That immutable subject permits only this repository's `main` branch to assume
the role; it does not trust the upstream repository, other forks, branches, or
pull requests. The role can push images to this project's ECR repository and
update/invoke only its backend Lambda stack/function.

### 1. Backend — Lambda function URL, RDS PostgreSQL

```bash
make aws-deploy-backend   # ECR + build & push + create/update the stack + migrate, prints the URL
```

The app runs as one **Lambda function** from a container image
(`backend/Dockerfile.lambda`): FastAPI is adapted to Lambda by
[Mangum](https://github.com/Kludex/mangum) in `app/lambda_handler.py`, and serves
the Next.js static export from the same image. The function URL
(`https://<id>.lambda-url.<region>.on.aws`) is both the website and API origin.
`backend/Dockerfile` stays the local/compose image.

The database is a **single-AZ RDS for PostgreSQL** instance (`db.t4g.micro`)
with 20 GiB of encrypted `gp3` storage. It stays running rather than pausing
when idle; the Free account plan's eligibility and usage limits apply.

The function sits in the account's **default VPC**, next to the database, so the
database is never public: its security group only accepts the function's. Static
assets and API requests share the same Lambda; the function needs no NAT gateway.

Migrations run in the same function: invoked directly with
`{"action": "migrate"}` it applies them instead of serving a request. Function
URL events never carry that key, so no web request can trigger it.
`make aws-deploy-backend` invokes it after every deploy, so migrations run once
per deploy rather than racing on each cold start.

The first deploy takes several minutes while RDS provisions the instance. It is
idempotent — run it again to ship a new version. The image is passed to the
stack by digest, not by tag, so every push really does update the function. If
the stack is still busy with an earlier update, the target waits for it rather
than failing.

| Command | What it does |
|---------|--------------|
| `make aws-url` | Print the app/API URL (`/`, `/docs`, and `/health`) |
| `make aws-status` | Stack outputs plus the API function's state |
| `make aws-logs` | Follow the function logs from CloudWatch |
| `make aws-migrate` | Apply migrations again on their own |
| `make aws-destroy` | Delete every stack (asks first — the database goes too) |

The image is built for `AWS_LAMBDA_ARCH` (`x86_64` by default).
`AWS_LAMBDA_ARCH=arm64 make aws-deploy-backend` is ~20% cheaper and builds
natively on Apple Silicon. The image platform follows this variable, so the two
cannot drift apart. The build passes `--provenance=false` because Lambda rejects
the multi-manifest image index that BuildKit otherwise pushes.

### 2. Frontend — served by the Lambda function URL

```bash
make aws-deploy-frontend   # rebuild and deploy the combined frontend/API image
make aws-frontend-url      # print the shared site/API URL
```

The Next.js **static export** is built with Cognito settings and bundled into the
Lambda container image. FastAPI serves route `index.html` files, JavaScript,
styles, and images alongside `/api/v1`, all from the same HTTPS function URL.
This avoids CloudFront account verification and separate production CORS
configuration. Function URLs do not support custom domains.

### Cost

- **Lambda** — 1M requests and 400,000 GB-seconds a month, always free. Each
  page, API call, and static asset request invokes the function.
- **RDS PostgreSQL** is a continuously running instance plus storage. Check the
  AWS Free Tier page and account-plan limits for current eligibility; after
  allowances or plan changes, normal RDS charges apply.
- **ECR** — 500 MB in the free tier; the lifecycle policy keeps five images.

`make aws-destroy` deletes everything, database included, with no snapshot left
behind. Accounts opened after July 2025 get credits instead of the classic free
tier — check your billing console rather than assuming.

### Known trade-offs

- **No custom domain**: Lambda function URLs cannot take one. A custom domain
  would require another HTTPS entry point, such as API Gateway or CloudFront.
- The database password reaches the function as a plain environment variable.
  Moving it to SSM Parameter Store or Secrets Manager is the first thing to
  harden.
- **Cold starts**: the first request after a few idle minutes waits ~1–2 s while
  Lambda starts the container. The database itself does not pause.
- Every warm instance holds one database connection. Nothing is reserved by
  default (`MaxConcurrency=0`): new accounts have a Lambda concurrency limit of
  10 in total and Lambda refuses to reserve any of it, so that limit is the cap,
  well under the cluster's connection limit. Once the limit is raised, set
  `MaxConcurrency` to keep a spike off the database; requests beyond it get
  HTTP 429. RDS Proxy is the proper fix, and it is not free.
- The function URL is public: FastAPI checks the Cognito access token on every
  `/api/v1` request, but there is no request throttling in front of it beyond
  the concurrency limit.
- Cognito sends its emails (sign-up codes, password resets) itself, capped at 50
  a day. Switch the pool to SES before real traffic.
- Signing up with a password and later with Google under the same email makes
  two separate Cognito users, with separate meetings. Linking them needs a
  pre-sign-up Lambda trigger.
- Deleting the backend stack takes ~20 minutes: Lambda releases its VPC network
  interfaces slowly, and the security groups wait for them.
- One RDS instance: there is no standby to fail over to.

## API

Base path `/api/v1`. Full schema at `/docs`. Everything under it needs
`Authorization: Bearer <Cognito access token>` (`401` otherwise) and only ever
touches the caller's own meetings: someone else's meeting is a `404`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/meetings?date=&q=&limit=&offset=` | Meetings overlapping a day (today by default) |
| `GET` | `/meetings/{id}` | One meeting |
| `POST` | `/meetings` | Create a meeting |
| `PUT` | `/meetings/{id}` | Replace a meeting's details and participants |
| `DELETE` | `/meetings/{id}` | Delete a meeting and its participants |
| `GET` | `/me` | The signed-in user's profile |
| `POST` | `/me/sync` | Store the profile from the user's ID token (after sign-in) |
| `GET` | `/health` | Liveness + database check |

Every error uses one envelope:

```json
{ "error": { "code": "validation_error", "message": "…", "details": [{ "field": "ends_at", "message": "…" }] } }
```

### Time handling

Timestamps are stored in UTC and **served with the application timezone's offset**
(`APP_TIMEZONE`, default `Europe/Kyiv`). "Today" is that timezone's calendar day,
and a meeting is listed if it *overlaps* the day — so a 23:00–00:30 meeting appears
on both days. The UI reads the wall-clock time straight from the offset the API
sent, so every client shows the same time as the day it was listed under.

## Layout

```
backend/    FastAPI app (api → services → repositories → models), Alembic, tests
frontend/   Next.js app, shadcn/ui primitives in components/ui
infra/      CloudFormation templates behind the aws-* targets
docker-compose.yml
```

## Continuous integration

`.github/workflows/style.yml` runs on every push to `main` and gates style only:

| Job | Runs | Against |
|-----|------|---------|
| Backend — ruff | `ruff check` (GitHub annotations) + `ruff format --diff` | `backend/` |
| Frontend — ESLint | `npm ci` + `npm run lint` | `frontend/` |

Ruff is pinned to the version the backend image ships (0.16.6) and Node matches
the container's Node 22, so CI and local containers agree on what passes.

Reproduce either job locally:

```bash
make lint                                   # both, through the running containers
cd backend  && uvx ruff@0.16.6 check . && uvx ruff@0.16.6 format --diff .
cd frontend && npm ci && npm run lint
```

There is no deploy (CD) stage — no target is configured yet.

## Development notes

- The backend bind-mounts `./backend`, so `uvicorn --reload` picks up edits live.
- The frontend runs `next dev` in the container with the same bind mount.
- Backend tests run against a real Postgres (`meetings_test`), truncating tables
  between tests; `make test` creates that database if it is missing
