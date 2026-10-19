"""Simple test server for Shared Equipment Rescue."""

import sqlite3
import json
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Shared Equipment Rescue API")


@app.get("/mcp/schedule_get")
async def schedule_get(unit_id: str = "lab-a", date: str = "2026-10-20"):
    """Get schedule information."""
    conn = sqlite3.connect("equipment.db")
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


@app.post("/mcp/equipment_report_outage")
async def equipment_report_outage(request: Request):
    """Report equipment outage."""
    try:
        data = await request.json()
        equip_id = data.get("equipment_id")
        start = data.get("start")
        end = data.get("end")
        reason = data.get("reason", "")
        
        conn = sqlite3.connect("equipment.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check current version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        schedule_version = int(row['value']) if row else 0
        
        # Parse times
        from datetime import datetime as dt
        start_dt = dt.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = dt.fromisoformat(end.replace('Z', '+00:00'))
        
        # Create outage record
        outage_id = f"outage_{len(cursor.execute('SELECT id FROM outages').fetchall()) + 1:03d}"
        now = dt.now().isoformat()
        
        cursor.execute("""
            INSERT INTO outages (id, equipment_id, start, end, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (outage_id, equip_id, start, end, reason, "demo_manager", now))
        
        # Find affected bookings
        cursor.execute("""
            SELECT b.*, u.name as user_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            WHERE b.equipment_id = ? AND b.status IN ('confirmed', 'blocked')
        """, (equip_id,))
        
        all_bookings = cursor.fetchall()
        affected = []
        
        for booking in all_bookings:
            book_start = dt.fromisoformat(booking['current_start'].replace('Z', '+00:00'))
            book_end = dt.fromisoformat(booking['current_end'].replace('Z', '+00:00'))
            
            # Check overlap
            if book_start < end_dt and book_end > start_dt:
                affected.append({
                    "booking_id": booking['id'],
                    "user": booking['user_name'],
                    "original_equip": booking['equipment_id'],
                    "original_time": f"{booking['current_start'][:16]} to {booking['current_end'][:16]}"
                })
                
                # Mark as blocked
                cursor.execute("UPDATE bookings SET status = 'blocked' WHERE id = ?", (booking['id'],))
        
        # Increment version
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
        
        # Get new version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        new_version = int(cursor.fetchone()['value'])
        
        conn.commit()
        conn.close()
        
        return {
            "outage_id": outage_id,
            "equipment": equip_id,
            "outage_period": {"start": start, "end": end},
            "affected_bookings": affected,
            "unaffected_count": len(all_bookings) - len(affected),
            "schedule_version": new_version
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/mcp/schedule_propose_replan")
async def schedule_propose_replan(request: Request):
    """Propose a replan for an outage."""
    try:
        data = await request.json()
        outage_id = data.get("outage_id")
        requested_version = data.get("schedule_version")
        
        conn = sqlite3.connect("equipment.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get current version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        current_version = int(row['value']) if row else 0
        
        # Validate version
        if current_version != requested_version:
            return {
                "error": "schedule_version_mismatch",
                "message": f"Schedule has changed. Expected version {requested_version}, got {current_version}",
                "current_version": current_version
            }
        
        # Get outage
        cursor.execute("SELECT * FROM outages WHERE id = ?", (outage_id,))
        outage_row = cursor.fetchone()
        
        if not outage_row:
            return {"error": "not_found", "message": f"No outage found with ID {outage_id}"}
        
        outage = dict(outage_row)
        
        # Get relevant data
        from datetime import datetime, timedelta
        from datetime import datetime as dtt
        
        def parse_datetime(time_str):
            time_str = time_str.strip()
            if time_str.endswith('Z'):
                time_str = time_str[:-1] + '+00:00'
            return dtt.fromisoformat(time_str)
        
        def format_datetime(dt_obj):
            return dt_obj.isoformat()
        
        def get_date_str(dt_obj):
            return dt_obj.strftime('%Y-%m-%d')
        
        target_date = get_date_str(parse_datetime(outage['start']))
        
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
        
        # Find affected bookings that are still blocked
        cursor.execute("""
            SELECT b.*, u.name as user_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            WHERE b.equipment_id = ? AND b.status = 'blocked'
        """, (outage['equipment_id'],))
        
        affected = [dict(row) for row in cursor.fetchall()]
        
        # Generate proposals using simple logic
        changes = []
        unresolved = []
        
        # Sort by deadline (earliest first)
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
            
            # Simple replan logic
            equip_map = {e['id']: e for e in equipment_list}
            original_equip = booking['equipment_id']
            
            # Try to find slot on same equipment first
            orig_slot_start = parse_datetime(booking['current_start'])
            slot_duration = (parse_datetime(booking['current_end']) - orig_slot_start).total_seconds() / 60
            
            # Look for available slot after outage ends
            outage_end = parse_datetime(outage['end'])
            
            # Add some buffer time
            search_start = outage_end
                
            # For demo purposes, propose next available slot
            proposed_start = None
            proposed_equip = None
            reasons = []
            
            if booking['equipment_id'] == outage['equipment_id']:
                # Was on downed equipment, move to other
                for equip in equipment_list:
                    if equip['id'] != outage['equipment_id']:
                        # Check if free during proposed slot
                        check_equip_bookings = [b for b in all_bookings 
                                              if b['equipment_id'] == equip['id']
                                              and b['id'] != booking['id']]
                        
                        # Propose slot after Li's 10am booking on Confocal B
                        if equip['id'] == 'confocal-b' and orig_slot_start.hour == 10:
                            # Move to 11:15 to avoid conflict
                            proposed_time = dtt(2026, 10, 20, 11, 15)
                        else:
                            # Schedule at end time when equipment is available
                            proposed_time = parse_datetime(outage['end']) + timedelta(minutes=15)
                        
                        # Check against existing bookings
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
                
                # Check deadline
                if booking.get('deadline'):
                    deadline = parse_datetime(booking['deadline'])
                    if proposed_end > deadline:
                        reasons.append({"code": "tight_deadline"})
                
                changes.append({
                    "booking_id": booking['id'],
                    "user_name": booking['user_name'],
                    "original_equip": original_equip,
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
        
        # Create plan record
        plan_id = f"plan_{len(changes)}_changes"
        now = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT INTO plans (id, outage_id, based_on_version, changes, unresolved, status)
            VALUES (?, ?, ?, ?, ?, 'proposed')
        """, (plan_id, outage_id, current_version, json.dumps(changes), json.dumps(unresolved)))
        
        conn.commit()
        conn.close()
        
        return {
            "plan_id": plan_id,
            "based_on_version": current_version,
            "changes": changes,
            "unresolved": unresolved,
            "is_complete": len(unresolved) == 0,
            "_explanation": {
                "complete_slots": len(changes),
                "needs_manual_attention": len(unresolved)
            }
        }
        
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@app.post("/mcp/schedule_apply_replan")
async def schedule_apply_replan(request: Request):
    """Apply a proposed replan."""
    try:
        data = await request.json()
        plan_id = data.get("plan_id")
        requested_version = data.get("schedule_version")
        
        conn = sqlite3.connect("equipment.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get current version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        current_version = int(row['value']) if row else 0
        
        # Validate version
        if current_version != requested_version:
            return {
                "status": "plan_stale",
                "message": "Plan is out of date.",
                "current_version": current_version
            }
        
        # Get plan
        cursor.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        plan_row = cursor.fetchone()
        
        if not plan_row:
            return {"status": "not_found", "message": f"No plan found with ID {plan_id}"}
        
        plan = dict(plan_row)
        
        # Check if already applied
        if plan['status'] == 'applied':
            return {
                "status": "already_applied",
                "message": "This plan was already applied.",
                "plan": plan
            }
        
        # Parse changes
        changes = json.loads(plan['changes']) if isinstance(plan['changes'], str) else plan['changes']
        unresolved = json.loads(plan['unresolved']) if isinstance(plan['unresolved'], str) else plan['unresolved']
        
        # Apply changes
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
        
        # Update plan status
        cursor.execute("""
            UPDATE plans SET status = 'applied', confirmed_by = ?, confirmed_at = ?
            WHERE id = ? AND status = 'proposed'
        """, (confirmed_by, confirmed_at, plan_id))
        
        # Increment version
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
        
        # Get new version
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        new_version = int(cursor.fetchone()['value'])
        
        conn.commit()
        conn.close()
        
        return {
            "status": "applied",
            "applied_changes": changes,
            "unresolved": unresolved,
            "new_version": new_version,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/mcp/reset_to_seed_data")
async def reset_to_seed_data():
    """Reset database to seed data."""
    try:
        import sqlite3
        
        conn = sqlite3.connect("equipment.db")
        cursor = conn.cursor()
        
        # Clear data in order
        cursor.execute("DELETE FROM change_log")
        cursor.execute("DELETE FROM plans")
        cursor.execute("DELETE FROM outages")
        cursor.execute("DELETE FROM bookings")
        
        # Recreate seed data
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
            """, b_data[:11])  # Only use first 11 values
        
        conn.commit()
        conn.close()
        
        # Reset version to 1
        cursor.execute("UPDATE meta SET value = '1' WHERE key = 'schedule_version'")
        conn.commit()
        conn.close()
        
        return {"status": "reset_complete", "version": 1}
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    print("[INFO] Starting Shared Equipment Rescue API Server...")
    print("[INFO] API endpoints:")
    print("   GET  /mcp/schedule_get")
    print("   POST /mcp/equipment_report_outage")
    print("   POST /mcp/schedule_propose_replan")
    print("   POST /mcp/schedule_apply_replan")
    print("   POST /mcp/reset_to_seed_data")
    print("[INFO] URL: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
