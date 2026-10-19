"""Generate contracts/tools.json from the live FastMCP tool registry.

Run from repo root:  python _gen_contracts.py
Writes contracts/tools.json (inputSchema + outputSchema per tool).
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_server.server import mcp  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts", "tools.json")


async def main():
    tools = await mcp.list_tools()
    doc = {
        "_meta": {
            "title": "Shared Equipment Rescue — MCP tool contract v1",
            "note": "Auto-generated from mcp_server.tool registry; edit mcp_server instead.",
        },
        "tools": {
            t.name: {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
                "outputSchema": t.outputSchema,
            }
            for t in sorted(tools, key=lambda t: t.name)
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("wrote", OUT, "tools:", list(doc["tools"]))


asyncio.run(main())
