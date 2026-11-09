# 15. Redis Streams and consumer groups

## A stream is an append-only log

A Redis Stream is a list of entries that only ever grows at the end. Each
entry gets an id like `1794216930353-0` (the milliseconds when it was added,
then a counter) and holds a small map of string fields.

```
XADD stream:orders * outbox_id 7 type order.placed ...   -> "1794216930353-0"
XRANGE stream:orders - +                                  -> every entry, oldest first
```

Unlike pub/sub, reading an entry doesn't remove it, and an entry added while
nobody is listening is still there later. That's why the relay can publish
before any worker is running: the messages wait.

## Consumer groups share the work

A **consumer group** is a named reader of one stream that remembers how far
it has got. Several worker processes (**consumers**) join the same group,
and Redis hands each new entry to **exactly one** of them.

```
XGROUP CREATE stream:orders order-workers 0 MKSTREAM          # once
XREADGROUP GROUP order-workers worker-a COUNT 10 STREAMS stream:orders >
XACK stream:orders order-workers 1794216930353-0               # "done"
```

- `>` means "give me entries no one in this group has been given yet".
- `0` in `XGROUP CREATE` means "start from the very first entry", so nothing
  published before the group existed is skipped. (`$` would mean "only new
  ones from now on".)
- `MKSTREAM` creates the stream if it doesn't exist yet.

**Analogy:** a restaurant ticket rail. Orders are pinned along the rail
(the stream). Each cook (consumer) takes the next ticket nobody has taken.
The head chef keeps a list of tickets taken but not yet served (the
**pending entries list**, or PEL). A cook says "served" (`XACK`) only once
the dish is really out.

## The pending entries list (PEL)

Every entry handed out with `XREADGROUP` sits in the group's PEL until it's
acknowledged. If a worker crashes halfway, the entry stays there, marked
with which consumer had it and how many times it was delivered:

```
XPENDING stream:orders order-workers   -> how many are unacknowledged, and by whom
```

`>` never hands out a pending entry again. Picking up stuck ones is a
separate step (`XAUTOCLAIM`, in S4.6). That is how the system gets
**at-least-once** processing: acknowledge only after the work is committed,
and anything unacknowledged can be retried.

Try it: `learning/examples/s4_3/stream_demo.py` runs two consumers in one
group, acks some entries and leaves one pending.
