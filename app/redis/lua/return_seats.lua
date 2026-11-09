-- return_seats.lua: put a cancelled order's seats back on sale in Redis, EXACTLY once.
--
-- Runs in the worker after the cancel was committed in Postgres (rule 6).
-- A marker key per order makes it idempotent: the first call sets the marker
-- and returns the seats; any repeat (a redelivered message) finds the marker
-- and changes nothing. All in one atomic script, so two workers can't both.
--
-- General admission: add the quantity back to the tier's counter.
-- Reserved seating (seat ids given): take the seats out of sold:{event}.
-- A missing counter or sold set is never created (rule 4): the next rebuild
-- reads Postgres, where the cancel already freed these seats.
--
-- KEYS: 1 = inv:{event}:{tier}:avail   2 = returned:{order_id}   3 = sold:{event}
-- ARGV: 1 = seats to give back   2 = how long to keep the marker (seconds)
--       3.. = seat ids (reserved seating only)
--
-- Returns:  1 = seats returned now
--           0 = already returned earlier (no change)
--          -1 = counter or sold set missing: nothing to change in Redis

if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', tonumber(ARGV[2])) then
  return 0
end

if #ARGV > 2 then
  if redis.call('EXISTS', KEYS[3]) == 0 then
    return -1
  end
  for i = 3, #ARGV do
    redis.call('SREM', KEYS[3], ARGV[i])
  end
  return 1
end

if redis.call('EXISTS', KEYS[1]) == 0 then
  return -1
end
redis.call('INCRBY', KEYS[1], tonumber(ARGV[1]))
return 1
