-- reserve_seats.lua: hold specific seats, ALL or NOTHING, atomically.
--
-- Every requested seat must be free: no live hold on it (seat:{event}:{id}
-- doesn't exist) and not sold (not in sold:{event}). If even one is taken,
-- nothing at all is written. Redis runs the whole script as one step, so two
-- buyers choosing overlapping seats can never both get one of them.
--
-- KEYS: 1 = hold:{hold_id}   2 = holds:expiry   3 = uhold:{event}:{user}
--       4 = sold:{event}     5.. = seat:{event}:{seat_id}, one per seat
-- ARGV: 1 = hold_id   2 = user_id   3 = expires_at_ms   4 = user_cap
--       5 = ttl_seconds   6 = event_id   7 = tier_id
--       8.. = the seat ids, in the same order as KEYS 5..
--
-- Returns: {1}           reserved
--          {-1, seat_id} that seat is held or sold (the first one found)
--          {-2}          sold set missing: NOT initialised, never "nothing
--                        sold" (rule 4); rebuild it from the database
--          {-3}          this user would go over their per-event cap

local SEATS_FROM = 5
local seat_count = #KEYS - SEATS_FROM + 1

-- The sold set always holds a marker member once built, so "missing" can
-- only mean "not built yet" (Redis restarted or was flushed).
if redis.call('EXISTS', KEYS[4]) == 0 then
  return {-2}
end

local held = tonumber(redis.call('GET', KEYS[3]) or '0')
if held + seat_count > tonumber(ARGV[4]) then
  return {-3}
end

for i = SEATS_FROM, #KEYS do
  local seat_id = ARGV[8 + i - SEATS_FROM]
  if redis.call('EXISTS', KEYS[i]) == 1 or redis.call('SISMEMBER', KEYS[4], seat_id) == 1 then
    return {-1, seat_id}
  end
end

-- Every seat is free: from here on, do every write.
for i = SEATS_FROM, #KEYS do
  redis.call('SET', KEYS[i], ARGV[1])  -- the seat now points at this hold
end
local seat_list = table.concat(ARGV, ',', 8, #ARGV)
redis.call('INCRBY', KEYS[3], seat_count)
redis.call('EXPIRE', KEYS[3], tonumber(ARGV[5]) + 900)
redis.call('HSET', KEYS[1],
  'user', ARGV[2], 'event', ARGV[6], 'tier', ARGV[7], 'qty', seat_count,
  'status', 'HELD', 'expires_at', ARGV[3], 'seats', seat_list)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]) + 900)
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[1])
return {1}
