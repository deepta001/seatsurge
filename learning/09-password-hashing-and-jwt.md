# Primer 9: Password hashing (part 1; JWT comes in S1.4)

**Analogy:** a hash is a paper shredder that always shreds the same page into
the same confetti pattern. You can check whether a page matches the confetti
(shred it and compare), but you can't un-shred confetti back into the page.

## Why never store the password itself

Databases leak: backups, logs, a misconfigured server. If you stored
passwords, every user's password is exposed, and people reuse passwords on
other sites. If you stored hashes, an attacker has to **guess** each password
and hash every guess to compare.

## Why argon2, and why slow is good

A normal hash (SHA-256) takes nanoseconds, so a graphics card can try
billions of guesses per second. argon2 is built to be **slow and
memory-hungry** (~55 ms and 64 MB per hash on this laptop). That's nothing for
one login, but brutal for billions of guesses.

## Salt

Each hash mixes in a random **salt**, stored inside the hash string itself:

```
$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
```

So two users with the same password get **different** hashes, and an attacker
can't crack everyone at once with a precomputed table.

## In this project

- `app/core/security.py`: `hash_password()` and `verify_password()`.
- Registration stores only the hash. The API response model has no
  password field at all.
- Passwords must be 12 to 128 characters. The maximum stops someone sending
  a huge "password" to make the server burn time hashing it.

## Try it

```
uv run python -c "from app.core.security import hash_password as h; print(h('pw')); print(h('pw'))"
```

The same password is printed twice as two different hashes.

---

# Part 2: JWT access tokens (S1.4)

**Analogy:** a JWT is a festival wristband with a tamper-proof seal. Staff
don't phone the box office every time you walk past; they glance at the
wristband (who you are, which areas you're allowed in, when it expires) and
check that the seal is intact.

## The three parts: `header.payload.signature`

- **Header:** `{"alg": "HS256", "typ": "JWT"}`.
- **Payload:** the claims, for example
  `{"sub": "4", "role": "USER", "type": "access", "iat": ..., "exp": ...}`.
  It's only base64-encoded, **not encrypted**: anyone can read it, so never
  put secrets in it.
- **Signature:** HMAC-SHA256 of the first two parts, using `JWT_SECRET_KEY`.
  Change one character of the payload and the signature no longer matches.

## Why the API can skip the database

The signature proves the server issued the token, and `exp` proves it's
recent. So `get_current_user` trusts the claims without a query, which keeps
every request fast (CLAUDE.md section 9).

**Trade-off:** a deleted or demoted user keeps their old powers until the
token expires. Keeping tokens short (15 min) limits that window, and refresh
tokens (S1.5) keep people signed in without long-lived access tokens.

## Attacks the tests cover (`tests/unit/test_tokens.py`)

| Attack | Why it fails |
|---|---|
| Edit the payload to say `ADMIN` | The signature no longer matches |
| Sign your own token | You don't have the secret key |
| `alg: none` (no signature) | We accept only `HS256` (`algorithms=[...]` is pinned) |
| Reuse an old token | `exp` has passed |
| Use a refresh token as an access token | The `type` claim must be `access` |

## Login without leaking who has an account

A wrong password and an unknown email return the **same** 401 body, and take
about the same time (an unknown email is still checked against a dummy
hash). Measured live: 73 ms vs 74 ms.

## Try it

Open http://127.0.0.1:8000/docs, log in with `POST /auth/login`, click
**Authorize**, paste the `access_token`, and call `GET /me`.

---

# Part 3: Refresh tokens (S1.5)

**Analogy:** a refresh token is a cloakroom ticket. Hand it in and you get
your coat (a new access token) **plus a new ticket**; the old ticket is
torn up. If someone later shows up with a torn-up ticket, the cloakroom knows
a copy was made and cancels every ticket from that visit.

## The flow

```
login              -> access A1 (15 min) + refresh R1 (7 days)
refresh R1         -> access A2 + refresh R2      (R1 marked used)
refresh R2         -> access A3 + refresh R3
refresh R1 again   -> 401, and R2 and R3 are revoked too (reuse = theft)
logout R3          -> R3's whole family is revoked
```

## Why each piece

- **Random, not a JWT:** it has to be looked up and revoked anyway, so
  there's no point making it self-describing.
- **Stored as a SHA-256 hash:** a database leak doesn't hand out working
  tokens.
- **Rotation (single use):** a leaked token is only useful until its owner
  next refreshes.
- **Family revocation on reuse:** if both the thief and the real user hold
  copies, whoever goes second triggers it, and both must log in again.
- **One conditional UPDATE to claim a token:** of 5 simultaneous refreshes
  with the same token, exactly one wins (tested).
- **Refresh reads the user from the DB:** a role change takes effect at the
  next refresh, within 15 minutes.
