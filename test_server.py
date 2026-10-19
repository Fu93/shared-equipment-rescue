"""
Standalone test server for Shared Equipment Rescue.
This is a simpler approach without relying on FastMCP's CLI interface.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Shared Equipment Rescue MCP Server")


@app.get("/mcp/schedule_get")
async def schedule_get(unit_id: str = "lab-a", date: str = "2026-10-20"):
    """Get schedule information."""
    try:
        import sqlite3
        
        # Initialize database first
        db_path = "equipment.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get schedule version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        schedule_version = int(row['value']) if row else 0
        
        # Get equipment
        cursor.execute("SELECT * FROM equipment WHERE unit_id = ?", (unit_id,))
        equipment_list = [dict(row) for row in cursor.fetchall()]
        
        # Get bookings with user info
        cursor.execute("""
            SELECT b.*, u.name as user_name 
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            WHERE DATE(b.current_start) = ?
            ORDER BY b.current_start
        """, (date,))
        bookings = [dict(row) for row in cursor.fetchall()]
        
        # Get active outages
        cursor.execute("""
            SELECT * FROM outages 
            WHERE DATE(start) <= ? AND DATE(end) >= ?
            ORDER BY start DESC
        """, (date, date))
        outages = [dict(row) for row in cursor.fetchall()]
        
        # Get pending plans
        cursor.execute("SELECT * FROM plans WHERE status = 'proposed' ORDER BY id DESC")
        pending_plans = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "schedule_version": schedule_version,
            "timezone": "Europe/London",
            "date": date,
            "equipment": [{"id": e["id"], "name": e["name"]} for e in equipment_list],
            "bookings": [{"id": b["id"], "user": b["user_name"], "equipment": b["equipment_id"], 
                         "start": b["current_start"][:16], "end": b["current_end"][:16],
                         "status": b["status"]} for b in bookings],
            "outages": outages,
            "pending_plans": pending_plans
        }
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500, 
            content={
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        )


@app.post("/mcp/equipment_report_outage")
async def equipment_report_outage(request: dict):
    """Report equipment outage."""
    from mcp_server.db import init_database, create_outage, increment_schedule_version, get_db_connection
    from mcp_server.engine import parse_datetime
    
    init_database()
    
    equip_id = request.get("equipment_id")
    start = request.get("start")
    end = request.get("end")
    reason = request.get("reason")
    
    outage = create_outage(equip_id, start, end, reason)
    
    return {
        "status": "outage_reported",
        "outage": outage,
        "message": f"Equipment {equip_id} marked as down from {start} to {end}"
    }


@app.post("/mcp/reset_to_seed_data")
async def reset_to_seed_data():
    """Reset database to seed data."""
    from mcp_server.seed import seed_database
    from mcp_server.db import get_schedule_version
    
    result = seed_database()
    version = get_schedule_version()
    
    return {"status": "reset_complete", **result, "version": version}


if __name__ == "__main__":
    print("[INFO] Starting standalone test server...")
    print("[INFO] API available at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
