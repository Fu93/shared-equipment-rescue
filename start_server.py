#!/usr/bin/env python
"""Simple script to start MCP server with proper logging."""

import sys
from mcp_server import init_database, seed_database
from mcp_server.server import mcp

print("=" * 60)
print("SHARED EQUIPMENT RESCUE - MCP SERVER")
print("=" * 60)

# Initialize database
print("\n[INFO] Initializing database...")
try:
    init_database()
    print("[OK] Database initialized")
except Exception as e:
    print(f"[WARN] Database error: {e}")

# Seed data
print("\n[INFO] Seeding demo data...")
try:
    result = seed_database()
    print(f"[OK] {result['message']}")
except Exception as e:
    print(f"[WARN] Seed error: {e}")

# Start server
print("\n[INFO] Starting MCP Server on http://localhost:8000")
print("=" * 60)

if __name__ == "__main__":
    mcp.run()
