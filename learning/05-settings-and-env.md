# Primer 5: Settings and environment variables

**Analogy:** the code is a recipe and the settings are the shopping list for
this particular kitchen. The recipe never changes, but the list says which
oven (database) to use, and the key to the pantry (password) is kept in your
pocket, not written in the recipe book.

## Environment variables

These are name=value pairs that the operating system hands to every program it
starts. In PowerShell: `$env:ENVIRONMENT = 'production'`.

## The `.env` file

This is a plain-text list of name=value lines, loaded for convenience during
local development.

- **`.env`** holds your real secrets. It's listed in `.gitignore`, so it's
  never committed.
- **`.env.example`** is the committed template with `CHANGE_ME`
  placeholders, so a new developer knows what to fill in.
- **Order of priority:** a real environment variable beats the `.env` file,
  which beats the default in the code.

## Why one typed `Settings` class

`app/core/settings.py` declares each setting once, with its type.
pydantic-settings reads the values and **validates** them when the app
starts:

- If a value is missing or wrong, the app crashes immediately with a clear
  message, instead of failing later in some confusing way. This is called
  "fail fast".
- `SecretStr` hides passwords when printed (`**********`). Use
  `.get_secret_value()` only at the one place that really needs the password.
- `get_settings()` is wrapped in `@lru_cache`, which remembers the result, so
  `.env` is read once, not on every request.

## Try it

```
uv run python -c "from app.core.settings import get_settings; print(get_settings())"
```

```
$env:ENVIRONMENT = 'banana'; uv run python -c "from app.core.settings import get_settings; get_settings()"
```

(The second one fails on purpose. Run `Remove-Item Env:ENVIRONMENT` afterwards.)
