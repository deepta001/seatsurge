# Interview notes

Likely questions about seatsurge, with short, honest answers about THIS
codebase, including what it doesn't do. Each answer points at the code or
document that backs it. Practise saying them in your own words; don't
memorise.

## The big picture

### 1. What is seatsurge, in two sentences?
A ticket booking backend built to stay correct when far more people try to
buy than there are seats. Redis is the fast, atomic gate for holding seats;
Postgres is the source of truth and refuses to oversell even if Redis is
wrong.

### 2. Walk me through one purchase.
Hold (`POST /events/{id}/holds`): one Lua script in Redis takes the seats
atomically and records a 5-minute hold. Confirm (`POST /holds/{id}/confirm`):
the server reads the hold (never trusting client-sent seats or prices),
charges the mock payment, and writes a PENDING order plus an outbox row in
one Postgres transaction; it answers 202. A relay moves the outbox row to a
Redis Stream; a worker in a consumer group issues numbered tickets with a
conditional UPDATE, marks the order CONFIRMED, and acks only after the
commit. (`app/services/holds.py`, `orders.py`, `app/worker/`)

### 3. Why two stores? Why not just Postgres?
Every purchase would then update the same tier row, a "hot row": thousands of
transactions queue on its lock. Redis does the check-and-take in
microseconds (~52 us measured), in memory, without row locks. Postgres keeps
the durable truth and the backstops. The cost is keeping the two in step,
which is what the outbox, idempotency, rehydrate and reconcile are for.

## Correctness under concurrency

### 4. What's the race condition, and how do you prevent it?
"Read the count, check it's enough, then decrement" lets two requests both
read "1 left" and both take it. A Lua script runs atomically inside Redis,
so check-and-take is one indivisible step. `learning/examples/s2_1/` shows
the naive version overselling; test 1 fails if the script is swapped for it.

### 5. What if Redis is wrong, or loses everything?
Postgres refuses: issuing tickets is `UPDATE tiers SET sold = sold + q WHERE
sold + q <= capacity`, `sold <= capacity` is a CHECK, and a seat can have only
one ISSUED ticket (partial unique index). If that backstop fires, the order
fails, its seats are released, and `invariant_violations_total` goes up.
Measured: with Redis FLUSHALLed mid-sale, 100 tickets for 100 seats, 0
oversold (tests 4, 11; `loadtest/chaos.py flush-redis`).

### 6. A Redis key is missing. Is that zero seats left?
Never (rule 4). Missing means "not initialised": one request rebuilds it from
Postgres under a lock (capacity - sold - active holds - PENDING orders) and
the others wait briefly. Counting PENDING orders matters: without it, a
rebuild mid-sale would hand their seats out again (test 12).

### 7. Why holds with a timeout instead of buying in one step?
Paying takes time and people abandon checkouts. A hold reserves seats
without blocking anyone forever: every hold expires (5 minutes), and a
sweeper returns abandoned ones, exactly once (test 5).

## Reliability

### 8. What's the outbox pattern, and why use it?
Writing the order to Postgres and publishing a message to Redis are two
systems; one can succeed while the other fails. The outbox writes the order
AND an "event to publish" row in the same transaction; a relay publishes
committed rows later. So an order can't exist without its event, or the
reverse (tests 8, 10).

### 9. At-least-once delivery means duplicates. How are they harmless?
The worker records each message's outbox id in `processed_messages` in the
same transaction as its work; a duplicate finds the row and is skipped and
acked. Tested with the same message on two workers at once (test 7).

### 10. What happens when the worker crashes mid-order?
Nothing is acked before its commit, so an unfinished message stays pending
and is claimed again (XPENDING + XCLAIM) when the worker is back. Measured:
SIGKILL with 34 orders waiting, restart 5 s later, 100 tickets, consistent.

### 11. What if a message can never succeed?
Typed errors decide: a `PermanentError` (or 5 failed deliveries) sends it to
`stream:orders:dead`, marks the order FAILED, and releases its seats, so a
dead order never leaks inventory (test 9). In the relay, a Redis outage
costs an outbox row no attempts: it's not the row's fault, and otherwise an
outage would kill every row.

### 12. Two workers on the same event: don't they fight over the tier row?
They wait briefly on its row lock, never retry or lose updates, because the
update is one atomic statement, not read-modify-write, and there's no ORM
version column. Test 16 runs two relays and two consumers at once; a
read-modify-write mutation lost 14 of 30 orders and was caught.

## API and security

### 13. How do you make retries safe?
Holds and confirms require an `Idempotency-Key`: the same key replays the
first answer; the same key with a different body is a 422 (test 6). Orders
also have `UNIQUE(user_id, idempotency_key)` in Postgres. Honest gap: hold
idempotency records live in Redis, so after a Redis flush a retried hold
could create a second hold (still within the per-user cap).

### 14. How do you stop one user grabbing everything, or bots flooding?
A per-user hold cap checked inside the same Lua script (so parallel requests
can't bypass it), at most 10 seats per hold, a purchase cap per event in
Postgres, and sliding-window rate limits (holds per user, logins per email
and per IP) returning 429 with Retry-After (test 14).

### 15. Behind a load balancer, every request comes from nginx. How does the per-IP limit work?
nginx overwrites `X-Forwarded-For` with the address it saw, and uvicorn
trusts that header only from nginx's fixed address. A demo sending 25 logins
with fake IPs got limited after 20; with the protections removed, none were.

### 16. What does the client never control?
Its role (registration is always USER), seats, quantities and prices at
confirm, ticket numbers, and the correlation id (nginx replaces it). Errors
never echo input or internals; a 500 has only a correlation id (rule 10).

## Operations

### 17. How would you know something is wrong in production?
Prometheus metrics: `invariant_violations_total` (must be 0), dead letters,
outbox pending and oldest age, stream pending, holds rejected by reason,
latency by route. A provisioned Grafana dashboard shows them. JSON logs carry
one correlation id from nginx through the API, the outbox row and the worker,
so one search finds a request's whole journey.

### 18. How do you prove Postgres and Redis agree?
`scripts/verify_consistency.py` checks each tier: sold = ISSUED tickets =
CONFIRMED seats, nothing PENDING, and the Redis counter equals what Postgres
and live holds imply. Exit 1 on any mismatch. It runs after every load and
chaos run.

### 19. What were the performance numbers, and what limits them?
1,000 buyers on 100 seats on one laptop: hold p50/p95/p99 2.2/2.9/3.0 s,
~356 requests/s, all runs exactly 100 tickets and 0 oversold. The latency is
queueing: each replica's single Python process is at 100% CPU, and the
laptop is at 85 to 92% with the load generator on it. Doubling replicas
halved server-side time but not the client's. These are correctness results,
not capacity numbers (`docs/benchmarks.md`).

### 20. What would you do next?
Measure with the load generator on another machine; run more server
processes per replica (recalculating the DB connection budget); cut CPU per
hold (cache the event/tier lookup); add Postgres high availability; make
hold idempotency survive a Redis loss; and maybe a virtual waiting room in
front of very large sales.

## Questions about the process

### 21. What bug are you proudest of finding?
Good candidates, all real: an SSE endpoint that held a database connection
per viewer (about 15 viewers would have stalled purchases); a read order in
the counter rebuild that could miss seats during a commit; Alembic's logging
setup silently disabling the app's error logs; Locust's CSV files dropping
up to 215 of 1,100 requests, caught before publishing benchmarks.

### 22. How do you know your tests test anything?
Mutation checks: for each feature, I broke the code on purpose (naive
check-then-take, read-modify-write, removing a lock, trusting a header) and
confirmed a test failed. A few weren't caught at first, and tests were added
until they were.
