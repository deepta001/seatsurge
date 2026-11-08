# Failure modes

Every row is a way the system could go wrong, how the design prevents it, and
the test that proves it. The numbers match the adversarial test list in
CLAUDE.md section 11. Rows are added as each test is built; only tested
protections are listed here.

| # | Failure | What breaks | How this design prevents it | Test |
|---|---|---|---|---|
| 15 | Someone registers and asks to be an admin (`"role": "ADMIN"`, `is_admin`, and so on) | An attacker gets admin powers, such as creating or deleting events | The register request rejects unknown fields (422); `register_user()` has no `role` parameter and always sets `USER`; the DB column defaults to `USER` with a CHECK allowing only USER/ADMIN. Admins come only from a separate CLI (S1.6). | `tests/adversarial/test_15_self_registration_cannot_create_admin.py` |
| - | Two sign-ups with the same email at the same moment | Two accounts for one email; a later login is ambiguous | No check-then-insert. The `uq_users_email` UNIQUE constraint decides atomically, and the loser gets a typed `UserAlreadyExists` (409). | `tests/integration/test_register.py::test_ten_simultaneous_signups_with_one_email_create_exactly_one_user` |
