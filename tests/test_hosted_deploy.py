"""Hosted-demo settings (deploy/render_start.sh): public Host, client IP, forwarding.

Every setting is opt-in through an environment variable, so the local
defaults (loopback only, raw socket peer) stay exactly as they were.
"""

import importlib
import os
import sys

from starlette.requests import Request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))


def _web(monkeypatch, **env):
    for key in ("SER_ALLOWED_HOSTS", "SER_CLIENT_IP_HEADER", "SER_ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import app as web_app
    return importlib.reload(web_app)


def _request(headers, peer="10.0.0.7"):
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/mcp", "headers": raw,
                    "client": (peer, 5555), "query_string": b""})


def test_public_host_is_refused_by_default(monkeypatch):
    web = _web(monkeypatch)
    assert not web._loopback_host_allowed("demo.onrender.com")
    assert web._loopback_host_allowed("127.0.0.1:8080")


def test_allowed_hosts_accepts_only_the_listed_name(monkeypatch):
    web = _web(monkeypatch, SER_ALLOWED_HOSTS="demo.onrender.com, *.evil.com ,bad/x")
    assert web._loopback_host_allowed("demo.onrender.com")
    assert web._loopback_host_allowed("Demo.onrender.com:443")
    assert not web._loopback_host_allowed("evil.onrender.com")
    assert not web._loopback_host_allowed("x.evil.com")
    assert web.EXTRA_ALLOWED_HOSTS == {"demo.onrender.com"}


def test_client_ip_defaults_to_socket_peer(monkeypatch):
    web = _web(monkeypatch)
    req = _request({"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4"})
    assert web.client_ip(req) == "10.0.0.7"


def test_client_ip_uses_configured_edge_header(monkeypatch):
    web = _web(monkeypatch, SER_CLIENT_IP_HEADER="cf-connecting-ip")
    assert web.client_ip(_request({"cf-connecting-ip": "203.0.113.9"})) == "203.0.113.9"
    assert web.client_ip(_request({})) == "10.0.0.7"
    assert web.client_ip(_request({"cf-connecting-ip": "1.1.1.1, 2.2.2.2"})) == "10.0.0.7"


def test_x_forwarded_for_is_never_the_key(monkeypatch):
    web = _web(monkeypatch, SER_CLIENT_IP_HEADER="x-forwarded-for")
    assert web.client_ip(_request({"x-forwarded-for": "1.2.3.4"})) == "10.0.0.7"


def test_upstream_headers_overwrite_client_ip_and_drop_forwarding(monkeypatch):
    web = _web(monkeypatch, SER_CLIENT_IP_HEADER="cf-connecting-ip")
    req = _request({"cf-connecting-ip": "203.0.113.9", "x-ser-client-ip": "6.6.6.6",
                    "x-forwarded-for": "1.2.3.4", "authorization": "Bearer tok-manager"})
    out = {k.lower(): v for k, v in web.upstream_headers(req).items()}
    assert out["x-ser-client-ip"] == "203.0.113.9"
    assert "x-forwarded-for" not in out
    assert out["authorization"] == "Bearer tok-manager"


def _scope(peer, ip=None):
    headers = [(b"x-ser-client-ip", ip.encode())] if ip else []
    return {"type": "http", "client": (peer, 1234), "headers": headers}


def test_mcp_key_ignores_proxy_header_unless_enabled(monkeypatch):
    from mcp_server import server
    monkeypatch.delenv("SER_TRUST_PROXY_CLIENT_IP", raising=False)
    assert server._client_key(_scope("127.0.0.1", "203.0.113.9")) == "127.0.0.1"


def test_mcp_key_trusts_proxy_header_only_from_loopback(monkeypatch):
    from mcp_server import server
    monkeypatch.setenv("SER_TRUST_PROXY_CLIENT_IP", "1")
    assert server._client_key(_scope("127.0.0.1", "203.0.113.9")) == "fwd:203.0.113.9"
    assert server._client_key(_scope("198.51.100.4", "203.0.113.9")) == "198.51.100.4"
    assert server._client_key(_scope("127.0.0.1")) == "127.0.0.1"


# D5: a listed public name with a malformed port is refused ------------------


def test_allowed_host_port_must_be_numeric(monkeypatch):
    web = _web(monkeypatch, SER_ALLOWED_HOSTS="demo.onrender.com")
    assert web._loopback_host_allowed("demo.onrender.com:443")
    assert web._loopback_host_allowed("demo.onrender.com:8080")
    for bad in ("demo.onrender.com:abc", "demo.onrender.com:", "demo.onrender.com:0",
                "demo.onrender.com:65536", "demo.onrender.com:-1", "demo.onrender.com:+443",
                "demo.onrender.com:\u0664\u0664\u0663"):
        assert not web._loopback_host_allowed(bad), bad


# D1: the platform's bare HEAD / probe is ledgered as host_probe, still refused


def _guard_call(monkeypatch, method, path, headers, peer="127.0.0.1", query=b""):
    import asyncio
    from mcp_server import server
    events, sent = [], []
    monkeypatch.setattr(server.dbm, "record_transport_event_standalone",
                        lambda **kw: events.append(kw))

    async def inner(scope, receive, send):  # must never be reached on a refusal
        raise AssertionError("refused request reached the app")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": method, "path": path, "query_string": query,
             "client": (peer, 4444),
             "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(server.TransportGuardMiddleware(inner)(scope, receive, send))
    return sent[0]["status"], [e["event"] for e in events]


def test_probe_is_plain_host_refusal_by_default(monkeypatch):
    monkeypatch.delenv("SER_CLASSIFY_PLATFORM_PROBES", raising=False)
    assert _guard_call(monkeypatch, "HEAD", "/", {"host": "10.1.2.3:8765"}) == (403, ["host"])


def test_platform_probe_is_neutral_but_still_refused(monkeypatch):
    monkeypatch.setenv("SER_CLASSIFY_PLATFORM_PROBES", "1")
    assert _guard_call(monkeypatch, "HEAD", "/", {"host": "10.1.2.3:8765"}) == (403, ["host_probe"])


def test_real_foreign_host_attempts_stay_host_events(monkeypatch):
    monkeypatch.setenv("SER_CLASSIFY_PLATFORM_PROBES", "1")
    evil = {"host": "evil.example"}
    assert _guard_call(monkeypatch, "GET", "/", evil) == (403, ["host"])
    assert _guard_call(monkeypatch, "POST", "/mcp", evil) == (403, ["host"])
    assert _guard_call(monkeypatch, "HEAD", "/mcp", evil) == (403, ["host"])
    assert _guard_call(monkeypatch, "HEAD", "/", evil, query=b"x=1") == (403, ["host"])
    assert _guard_call(monkeypatch, "HEAD", "/", {**evil, "authorization": "Bearer tok-manager"}) == (403, ["host"])
    assert _guard_call(monkeypatch, "HEAD", "/", {**evil, "cookie": "a=b"}) == (403, ["host"])
    assert _guard_call(monkeypatch, "HEAD", "/", evil, peer="203.0.113.5") == (403, ["host"])
    # a foreign Origin is refused as "origin" before the Host check, probe or not
    assert _guard_call(monkeypatch, "HEAD", "/", {**evil, "origin": "https://evil.example"}) == (403, ["origin"])


def test_page_warns_only_on_real_refusals():
    html = open(os.path.join(ROOT, "web", "static", "index.html"), encoding="utf-8").read()
    assert "for (const k of ['origin', 'host', 'rate_429'])" in html
    assert "host_probe" in html  # shown in the badge tooltip, not as a warning


# D3: deploy/render_start.sh startup timeout and exit reporting ---------------

import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

START = os.path.join(ROOT, "deploy", "render_start.sh")
needs_bash = pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None,
                                reason="start script is bash, for Linux hosts")

FAKE_PY = r'''#!/usr/bin/env bash
# fake "python" for render_start.sh tests; FAKE_MODE picks the behaviour
REAL="__REAL__"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "mcp_server" ]; then
  case "$FAKE_MODE" in
    silent)      exec "$REAL" -c "import time; time.sleep(60)" ;;
    crash_start) exit 2 ;;
    *) exec "$REAL" -c "
import socket, sys, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()
time.sleep(1.5 if sys.argv[2] == 'mcp_dies' else 60)
sys.exit(3)" "$SER_MCP_PORT" "$FAKE_MODE" ;;
  esac
fi
if [ "${1:-}" = "app.py" ]; then
  touch "$FAKE_MARK"
  [ "$FAKE_MODE" = "web_dies" ] && { sleep 1; exit 4; }
  exec "$REAL" -c "import time; time.sleep(60)"
fi
exec "$REAL" "$@"
'''


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def _run_start(tmp_path, mode, timeout_s="2"):
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake = bindir / "python"
    fake.write_text(FAKE_PY.replace("__REAL__", sys.executable)); fake.chmod(0o755)
    mark = tmp_path / "web_started"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_MODE": mode,
           "FAKE_MARK": str(mark), "SER_MCP_PORT": str(_free_port()), "PORT": str(_free_port()),
           "SER_MCP_START_TIMEOUT": timeout_s, "SER_DB_PATH": str(tmp_path / "x.db")}
    t0 = time.monotonic()
    p = subprocess.run(["bash", START], env=env, capture_output=True, text=True, timeout=40)
    return p.returncode, p.stderr, mark.exists(), time.monotonic() - t0


@needs_bash
def test_start_times_out_when_mcp_never_listens(tmp_path):
    rc, err, web_started, took = _run_start(tmp_path, "silent")
    assert rc == 1, err
    assert "still not listening" in err and "after 2s" in err, err
    assert not web_started, "proxy must not start without the MCP server"
    assert took < 15


@needs_bash
def test_start_reports_mcp_crash_during_startup(tmp_path):
    rc, err, web_started, _ = _run_start(tmp_path, "crash_start")
    assert rc == 1
    assert "exited during startup with status 2" in err, err
    assert not web_started


@needs_bash
def test_start_names_the_mcp_server_when_it_exits(tmp_path):
    rc, err, web_started, _ = _run_start(tmp_path, "mcp_dies", timeout_s="10")
    assert web_started
    assert rc == 3, err
    assert "MCP server (pid" in err and "exited with status 3" in err, err


@needs_bash
def test_start_names_the_web_proxy_when_it_exits(tmp_path):
    rc, err, web_started, _ = _run_start(tmp_path, "web_dies", timeout_s="10")
    assert web_started
    assert rc == 4, err
    assert "web proxy (pid" in err and "exited with status 4" in err, err


# D7: always the light palette (no OS-dark, no Chrome Auto Dark) --------------


def test_page_opts_out_of_forced_darkening():
    html = open(os.path.join(ROOT, "web", "static", "index.html"), encoding="utf-8").read()
    assert '<meta name="color-scheme" content="only light">' in html
    assert ":root { color-scheme: only light; }" in html
    assert "prefers-color-scheme" not in html  # dark styling is opt-in (?theme=dark) only
