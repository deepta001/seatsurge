# Primer 6: Docker and Docker Compose

**Analogy:** an **image** is a flat-pack furniture kit, and a **container**
is the assembled piece. **Docker Compose** is the floor plan: "put a Postgres
here and a Redis there, wire them up like this". One command builds the whole
room.

## Why containers

- **Same everywhere:** `postgres:16-alpine` is the same Postgres on your
  laptop, in CI and on a server.
- **Disposable:** you can delete it and recreate it in seconds. That's handy
  when we deliberately break things (flush Redis, kill the worker).
- **Nothing installed on Windows itself:** no Postgres or Redis installers
  needed.

## The parts of `docker-compose.yml`

| Part | Meaning |
|---|---|
| `image` | Which kit to use (name:version). |
| `environment` | Env vars passed into the container. `${POSTGRES_PASSWORD:?...}` is filled from `.env`, and Compose refuses to start if it's missing. |
| `ports: "127.0.0.1:5432:5432"` | Connects port 5432 on your computer to 5432 in the container, reachable only from this computer. |
| `volumes` | A named volume keeps Postgres data even if the container is removed. |
| `healthcheck` | A command Docker runs every 5s to ask "are you ready?" (`pg_isready`, `redis-cli ping`). |

## Commands

```
docker compose up -d --wait   # start in the background; wait until healthy
docker compose ps             # what's running and whether it's healthy
docker compose logs redis     # a service's output
docker compose stop redis     # stop one service (data kept)
docker compose down           # stop and remove containers (volume kept)
docker compose down -v        # ...and delete the data volume too (careful!)
```

## Try it

```
uv run python -m scripts.check_connections
```

Then stop Redis (`docker compose stop redis`), run the check again, and read
the error.
