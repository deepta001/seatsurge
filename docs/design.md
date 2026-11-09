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

### Releasing holds: one idempotent script for cancels and expiry (S2.7)
- **Chosen:** `release_hold.lua` returns seats only if the hold is still
  `HELD`, then marks it RELEASED (user cancel) or EXPIRED (sweeper). Any
  second attempt (a retry, two sweepers, or a sweeper racing a cancel) sees
  the new status and changes nothing. Tested with 10 simultaneous releases,
  3 simultaneous sweepers, and a cancel racing the sweeper.
- **Keys:** the inventory and uhold keys depend on the hold's fields, so the
  wrapper reads the hold first and passes them as KEYS (declared keys only,
  so it stays cluster-safe). The script re-checks event, tier and user
  against the record (-4 if they don't match), so a stale read can't touch
  the wrong counters.
- **A missing counter is not re-created** by a release (that would invent a
  count); rule 4's rebuild-from-DB (S2.8) handles it.
- **`uhold` never goes negative**, and since S2.7 it gets a safety TTL of
  hold TTL + 900 s on every reserve, so a missed release can't strand a user
  at the cap.
- **Ownership:** `DELETE /holds/{id}` answers 404 for both unknown and
  someone else's holds, so hold ids can't be probed (rule 1).
- **CONFIRMING / CONSUMED holds are never released** by this script; the
  sweeper's grace-period check for CONFIRMING holds comes with confirm in
  Phase C.

### The sweeper (S2.7)
- Runs in the separate worker process (`python -m app.worker.main`), once
  per second: `ZRANGEBYSCORE holds:expiry -inf now LIMIT 100`, then releases
  each hold in "only if expired" mode.
- Safe to run several copies at once (idempotent releases). A failed pass
  is logged and retried next tick; it never stops the loop.
- Measured live: a 30-second hold was released within 0.3 s of its expiry.

### Rehydrating a missing counter, single-flight (S2.8)
- **When:** `reserve_tier.lua` returns NOT_INITIALISED. `create_hold` calls
  `rehydrate_tier`, then retries the reservation once (the first attempt
  wrote nothing, so the same hold id is reused).
- **Formula:** `capacity - sold (Postgres) - seats in HELD/CONFIRMING holds
  (Redis) - seats in PENDING orders (Phase C; 0 for now)`, clamped at 0.
- **Single-flight:** redis-py's `Lock` (`lock:rehydrate:{event}:{tier}`,
  10 s timeout, non-blocking acquire). One process rebuilds. Others poll for
  the counter for up to 2 s, then fall back to 503 `inventory_not_ready`.
  The value is written with `SET NX`, so it can't overwrite a counter that
  appeared meanwhile. Measured: 50 simultaneous requests caused exactly 1
  rebuild and 25 two-seat holds on 50 seats.
- **Why not "missing = 0" or "missing = capacity":** shown live. Zero
  wrongly sells out; capacity oversells (7 held + 10 = 17 of 10 seats).
- **Races, and why they're safe:** no new holds can be created while the
  counter is missing, because every reserve returns NOT_INITIALISED. A hold
  released *during* the rebuild may already have been counted as active,
  which **under**-counts (seats temporarily unsellable). That's the safe
  direction; the admin reconcile (S5.1) corrects it.
- **Known costs and gaps:** counting active holds walks all of
  `holds:expiry` (fine at this scale; a per-tier index would fix it). If
  Redis is fully flushed, the hold records are gone too, so they can't be
  subtracted. Recovery from a full flush mid-sale (counting PENDING orders
  in Postgres) is S5.1/S5.2, test 11.

### Test 1 and what it proves (S2.9)
- **The test:** a start barrier; 500 HTTP buyers wanting 1-4 seats each on
  50 seats; two random seeds x counter present or missing.
- **It checks:** never oversold; seats held + seats left = capacity; every
  refusal is `sold_out` and nobody is refused while their quantity is still
  available; one hold record per winner with the right qty and owner;
  uhold per user; Postgres `sold` untouched.
- **Mutation check:** swapping `ReserveTierScript` for a naive GET-then-DECRBY
  (a throwaway pytest plugin) makes it fail with 52 of 50 seats, so the test
  really detects overselling.
- **3 processes:** `learning/examples/s2_9/three_replicas_demo.py` sends
  1,000 buyers round-robin to 3 uvicorn processes on 100 seats: exactly 100
  holds, 900 sold_out. The S2.1 naive version, run right after against the
  same Redis, sold 103.

### Performance finding to investigate in S8.3 (not yet a benchmark)
- On this Windows laptop, with Postgres and Redis in Docker Desktop:
  - Median Redis PING 1.8 ms; Postgres SELECT 1 2.2 ms.
  - `GET /health/live` 8.8 ms; `/health/ready` 22.8 ms.
- The 3-process demo handled 300 hold requests in 8.1 s and 1,000 in 18.7 s.
  A first 1,000-buyer attempt timed out on the client side (30 s).
- Each hold makes several sequential Redis and Postgres round trips, plus
  framework overhead. The cause hasn't been profiled; suspects to check in
  S8.3 are the per-request Postgres reads, Docker Desktop's port forwarding
  on Windows, and uvicorn's pure-Python HTTP parsing. **No performance claim
  is made until then.**

## Phase C: orders and tickets

### Order and ticket tables (S3.1)
- **Order ids are UUIDs**, not 1, 2, 3...: they appear in URLs, and
  sequential ids would reveal order volume and invite guessing.
- **Two columns added to the CLAUDE.md schema: `orders.tier_id` and
  `orders.quantity`.** The spec needs both. The rehydrate formula (section 5)
  subtracts "seats in PENDING orders" per tier, and confirm (section 7.2)
  enforces a per-user purchase cap per event, which needs quantities. They
  are indexed `(tier_id, status)` for that count.
- **Backstops in Postgres:**
  - `uq_orders_hold_id`: one hold becomes at most one order.
  - `uq_orders_user_id_idempotency_key`.
  - Partial unique indexes `uq_tickets_issued_seat (event_id, seat_id)` and
    `uq_tickets_issued_number (tier_id, ticket_number)`, both
    `WHERE status = 'ISSUED'`, so cancelled tickets free their seat or
    number. NULL `seat_id` (general admission) never clashes.
- **`tickets.seat_id` has no foreign key yet;** the seats table and its FK
  arrive with reserved seating (S6.1).
- `outbox_events` and `processed_messages` are added where first used (S3.3,
  S4.4).
