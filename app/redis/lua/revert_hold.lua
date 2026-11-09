-- revert_hold.lua: undo consume_hold (CONFIRMING -> HELD) when confirming fails.
--
-- Used when payment is declined or the database write fails: the seats stay
-- the user's until the hold's ORIGINAL expiry time. If that time has already
-- passed, the sweeper releases it on its next pass.
--
-- KEYS: 1 = hold:{hold_id}   2 = holds:expiry   3 = holds:confirming
-- ARGV: 1 = hold_id
-- Returns: 1 = reverted, 0 = not CONFIRMING (nothing to undo)

local hold = KEYS[1]
if redis.call('HGET', hold, 'status') ~= 'CONFIRMING' then
  return 0
end
redis.call('HSET', hold, 'status', 'HELD')
redis.call('ZREM', KEYS[3], ARGV[1])
redis.call('ZADD', KEYS[2], redis.call('HGET', hold, 'expires_at'), ARGV[1])
return 1
