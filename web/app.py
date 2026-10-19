"""Simple web server for Shared Equipment Rescue demo."""

from fastapi import FastAPI, StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI(title="Shared Equipment Rescue Web UI")

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_home():
    """Serve the main HTML page."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
