# Issue 020: Database migrations (Alembic) and PostgreSQL

**Difficulty:** 🟡 medium · **Area:** backend · **Skills:** Python, SQLAlchemy, SQL

## Why
Tables are created with `create_all()` in development, which never changes existing tables. Every time someone adds a column (e.g. issues 005 and 016), everyone has to delete their database. A real deployment needs PostgreSQL and proper migrations.

## What to do
- Add Alembic with an initial migration matching `backend/app/models.py`.
- In development, run migrations on startup instead of `create_all()` (keep tests fast; they can still use `create_all`).
- Verify the whole test suite against PostgreSQL (`DATABASE_URL=postgresql+asyncpg://…`). `asyncpg` is already in `backend/requirements.txt`.
- When two drivers are matched at the same moment, lock the ride row during assignment (`SELECT … FOR UPDATE`) so it can't be assigned twice.
- Document the workflow ("I changed a model, now what?") in `docs/BACKEND.md`.

## Where to look
- `backend/app/db.py`: `create_all`.
- `backend/app/main.py`: the `lifespan` startup.
- `backend/app/services/dispatch.py`: assignment.

## Done when
- [ ] `alembic upgrade head` builds the schema from an empty PostgreSQL database.
- [ ] Adding a column needs a migration, not a database delete.
- [ ] The tests pass on SQLite and PostgreSQL.
