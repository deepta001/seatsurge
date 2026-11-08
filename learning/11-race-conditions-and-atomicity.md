# Primer 11: Race conditions and atomicity

**Analogy:** two shop assistants share one whiteboard saying "Seats left: 1".
Both glance at it at the same moment, both say "yes, there's one!", both sell
it, and both rub out the number and write "0" (or "-1"). Each did the right
thing on their own; the bug is the **gap between looking and writing**.

## Check-then-act

```python
if available > 0:  # 1. CHECK
    ...  #    (a gap: network, database, any await)
    available -= 1  # 2. ACT, based on a check that may be stale now
```

A **race condition** is when the result depends on the timing of other
requests. In an async server, every `await` is a point where other requests
run, so the gap is always there.

## What S2.1 measured

`learning/examples/s2_1/oversell_demo.py`: 1,000 buyers, 100 seats, everyone
released together.

| Version | Result |
|---|---|
| In memory, with a pause in the gap | sold 1,000 for 100 seats, every run |
| Real Redis, `GET` then `DECR` | oversold in 11 of 13 runs, by 1 to 41 seats; counter went negative |
| 1 buyer, 1 seat | always fine; that's why casual testing misses it |

Notice that the Redis version **sometimes came out right**. Intermittent bugs
are the worst kind: they pass tests on a quiet day and fail during the busiest
sale of the year.

## Atomicity: the fix (coming in S2.2 and S2.3)

An operation is **atomic** if nobody can see or change anything halfway
through it. The fix is to make check-and-act **one indivisible step**:

- Redis runs one command at a time, so a single command like `DECR` is
  atomic. But a check plus a decrement is two commands.
- A **Lua script** runs inside Redis as one step: "if available >= qty then
  decrement and create the hold, else refuse". No other command can run in the
  middle (S2.2, S2.3).
- **Postgres's** `CHECK (sold <= capacity)` is the backstop if Redis is ever
  wrong (S4.5).

## Why not just a Python lock?

An `asyncio.Lock` fixes it inside **one** process. But seatsurge runs **three**
API replicas (S8.1), each with its own memory and its own locks, so the
shared state must be guarded where it lives: in Redis and in Postgres.
