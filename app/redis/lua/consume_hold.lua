-- consume_hold.lua: start confirming a hold (HELD -> CONFIRMING), atomically.
--
-- Returns the hold's OWN event, tier and quantity: the server-side truth that
-- confirm uses, never anything the client sent (CLAUDE.md rule 1).
-- The hold moves from holds:expiry to holds:confirming, so the expiry sweeper
-- leaves it alone while it's being bought. Its seats stay taken.
--
-- KEYS: 1 = hold:{hold_id}   2 = holds:expiry   3 = holds:confirming
-- ARGV: 1 = hold_id   2 = user id of the caller   3 = now in ms
--       4 = grace in ms (how long a confirm may take before the sweeper
--           checks on it; the score in holds:confirming is expires_at + grace)
--
-- Returns: {1, event, tier, qty}  started confirming
--          {-1}  no such hold
--          {-2}  belongs to someone else
--          {-3}  already CONFIRMING or CONSUMED (a confirm already ran)
--          {-4}  expired or released

local hold = KEYS[1]
local status = redis.call('HGET', hold, 'status')
if not status then
  return {-1}
end
if redis.call('HGET', hold, 'user') ~= ARGV[2] then
  return {-2}
end
if status == 'CONFIRMING' or status == 'CONSUMED' then
  return {-3}
end
if status ~= 'HELD' then
  return {-4}
end
local expires_at = tonumber(redis.call('HGET', hold, 'expires_at'))
if expires_at <= tonumber(ARGV[3]) then
  return {-4}  -- expired but not swept yet: too late all the same
end

redis.call('HSET', hold, 'status', 'CONFIRMING')
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZADD', KEYS[3], expires_at + tonumber(ARGV[4]), ARGV[1])
-- Keep the record for a day: the worker needs it until tickets are issued.
redis.call('EXPIRE', hold, 86400)
return {1, redis.call('HGET', hold, 'event'), redis.call('HGET', hold, 'tier'),
        redis.call('HGET', hold, 'qty')}
