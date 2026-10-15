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
update/invoke only its backend Lambda stack/function. It also has read-only
`ec2:DescribeSecurityGroups`, `ec2:DescribeSubnets`, and `ec2:DescribeVpcs`
access so CloudFormation can validate the Lambda's VPC configuration during
image updates. It can describe only this project's RDS instance to resolve its
Lambda endpoint. It can read and pass only the generated backend Lambda
execution role, and only to `lambda.amazonaws.com`.

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
Function URLs do not support custom domains natively.

### 3. CloudFront CDN (optional)

```bash
make aws-deploy-cloudfront   # deploy CloudFront in front of the Lambda backend and update Cognito
make aws-cloudfront-url      # print the https://<id>.cloudfront.net URL
```

`infra/cloudfront.yml` provisions a CloudFront distribution that sits in front of the
Lambda function URL. It caches static assets (`/_next/static/*`, `/static/*`) at global
edge locations, passes API requests directly through with authentication preserved, and
automatically updates Cognito's redirect URLs with the CloudFront domain. Custom domains
are supported via `CLOUDFRONT_DOMAIN` and `CLOUDFRONT_CERT_ARN`.

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

---

## Module 5: Event-Driven Architecture — Weekly Reports

A decoupled, event-driven pipeline that computes weekly meetings insights, saves CSV reports to S3, and delivers them via Amazon SES with zero synchronous blocking.

### Architecture

```
                                  [EventBridge Scheduler]
                                   cron(0 7 ? * MON *)
                                            │
               make report-now              │ (command)
             (on-demand trigger)            ▼
                      │              [ SQS Queue ] ──(after 3 fails)──→ [ SQS DLQ ]
                      └─────────────► report-requests                   report-requests-dlq
                                            │
                                            │ EventSourceMapping (batchSize=1)
                                            ▼
                               [ Lambda: report-builder ]  (VPC, no NAT)
                                      │         │
                   queries PostgreSQL │         │ writes CSV via Gateway VPCEndpoint
                                      ▼         ▼
                                 [ RDS DB ]   [ S3 Bucket ]
                                              reports/*.csv
                                                    │
                                                    │ s3:ObjectCreated:* (event)
                                                    ▼
                                  [ Lambda: report-mailer ] (outside VPC, public internet)
                                                    │
                                                    │ sesv2:send_email (MIME with attachment)
                                                    ▼
                                              [ Amazon SES ] ──→ Recipient Inbox
```

### Key Components

1. **EventBridge Scheduler (`WeeklyReportSchedule`)**:
   Runs every Monday at 07:00 (`Europe/Kyiv` timezone), dispatching a command message `{"week": null, "source": "schedule"}` to SQS.
2. **Amazon SQS (`ReportRequestsQueue` + `ReportRequestsDlq`)**:
   Buffers requests with `VisibilityTimeout = 360s` (6x builder timeout). Failed messages retry up to 3 times before dead-lettering into the DLQ.
3. **Builder Lambda (`successfulsuccess-report-builder`)**:
   Runs in the private VPC with access to PostgreSQL. Resolves target week (or defaults to previous ISO week), aggregates insights (total meetings, duration, week-over-week deltas, top 5 longest meetings, and organiser/participant breakdowns), and writes the CSV to `s3://<bucket>/reports/<week>.csv` via the free S3 Gateway VPC Endpoint.
4. **Mailer Lambda (`successfulsuccess-report-mailer`)**:
   Triggered asynchronously by S3 `s3:ObjectCreated:*` notifications. Runs outside the VPC, downloads the CSV, builds a multipart MIME message with Python `email.message.EmailMessage`, and transmits it via Amazon SES (`sesv2.send_email`).
5. **Amazon SES**:
   Domain identity (`successful.pp.ua`) with Easy DKIM CNAME records, plus verified recipient address (`madiar.pn@ucu.edu.ua`).

### Report Commands

```bash
make aws-deploy-reports       # Deploy infra/reports.yml stack (S3, SQS, Lambdas, Schedule, SES)
make report-now WEEK=2026-W41 # Request on-demand report generation via SQS
make report-schedule-test     # Trigger builder using schedule message payload
make report-dlq-test          # Test DLQ routing with poison pill payload
make report-dlq-redrive       # Redrive failed messages from DLQ back to primary queue
make report-s3-ls             # List generated reports in S3 bucket
make report-logs-builder      # Tail CloudWatch logs of builder Lambda
make report-logs-mailer       # Tail CloudWatch logs of mailer Lambda
```

---

## Lab 5 Submission Deliverables & Written Answers

### 1. Link to Commit
Commit adding report logic (`app/reports/weekly.py`), builder handler (`app/reports/lambda_handler.py`), mailer handler (`app/reports/mailer.py`), CloudFormation template (`infra/reports.yml`), test suites, and Makefile targets.

### 2. S3 Reports Listing (`aws s3 ls`)
```text
Reports in s3://successfulsuccess-reports-584503398119/reports/:
2026-10-15 17:52:14        692 reports/2026-W40.csv
2026-10-15 17:51:46        635 reports/2026-W41.csv
```
- `reports/2026-W41.csv`: Generated automatically by schedule trigger.
- `reports/2026-W40.csv`: Generated on-demand via `make report-now WEEK=2026-W40`.

### 3. CloudWatch Log Lines (One per Trigger)

- **Schedule Trigger (Builder)**:
  ```text
  [INFO] 2026-10-15T17:51:45.061Z 544d8a9c-b53a-5c75-8e97-e9d7a1d028eb report-builder triggered: trigger=schedule week=2026-W41
  ```
- **SQS Message Trigger (Builder)**:
  ```text
  [INFO] 2026-10-15T17:50:39.492Z 87ee5a1a-47c5-5234-afd1-3951535f77c2 report-builder triggered: trigger=sqs week=2026-W41
  ```
- **S3 Upload Trigger (Mailer)**:
  ```text
  [INFO] 2026-10-15T17:50:41.376Z fb092d82-5c75-49e5-a5f9-a04972b1ba2d report-mailer triggered: trigger=s3 bucket=successfulsuccess-reports-584503398119 key=reports/2026-W41.csv
  ```

---

### Part 3, Step 7 Written Answers

#### Question 1: Handling Duplicate S3 ObjectCreated Events & Idempotency
**Question**: *The mailer got the same ObjectCreated event twice, and the person got two identical emails. Where would you store "this report was already sent", and what would the key be?*

**Answer**:
To make the mailer idempotent and prevent duplicate email dispatch when an S3 file is overwritten or when S3 delivers an `ObjectCreated` event more than once:
- **Storage**: Store the deduplication state in **Amazon DynamoDB** (or Redis / a lightweight state table) with atomic conditional writes (`attribute_not_exists(pk)`).
- **Key**: The partition key would be `report_sent#<bucket>#<key>#<object_eTag_or_versionId>` (or simply `report_sent#reports/<week>.csv` if only one email per week is permitted).
- **Behavior**: Before dispatching via SES, the mailer executes `PutItem` with `ConditionExpression="attribute_not_exists(pk)"`. If the key already exists, the write fails with `ConditionalCheckFailedException`, allowing the mailer to log `"Duplicate event ignored: report already sent"` and exit cleanly without sending a duplicate email. A TTL (e.g., 30 days) can be attached to automatically clean up old deduplication keys.

---

#### Question 2: VPC Lambda SES Connectivity & Cost Tradeoffs
**Question**: *The builder in the VPC could not reach SES. List three ways to fix that, with their monthly cost: a NAT gateway, a VPC interface endpoint for SES, and the split you built. Which would you choose with ten more emails a week? With a million?*

**Answer**:
1. **NAT Gateway**:
   - *Cost*: ~$0.045/hour (~$32.40/month per AZ) + $0.045/GB data processed + Elastic IP cost (~$3.65/mo) = **~$36.00/month**.
2. **VPC Interface Endpoint (AWS PrivateLink for SES)**:
   - *Cost*: ~$0.01/hour per AZ (~$7.20/month for single AZ, or ~$14.40/month for 2 AZs) + $0.01/GB data processed = **~$7.20 - $14.40/month**.
3. **The Split Built in Lab 5 (Two Lambdas connected via S3 & Gateway Endpoint)**:
   - *Cost*: S3 Gateway VPC Endpoint is **$0.00 (free)**. S3 storage and Lambda invocations at low volume fall well within the AWS Free Tier, costing **$0.00/month**.
- **Choice with 10 more emails a week**:
  The **Split architecture built in this lab ($0.00/mo)**. Paying $14 to $36/month for 10 emails is a waste of cloud budget.
- **Choice with a million emails a week**:
  The **VPC Interface Endpoint (~$14.40/mo + SES charges)** if synchronous transactional emails from backend handlers are required; or continue using the **Split / SQS architecture** if emails are batch/event-driven reports, because SQS and S3 easily absorb massive surges with built-in retries, backpressure, and zero NAT gateway bottlenecks.

---

#### Question 3: Long-Lived Download Links vs Presigned URL Expiration
**Question**: *You could send a presigned S3 link instead of an attachment. A presigned URL signed with a Lambda role's temporary credentials stops working when those credentials expire, often within hours. How would you send a link that works for a week?*

**Answer**:
Temporary STS credentials issued to Lambda execution roles expire within 15 minutes to 12 hours; any presigned URL created using those credentials becomes invalid as soon as the temporary credentials expire, regardless of the `ExpiresIn=604800` parameter.
To send a download link valid for a full week (7 days):
1. **CloudFront Signed URLs**: Distribute the private S3 bucket through CloudFront using Origin Access Control (OAC). Sign the URL using CloudFront's RSA private key (managed via CloudFront Key Groups). CloudFront signed URLs are evaluated at CloudFront edge caches and can remain valid for days, weeks, or months without STS credential expiration limits.
2. **Sign with Long-Lived IAM Credentials**: Use an IAM User with restrictive S3 read permissions whose credentials do not expire, stored securely in AWS Secrets Manager or Parameter Store. SigV4 URLs generated with permanent IAM user credentials can have a maximum validity of 7 days (604,800 seconds).
3. **Application Download Endpoint**: Send a permanent application link (e.g. `https://successful.pp.ua/api/v1/reports/2026-W41`). When the user clicks it, the authenticated backend generates a short-lived (e.g. 5-minute) redirect to S3 on the fly.

---

### Class Discussion Guide

1. **Commands vs Events**:
   - In the cake shop: An *order slip* ("Bake Napoleon, 8 portions") is a **command** directed at the bakers. A *cake placed on the shelf* is an **event** ("CakeBaked").
   - In Lab 5: EventBridge Scheduler putting `{"week": null, "source": "schedule"}` onto SQS is a **command** (telling the builder to run). The S3 PutObject resulting in `s3:ObjectCreated` is an **event** (a past fact). The builder does not know the mailer exists.
2. **Idempotency**:
   - Writing `reports/2026-W40.csv` to S3 is **idempotent**: running it ten times overwrites the exact same file and leaves one CSV.
   - Sending an email via SES is **not idempotent**: calling SES ten times sends ten distinct emails to the recipient's inbox.
3. **Eventual Consistency**:
   - If a meeting is edited at 07:01, the 07:00 report reflects the database state at snapshot execution time. This is standard eventual consistency for analytical reporting.
4. **Adding Slack Notifications**:
   - To add a Slack notification when a report is ready, change **nothing** in the builder Lambda. Simply subscribe a new Lambda function to the same S3 `s3:ObjectCreated:*` event (or route S3 events via EventBridge/SNS to multiple subscribers).
5. **Redis vs RabbitMQ**:
   - For financial payments where losing a message is catastrophic, **RabbitMQ** (or SQS) is preferred over Redis because RabbitMQ supports explicit consumer ACKs, durable disk queues, and dead-letter exchanges out of the box, whereas standard Redis list pops remove messages immediately upon retrieval.
6. **SQS Visibility Timeout vs Lambda Timeout**:
   - The SQS visibility timeout must exceed the function timeout (recommended >= 6x). If visibility timeout were shorter than function execution time, SQS would assume the first worker died and re-deliver the message to a second worker while the first is still processing, causing duplicate concurrent execution.

