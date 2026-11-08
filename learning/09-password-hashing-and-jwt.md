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
