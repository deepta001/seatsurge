-- release_hold.lua: give a hold's seats back, EXACTLY once.
--
-- Used when a user cancels a hold (RELEASED), by the sweeper when a hold's
-- time is up (EXPIRED), and by the worker when an order FAILED (RELEASED,
-- with ARGV[9] = '1' because that hold is CONFIRMING). Atomic, and
-- idempotent: the status check means a second call (a retry, or the sweeper
-- racing a user's cancel) changes nothing.
--
-- KEYS: 1 = hold:{hold_id}   2 = holds:expiry
--       3 = inv:{event}:{tier}:avail   4 = uhold:{event}:{user}
--       5 = holds:confirming
-- ARGV: 1 = hold_id   2 = new status (RELEASED or EXPIRED)
--       3 = user id that must own the hold ('' = anyone, for the sweeper)
--       4 = now in ms (only used when ARGV[5] == '1')
--       5 = '1' = only release if the hold has expired (sweeper mode)
--       6 = event id   7 = tier id   8 = user id   (what the caller read,
--           re-checked here so KEYS 3 and 4 really belong to this hold)
--       9 = '1' = also release a CONFIRMING hold (only after its order FAILED
--           in the database; never used by the API or the sweeper)
--
-- Returns:  1 = released now
--           0 = already finished earlier (no change)
--          -1 = no such hold
--          -2 = belongs to someone else (no change)
--          -3 = not expired yet (sweeper mode; no change)
--          -4 = keys don't match the hold's record (no change)

local hold = KEYS[1]
local status = redis.call('HGET', hold, 'status')
if not status then
  redis.call('ZREM', KEYS[2], ARGV[1])  -- tidy stale index entries
  redis.call('ZREM', KEYS[5], ARGV[1])
  return -1
end

if ARGV[3] ~= '' and redis.call('HGET', hold, 'user') ~= ARGV[3] then
  return -2
end

if redis.call('HGET', hold, 'event') ~= ARGV[6]
    or redis.call('HGET', hold, 'tier') ~= ARGV[7]
    or redis.call('HGET', hold, 'user') ~= ARGV[8] then
  return -4
end

-- Only a HELD hold gives seats back. RELEASED/EXPIRED already did; a
-- CONSUMED hold became tickets; a CONFIRMING hold is being bought, and is
-- only released when the caller says its order FAILED (ARGV[9]).
local releasable = status == 'HELD' or (status == 'CONFIRMING' and ARGV[9] == '1')
if not releasable then
  redis.call('ZREM', KEYS[2], ARGV[1])
  return 0
end

if ARGV[5] == '1' and tonumber(redis.call('HGET', hold, 'expires_at')) > tonumber(ARGV[4]) then
  return -3
end

local qty = tonumber(redis.call('HGET', hold, 'qty'))

-- Return the seats, but never CREATE a missing counter: a missing counter
-- means "rebuild from the database" (rule 4), and that rebuild will see
-- this hold is no longer active.
if redis.call('EXISTS', KEYS[3]) == 1 then
  redis.call('INCRBY', KEYS[3], qty)
end

-- The user's held count goes down, but never below zero.
local held = tonumber(redis.call('GET', KEYS[4]) or '0')
if held - qty > 0 then
  redis.call('DECRBY', KEYS[4], qty)
else
  redis.call('DEL', KEYS[4])
end

redis.call('HSET', hold, 'status', ARGV[2])
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[5], ARGV[1])
return 1
