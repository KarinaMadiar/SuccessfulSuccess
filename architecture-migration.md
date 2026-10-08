# AWS architecture migration

How the AWS deployment of the meetings app changed, from the first committed
version to what runs now. The local `docker compose` setup did not change along
the way. The current deploy instructions are in the [README](../README.md#deploy-to-aws).

## Summary

| | Before (initial commit) | After (now) |
|---|---|---|
| Region | eu-central-1 (plus a us-east-1 certificate for CloudFront) | **us-east-1** for everything |
| API compute | ECS Fargate task (always on) behind an Application Load Balancer | **Lambda** container image, called through its **function URL** |
| Database | RDS PostgreSQL `db.t3.micro` (always on) | **Aurora Serverless v2** PostgreSQL, 0–1 ACU, pauses when idle |
| Frontend | S3 + CloudFront, with `/api/*` proxied to the ALB | Private **S3** bucket + **CloudFront** (origin access control), on the flat-rate **Free plan** |
| Frontend → API | Same origin through CloudFront (no CORS) | Browser calls the function URL directly; FastAPI CORS allows the site's origins |
| Custom domains | API on the ALB (regional certificate), site on CloudFront (us-east-1 certificate) | Site only: `demo.your-domain.com` (us-east-1 certificate). The API keeps its function URL |
| Deploy order | Backend and frontend deployed separately | `make aws-deploy`: backend first, then the frontend built against the backend's URL |
| Idle cost | ALB + Fargate task + RDS instance billed around the clock | Close to zero: Lambda and a paused Aurora bill nothing for compute |
| Tagging | Stack names only | `PROJECT_NAME` tag on every stack and on every resource that takes tags |

## Stage 0 — the initial architecture

![Stage 0: CloudFront in front of S3 and an ALB, a Fargate task and an RDS instance](diagrams/stage0-initial.png)

- **Backend** (`infra/backend.yml`): an ECS cluster running one Fargate task
  (0.25 vCPU) of the FastAPI image behind an Application Load Balancer, in the
  default VPC. The task had a public IP so it could pull from ECR without a NAT
  gateway. An RDS `db.t3.micro` PostgreSQL instance held the data.
- **Frontend** (`infra/frontend.yml`): one CloudFront distribution in front of
  two origins, the S3 bucket for the static export and the ALB for `/api/*`. The
  browser saw a single origin, so there was no CORS and no mixed-content problem
  with the plain-HTTP ALB.
- **Certificates** (`infra/certificate.sh`): `make aws-cert` issued the API's
  certificate in the stack's region for the ALB, and `make aws-frontend-cert`
  issued the site's certificate in **us-east-1**, the only region CloudFront
  reads certificates from.
- **Cost profile**: the ALB, the Fargate task and the RDS instance all billed
  around the clock. `make aws-stop` could scale the task to zero, but not the
  ALB or the database.

## Stage 1 — Lambda and S3 website hosting (work in progress, never committed)

This was the uncommitted state of the repository when the migration below
started.

![Stage 1: an S3 website endpoint over HTTP, and a Lambda function URL in front of RDS](diagrams/stage1-lambda-s3-website.png)

- **ECS, the ALB and the certificates were removed.** The API became a Lambda
  function built from `backend/Dockerfile.lambda`, running the same FastAPI app
  through [Mangum](https://github.com/Kludex/mangum) (`app/lambda_handler.py`)
  and exposed through its function URL. The function sits in the default VPC
  next to the database, with no NAT gateway.
- **Migrations** moved into the function: invoked directly with
  `{"action": "migrate"}` it runs Alembic. `make aws-deploy-backend` calls it
  once after every deploy.
- **CloudFront was dropped**, because the account could not create
  distributions at that point. The site was served from an S3 website endpoint
  over plain HTTP.
- The database was still an RDS `db.t3.micro`, and everything was in
  eu-central-1.

## Stage 2 — this migration, step by step

### 1. RDS instance → Aurora Serverless v2

`AWS::RDS::DBInstance` (`db.t3.micro`) was replaced by an `AWS::RDS::DBCluster`
(`aurora-postgresql`) with one `db.serverless` writer instance.

- Scaling: `MinCapacity: 0`, `MaxCapacity: 1`. This is the smallest Aurora
  allows: 0 means paused, and 1 ACU is the lowest maximum.
- `SecondsUntilAutoPause: 300`, the shortest delay allowed. An idle deployment
  pays only for storage.
- Resuming from a pause takes about 15 s, so the Lambda timeout went from 29 s
  to 60 s.
- The engine version defaults to the region's current one, which supports
  pausing at 0 ACU.

### 2. Region: eu-central-1 → us-east-1

`AWS_REGION` became `us-east-1` in `.env`, `.env.example` and as the Makefile
default. With everything in us-east-1, CloudFront, its ACM certificate and its
WAF web ACL all live in the same region as the rest of the stacks.

A full stage-1 deployment was already running in eu-central-1: a backend stack
with an Aurora cluster, plus an ECR stack. It was deleted with
`make aws-destroy AWS_REGION=eu-central-1`. A check afterwards found no stacks,
databases, repositories, functions, log groups, security groups or
`PROJECT_NAME`-tagged resources left in that region. No data was carried over.

### 3. Lambda function URL as the backend URL

The function URL stays the public API endpoint:
`https://<id>.lambda-url.us-east-1.on.aws`. The frontend build bakes it in as
`NEXT_PUBLIC_API_BASE_URL`, read from the backend stack's `ApiUrl` output.

### 4. Deploy order: backend first, then frontend

- A new `make aws-deploy` target runs `aws-deploy-backend` and then
  `aws-deploy-frontend`.
- The frontend target refuses to run until the backend stack exists, because it
  needs the API URL for the build.
- CORS follows the frontend. With `AWS_CORS_ORIGINS` empty, the backend deploy
  reads the frontend stack's `AllowedOrigins` output: the CloudFront URL plus
  any custom domain. On the very first deploy the frontend does not exist yet,
  so the API starts with `*`, and the next backend deploy narrows it.

### 5. Frontend: S3 website → S3 + CloudFront

- **S3 + CloudFront.** Once the account could create distributions again, the
  frontend moved from the S3 website endpoint back to S3 + CloudFront.
- **What the current template creates:**
  - A **private** S3 bucket with all public access blocked. CloudFront reads it
    through **origin access control**, and the bucket policy admits only this
    distribution.
  - A **CloudFront Function** that maps clean URLs (`/meetings/new`,
    `/meetings/new/`) onto the export's `index.html` files. S3's REST endpoint
    has no index documents.
  - A redirect from HTTP to HTTPS, and 403/404 responses mapped to the
    export's `404.html` with a 404 status.
- **Deploy.** `make aws-deploy-frontend` syncs the build to the bucket. HTML is
  uploaded with `no-cache` and hashed assets with a one-year immutable header,
  and every deploy invalidates `/*`.

### 6. CloudFront flat-rate Free plan

The distribution is subscribed to CloudFront's **Free** plan through
`AWS::PricingPlanManager::Subscription`. The plan is $0 a month for 1M requests
and 100 GB, with no overage charges, and includes WAF and DDoS protection.

- The plan requires a WAF web ACL of its own on the distribution. The stack
  creates one (`Scope: CLOUDFRONT`, default action `Allow`).
- `PriceClass_100` was removed, because the plan covers every edge location.
- AWS allows 3 Free plans per account and refuses them while the account is on
  the AWS Free Tier. `AWS_CLOUDFRONT_PLAN=PAY_AS_YOU_GO` skips the
  subscription in that case.
- The stack output `PricingPlanStatus` reads `ACTIVE` once the plan applies.

### 7. Custom domain for the frontend

- The domain is set in `.env`:
  `AWS_FRONTEND_DOMAIN=demo.your-domain.com`.
- `infra/certificate.sh` was restored for this. `make aws-frontend-cert`
  requests the certificate in us-east-1 and waits for DNS validation.
- `make aws-deploy-frontend` then adds the domain as a CloudFront alias with
  that certificate. If a Route 53 zone exists it also creates A/AAAA alias
  records; otherwise it prints the CNAME to add.
- `your-domain.com` is hosted outside Route 53, so two CNAME records are added
  manually at its DNS provider:
  - the ACM validation record `_<token>.demo` → `_<token>.acm-validations.aws`
  - `demo` → the distribution's `*.cloudfront.net` name

### 8. Tagging

Every stack is deployed with `--tags PROJECT_NAME=<PROJECT_NAME>`. Every
resource that supports tags also sets them explicitly in the templates:

```yaml
Tags:
  - Key: PROJECT_NAME
    Value: !Ref ProjectName
```

This covers the ECR repository, security groups, the DB subnet group, the
Aurora cluster and instance, the IAM role, the log group, the Lambda function,
the S3 bucket, the WAF web ACL and the CloudFront distribution.

Some resources cannot take tags: the function URL, Lambda permissions, origin
access control, CloudFront Functions, Route 53 records and the pricing-plan
subscription.

## Problems hit along the way

| Problem | Cause | Fix |
|---|---|---|
| First us-east-1 backend deploy rolled back: *"ReservedConcurrentExecutions … decreases account's UnreservedConcurrentExecution below its minimum value of [10]"* | New accounts have a Lambda concurrency limit of 10, and Lambda always keeps 10 unreserved, so reserving 20 was impossible | `MaxConcurrency` now defaults to `0`, meaning nothing is reserved. The account limit of 10 is already below the database's connection limit. |
| The retry failed: stack *"is in ROLLBACK_COMPLETE state and can not be updated"* | A stack whose first create fails can only be deleted | The deploy targets now delete a `ROLLBACK_COMPLETE` stack before retrying (`clear-failed-create`). Such a stack holds no resources. |

## Current architecture

![Current architecture: CloudFront Free plan with WAF in front of a private S3 bucket; the frontend calls a Lambda function URL; Lambda reaches Aurora Serverless v2](diagrams/stage2-current.png)

| Stack | Template | Contents |
|---|---|---|
| `demo-ecr` | `infra/ecr.yml` | ECR repository for the Lambda image (keeps 5 images) |
| `demo-backend` | `infra/backend.yml` | Lambda function + function URL, Aurora Serverless v2 cluster, security groups, IAM role, log group |
| `demo-frontend` | `infra/frontend.yml` | S3 bucket, CloudFront distribution + function, origin access control, WAF web ACL, Free plan subscription, optional Route 53 records |

| Command | What it does |
|---|---|
| `make aws-deploy` | Backend, then frontend |
| `make aws-deploy-backend` | Build and push the image, deploy the backend stack, run migrations |
| `make aws-frontend-cert` | Issue the us-east-1 certificate for `AWS_FRONTEND_DOMAIN` |
| `make aws-deploy-frontend` | Deploy the frontend stack, build against the API URL, upload, invalidate |
| `make aws-destroy` | Delete all three stacks, database included |

## Remaining steps

1. **Certificate:** add the ACM validation CNAME at the DNS provider, and let
   `make aws-frontend-cert` finish.
2. **Frontend:** run `make aws-deploy-frontend` to attach the domain, the web
   ACL and the Free plan.
3. **Backend:** run `make aws-deploy-backend` so CORS allows the CloudFront URL
   and the custom domain instead of `*`.
4. **Hardening:** move the database password from a Lambda environment variable
   to SSM Parameter Store or Secrets Manager.
