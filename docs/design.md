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

### The mock payment provider (S3.2)
- **Constraint:** CLAUDE.md section 9 forbids test/simulation endpoints in
  the app, so there is no `/payments` route (a test asserts this).
- **Chosen:** copy real providers. The client obtains a token from the
  provider (in test mode, fixed tokens), and the server charges it.
  `MockPaymentProvider` lives in-process, created once at startup
  (`app.state.payments`, `get_payments` dependency):
  - `tok_ok` succeeds (unless declined at random by `PAYMENT_FAILURE_RATE`).
  - `tok_declined` gives 402 `payment_declined`.
  - `tok_unavailable` gives 503 `payment_unavailable` + Retry-After
    (temporary).
  - Anything else gives 422 `invalid_payment_token`, so a raw card number is
    never accepted.
- **Idempotent charges** per key (same key + same amount returns the first
  charge; a different amount is an error), and `refund()` for when our own
  write fails after charging (used in S3.3).
- **Seeded randomness** (`random.Random(seed)`) makes declines repeatable in
  tests: seed 7 at 30% gave the same count on two runs, within 250-350 of
  1,000.
- **Limits of a mock:** charges live in process memory (lost on restart, not
  shared between replicas). That's fine, because the order in Postgres, not
  the mock, is the record of a purchase.

### Confirming a hold (S3.3)
- **Flow:**
  1. `consume_hold.lua` checks the hold exists, belongs to the caller, is
     HELD and is unexpired. It sets CONFIRMING, moves the hold from
     `holds:expiry` to `holds:confirming` (score = expires_at + grace),
     extends the record's TTL to 24 h, and returns the hold's own event,
     tier and quantity.
  2. Price = tier price (Postgres) x the hold's quantity, then a purchase-cap
     pre-check.
  3. Charge the mock provider, with idempotency key `hold:{hold_id}`.
  4. One transaction: lock the user's row (`SELECT ... FOR UPDATE`), re-check
     the cap, insert the PENDING order plus the `order.placed` outbox row,
     and commit.
  5. Respond 202 `{order_id, status}`.
- **Failure handling:** any error after step 1 runs `revert_hold.lua`
  (CONFIRMING -> HELD, back on `holds:expiry` with its original expiry). A
  payment already taken is refunded. So payment declined, provider down, the
  cap reached, or a DB error all leave the user holding their seats.
- **Why lock the user row, not a shared row:** two confirms by the same user
  could both pass the "under 10 tickets" check (check-then-insert). The lock
  serialises one user's confirms only, so it isn't a hot row (rule 7).
- **No database transaction is open during the payment call:** the pre-check
  transaction is ended before charging, and the lock is only taken
  afterwards, so a slow provider never holds a database lock.
- **Idempotency:** the same Redis machinery as holds, shared through
  `app/api/idempotent.py` (`run_idempotently`, which the hold route now uses
  too). Backstops are `uq_orders_hold_id` and
  `uq_orders_user_id_idempotency_key`. Confirming an already-confirmed hold
  with a new key returns the existing order. Concurrent confirms get 409
  `confirm_in_progress` until the first one commits.
- **Errors:** 404 hold_not_found (unknown or foreign, rule 1), 410
  hold_expired, 402 / 503 / 422 from payments, 409 purchase_limit_exceeded,
  and 409 confirm_in_progress.
- **Rehydrate now counts pending orders:** live holds (HELD in
  `holds:expiry`, plus CONFIRMING in `holds:confirming`), plus PENDING
  orders whose hold is no longer in Redis. A PENDING order whose CONFIRMING
  hold is still there is counted once, through the hold.
- **Still to come:** the sweeper's check on CONFIRMING holds past
  expiry + grace (section 7.5), and issuing tickets (the worker, M4).

### Robustness: one bad Redis entry must not stop everything (S3.3)
- **Found while testing the demo cleanup:** a hold-index entry whose record
  wasn't a hash (WRONGTYPE) made every counter rebuild fail (500 for the
  rebuilder, 503 for everyone waiting). It would also have failed every
  sweeper pass.
- **Fix:** both skip such entries per hold and log them; the sweeper also
  drops them from `holds:expiry`. They can't be real holds, so skipping
  them can't hide held seats. Regression tests in adversarial tests 12 and 5.

### The outbox relay (S4.1)
- **What it does:** `app/worker/relay.py` reads due PENDING rows from
  `outbox_events` (oldest first, 50 at a time), XADDs each to
  `stream:orders`, marks it PUBLISHED and commits. It runs as an asyncio task
  in the worker process, next to the sweeper.
- **Why an outbox instead of publishing from the confirm request:** Postgres
  and Redis can't share a transaction. Publish-then-commit can announce an
  order that never existed; commit-then-publish can lose the message if the
  API dies in between. Writing the message as a row in the order's own
  transaction makes "order exists" and "message exists" one atomic fact.
- **Publish, then mark (at-least-once):** if the relay dies after XADD but
  before its commit, the row is still PENDING and is published again. That's
  a duplicate, never a loss. Every message carries `outbox_id`, so the
  consumer can de-duplicate even though each copy gets a new stream entry
  id (S4.4).
- **`FOR UPDATE SKIP LOCKED`:** rows are locked while a relay works on them;
  a second relay skips them instead of queueing behind the lock. Several
  relays (or worker replicas) share the work without double-publishing or
  waiting. Alternative: a single relay with no locking. It's simpler, but
  running two by accident would publish everything twice.
- **One row's failure is isolated:** each XADD has its own try/except, so a
  failing row stays PENDING and the rest of the batch is still published.
- **The row locks are held during the XADDs:** a batch is at most 50 fast
  Redis calls, so the locks are short. A Redis outage fails the XADDs
  quickly, the batch commits only the rows that succeeded, and the loop
  backs off for 0.5 s.
- **Still to come:**
  - attempts, `last_error`, exponential backoff and DEAD (S4.2);
  - deleting old PUBLISHED rows;
  - trimming the stream once consumers acknowledge (S4.3+).

### Relay retries, backoff and DEAD (S4.2)
- **Three kinds of failure, three reactions:**

  | Failure | Example | Reaction |
  |---|---|---|
  | Redis unreachable | `ConnectionError`, `TimeoutError` | Stop the batch, count **no** attempt, retry next tick. An outage isn't the row's fault; counting it would turn a 5-minute outage into hundreds of DEAD orders. |
  | Permanent | `PermanentError` (an unknown event type) | DEAD immediately. Retrying can't help. |
  | Anything else | Redis rejecting this message | `attempts += 1`, store `last_error`, retry after 1 s, 2 s, 4 s ... (capped at 300 s); DEAD after 8 attempts. |

- **Why exponential backoff:** retrying a failing row every 0.5 s floods the
  logs and hammers whatever is failing. Doubling the wait gives a quick
  retry for blips and a slow one for real problems. Jitter (random spread)
  isn't needed yet, because each row's timer starts when it fails.
- **Why the database clock:** `next_retry_at = now() + delay` is computed in
  Postgres, the same clock the relay's `next_retry_at <= now()` query reads.
  Workers on machines with skewed clocks still agree.
- **The "alert" is an ERROR log for now;** S8.2 adds a dead-letter metric
  for Prometheus.
- **DEAD rows are kept** for an operator to inspect and re-queue (set
  `status = 'PENDING', attempts = 0`).
- **Known gap:** an `order.placed` row that goes DEAD leaves its order
  PENDING, with the seats still taken by the CONFIRMING hold. This needs an
  operator today. The worker's dead-letter path (S4.6) and reconcile (S5.1)
  are where that gets handled.
- **Clean-up:** PUBLISHED rows older than 24 h are deleted, at most 1,000 per
  call, once a minute, so the table stays small and the relay's queries stay
  fast. PENDING and DEAD rows are never deleted.

### The stream consumer (S4.3)
- **Redis Streams with a consumer group, not pub/sub:** a stream keeps
  messages until they're processed, even if no worker is running. Pub/sub
  drops them. The group `order-workers` gives each message to exactly one
  worker, so more worker processes means more throughput without
  double-processing.
- **The group starts at id `0`:** messages the relay published before any
  worker existed are still delivered. `$` would silently skip them.
- **Ack only after the handler succeeded:** if a worker crashes mid-message,
  the message stays in the pending entries list (PEL) and can be retried.
  Acking first would lose it. Together with the relay this is
  at-least-once delivery, so the handler must be idempotent (S4.4).
- **A failed message stays pending and doesn't stop the batch.** Picking
  pending messages back up (`XAUTOCLAIM`), counting deliveries and
  dead-lettering are S4.6.
- **Blocking reads:** `XREADGROUP ... BLOCK 1000` waits inside Redis for up
  to 1 s, so an idle worker isn't polling in a tight loop and a new
  message is handled within milliseconds.
- **The consumer name is hostname-pid,** so XPENDING shows exactly which
  process holds a stuck message.
- **Not wired into the worker yet:** it joins in S4.5, when the ticket
  handler exists. Running it earlier would have nothing real to do.
- **Still to come:** trimming the stream (`XTRIM`) once entries are acked,
  and the `processed_messages` de-duplication (S4.4).

### Idempotent processing (S4.4)
- **Why:** delivery is at-least-once. Duplicates come from a relay crash
  after XADD but before marking PUBLISHED, and from a worker crash after
  committing but before XACK (redelivered in S4.6). Processing a duplicate
  must change nothing.
- **How:** `run_once` opens one transaction, inserts the message id into
  `processed_messages` (`ON CONFLICT DO NOTHING`), and runs the handler in
  that same transaction. If the insert finds the id already there, it's a
  duplicate: skip the work, return normally, and the consumer acks it.
- **The same transaction is the key point.** If the "done" mark were
  committed first and the work then crashed, the message would be marked
  done with the work never done: a lost order. In one transaction, both
  commit or neither does, and a redelivery tries again. The mutation check
  showed this exact bug is caught by test 7.
- **Concurrent duplicates:** two workers with copies of the same message
  both INSERT the same primary key. Postgres makes the second wait for the
  first transaction. If the first commits, the second sees a conflict and
  skips; if it rolls back, the second does the work. No application locks
  are needed.
- **Key = the outbox id, not the stream entry id:** a re-published row gets
  a fresh entry id, so keying by entry id would let relay duplicates
  through.
- **Alternative considered:** making each handler naturally idempotent
  (e.g. "set status CONFIRMED" is safe to repeat), but "sold = sold + 2"
  and "insert tickets" are not. One generic table protects every handler.
- **Still to come:** deleting old `processed_messages` rows (they must be
  kept longer than any message can be redelivered).

### Issuing tickets with database backstops (S4.5)
- **One statement does the check and the write:**
  `UPDATE tiers SET sold = sold + q, next_number = next_number + q
  WHERE id = :tier AND sold + q <= capacity RETURNING next_number`.
  - There is no "read sold, decide, write" gap for another worker to slip
    into.
  - 0 rows means the tier would pass capacity: `InvariantViolation`, and
    nothing is written.
- **Ticket numbers come from the same statement:** `next_number - q + 1 ..
  next_number`. Cancelling (S5.3) lowers `sold` but never `next_number`, so
  numbers are never reused.
- **Finding from the mutation check:** the UPDATE locks the tier row until
  commit, so issuers for one tier run one at a time anyway, and even
  "count + 1" numbering would be correct here. RETURNING is chosen because
  it's one statement instead of two, and correct without relying on that
  ordering.
- **Isn't that a hot row (rule 7)?** The lock lasts one short transaction
  per order inside the worker, not per HTTP request. Holds and the
  never-oversell gate live in Redis. One tier row per worker transaction is
  the price of a database-enforced guarantee. Test 16 (S8.4) checks two
  workers don't fight over it.
- **Layers of defence (any one stops an oversell):**
  1. `reserve_tier.lua` in Redis;
  2. the conditional UPDATE;
  3. the `CHECK (sold <= capacity)` constraint;
  4. the `uq_tickets_issued_number` unique index (stops any code that
     invents numbers itself; see the S4.5 demo).
- **Facts come from the order row, not the message:** `issue_tickets` reads
  the quantity and tier from `orders`; the message only carries the order
  id (rule 1).
- **Redis after the commit (rule 6):** `finish_hold.lua` (CONFIRMING ->
  CONSUMED, lowers the user's held count, leaves `holds:confirming`, does
  not return seats) runs after the commit. If the worker dies between the
  commit and this step, the message isn't acked; its redelivery is skipped
  as a duplicate, but the after-commit step runs again and finishes the
  job. That's why `run_once` runs `after_commit` for duplicates too, and
  why the script is idempotent.
- **A short window that undersells, never oversells:** between the commit
  and `finish_hold`, a rebuild counts the seats both as sold (DB) and as a
  CONFIRMING hold, so availability is briefly too low.
- **When the backstop fires today,** the message stays pending and the
  order PENDING. S4.6 turns that into FAILED, releases the hold and counts
  `invariant_violations_total`.

### Retries, dead letters and releasing a failed order's seats (S4.6)
- **Typed failures decide what happens (rule 9):**

  | Failure | Reaction |
  |---|---|
  | `PermanentError`, including `InvariantViolation`, a malformed message, or an unknown type | Dead-letter at once. Retrying can't help. |
  | Anything else (`TransientError`, a DB timeout, a bug) | Leave it unacked and retry with backoff (1 s, 2 s, 4 s, 8 s, capped at 60 s). After 5 failed deliveries, dead-letter it. |

- **Retrying uses the pending list itself:** `XPENDING ... IDLE` lists
  unacknowledged messages with their idle time and delivery count. A message
  whose backoff has passed is taken over with `XCLAIM ... min_idle_time`;
  if another worker claimed it a moment earlier, its idle time was reset
  and Redis refuses the second claim, so only one worker retries it. The
  same pass rescues messages left by a worker that crashed.
- **Why XPENDING + XCLAIM rather than XAUTOCLAIM** (which CLAUDE.md
  suggests): XAUTOCLAIM uses one idle threshold for every message, so it
  can't give each message its own growing delay. It's a technique choice
  inside the same design.
- **A dead letter never leaks seats.** Before a dead `order.placed` is
  acked, its compensation runs:
  1. lock the order;
  2. PENDING becomes FAILED (committed first, rule 6);
  3. if the order is FAILED, release the hold with `release_hold.lua` in its
     explicit CONFIRMING mode: seats back to the counter, the user's held
     count lowered, the hold removed from `holds:confirming`.
- **A CONFIRMED order is never compensated.** If tickets were issued and
  only the after-commit Redis step kept failing, the seats are really sold.
  Releasing them would sell them twice; a test covers exactly this.
- **Only the worker may release a CONFIRMING hold.** The user's cancel and
  the sweeper still can't. Cancelling mid-purchase returns 204 and changes
  nothing (found by a mutation that was first not caught).
- **Every step can be repeated.** Compensation is idempotent (FAILED stays
  FAILED; release only acts on CONFIRMING). If dead-lettering crashes
  before the XACK, the message is still pending and the whole thing runs
  again. The dead stream may then hold a duplicate, which carries the same
  `dead_entry_id`.
- **Not done here:**
  - refunding a FAILED order's payment (the mock provider is in the API
    process);
  - metrics (`invariant_violations_total`, dead-letter count), which come
    in S8.2. ERROR logs are the alert for now.

### Relay crashes (S4.7)
Every place the relay can die leaves a recoverable state:

| Crash point | State left behind | Recovery |
|---|---|---|
| Before the relay runs at all | Order + PENDING outbox row (one transaction) | The next relay pass publishes it |
| After XADD, before marking PUBLISHED | Message on the stream, row still PENDING | Published again: a duplicate with the same `outbox_id`, skipped by `run_once` |
| While holding row locks (connection dies) | Locks held by a dead session | Postgres ends the session and frees its locks; the next relay takes the rows |

The one order that would lose messages is "mark PUBLISHED, then XADD": a
crash in between leaves a row that says PUBLISHED but was never sent. The
relay never does that.

## Phase D: recovery

### Reconcile (S5.1)
- **What:** `POST /admin/events/{id}/reconcile` recomputes every tier's
  Redis counter and **overwrites** it. Rehydrate (S2.8) only fills a
  missing counter; reconcile also fixes one that exists but is wrong. The
  response shows `before` and `after`, so drift is visible.
- **Formula (the same as rehydrate):** capacity - sold - seats in live holds
  (HELD or CONFIRMING) - seats in PENDING orders whose hold is gone from
  Redis.
- **Pausing new holds while it recomputes:** under the tier's rehydrate
  lock, the counter is removed with GETDEL. A reserve that arrives now sees
  "not initialised" and waits on the lock (rule 4) instead of taking seats.
  When the new value is SET, it carries on. Without the delete, a hold
  taken during the recompute would be overwritten, and the counter would
  claim seats that are actually held (the rush test catches exactly that).
- **Read Postgres first, as one snapshot, then Redis:** a single SQL
  statement reads `sold` and the PENDING orders at the same instant; Redis
  is read after.
  - If the worker finishes an order in between, its seats are counted twice
    (as sold or pending, and as a CONFIRMING hold): available is briefly
    too low.
  - The old order (Postgres, Redis, Postgres) could count them zero times:
    too high, an oversell at the Redis gate. Fixed in S5.1 for rehydrate
    too.
- **Releases during the recompute** (a hold expiring, or a FAILED order's
  hold released) don't add to a missing counter, by design. The recompute
  may then count those seats as held: too low, safe. Running reconcile
  again corrects it.
- **Not covered:** per-user held counts (`uhold:*`) aren't reconciled.
