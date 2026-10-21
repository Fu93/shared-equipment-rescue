"""Console entry: python -m mcp_server  → uvicorn on 127.0.0.1:8765/mcp."""

from __future__ import annotations


def main() -> None:
    from .server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
