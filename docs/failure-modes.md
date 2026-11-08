# Failure modes

Every row is a way the system could go wrong, how the design prevents it, and
the test that proves it. The numbers match the adversarial test list in
CLAUDE.md section 11. Rows are added as each test is built; only tested
protections are listed here.

| # | Failure | What breaks | How this design prevents it | Test |
|---|---|---|---|---|
| 15 | Someone registers and asks to be an admin (`"role": "ADMIN"`, `is_admin`, and so on) | An attacker gets admin powers, such as creating or deleting events | The register request rejects unknown fields (422); `register_user()` has no `role` parameter and always sets `USER`; the DB column defaults to `USER` with a CHECK allowing only USER/ADMIN. Admins come only from a separate CLI (S1.6). | `tests/adversarial/test_15_self_registration_cannot_create_admin.py` |
| - | Two sign-ups with the same email at the same moment | Two accounts for one email; a later login is ambiguous | No check-then-insert. The `uq_users_email` UNIQUE constraint decides atomically, and the loser gets a typed `UserAlreadyExists` (409). | `tests/integration/test_register.py::test_ten_simultaneous_signups_with_one_email_create_exactly_one_user` |
| - | A user edits their token to say `"role": "ADMIN"`, or signs their own, or sends `alg: none` | Anyone becomes admin | Tokens are HS256-signed with a secret only the server knows; `decode_access_token` pins `algorithms=["HS256"]`, requires every claim, and checks `type == "access"`; any failure is a 401 with no detail | `tests/unit/test_tokens.py` |
| - | A stolen access token is used later | The thief acts as the user indefinitely | Access tokens expire after 15 minutes (`exp` is checked on every request) | `tests/unit/test_tokens.py::test_an_expired_token_is_rejected` |
| - | An attacker uses login to discover which emails are registered | Targeted phishing or password guessing | An identical 401 body for "no such email" and "wrong password", and similar timing, because unknown emails are still checked against a dummy hash (measured 73 vs 74 ms) | `tests/integration/test_login.py::test_wrong_password_and_unknown_email_get_the_identical_401` |
