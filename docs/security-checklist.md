# Security checklist

CLAUDE.md section 9 (plus rule 10), item by item: the status, where it's
done, and the test that proves it. Audited in S7.2. "Pending" items depend
on parts not built yet and are listed so they aren't forgotten.

| # | Requirement | Status | How | Proof |
|---|---|---|---|---|
| 1 | Self-registration is always `USER` | Done | The register request has no `role` field (unknown fields are a 422); `register_user()` always sets `USER`; DB CHECK on `role` | adversarial test 15 |
| 2 | Admins only via a CLI or env-seeded value; no default credentials | Done | `scripts/seed_admin.py`; `.env.example` only has `CHANGE_ME` placeholders, and **the app refuses to start with one** (S7.2) | `tests/unit/test_seed_admin.py`, `test_security_hardening.py::test_settings_refuse_the_placeholder_secrets` |
| 3 | JWT access token (15 min) with user id and role, plus a refresh token | Done | HS256 with a 32+ character secret; algorithm pinned; claims required; refresh tokens stored hashed, rotated, reuse revokes the family | `tests/unit/test_tokens.py`, `tests/integration/test_refresh.py` |
| 4 | The auth dependency doesn't hit the DB on every request | Done | `get_current_user` only verifies the token | `tests/unit/test_me.py` (passes with the DB unreachable) |
| 5 | Passwords: minimum length, argon2/bcrypt | Done | 12-128 characters; argon2id | `tests/integration/test_register.py`, `tests/unit/test_security.py` |
| 6 | Login endpoint rate limited | Done (S7.1) | 5 per email and 20 per IP per 60 s, sliding window. Behind nginx (S8.1) the IP is the real client's: nginx overwrites `X-Forwarded-For`, and the api trusts it only from nginx's fixed address | adversarial test 14; `test_deploy_config.py`; `learning/examples/s8_1/spoofed_ip_demo.py` (25 attempts with fake IPs: 20 x 401, then 429) |
| 7 | CORS: origin allowlist from env; no wildcard with credentials | Done (S7.2) | `CORS_ORIGINS` (empty = none); `"*"` refused at startup; `allow_credentials=False` (tokens travel in headers, not cookies) | `test_security_hardening.py` (CORS, wildcard) |
| 8 | No test or simulation endpoints in the app | Done | The route list is pinned: a new route fails a test until it's added on purpose; load generation will live in `loadtest/` | `test_security_hardening.py::test_the_app_serves_exactly_the_known_routes` |
| 9 | Secrets only from `.env` (with `.env.example`) | Done | Settings have no defaults for secrets; `SecretStr` hides them in logs; `.env` is git-ignored; placeholders are refused | `test_settings_refuse_the_placeholder_secrets`, `.gitignore` |
| 10 | Redis requires a password | Done | Compose runs `redis-server --requirepass` and refuses to start without `REDIS_PASSWORD` | `docker-compose.yml` |
| 11 | `/metrics` is not publicly routed | **Partly (S8.1)** | nginx already answers `/metrics` with 404; the endpoint itself arrives in S8.2 | `test_deploy_config.py::test_nginx_streams_sse_unbuffered_and_hides_metrics` |
| 12 | Containers run as non-root | Done (S8.1) | The app image ends with `USER appuser` (uid 10001); nginx uses the official unprivileged image; Postgres and Redis drop to their own users | `tests/unit/test_deploy_config.py::test_app_containers_do_not_run_as_root`; `id` in each container showed `appuser` / `nginx` |
| 13 | Request size caps: at most 10 seats per hold, a per-user hold cap that repeated calls can't bypass | Done | Body limit 16 KB; 1-10 seats per hold; the per-user cap is checked atomically in Lua | `tests/unit/test_body_limit.py`, `tests/concurrency/test_user_hold_cap.py`, `test_seat_holds.py` |
| 14 | Rule 10: client errors never include raw exception text | Done (S7.2) | Typed errors return `{error, message}`; **422s no longer echo the submitted values** (a short password isn't sent back); unexpected errors return a generic 500 with a `correlation_id`, and the details go only to the log | `test_security_hardening.py` (422, 500) |
| 15 | Interactive API docs not public in production | Done (S7.2, extra) | `/docs`, `/redoc`, `/openapi.json` are off when `ENVIRONMENT=production` | `test_security_hardening.py::test_api_docs_are_off_in_production` |

## Found and fixed during the audit

- **No CORS policy at all.** Added an allowlist from the environment.
- **The app started happily with `CHANGE_ME` secrets.** It now refuses.
- **422 responses echoed the submitted value,** including a rejected
  password. They now say which field and what's wrong, not what was sent.
- **Unexpected errors were FastAPI's plain-text 500** with no way to find
  the matching log line. They now carry a correlation id (body and
  `X-Correlation-ID` header).
- **Alembic's logging setup silenced every existing logger** (the default
  `disable_existing_loggers=True`). Found while testing the 500 log line;
  the app's error logs vanished in any process that had run migrations.
