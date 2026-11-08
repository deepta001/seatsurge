-- reserve_tier.lua: hold `qty` general-admission seats in one tier, atomically.
--
-- Redis runs this whole script as ONE step: no other command can run in the
-- middle, so two buyers can never both take the last seat (CLAUDE.md rule 3).
-- Every refusal returns BEFORE the first write, so a refused request changes
-- nothing at all (all or nothing).
--
-- KEYS: 1 = inv:{event}:{tier}:avail   2 = hold:{hold_id}
--       3 = holds:expiry               4 = uhold:{event}:{user}
-- ARGV: 1 = qty            2 = hold_id     3 = user_id   4 = expires_at_ms
--       5 = user_cap       6 = ttl_seconds 7 = tier_id   8 = event_id
--
-- Returns:  1 = reserved
--          -1 = sold out (fewer than qty seats left)
--          -2 = counter missing: NOT initialised, never "zero" (rule 4)
--          -3 = this user would go over their per-event cap

local qty = tonumber(ARGV[1])

local avail = tonumber(redis.call('GET', KEYS[1]))
if avail == nil then
  return -2
end

local held = tonumber(redis.call('GET', KEYS[4]) or '0')
if held + qty > tonumber(ARGV[5]) then
  return -3
end

if avail < qty then
  return -1
end

-- All checks passed: from here on, do every write.
redis.call('DECRBY', KEYS[1], qty)
redis.call('INCRBY', KEYS[4], qty)
redis.call('HSET', KEYS[2],
  'user', ARGV[3], 'event', ARGV[8], 'tier', ARGV[7], 'qty', qty,
  'status', 'HELD', 'expires_at', ARGV[4])
-- The record outlives the hold by 15 minutes, so the sweeper and the
-- confirm step can still read it just after it expires.
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[6]) + 900)
redis.call('ZADD', KEYS[3], ARGV[4], ARGV[2])
return 1
