-- rate_limit.lua: a sliding-window limit, "at most LIMIT requests in any WINDOW".
--
-- The key is a sorted set of this caller's recent requests, scored by time.
-- Each call: forget requests older than the window, count the rest, and
-- either refuse (saying how long until the oldest one leaves the window) or
-- record this request. Atomic, so 50 requests arriving together can't all
-- read "9 so far" and all get in.
--
-- The time comes from Redis itself (TIME), not the caller, so three API
-- replicas with slightly different clocks still share one window.
--
-- KEYS: 1 = rl:{scope}:{who}
-- ARGV: 1 = window in ms   2 = limit   3 = a unique id for this request
--
-- Returns: 0        allowed (and counted)
--          n > 0    refused: retry after n milliseconds

local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local window = tonumber(ARGV[1])

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)

if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  local oldest = tonumber(redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')[2])
  return math.max(1, oldest + window - now)
end

redis.call('ZADD', KEYS[1], now, ARGV[3])
-- The whole set disappears once the window has passed with no requests.
redis.call('PEXPIRE', KEYS[1], window)
return 0
