# Primer 10: Redis data types and TTLs

**Analogy:** Redis is a whiteboard in RAM. It's incredibly fast (it never
touches a disk to answer), it does one command at a time, and things written
on it can be given a self-destruct timer.

## The types seatsurge uses (CLAUDE.md section 5)

| Type | Commands | Used for |
|---|---|---|
| String / counter | `SET`, `GET`, `INCR`, `DECRBY` | `inv:{event}:{tier}:avail`: live seats left; `uhold:...`: seats a user holds |
| Hash (a record with fields) | `HSET`, `HGET`, `HGETALL` | `hold:{id}`: user, tier, qty, status, expires_at |
| Sorted set (members ordered by a score) | `ZADD`, `ZRANGEBYSCORE` | `holds:expiry`: score = expiry time, so "which holds have expired?" is one fast query |
| Set (unique members) | `SADD`, `SISMEMBER` | `sold:{event}`: seat ids already sold |
| Stream | `XADD`, `XREADGROUP` | `stream:orders` (Phase C) |

## TTL: every hold expires

`SET key value EX 300` or `EXPIRE key 300` makes Redis delete the key
automatically after 300 seconds. `TTL key` shows the seconds left (`-2` means
the key doesn't exist). That's how an abandoned hold disappears without anyone
cleaning up.

## Missing is not zero

`GET` on a key that doesn't exist returns **nothing** (`nil`), not `0`. If the
inventory counter is missing (Redis restarted or was flushed), "0 seats left"
would be a lie that stops all sales, and treating it as "plenty" would
oversell. CLAUDE.md rule 4: missing means "not set up yet", so rebuild it
from the database (S2.8).

## One command at a time

Redis runs commands **one after another**, never two at once. So a single
`DECRBY` is atomic. But `GET` followed by `DECRBY` is **two** commands, and
other clients' commands can run in between. That's the S2.1 bug.

## Try it (Docker running)

```
docker compose exec redis redis-cli SET demo 100
docker compose exec redis redis-cli DECRBY demo 3
docker compose exec redis redis-cli SET sticker held EX 5
docker compose exec redis redis-cli TTL sticker
```
