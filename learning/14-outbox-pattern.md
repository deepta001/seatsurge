# 14. The outbox pattern

## The problem: two systems, no shared "commit"

After a confirm, two things must happen: save the order in **Postgres**, and
tell the worker (through **Redis**) to issue tickets. There is no single
transaction that covers both databases, so whichever you do first, a crash
in between leaves them disagreeing:

| Order of work | Crash in between | Result |
|---|---|---|
| Send the Redis message, then commit the order | after the send | The worker issues tickets for an order that doesn't exist |
| Commit the order, then send the message | after the commit | A paid order that never gets tickets |

## The fix: write the message into the database too

Put the message in an `outbox_events` table and insert it **in the same
transaction** as the order. Now "the order exists" and "the message exists"
are one atomic fact: both or neither.

A separate **relay** then reads the outbox and publishes each row:

```
confirm:  BEGIN; INSERT order; INSERT outbox_event; COMMIT
relay:    SELECT pending rows -> XADD to stream:orders -> mark PUBLISHED
worker:   reads stream:orders -> issues tickets          (S4.3+)
```

**Analogy:** the outbox is a letter tray on your desk. You write the
contract and its covering letter together and put both in the tray. A
courier (the relay) empties the tray. If the courier is off sick, the letters
wait in the tray: they are never lost.

## The catch: duplicates

The relay publishes, **then** marks the row PUBLISHED. If it crashes between
those two steps, the row is still PENDING and gets published again. So the
outbox gives **at-least-once** delivery: never lost, sometimes twice. That is
why the worker must be **idempotent** (S4.4): it remembers which `outbox_id`
it has handled and skips repeats.

## Several relays at once: `FOR UPDATE SKIP LOCKED`

```sql
SELECT * FROM outbox_events
 WHERE status = 'PENDING' AND next_retry_at <= now()
 ORDER BY id LIMIT 50
 FOR UPDATE SKIP LOCKED;
```

- `FOR UPDATE` locks the rows this relay took until it commits.
- `SKIP LOCKED` makes another relay **skip** those rows instead of waiting,
  and take the next free ones. Two relays share the work and never publish
  the same row at the same time.

Try it: `learning/examples/s4_1/skip_locked_demo.py` opens two transactions
and shows the second one skipping the rows the first has locked.
