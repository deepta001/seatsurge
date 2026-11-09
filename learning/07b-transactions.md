# Primer 7b: Transactions (all or nothing)

**Analogy:** a bank transfer is two steps: take $50 from Alice, give $50 to
Bob. If the power cuts out between them, the money must not vanish. A
transaction is a promise: **either every step happens, or none of them do.**

## ACID, in plain words

| Letter | Means | In seatsurge |
|---|---|---|
| **A**tomic | All the steps happen, or none do | an order and its outbox row are saved together (S3.3) |
| **C**onsistent | Every rule (constraint) holds when it's committed | `sold <= capacity`, unique issued tickets |
| **I**solated | Others don't see your half-finished work | another request never sees an order without its outbox row |
| **D**urable | Once committed, it survives a crash | a PENDING order is never lost |

## The commands

```sql
BEGIN;              -- start
INSERT ...;         -- step 1
INSERT ...;         -- step 2
COMMIT;             -- make it all permanent (or ROLLBACK to undo it all)
```

In SQLAlchemy: `async with engine.begin():` (commit on success, roll back on
error), or `session.commit()` / `session.rollback()`. A **savepoint**
(`begin_nested()`) is a smaller transaction inside a bigger one.

## Why it matters here

Confirming a hold (S3.3) must write the **order** and a "please issue the
tickets" note (the **outbox** row) together. If the order were saved but the
note lost, the customer would pay and never get tickets. If the note were
saved without the order, the worker would issue tickets for nothing.

## The rules Postgres keeps for us (S3.1)

- `orders.hold_id` is UNIQUE: one hold can become at most one order.
- `UNIQUE(user_id, idempotency_key)`: retried confirms find the first order.
- `uq_tickets_issued_seat` and `uq_tickets_issued_number` are **partial**
  unique indexes (`WHERE status = 'ISSUED'`). No two issued tickets share a
  seat or a number, but a cancelled ticket's seat can be sold again.
- In a unique index, NULLs are never equal, so general-admission tickets
  (no seat) never clash on the seat index.

## Try it

```
uv run python -m learning.examples.s3_1.transaction_demo
```

It writes an order and then a failing ticket two ways: as separate steps,
where the order is left behind half-done, and as one transaction, where both
vanish together. Then it rolls everything back.
