# fastapi-saas-starter

Async multi-tenant SaaS backend starter — FastAPI + SQLAlchemy 2.0 + Alembic
+ PostgreSQL 16 + Redis 7. Built as a public portfolio artifact.

> **Status:** PR 1 of 4 (Foundation slice). Auth, tenant/user CRUD,
> isolation, plans and rate limiting land in PRs 2–4 on chained branches.

## Quickstart

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env and set SECRET_KEY to a real random value:
python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose up -d --build
curl http://localhost:8000/health
```

### Local venv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                                # fast unit tests, no Postgres needed
# Against a live stack:
docker compose up -d postgres redis
export DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app
alembic upgrade head
uvicorn app.main:app --reload
```

## Architecture (this slice)

```
app/
├── main.py          FastAPI factory: create_app(), /health, CORS, lifespan
├── config.py        pydantic-settings Settings; fail-fast on missing SECRET_KEY
├── database.py      async engine, AsyncSessionLocal, get_db, Base
├── core/
│   └── security.py  bcrypt-direct hash/verify + JWT create/decode
└── models/          SQLAlchemy 2.0 ORM (Tenant, User, Subscription, Plan)
alembic/             Async env.py + 0001_initial migration (Postgres UUID)
tests/               pytest + pytest-asyncio; SQLite-in-memory by default
```

## Endpoints (PR 1)

| Method | Path           | Purpose                                  |
|--------|----------------|------------------------------------------|
| GET    | `/health`      | Liveness probe — no DB, no Redis, 200 OK |
| GET    | `/api/v1/`     | API v1 root marker (routers land in PR 2) |

Subsequent PRs add: `/api/v1/auth/login`, `/api/v1/health/detailed`,
`/api/v1/tenants`, `/api/v1/users`, `/api/v1/plans`.

## Environment

See `.env.example` for every supported variable. `SECRET_KEY` is mandatory
in production (`DEBUG=false`); `Settings()` refuses to boot without it.

## Testing

```bash
pytest                                  # default: SQLite in-memory, no infra
pytest --cov=app --cov-fail-under=70     # coverage gate used in CI
ruff check app tests                     # lint
```

Coverage gate `--cov-fail-under=70` is enforced in CI.

## Limitations

- No refresh tokens, no email verification, no password reset (out of scope).
- No payment gateway integration.
- `CORS_ORIGINS` defaults to permissive `localhost` — tighten for production.

## License

MIT
