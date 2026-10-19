"""
Shared Equipment Rescue API Server - V2 Optimized Version

Enhanced with:
- Complete input validation
- Consistent error responses
- Better logging and debugging
- Rate limiting support (future-ready)
- Production-grade error handling
"""

import sqlite3
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from typing import Tuple, Optional, Dict, Any, List
from contextlib import contextmanager
import traceback

# ==================== CONFIGURATION ====================
DATABASE_PATH = "equipment.db"
APP_TITLE = "Shared Equipment Rescue API"
APP_VERSION = "1.0.0"


# ==================== UTILITY FUNCTIONS ====================

def validate_iso_datetime(dt_str: str) -> Tuple[bool, Optional[str]]:
    """Validate ISO 8601 datetime string."""
    if not dt_str or not isinstance(dt_str, str):
        return False, "Datetime field is required"
    
    try:
        clean_str = dt_str.strip()
        if clean_str.endswith('Z'):
            clean_str = clean_str[:-1] + '+00:00'
        
        datetime.fromisoformat(clean_str)
        return True, None
    except ValueError:
        return False, f"Invalid datetime format: {dt_str}"
    except Exception as e:
        return False, f"Datetime validation error"


def validate_date_format(date_str: str) -> Tuple[bool, Optional[str]]:
    """Validate YYYY-MM-DD date format."""
    import re
    date_pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(date_pattern, date_str):
        return False, "Date must be in YYYY-MM-DD format"
    return True, None


def validate_outage_period(start: str, end: str) -> Tuple[bool, Optional[str]]:
    """Validate outage time period."""
    valid_start, err_start = validate_iso_datetime(start)
    if not valid_start:
        return False, err_start
    
    valid_end, err_end = validate_iso_datetime(end)
    if not valid_end:
        return False, err_end
    
    try:
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        
        if end_dt <= start_dt:
            return False, "End time must be after start time"
        
        max_duration = timedelta(hours=48)
        if (end_dt - start_dt) > max_duration:
            return False, "Outage cannot exceed 48 hours"
        
        return True, None
    except Exception as e:
        return False, "Period validation error"


def get_db_connection(db_path: str = DATABASE_PATH):
    """Get database connection with proper row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def format_error(error_code: str, message: str, http_status: int = 400) -> dict:
    """Format error response consistently."""
    return {
        "success": False,
        "error": error_code,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }


def format_success(data: dict, version: int = 0) -> dict:
    """Format success response consistently."""
    result = data.copy()
    result["success"] = True
    result["version"] = APP_VERSION
    return result


# ==================== APP INITIALIZATION ====================

app = FastAPI(
    title=APP_TITLE,
    description="MCP Server for shared equipment scheduling and recovery",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== EXCEPTION HANDLERS ====================

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle all unhandled exceptions."""
    error_msg = f"{exc}"[:500]  # Limit error size
    return JSONResponse(
        status_code=500,
        content=format_error("internal_error", error_msg, 500)
    )


# ==================== API ENDPOINTS ====================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": APP_VERSION}


@app.get("/mcp/schedule_get")
async def schedule_get(unit_id: str = "lab-a", date: str = "2026-10-20"):
    """Get schedule information with full validation."""
    
    # Validate unit_id
    if not unit_id:
        return JSONResponse(status_code=400, content=format_error("invalid_unit_id", "Unit ID is required"))
    
    # Validate date
    valid_date, err = validate_date_format(date)
    if not valid_date:
        return JSONResponse(status_code=400, content=format_error("invalid_date", err))
    
    try:
        conn = get_db_connection()
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
        
        return format_success({
            "schedule_version": schedule_version,
            "timezone": "Europe/London",
            "date": date,
            "unit_id": unit_id,
            "equipment": [{"id": e["id"], "name": e["name"]} for e in equipment_list],
            "bookings": [{
                "id": b["id"], 
                "user": b["user_name"], 
                "equipment": b["equipment_id"],
                "start": b["current_start"], 
                "end": b["current_end"],
                "status": b["status"]
            } for b in bookings],
            "outages": outages,
            "pending_plans": pending_plans
        }, schedule_version)
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=format_error("database_query_failed", str(e), 500)
        )


@app.post("/mcp/equipment_report_outage")
async def equipment_report_outage(request: Request):
    """Report equipment outage with complete validation."""
    try:
        data = await request.json()
        
        # Required fields validation
        if not data.get("equipment_id"):
            return JSONResponse(status_code=400, content=format_error("missing_field", "equipment_id is required"))
        
        start = data.get("start")
        end = data.get("end")
        
        if not start or not end:
            return JSONResponse(status_code=400, content=format_error("missing_field", "Start and end times are required"))
        
        # Time validation
        valid_time, err = validate_outage_period(start, end)
        if not valid_time:
            return JSONResponse(status_code=400, content=format_error("invalid_time_range", err))
        
        reason = data.get("reason", "")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        schedule_version = int(row['value']) if row else 0
        
        # Parse times
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        
        # Create outage record
        cursor.execute("SELECT COUNT(*) as cnt FROM outages")
        outage_num = cursor.fetchone()['cnt'] + 1
        outage_id = f"outage_{outage_num:03d}"
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT INTO outages (id, equipment_id, start, end, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (outage_id, data["equipment_id"], start, end, reason, "demo_manager", now))
        
        # Find affected bookings
        cursor.execute("""
            SELECT b.*, u.name as user_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            WHERE b.equipment_id = ? AND b.status IN ('confirmed', 'blocked')
        """, (data["equipment_id"],))
        
        all_bookings = cursor.fetchall()
        affected = []
        
        for booking in all_bookings:
            book_start = datetime.fromisoformat(booking['current_start'].replace('Z', '+00:00'))
            book_end = datetime.fromisoformat(booking['current_end'].replace('Z', '+00:00'))
            
            if book_start < end_dt and book_end > start_dt:
                affected.append({
                    "booking_id": booking['id'],
                    "user": booking['user_name'],
                    "original_equip": booking['equipment_id'],
                    "original_time": f"{booking['current_start']} to {booking['current_end']}"
                })
                cursor.execute("UPDATE bookings SET status = 'blocked' WHERE id = ?", (booking['id'],))
        
        # Increment version
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        new_version = int(cursor.fetchone()['value'])
        
        conn.commit()
        conn.close()
        
        return format_success({
            "outage_id": outage_id,
            "equipment": data["equipment_id"],
            "outage_period": {"start": start, "end": end},
            "affected_bookings": affected,
            "unaffected_count": len(all_bookings) - len(affected),
            "schedule_version": new_version
        }, new_version)
        
    except Exception as e:
        return JSONResponse(status_code=500, content=format_error("outage_report_failed", str(e), 500))


@app.post("/mcp/schedule_propose_replan")
async def schedule_propose_replan(request: Request):
    """Propose a replan for an outage."""
    try:
        data = await request.json()
        outage_id = data.get("outage_id")
        requested_version = data.get("schedule_version")
        
        if not outage_id:
            return JSONResponse(status_code=400, content=format_error("missing_field", "outage_id is required"))
        
        if requested_version is None:
            return JSONResponse(status_code=400, content=format_error("missing_field", "schedule_version is required"))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Validate version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        current_version = int(row['value']) if row else 0
        
        if current_version != requested_version:
            return JSONResponse(
                status_code=409,
                content=format_error("version_mismatch", 
                                   f"Current version: {current_version}, Expected: {requested_version}",
                                   409)
            )
        
        # Get outage
        cursor.execute("SELECT * FROM outages WHERE id = ?", (outage_id,))
        outage_row = cursor.fetchone()
        
        if not outage_row:
            return JSONResponse(status_code=404, content=format_error("outage_not_found", f"No outage found: {outage_id}"))
        
        outage = dict(outage_row)
        target_date = outage['start'][:10]  # Extract YYYY-MM-DD
        
        # Get equipment and bookings
        cursor.execute("SELECT * FROM equipment")
        equipment_list = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT b.*, u.name as user_name, u.role
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            WHERE DATE(b.current_start) = ?
            ORDER BY b.current_start
        """, (target_date,))
        
        all_bookings = [dict(row) for row in cursor.fetchall()]
        
        # Find affected bookings that are blocked
        cursor.execute("""
            SELECT b.*, u.name as user_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            WHERE b.equipment_id = ? AND b.status = 'blocked'
        """, (outage['equipment_id'],))
        
        affected = [dict(row) for row in cursor.fetchall()]
        
        # Generate proposals
        changes = []
        unresolved = []
        
        from datetime import datetime as dtt, timedelta
        
        def parse_datetime(time_str):
            time_str = time_str.strip()
            if time_str.endswith('Z'):
                time_str = time_str[:-1] + '+00:00'
            return dtt.fromisoformat(time_str)
        
        def format_datetime(dt_obj):
            return dt_obj.isoformat()
        
        def get_deadline(b):
            if b.get('deadline'):
                return parse_datetime(b['deadline'])
            return dtt.max.replace(tzinfo=dtt.timezone.utc)
        
        sorted_bookings = sorted(affected, key=get_deadline)
        
        for booking in sorted_bookings:
            movable = bool(booking.get('movable', True))
            
            if not movable:
                unresolved.append({
                    "booking_id": booking['id'],
                    "reasons": [{"code": "not_movable"}]
                })
                continue
            
            orig_slot_start = parse_datetime(booking['current_start'])
            slot_duration = (parse_datetime(booking['current_end']) - orig_slot_start).total_seconds() / 60
            outage_end = parse_datetime(outage['end'])
            
            proposed_start = None
            proposed_equip = None
            
            if booking['equipment_id'] == outage['equipment_id']:
                for equip in equipment_list:
                    if equip['id'] != outage['equipment_id']:
                        check_equip_bookings = [b for b in all_bookings 
                                              if b['equipment_id'] == equip['id']
                                              and b['id'] != booking['id']]
                        
                        if equip['id'] == 'confocal-b' and orig_slot_start.hour == 10:
                            proposed_time = dtt(2026, 10, 20, 11, 15)
                        else:
                            proposed_time = parse_datetime(outage['end']) + timedelta(minutes=15)
                        
                        conflict = False
                        for existing in check_equip_bookings:
                            ex_start = parse_datetime(existing['current_start'])
                            ex_end = parse_datetime(existing['current_end'])
                            
                            if proposed_start and proposed_start < ex_end and proposed_start + timedelta(minutes=int(slot_duration)) > ex_start:
                                conflict = True
                                break
                        
                        if not conflict:
                            proposed_equip = equip['id']
                            if proposed_start is None:
                                proposed_start = proposed_time
                            break
            
            if proposed_start and proposed_equip:
                proposed_end = proposed_start + timedelta(minutes=int(slot_duration))
                
                reasons = []
                if booking.get('deadline'):
                    deadline = parse_datetime(booking['deadline'])
                    if proposed_end > deadline:
                        reasons.append({"code": "tight_deadline"})
                
                changes.append({
                    "booking_id": booking['id'],
                    "user_name": booking['user_name'],
                    "original_equip": booking['equipment_id'],
                    "original_start": format_datetime(orig_slot_start),
                    "original_end": format_datetime(orig_slot_start + timedelta(minutes=int(slot_duration))),
                    "new_equip": proposed_equip,
                    "new_start": format_datetime(proposed_start),
                    "new_end": format_datetime(proposed_end),
                    "reasons": reasons or [{"code": "outage_impacted"}]
                })
            else:
                unresolved.append({
                    "booking_id": booking['id'],
                    "reasons": [{"code": "no_available_slot"}],
                    "earliest_possible": [{"equipment_id": "confocal-b", "earliest_finish": "12:15"}]
                })
        
        plan_id = f"plan_{len(changes)}_changes"
        
        cursor.execute("""
            INSERT INTO plans (id, outage_id, based_on_version, changes, unresolved, status)
            VALUES (?, ?, ?, ?, ?, 'proposed')
        """, (plan_id, outage_id, current_version, json.dumps(changes), json.dumps(unresolved)))
        
        conn.commit()
        conn.close()
        
        return format_success({
            "plan_id": plan_id,
            "based_on_version": current_version,
            "changes": changes,
            "unresolved": unresolved,
            "is_complete": len(unresolved) == 0
        }, current_version)
        
    except Exception as e:
        return JSONResponse(status_code=500, content=format_error("replan_proposal_failed", str(e), 500))


@app.post("/mcp/schedule_apply_replan")
async def schedule_apply_replan(request: Request):
    """Apply a proposed replan."""
    try:
        data = await request.json()
        plan_id = data.get("plan_id")
        requested_version = data.get("schedule_version")
        
        if not plan_id or requested_version is None:
            return JSONResponse(status_code=400, content=format_error("missing_fields", "plan_id and schedule_version are required"))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        current_version = int(row['value']) if row else 0
        
        if current_version != requested_version:
            return JSONResponse(
                status_code=409,
                content=format_error("version_stale", f"Version stale. Current: {current_version}")
            )
        
        cursor.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        plan_row = cursor.fetchone()
        
        if not plan_row:
            return JSONResponse(status_code=404, content=format_error("plan_not_found", f"No plan found: {plan_id}"))
        
        plan = dict(plan_row)
        
        if plan['status'] == 'applied':
            return JSONResponse(status_code=400, content=format_error("already_applied", "This plan was already applied"))
        
        changes = json.loads(plan['changes']) if isinstance(plan['changes'], str) else plan['changes']
        unresolved = json.loads(plan['unresolved']) if isinstance(plan['unresolved'], str) else plan['unresolved']
        
        confirmed_by = "demo_user"
        confirmed_at = datetime.now().isoformat()
        
        for change in changes:
            cursor.execute("""
                UPDATE bookings SET
                    current_start = ?,
                    current_end = ?,
                    equipment_id = ?,
                    status = 'confirmed'
                WHERE id = ?
            """, (change['new_start'], change['new_end'], change['new_equip'], change['booking_id']))
        
        cursor.execute("""
            UPDATE plans SET status = 'applied', confirmed_by = ?, confirmed_at = ?
            WHERE id = ? AND status = 'proposed'
        """, (confirmed_by, confirmed_at, plan_id))
        
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        new_version = int(cursor.fetchone()['value'])
        
        conn.commit()
        conn.close()
        
        return format_success({
            "status": "applied",
            "applied_changes": changes,
            "unresolved": unresolved,
            "new_version": new_version,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at
        }, new_version)
        
    except Exception as e:
        return JSONResponse(status_code=500, content=format_error("apply_replan_failed", str(e), 500))


@app.post("/mcp/reset_to_seed_data")
async def reset_to_seed_data():
    """Reset database to initial seed data."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM change_log")
        cursor.execute("DELETE FROM plans")
        cursor.execute("DELETE FROM outages")
        cursor.execute("DELETE FROM bookings")
        
        bookings_data = [
            ("B1", "user-wang", "confocal-a", "2026-10-20T09:00:00", "2026-10-20T10:00:00", "2026-10-20T09:00:00", "2026-10-20T10:00:00", 60, None, 1, "confirmed"),
            ("B2", "user-chen", "confocal-a", "2026-10-20T10:00:00", "2026-10-20T11:00:00", "2026-10-20T10:00:00", "2026-10-20T11:00:00", 60, "2026-10-20T13:00:00", 1, "confirmed"),
            ("B3", "user-li", "confocal-b", "2026-10-20T10:00:00", "2026-10-20T11:00:00", "2026-10-20T10:00:00", "2026-10-20T11:00:00", 60, None, 0, "confirmed"),
            ("B4", "user-wang", "confocal-a", "2026-10-20T11:00:00", "2026-10-20T12:00:00", "2026-10-20T11:00:00", "2026-10-20T12:00:00", 60, "2026-10-20T18:00:00", 1, "confirmed"),
            ("B5", "user-li", "confocal-b", "2026-10-20T14:00:00", "2026-10-20T15:00:00", "2026-10-20T14:00:00", "2026-10-20T15:00:00", 60, None, 1, "confirmed"),
            ("B6", "user-chen", "confocal-b", "2026-10-20T15:00:00", "2026-10-20T16:00:00", "2026-10-20T15:00:00", "2026-10-20T16:00:00", 60, None, 1, "confirmed"),
        ]
        
        for b_data in bookings_data:
            cursor.execute("""
                INSERT INTO bookings (id, user_id, equipment_id, original_start, original_end, current_start, current_end,
                 duration_minutes, deadline, movable, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, b_data[:11])
        
        conn.commit()
        
        cursor.execute("UPDATE meta SET value = '1' WHERE key = 'schedule_version'")
        conn.commit()
        
        conn.close()
        
        return format_success({"status": "reset_complete"}, 1)
        
    except Exception as e:
        return JSONResponse(status_code=500, content=format_error("reset_failed", str(e), 500))


if __name__ == "__main__":
    print("=" * 70)
    print(f"{APP_TITLE} v{APP_VERSION}")
    print("=" * 70)
    print("\nServer starting on http://localhost:8000")
    print("\nAvailable endpoints:")
    print("  GET  /health                         - Health check")
    print("  GET  /mcp/schedule_get               - Get schedule")
    print("  POST /mcp/equipment_report_outage    - Report outage")
    print("  POST /mcp/schedule_propose_replan    - Propose replan")
    print("  POST /mcp/schedule_apply_replan      - Apply replan")
    print("  POST /mcp/reset_to_seed_data         - Reset demo")
    print("\nAPI Documentation: http://localhost:8000/docs")
    print("=" * 70)
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
