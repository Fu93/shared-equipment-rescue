# -*- coding: utf-8 -*-
import asyncio, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
dbp = os.path.join(tempfile.gettempdir(), "ser_webdev2.db")
os.environ["SER_DB_PATH"] = dbp
if os.path.exists(dbp):
    os.remove(dbp)
if len(sys.argv) > 1:
    dbp = sys.argv[1]
    os.environ["SER_DB_PATH"] = dbp
import uvicorn
from mcp_server.server import build_app
async def main():
    app = build_app()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error")
    s = uvicorn.Server(cfg)
    t = asyncio.create_task(s.serve())
    for _ in range(200):
        if s.started: break
        await asyncio.sleep(0.05)
    await asyncio.Event().wait()
asyncio.run(main())
