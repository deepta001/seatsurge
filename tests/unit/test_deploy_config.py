"""The deployment files keep their safety settings (S8.1).

These are plain text checks on docker-compose.yml, deploy/nginx.conf and the
Dockerfile, so a later edit can't quietly undo a protection. The live
behaviour was checked by hand with learning/examples/s8_1/.
"""

import re
from pathlib import Path

from app.core.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
NGINX = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")

POSTGRES_MAX_CONNECTIONS = 100  # the postgres:16 default
API_REPLICAS = 3


def service_block(name: str) -> str:
    """The text of one top-level Compose service (up to the next one)."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z]|^\S)", COMPOSE, re.M | re.S)
    assert match, f"service {name} not found"
    return match.group(1)


def test_three_api_replicas_reachable_only_through_nginx() -> None:
    api = service_block("api")
    assert f"replicas: {API_REPLICAS}" in api
    assert not re.search(r"^\s+ports:", api, re.M)  # no way in except nginx


def test_the_api_trusts_forwarded_ips_only_from_nginx() -> None:
    trusted = re.search(r"FORWARDED_ALLOW_IPS: (\S+)", service_block("api"))
    nginx_ip = re.search(r"ipv4_address: (\S+)", service_block("nginx"))
    assert trusted and nginx_ip
    assert trusted.group(1) == nginx_ip.group(1)  # exactly nginx, never "*"


def test_nginx_overwrites_the_client_address_everywhere() -> None:
    # Appending ($proxy_add_x_forwarded_for) would keep a client's fake value.
    forwarded = re.findall(r"proxy_set_header X-Forwarded-For (\S+);", NGINX)
    assert forwarded and set(forwarded) == {"$remote_addr"}
    assert NGINX.count("proxy_pass") == len(forwarded)  # every route sets it


def test_nginx_streams_sse_unbuffered_and_hides_metrics() -> None:
    stream = NGINX.split("location ~ ^/events/[0-9]+/stream$", 1)[1].split("}", 1)[0]
    assert "proxy_buffering off;" in stream
    assert re.search(r"location = /metrics \{\s*return 404;", NGINX)


def test_app_containers_do_not_run_as_root() -> None:
    users = re.findall(r"^USER (\S+)", DOCKERFILE, re.M)
    assert users and users[-1] != "root"
    assert "nginx-unprivileged" in service_block("nginx")


def test_database_pools_fit_postgres_connection_limit() -> None:
    fields = Settings.model_fields
    default_size = fields["db_pool_size"].default
    default_overflow = fields["db_max_overflow"].default
    per_process = default_size + default_overflow
    worker_processes = 1
    total = per_process * (API_REPLICAS + worker_processes)
    assert total < POSTGRES_MAX_CONNECTIONS  # 15 x 4 = 60 < 100


def test_nginx_gives_every_request_its_own_correlation_id_and_logs_it() -> None:
    # S8.2b: nginx's $request_id replaces any client value, on every route.
    ids = re.findall(r"proxy_set_header X-Correlation-ID (\S+);", NGINX)
    assert ids and set(ids) == {"$request_id"}
    assert NGINX.count("proxy_pass") == len(ids)
    assert "correlation_id=$request_id" in NGINX  # in nginx's own access log line


def test_containers_log_json_and_uvicorn_leaves_access_logs_to_the_app() -> None:
    assert re.search(r"^\s+LOG_FORMAT: json", COMPOSE, re.M)
    assert '"--no-access-log"' in DOCKERFILE
