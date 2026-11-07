# Primer 2: HTTP, REST, JSON and status codes

**Analogy:** HTTP is a restaurant order slip. The client (your browser or
app) writes a slip, hands it to the server (the kitchen), and gets back a
plate with a little ticket saying how it went.

## A request has

- A **method** (what you want to do): `GET` reads, `POST` creates, `PATCH`
  changes, `DELETE` removes.
- A **path** (what you want it done to): `/events/42/holds`.
- **Headers** (extra notes on the slip), for example `Idempotency-Key: abc`.
- An optional **body**, usually JSON.

## A response has

- A **status code** (how it went):

  | Code | Meaning | In this project |
  |---|---|---|
  | 200 | OK | reading an event |
  | 201 | Created | a hold was made |
  | 202 | Accepted, still working on it | confirm (the worker finishes later) |
  | 404 | Not found | unknown event |
  | 409 | Conflict | sold out |
  | 422 | Your request is invalid | bad quantity |
  | 429 | Too many requests | rate limited |
  | 500 | Server bug | never show internals |

- A **body**, usually JSON.

## JSON

JSON is text that looks like Python dicts and lists:
`{"message": "Hello from seatsurge"}`. FastAPI turns your returned dict into
JSON for you.

## REST

REST is a convention: paths name **things** (nouns like `/events`, `/holds`)
and methods say the **action**. For example, `POST /events/42/holds` means
"create a hold on event 42".

## Try it

```
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ and http://127.0.0.1:8000/docs.
