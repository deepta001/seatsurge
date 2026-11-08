# Primer 12: Lua scripts inside Redis

**Analogy:** instead of phoning the box office twice ("any seats left?" ...
"OK, I'll take one"), you hand the clerk a sealed instruction card: "If there
are at least 2 seats, take 2; otherwise take none." The clerk does the whole
card before serving anyone else.

## Why Lua fixes the race

Redis runs a Lua script as **one uninterruptible step**: no other command can
run halfway through. So check-and-take becomes atomic, which is exactly what
S2.1 was missing. And because the script runs inside Redis, it works no matter
how many API replicas send it (unlike a Python lock).

## A tiny example: `learning/examples/s2_2/take_seats.lua`

```lua
local available = tonumber(redis.call('GET', KEYS[1]))
if available == nil then return -2 end        -- missing: NOT zero
local qty = tonumber(ARGV[1])
if available < qty then return 0 end          -- not enough: change nothing
redis.call('DECRBY', KEYS[1], qty)
return 1
```

- **`KEYS`:** the keys the script touches. **`ARGV`:** other arguments. Both
  are 1-indexed lists, and every value arrives as a string, hence `tonumber`.
- **`redis.call(...)`** runs a normal Redis command from inside the script.
- **Return codes** tell the caller what happened, without any partial
  changes: all or nothing.

## Running it

- **By hand:** `redis-cli --eval take_seats.lua seats_key , 2` (keys before
  the comma, args after).
- **Load once, call by fingerprint:** `SCRIPT LOAD` returns a SHA, then
  `EVALSHA <sha> 1 seats_key 2` avoids resending the script text every time.
- **From Python:** `script = redis.register_script(text)`, then
  `await script(keys=[...], args=[...])`, which uses EVALSHA automatically.

## Rules for writing scripts

- Keep them short and fast: while a script runs, Redis serves **nobody
  else**.
- Declare every key in `KEYS` (needed if Redis is ever clustered).
- Validate first, then write. Once you start writing, finish: no early
  return halfway through the writes.

## Measured (S2.2): naive vs Lua, 1,000 buyers on 100 seats

| Version | 5 side-by-side runs |
|---|---|
| Naive `GET` then `DECR` | oversold every run, by 2 to 43 seats |
| Lua `take_seats.lua` | exactly 100 sold, counter 0, every run (also in 10 more runs, and 2 runs with 5,000 buyers) |

```
uv run python -m learning.examples.s2_1.oversell_demo --mode all
```
