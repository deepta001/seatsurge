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

## Events and admins (S1.6)

### Admins are created only by a CLI
- **Chosen:** `scripts/seed_admin.py` asks for the password (or reads
  `SEATSURGE_ADMIN_PASSWORD`). The `create_admin` service is never reachable
  over HTTP, and `register_user` still has no role parameter.
- **Alternative:** a default admin account, or an "is_admin" flag at sign-up.
- **Why:** CLAUDE.md section 9 says no default credentials, and
  self-registration must never yield an admin.

### Event status is a one-way state machine, and only drafts can be deleted
- **Chosen:** DRAFT -> PUBLISHED -> CANCELLED (CANCELLED is final). DELETE
  only works on DRAFT events; published ones are cancelled instead.
- **Alternative:** free status edits, and hard delete with cascade.
- **Why:** once an event is published, tickets may exist (Phase C). Deleting
  it would leave orphaned tickets, and re-opening a cancelled event would
  confuse buyers who were told it's off.
- **Concurrency:** PATCH and DELETE lock the event row (`SELECT ... FOR
  UPDATE`) before checking the status, so two admins can't both pass the
  check at once. This is an admin-only, rarely-written row, so locking it
  doesn't conflict with "no hot rows" (which is about rows every order
  touches).

### Tiers can't be edited after creation (yet)
- **Why:** changing capacity has to stay consistent with the Redis inventory
  counters (Phase B), so tier edits wait until that exists.

### Admin checks use the token's role
- **Trade-off:** a demoted admin keeps admin rights until their access token
  expires (at most 15 minutes). The same stateless trade-off as S1.4.

## Public event browsing (S1.7)

### Separate public response models
- **Chosen:** `EventSummary` (list rows, no tiers) and `EventDetail` (with
  tiers), both without `created_by`. Admin responses keep it.
- **Why:** CLAUDE.md section 8 says never serialise ORM objects; each
  audience gets exactly the fields it needs.

### Offset paging, with a stable order
- **Chosen:** `limit` (1 to 100) and `offset` (0 to 10,000), plus `total`;
  ordered by `starts_at, id`.
- **Alternative:** keyset ("after this id") paging, which stays fast at any
  depth.
- **Why:** an event catalogue is small, offset paging is simple to read and
  use, and the caps bound the cost. The `id` tie-breaker makes the order
  deterministic, so pages never skip or repeat an event. Keyset paging can
  replace it if the catalogue grows large.

### Visibility rules
- Lists show upcoming PUBLISHED events only. A detail page also shows
  CANCELLED events, so ticket holders can see what happened. DRAFTs are
  indistinguishable from nonexistent ids (both 404).
- **Known gap:** admins can't list their drafts through the API yet; they
  get the id when they create one.

### No search index yet
- Name search is `ILIKE '%text%'`, which scans the table. That's fine for
  hundreds of events; a trigram (`pg_trgm`) or full-text index would be the
  next step if the catalogue grows.

## Phase B notes

### The Redis client queues for connections instead of failing (found S2.1, fixed S2.3)
- **Found:** with the default `redis.asyncio` pool (redis-py 8.1), 1,000
  simultaneous requests raised `MaxConnectionsError: Too many connections`.
- **Chosen:** `build_redis_client` uses a `BlockingConnectionPool`
  (`REDIS_MAX_CONNECTIONS`, default 50 per process;
  `REDIS_POOL_TIMEOUT_SECONDS`, default 5). A burst waits briefly for a
  connection instead of erroring. The test fixture uses the same builder, so
  the 500-buyer test exercises it.
- **Trade-off:** a request may wait up to 5 s for a connection under extreme
  load, then fail. That's better than failing at once, and the limit keeps
  Redis's own connection count bounded (3 replicas x 50).

### reserve_tier.lua: one script for the whole reservation (S2.3)
- **Chosen:** a single Lua script checks the counter exists (else -2), checks
  the per-user cap (-3), checks enough seats (-1), then writes everything:
  DECRBY the inventory, INCRBY the user's held count, HSET the hold record
  (+15-minute EXPIRE grace), and ZADD the expiry index.
- **Alternative:** several commands from Python, or a MULTI/EXEC transaction.
- **Why:** MULTI/EXEC can't branch on a value it just read, and separate
  commands reopen the S2.1 race. All refusals return **before** the first
  write, so a refused request changes nothing.
- **Order of checks:** "missing" first (never mistake it for sold out), then
  the user cap, then availability.
- **Return codes** are mapped to a `ReserveOutcome` enum in
  `app/redis/scripts.py`, so callers never see magic numbers.

### Creating a hold: Postgres for "can this be sold?", Redis for "is there room?" (S2.4)
- `create_hold` first reads the event and tier from Postgres (published,
  upcoming, general admission, tier belongs to event), then runs
  `reserve_tier.lua`. Availability is **only** decided inside Redis.
- The user comes from the token, never the request body (rule 1).
- Outcomes become typed errors: SoldOut 409, HoldLimitExceeded 409,
  InventoryNotReady 503 + `Retry-After` (a missing counter is never zero;
  rebuilding it automatically is S2.8).
- **Known cost:** two small Postgres reads per hold request. Fine for now;
  under a heavy herd, these facts (status, seating, tier ownership) rarely
  change and could be cached in Redis. Measure first (S8.3).
- **Known gap until S2.7:** holds don't release their seats yet when they
  expire or are abandoned.

### Idempotency keys for creating holds (S2.5)
- **Chosen:** a required `Idempotency-Key` header. Redis key
  `idem:{user}:{key}` goes through these states:
  1. `SET ... NX EX 30` claims it ("in progress"), atomically, so exactly one
     of several simultaneous retries does the work.
  2. The others get 409 `request_in_progress` + `Retry-After: 1`.
  3. On finishing, the answer is stored for 24 h with a SHA-256 fingerprint
     of route + body.
- **Same key + same request:** replay the stored answer (header
  `Idempotent-Replayed: true`). **Same key + different request:** 422
  `idempotency_key_reused`. Keys are per user.
- **What's stored:** final answers only (201, and 4xx such as sold_out). A
  503 or an unexpected error releases the claim, so a retry can succeed later.
- **Known crash window:** if the process dies after the Lua script reserved
  seats but before `complete()` stored the answer, the claim expires after
  30 s and a retry creates a second hold. The first one isn't lost forever:
  it expires after 5 minutes and its seats return (S2.7). Closing the window
  fully would mean writing the idempotency record inside the Lua script
  itself; noted as a possible improvement.
- **Alternative considered:** storing keys in Postgres with a UNIQUE
  constraint. That's slower on the hot path, and the hold itself lives in
  Redis anyway.

### Request limits (S2.6)
- **Per hold:** 1 to 10 seats (`HoldCreate.quantity`, 422 otherwise).
- **Per user per event:** at most `HOLD_USER_CAP` (10) seats held at once,
  enforced **inside** `reserve_tier.lua` against `uhold:{event}:{user}`, so
  simultaneous requests can't add up past it (tested: 20 x 1 seat gives 10;
  8 x 3 seats gives 9; 3 x 10 seats gives 10).
- **Per request body:** `MAX_REQUEST_BODY_BYTES` (16 KB), via
  `BodySizeLimitMiddleware`, the outermost layer. It refuses a declared
  oversized `Content-Length` (or a non-numeric one) immediately, and reads
  chunked bodies itself, stopping at the limit. 413 `payload_too_large`.
  - **Why read the body in the middleware:** the first version raised an
    error from inside FastAPI's body reading, and FastAPI turned it into a
    generic 400. Reading (at most 16 KB) first, then replaying it, keeps the
    decision outside FastAPI.
- **Not yet:** limits on how *often* a user can call (rate limiting, S7.1);
  nginx's `client_max_body_size` will add the same limit at the edge (S8.1).
- **To decide in S2.7:** `uhold` currently has no TTL. If releases ever fail,
  a user could stay stuck at the cap. The sweeper and release script must
  decrement it, and must never let it go below 0.
