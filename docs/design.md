# Design decisions

Each decision: what we chose, the alternative we considered, and why.
Decisions are added as they are made. The big ones from CLAUDE.md (Lua for
atomicity, holds with TTL, outbox, at-least-once plus idempotency, DB
backstops, no hot rows) get their own sections when those parts are built.

## Database

### Status fields are text plus a CHECK, not Postgres enum types (S1.1)
- **Chosen:** `VARCHAR(32)` with `CHECK (role IN ('USER','ADMIN'))`, via
  SQLAlchemy `Enum(native_enum=False, create_constraint=True)`.
- **Alternative:** native Postgres `ENUM` types.
- **Why:** both reject bad values at the database. Native enum types need
  special `ALTER TYPE` steps in migrations and are awkward to change or drop.
  Text plus CHECK migrates like any other constraint.

### Every constraint has a predictable name (S1.1)
- **Chosen:** a naming convention on `Base.metadata` (for example
  `ck_tiers_sold_within_capacity`).
- **Alternative:** let Postgres invent names.
- **Why:** Alembic needs stable names to alter or drop constraints, and
  readable names make errors self-explaining (the code checks
  `constraint_name` to tell a duplicate email from other failures).

### Uniqueness is decided by the database, never check-then-insert (S1.3)
- **Chosen:** insert, and translate a `uq_users_email` / `uq_users_username`
  violation into `UserAlreadyExists` (409).
- **Alternative:** `SELECT` first, then `INSERT` if free.
- **Why:** two simultaneous sign-ups could both pass the check. Proven by a
  10-way race test (exactly one 201).

## Authentication

### Access tokens are stateless JWTs checked without the database (S1.4)
- **Chosen:** 15-minute HS256 JWTs; `get_current_user` verifies the
  signature and expiry only.
- **Alternative:** look the user up on every request.
- **Why:** CLAUDE.md section 9 requires no DB hit per request, which keeps
  every authenticated call fast under load. **Trade-off:** a deleted or
  demoted user keeps access until their token expires (at most 15 minutes).

### Refresh tokens are stored, single-use and rotated, with reuse detection (S1.5)
- **Chosen:** a random 256-bit token; only its SHA-256 hash is stored in a
  new `refresh_tokens` table (not in the original CLAUDE.md schema; the
  student approved adding it).
  - Each use marks it used and issues a replacement in the same family.
  - Presenting a used token revokes the whole family.
  - Logout revokes the family.
- **Alternative:** a 7-day JWT refresh token with no table.
- **Why:** a stateless refresh token can't be revoked, so a stolen one works
  for 7 days and logout is cosmetic. Storing tokens makes logout real,
  rotation limits the damage a leaked token can do, and reuse detection
  notices theft (the thief and the real user can't both keep refreshing).
- **Race safety:** the token is claimed with one conditional `UPDATE ...
  WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > now()
  RETURNING ...`, so of N simultaneous refreshes with one token exactly one
  succeeds (5-way race test).
- **Why SHA-256 here but argon2 for passwords:** a refresh token is 256
  random bits, so there's nothing to guess and a fast hash is safe. Passwords
  are human-chosen and guessable, so they need a slow hash.
- **Known gaps:** expired and used rows are never deleted yet (a cleanup job
  is future work), and logout doesn't kill the current access token (it
  expires within 15 minutes).

## Local development

### Connection URLs use 127.0.0.1, not localhost (S0.8)
- **Why:** on Windows, `localhost` tries IPv6 `::1` first; Docker listens
  only on IPv4, and the fallback costs about 2s per new connection
  (measured: 2.03s vs 0.00s).

### Tools run as `python -m <tool>` (S0.5)
- **Why:** Windows Smart App Control blocks the unsigned `.exe` launchers
  that uv creates in `.venv\Scripts`.
