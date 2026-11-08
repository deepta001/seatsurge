-- Take `qty` seats ONLY if that many are left, as one indivisible step.
-- Redis runs the whole script before any other command, so nobody can
-- change the counter between the check and the decrement (the S2.1 bug).
--
-- KEYS[1] = the available-seats counter     ARGV[1] = how many seats to take
-- Returns:  1 = taken,  0 = not enough left,
--          -2 = counter missing: "not set up yet", NEVER the same as zero
--               (CLAUDE.md rule 4; the caller must rebuild it from the DB)

local available = tonumber(redis.call('GET', KEYS[1]))
if available == nil then
  return -2
end

local qty = tonumber(ARGV[1])
if available < qty then
  return 0
end

redis.call('DECRBY', KEYS[1], qty)
return 1
