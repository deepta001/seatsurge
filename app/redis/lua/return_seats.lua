-- return_seats.lua: put a cancelled order's seats back on the Redis counter, EXACTLY once.
--
-- Runs in the worker after the cancel was committed in Postgres (rule 6).
-- A marker key per order makes it idempotent: the first call sets the marker
-- and adds the seats; any repeat (a redelivered message) finds the marker and
-- changes nothing. All in one atomic script, so two workers can't both add.
--
-- KEYS: 1 = inv:{event}:{tier}:avail   2 = returned:{order_id}
-- ARGV: 1 = seats to give back   2 = how long to keep the marker (seconds)
--
-- Returns:  1 = seats returned now
--           0 = already returned earlier (no change)
--          -1 = counter missing: not created (rule 4); the rebuild will see
--               the lower `sold` in Postgres and count these seats as free

if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', tonumber(ARGV[2])) then
  return 0
end
if redis.call('EXISTS', KEYS[1]) == 0 then
  return -1
end
redis.call('INCRBY', KEYS[1], tonumber(ARGV[1]))
return 1
