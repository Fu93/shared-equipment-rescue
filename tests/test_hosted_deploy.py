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
