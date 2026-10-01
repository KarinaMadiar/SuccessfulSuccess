1. Purpose

This file is the implementation specification for the repository structure and
the contracts between its parts.

The repository is a monorepo containing the frontend, backend, database
configuration, migrations, tests, and Docker Compose configuration.

This document describes structure and contracts. It does not contain
implementation code.

The application is a meetings app: the main page shows today's meetings and
the user can create a meeting from the UI.

2. Repository layout

SuccessfulSuccess/
├── README.md
├── SPEC.md
├── PROJECT.md
├── docker-compose.yml
├── .env.example
├── Makefile
├── backend/
└── frontend/

backend/

Purpose: the FastAPI HTTP API, database access, domain models, validation,
business rules, migrations, and backend tests.

The backend is divided by responsibility:

backend/
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── entrypoint.sh
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
└── app/
    ├── __init__.py
    ├── main.py
    ├── config.py
    ├── errors.py
    ├── db.py
    ├── models/
    ├── schemas/
    ├── repositories/
    ├── services/
    └── api/

Responsibilities:

main.py — creates the FastAPI application, configures CORS, mounts
routers, and exposes /health.

config.py — application settings loaded from environment variables.

errors.py — common API error envelope and exception handlers.

db.py — asynchronous SQLAlchemy engine, session factory, and database
session dependency.

models/ — SQLAlchemy ORM models.

schemas/ — Pydantic request/response models.

repositories/ — database queries only; no HTTP concerns.

services/ — business rules, invariants, and timezone/day-window logic.

api/ — HTTP routing only; validates input, calls services, and maps
results to response schemas.

alembic/ — database migrations.

tests/ — backend tests if present in the repository structure.

frontend/

Purpose: the Next.js UI and the client-side API/data layer.

The structure follows the application specification:

frontend/
├── Dockerfile
├── package.json
├── next.config.ts
├── tsconfig.json
├── components.json
├── tailwind.config.ts
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── globals.css
│   └── meetings/
│       └── new/
├── components/
│   ├── ui/
│   ├── providers.tsx
│   ├── today-page.tsx
│   ├── app-header.tsx
│   ├── meeting-list.tsx
│   ├── meeting-card.tsx
│   ├── create-meeting-dialog.tsx
│   └── participants-input.tsx
├── lib/
│   ├── api.ts
│   ├── types.ts
│   ├── datetime.ts
│   └── utils.ts
└── hooks/
    └── use-meetings.ts

Responsibilities:

app/ — Next.js routes, layout, global styles, and meeting route.

components/ui/ — shadcn/ui primitives.

components/ — application UI components.

providers.tsx — TanStack Query and tooltip providers.

lib/api.ts — typed HTTP client for the backend.

lib/types.ts — frontend types matching backend response contracts.

lib/datetime.ts — date/time formatting.

hooks/use-meetings.ts — TanStack Query hooks for meeting data.

3. Runtime architecture

There are exactly three runtime services:

frontend (:3000)
      |
      | HTTP/JSON
      v
backend (:8000)
      |
      | asyncpg / SQLAlchemy 2
      v
postgres (:5432)

The frontend calls the backend directly using a configurable API base URL.

The backend uses PostgreSQL for persistent data.

PostgreSQL data is stored in a named Docker volume.

The server stores timestamps as UTC TIMESTAMPTZ.

The application timezone used to determine "today" is configured by
APP_TIMEZONE, whose default is Europe/Kyiv.

4. Backend API contract

The API prefix is:

/api/v1

GET /api/v1/meetings

Returns meetings for the requested day.

Without a date query parameter, the service uses today's date in
APP_TIMEZONE.

The result is sorted by:

starts_at ASC, name ASC

The response shape is:

{
  "items": [
    {
      "id": "uuid",
      "name": "Sprint planning",
      "description": "Plan the next two weeks",
      "location": "Room 3",
      "starts_at": "2026-09-10T10:00:00+03:00",
      "ends_at": "2026-09-10T11:00:00+03:00",
      "participants": [
        {
          "id": "uuid",
          "name": "Ostap",
          "email": "ostap@example.com",
          "position": 0
        }
      ],
      "created_at": "2026-09-09T18:20:11+03:00",
      "updated_at": "2026-09-09T18:20:11+03:00"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0,
  "date": "2026-09-10"
}

GET /api/v1/meetings/{id}

Returns one meeting.

Returns 404 when the meeting does not exist.

POST /api/v1/meetings

Creates a meeting.

Request fields:

name

description

location

starts_at

ends_at

participants

Each participant contains:

name

optional email

Successful creation returns 201 Created, the complete meeting, and a
Location header containing the created resource URL.

PUT /api/v1/meetings/{id}

Replaces all meeting fields and the complete participant list.

Returns 200 OK or 404 when the meeting does not exist.

DELETE /api/v1/meetings/{id}

Deletes a meeting and its participants.

Returns 204 No Content or 404 when the meeting does not exist.

GET /health

Returns:

{
  "status": "ok",
  "database": "ok"
}

Error contract

Every non-2xx response uses the common shape:

{
  "error": {
    "code": "validation_error",
    "message": "Meeting must end after it starts.",
    "details": [
      {
        "field": "ends_at",
        "message": "must be later than starts_at"
      }
    ]
  }
}

Known error codes include:

validation_error

not_found

internal_error

service_unavailable

FastAPI's default {"detail": ...} error shape must not leak through the API.

5. Backend layering contract

The layers have separate responsibilities.

api/

HTTP only.

It parses and validates requests, calls a service, and maps results to
response models.

services/

Business rules only.

This includes timezone/day-window calculations and meeting invariants.

repositories/

SQLAlchemy database queries only.

Repositories do not contain HTTP logic.

models/

SQLAlchemy ORM models.

schemas/

Pydantic input/output models.

ORM models and API schemas are separate types.

Participants are loaded eagerly so the API does not create an N+1 query
pattern.

6. Database contract

Database technology:

PostgreSQL 17

SQLAlchemy 2.0 async

asyncpg

Alembic

The schema contains meetings and participants.

The meetings table includes:

id

name

description

location

starts_at

ends_at

created_at

updated_at

The participants table includes:

id

meeting_id

name

email

position

participants.meeting_id references the meeting and deletes participants
when their meeting is deleted.

The database schema is created and evolved only through Alembic migrations.

The first migration is:

alembic/versions/0001_create_meetings.py

The backend startup sequence runs:

alembic upgrade head

before starting the application server.

7. Frontend contract

Technology:

Next.js 16 App Router

React 19

TypeScript strict

shadcn/ui

Tailwind CSS v4

TanStack Query v5

react-hook-form

zod

lucide-react

The main route / displays today's meetings.

The page has:

header/navigation;

today's meetings list;

meeting cards;

empty state;

loading state;

error state;

create-meeting dialog.

Creating a meeting:

validates the form;

sends POST /api/v1/meetings;

closes the dialog after success;

invalidates/refetches the meetings query;

makes the new meeting visible without a full page reload.

The browser-side backend URL comes from:

NEXT_PUBLIC_API_BASE_URL

The frontend API types must match the backend API contract in this document.

8. Docker Compose contract

docker-compose.yml defines exactly these services:

db

image: postgres:17-alpine

port: 5432:5432

named volume: pgdata:/var/lib/postgresql/data

PostgreSQL healthcheck using pg_isready

database: meetings

user: app

password: app

backend

build context: ./backend

port: 8000:8000

depends on db being healthy

runs Alembic migrations before Uvicorn

healthcheck uses GET /health

development bind mount: ./backend:/app

frontend

build context: ./frontend

port: 3000:3000

depends on the backend

development command runs Next.js on port 3000

development bind mount: ./frontend:/app

keeps /app/node_modules in an anonymous volume

browser API URL is http://localhost:8000

No Redis, Celery, RabbitMQ, nginx, Kubernetes, or additional database is
part of this architecture.

9. Version requirements

Backend:

python:3.12-slim

Frontend:

node:22-alpine

Database:

postgres:17-alpine

Backend dependencies are managed with uv.

Important runtime versions must be pinned; do not replace them with floating
latest tags.

10. Startup order

The expected local startup is:

1. PostgreSQL starts.
2. PostgreSQL becomes healthy.
3. Backend starts.
4. Backend runs `alembic upgrade head`.
5. Backend starts Uvicorn on port 8000.
6. Frontend starts Next.js on port 3000.

The repository must work with:

cp .env.example .env
docker compose up --build

Expected local endpoints:

http://localhost:3000
http://localhost:8000/docs
http://localhost:8000/health

11. Out of scope

Do not add features or infrastructure that are not specified.

In particular, do not add:

recurring meetings;

invitations;

email;

calendar integrations;

WebSockets;

Redis;

Celery;

RabbitMQ;

nginx;

Kubernetes;

additional databases;

a separate users directory for participants.

Authentication/Cognito-related behavior described explicitly in SPEC.md
remains part of the application specification; this file does not invent
additional authentication architecture.

12. Generation rule

This document is a structural specification, not an implementation request.

Before generating code, inspect this file and SPEC.md.

Every folder and service must have a stated purpose.

Do not create unused folders, services, queues, caches, proxies, databases,
or speculative abstractions.

Keep the API contract, database model, backend layers, and frontend types
consistent with one another.

Do not modify SPEC.md.
