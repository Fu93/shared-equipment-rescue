"""
FastMCP Server for Shared Equipment Rescue
Implements MCP 2025-11-25 specification with Streamable HTTP transport
"""

import os
from datetime import datetime
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP, Context

# Local imports
from .engine import (
    parse_datetime, format_datetime, get_date_str,
    find_affected_bookings, propose_replan
)
from .db import (
    init_database, get_db_connection, get_schedule_version, increment_schedule_version,
    list_bookings, get_outages, get_plans, create_outage, create_plan,
    apply_replan_changes, update_plan_status, log_change, get_unit
)

# Initialize MCP server
mcp = FastMCP(
    "Shared Equipment Rescue",
    host="0.0.0.0",
    port=8000
)


# ==================== TOOL DEFINITIONS ====================

@mcp.tool()
def schedule_get(
    unit_id: str = "lab-a",
    date: str = "2026-10-20"
) -> dict:
    """
    Get the schedule for a specific unit and date.
    
    Args:
        unit_id: The unit/department identifier
        date: Date in YYYY-MM-DD format
    
    Returns:
        Complete schedule information including bookings, equipment status, and pending items
    """
    from .db import get_schedule_version
    
    # Load data
    conn = get_db_connection()
    
    # Get equipment
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM equipment WHERE unit_id = ?
    """, (unit_id,))
    equipment_list = [dict(row) for row in cursor.fetchall()]
    
    # Get bookings
    bookings = list_bookings(unit_id=unit_id, date=date)
    
    # Get active outages
    outages = get_outages(equipment_id=None, date=date)
    
    # Get pending plans
    pending_plans = get_plans(status='proposed')
    
    # Check which bookings are affected by outages
    affected_booking_ids = set()
    for outage in outages:
        if not any(b['id'] == affected_booking_ids):
            for booking in bookings:
                if booking['equipment_id'] == outage['equipment_id']:
                    book_start = parse_datetime(booking['current_start'])
                    book_end = parse_datetime(booking['current_end'])
                    outage_start = parse_datetime(outage['start'])
                    outage_end = parse_datetime(outage['end'])
                    
                    if book_start < outage_end and book_end > outage_start:
                        affected_booking_ids.add(booking['id'])
    
    # Format response
    schedule_version = get_schedule_version()
    
    return {
        "schedule_version": schedule_version,
        "timezone": "Europe/London",
        "date": date,
        "equipment": [{
            "id": e["id"],
            "name": e["name"],
            "available_from": e["available_start"],
            "available_until": e["available_end"],
            "buffer_minutes": e.get("buffer_minutes", 15)
        } for e in equipment_list],
        "bookings": [{
            "id": b["id"],
            "user": b["user_name"],
            "user_id": b["user_id"],
            "role": b["role"],
            "equipment": b["equipment_id"],
            "start": b["current_start"],
            "end": b["current_end"],
            "deadline": b.get("deadline"),
            "status": b["status"],
            "movable": bool(b.get("movable", True))
        } for b in bookings],
        "outages": [{
            "id": o["id"],
            "equipment": o["equipment_id"],
            "start": o["start"],
            "end": o["end"],
            "reason": o.get("reason")
        } for o in outages],
        "pending_plans": pending_plans,
        "_system_message": f"{len(outages)} active outage(s), {len(pending_plans)} pending plan(s)"
    }


@mcp.tool()
def equipment_report_outage(
    equipment_id: str,
    start: str,
    end: str,
    reason: Optional[str] = None
) -> dict:
    """
    Report an equipment outage/failure. This identifies affected bookings but doesn't change them.
    
    Args:
        equipment_id: The equipment that is down
        start: Outage start time (ISO 8601)
        end: Outage end time (ISO 8601)
        reason: Optional description of what went wrong
    
    Returns:
        List of affected bookings with original times
    """
    from .engine import find_affected_bookings
    
    conn = get_db_connection()
    
    # Create outage record
    now = datetime.now().isoformat()
    outage = create_outage(
        equipment_id=equipment_id,
        start=start,
        end=end,
        reason=reason,
        created_by="demo_manager"
    )
    
    # Get affected bookings
    current_bookings = list_bookings(date=get_date_str(parse_datetime(start)))
    
    affected = []
    unaffected_count = 0
    
    for booking in current_bookings:
        book_start = parse_datetime(booking['current_start'])
        book_end = parse_datetime(booking['current_end'])
        
        # Check overlap
        if book_start < parse_datetime(end) and book_end > parse_datetime(start):
            affected.append({
                "booking_id": booking["id"],
                "user": booking["user_name"],
                "original_equip": booking["equipment_id"],
                "original_time": f"{booking['current_start']} to {booking['current_end']}"
            })
        else:
            unaffected_count += 1
    
    # Mark affected bookings as blocked
    cursor = conn.cursor()
    for a in affected:
        cursor.execute("""
            UPDATE bookings SET status = 'blocked' WHERE id = ?
        """, (a["booking_id"],))
    
    # Increment version
    new_version = increment_schedule_version()
    
    return {
        "outage_id": outage["id"],
        "equipment": equipment_id,
        "outage_period": {"start": start, "end": end},
        "affected_bookings": affected,
        "unaffected_count": unaffected_count,
        "schedule_version": new_version,
        "_note": "Affected bookings are now marked as 'blocked'. Use schedule_propose_replan to generate replacement slots."
    }


@mcp.tool()
def schedule_propose_replan(outage_id: str, schedule_version: int) -> dict:
    """
    Propose a replan for bookings affected by an outage. Doesn't modify anything yet.
    
    Args:
        outage_id: The outage identifier from equipment_report_outage
        schedule_version: Current schedule version to ensure consistency
    
    Returns:
        Proposed changes with reasons, unresolved items, and earliest possible alternatives
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Validate version
    current_version = get_schedule_version()
    if current_version != schedule_version:
        return {
            "error": "schedule_version_mismatch",
            "message": f"Schedule has changed. Expected version {schedule_version}, got {current_version}. Please call again.",
            "current_version": current_version
        }
    
    # Get outage
    cursor.execute("SELECT * FROM outages WHERE id = ?", (outage_id,))
    outage_row = cursor.fetchone()
    if not outage_row:
        return {"error": "not_found", "message": f"No outage found with ID {outage_id}"}
    outage = dict(outage_row)
    
    # Get relevant data
    target_date = get_date_str(parse_datetime(outage['start']))
    all_bookings = list_bookings(date=target_date)
    cursor.execute("SELECT * FROM equipment")
    equipment_list = [dict(row) for row in cursor.fetchall()]
    
    # Find affected bookings
    affected = []
    for b in all_bookings:
        book_start = parse_datetime(b['current_start'])
        book_end = parse_datetime(b['current_end'])
        if book_start < parse_datetime(outage['end']) and book_end > parse_datetime(outage['start']):
            if b['status'] in ['confirmed', 'blocked']:
                affected.append(b)
    
    # Generate proposals
    plan = propose_replan(
        outage=outage,
        affected_bookings=affected,
        equipment_list=equipment_list,
        all_bookings=all_bookings,
        schedule_version=schedule_version
    )
    
    # Create database record
    db_plan = create_plan(
        outage_id=outage_id,
        based_on_version=schedule_version,
        changes=plan.changes,
        unresolved=plan.unresolved
    )
    
    return {
        "plan_id": db_plan["id"],
        "based_on_version": schedule_version,
        "changes": plan.changes,
        "unresolved": plan.unresolved,
        "is_complete": plan.is_complete,
        "_explanation": {
            "complete_slots": len(plan.changes),
            "needs_manual_attention": len(plan.unresolved)
        }
    }


@mcp.tool()
def schedule_apply_replan(plan_id: str, schedule_version: int) -> dict:
    """
    Apply a proposed replan after human confirmation via elicitation.
    
    Args:
        plan_id: The plan identifier from schedule_propose_replan
        schedule_version: Current schedule version
    
    Returns:
        Result of applying the plan with status and details
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check current version
    current_version = get_schedule_version()
    if current_version != schedule_version:
        return {
            "status": "plan_stale",
            "message": "Plan is out of date. Schedule has changed since proposal.",
            "current_version": current_version
        }
    
    # Get plan
    cursor.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
    plan_row = cursor.fetchone()
    
    if not plan_row:
        return {
            "status": "not_found",
            "message": f"No plan found with ID {plan_id}"
        }
    
    plan = dict(plan_row)
    
    # Check if already applied
    if plan['status'] == 'applied':
        return {
            "status": "already_applied",
            "message": "This plan was already applied at " + plan.get('confirmed_at', 'unknown'),
            "plan": plan
        }
    
    # For demo purposes, auto-confirm if no elicitation is available
    # In production, this would wait for user confirmation from elicitation
    confirmed_by = "demo_system"  # Would be actual human from elicitation
    confirmed_at = datetime.now().isoformat()
    
    try:
        # Parse changes
        changes = eval(plan['changes']) if isinstance(plan['changes'], str) else plan['changes']
        unresolved = eval(plan['unresolved']) if isinstance(plan['unresolved'], str) else plan['unresolved']
        
        # Apply changes
        apply_replan_changes(db_conn=conn, plan={
            "id": plan_id,
            "changes": changes
        }, confirmed_by=confirmed_by)
        
        # Update plan status
        update_plan_status(
            plan_id=plan_id,
            status='applied',
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at
        )
        
        # Get new version
        new_version = increment_schedule_version()
        
        return {
            "status": "applied",
            "applied_changes": changes,
            "unresolved": unresolved,
            "new_version": new_version,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to apply plan: {str(e)}"
        }


# ==================== DEBUG TOOL FOR ELICITATION TESTING ====================

@mcp.tool()
def debug_confirm_test(confirmation: bool) -> dict:
    """
    Test tool for verifying elicitation flow works correctly.
    Accepts confirm/cancel from browser and returns result to MCP tool call.
    
    Args:
        confirmation: True for Confirm, False for Cancel
    """
    return {
        "received_confirmation": confirmation,
        "action_taken": "confirmed" if confirmation else "cancelled",
        "timestamp": datetime.now().isoformat(),
        "_note": "This should have been triggered by elicitation from web UI"
    }


# ==================== SEED DATA ====================

@mcp.tool()
def reset_to_seed_data() -> dict:
    """Reset database to seed/demo data."""
    from .seed import seed_database
    
    seed_database()
    
    return {
        "status": "reset_complete",
        "version": get_schedule_version(),
        "message": "Database reset to initial seed data"
    }


# Main entry point
if __name__ == "__main__":
    import sys
    
    # Initialize database
    init_database()
    
    # Run MCP server
    print("Starting Shared Equipment Rescue MCP Server...")
    mcp.run()
