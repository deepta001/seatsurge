-- finish_hold.lua: after tickets are issued, mark the hold CONSUMED (CONFIRMING -> CONSUMED).
--
-- Runs AFTER the database commit (rule 6). Its seats are now sold in Postgres,
-- so they are NOT returned to the counter; the hold just stops counting as
-- "held": it leaves holds:confirming and the user's held count goes down.
-- Idempotent: a second call finds CONSUMED and changes nothing, so a
-- redelivered message can safely run it again.
--
-- KEYS: 1 = hold:{hold_id}   2 = holds:confirming   3 = uhold:{event}:{user}
-- ARGV: 1 = hold_id   2 = event id   3 = user id (from the order, re-checked
--       here so KEY 3 really belongs to this hold)
--
-- Returns:  1 = finished now
--           0 = not CONFIRMING (already finished, or never confirmed): no change
--          -1 = no such hold (its record already expired): index tidied
--          -4 = the hold's record doesn't match the order (no change)

local hold = KEYS[1]
local status = redis.call('HGET', hold, 'status')
if not status then
  redis.call('ZREM', KEYS[2], ARGV[1])
  return -1
end
if redis.call('HGET', hold, 'event') ~= ARGV[2] or redis.call('HGET', hold, 'user') ~= ARGV[3] then
  return -4
end
if status ~= 'CONFIRMING' then
  redis.call('ZREM', KEYS[2], ARGV[1])
  return 0
end

local qty = tonumber(redis.call('HGET', hold, 'qty'))
local held = tonumber(redis.call('GET', KEYS[3]) or '0')
if held - qty > 0 then
  redis.call('DECRBY', KEYS[3], qty)
else
  redis.call('DEL', KEYS[3])
end

redis.call('HSET', hold, 'status', 'CONSUMED')
redis.call('ZREM', KEYS[2], ARGV[1])
-- Kept a day so a late re-confirm still finds it and gets the existing order.
redis.call('EXPIRE', hold, 86400)
return 1
