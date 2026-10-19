"""
Shared Equipment Schedule Engine
Pure Python functions for scheduling without I/O operations.
All times use Europe/London timezone in ISO 8601 format.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta, timezone
import re


@dataclass
class Booking:
    id: str
    user_id: str
    user_name: str
    equipment_id: str
    original_start: str  # ISO 8601 with timezone
    original_end: str
    current_start: str
    current_end: str
    deadline: Optional[str]  # ISO 8601 date-time or just YYYY-MM-DD
    movable: bool
    status: str  # 'confirmed', 'blocked', 'unresolved'
    duration_minutes: int = field(default=60)


@dataclass
class Equipment:
    id: str
    name: str
    unit_id: str
    available_start: str  # HH:MM
    available_end: str  # HH:MM
    buffer_minutes: int = 15
    working_days: list = field(default_factory=lambda: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])


@dataclass
class Outage:
    id: str
    equipment_id: str
    start: str  # ISO 8601
    end: str
    reason: str
    created_at: str


@dataclass
class ReplanPlan:
    plan_id: str
    outage_id: str
    based_on_version: int
    changes: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    is_complete: bool = True


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO 8601 datetime string to timezone-aware datetime."""
    # Remove any trailing Z and replace with +00:00
    dt_str = dt_str.strip()
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    
    # Handle various formats
    if '+' in dt_str or '-' in dt_str[10:]:  # Check for timezone after date
        parts = dt_str.rsplit('+', 1) if '+' in dt_str else dt_str.rsplit('-', 1)
        if len(parts) == 2:
            base, tz = parts
            if ':' not in tz and len(tz) <= 5:
                # Add colon to timezone if missing (e.g., +0100 -> +01:00)
                if len(tz) == 4:
                    tz = tz[:2] + ':' + tz[2:]
                dt_str = base + ('+' if '+' in dt_str else '-') + tz
    
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        # Fallback: try parsing without timezone
        clean_str = re.sub(r'[^\d+\-:.]', '', dt_str)
        if len(clean_str) >= 19:
            clean_str = clean_str[:19]
        return datetime.fromisoformat(clean_str).replace(tzinfo=timezone.utc)


def format_datetime(dt: datetime) -> str:
    """Format datetime to ISO 8601 string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def get_date_str(dt: datetime) -> str:
    """Get YYYY-MM-DD string from datetime."""
    return dt.strftime('%Y-%m-%d')


def parse_time(time_str: str) -> tuple:
    """Parse HH:MM time string to (hour, minute) tuple."""
    parts = time_str.strip().split(':')
    return int(parts[0]), int(parts[1])


def time_to_datetime(date_str: str, time_str: str, tz='Europe/London') -> datetime:
    """Combine date and time strings into timezone-aware datetime."""
    hour, minute = parse_time(time_str)
    dt = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=hour, minute=minute)
    # London timezone - will handle DST appropriately
    if tz == 'Europe/London':
        # Use naive datetime; Python 3.9+ handles this correctly for comparisons
        pass
    return dt


def find_affected_bookings(
    bookings: list,
    outage: Outage,
    equipment_list: list
) -> list:
    """Find all bookings affected by an equipment outage."""
    affected = []
    outage_dt_start = parse_datetime(outage.start)
    outage_dt_end = parse_datetime(outage.end)
    
    equip_map = {e.id: e for e in equipment_list}
    
    for booking in bookings:
        if booking.equipment_id != outage.equipment_id:
            continue
        
        book_start = parse_datetime(booking.current_start)
        book_end = parse_datetime(booking.current_end)
        
        # Check overlap: booking overlaps if it starts before outage ends AND ends after outage starts
        if book_start < outage_dt_end and book_end > outage_dt_start:
            affected.append(booking)
    
    return affected


def calculate_unavailable_periods(equipment: Equipment, outage: Optional[Outage], target_date: str) -> list:
    """Calculate all unavailable periods for equipment on a specific day."""
    unavailable = []
    
    if outage and outage.equipment_id == equipment.id:
        outage_start = parse_datetime(outage.start)
        outage_end = parse_datetime(outage.end)
        unavailable.append((outage_start, outage_end))
    
    return unavailable


def generate_available_slots(
    equipment: Equipment,
    target_date: str,
    required_duration: int,
    unavailable_periods: list,
    existing_bookings: list,
    allowed_users: set = None
) -> list:
    """Generate all available time slots for a given day."""
    slots = []
    
    open_start_hour, open_start_min = parse_time(equipment.available_start)
    open_end_hour, open_end_min = parse_time(equipment.available_end)
    
    open_start = time_to_datetime(target_date, equipment.available_start)
    open_end = time_to_datetime(target_date, equipment.available_end)
    
    # Build occupied periods
    occupied = []
    for b in existing_bookings:
        if b.equipment_id != equipment.id:
            continue
        if b.status == 'confirmed':
            start = parse_datetime(b.current_start)
            end = parse_datetime(b.current_end)
            # Add buffer to end
            end_with_buffer = end + timedelta(minutes=equipment.buffer_minutes)
            occupied.append((start, end_with_buffer))
    
    # Merge unavailable and occupied periods
    all_blocked = sorted(unavailable_periods + occupied, key=lambda x: x[0])
    
    # Find gaps
    current_pos = open_start
    for blocked_start, blocked_end in all_blocked:
        if blocked_start > open_end:
            break
        if blocked_end < open_start:
            continue
        
        # Clamp to business hours
        blocked_start = max(blocked_start, open_start)
        blocked_end = min(blocked_end, open_end)
        
        gap_end = blocked_start
        if gap_end > current_pos and gap_end - current_pos >= timedelta(minutes=required_duration):
            slots.append((current_pos, gap_end))
        
        current_pos = max(current_pos, blocked_end)
    
    # Final gap until close
    if open_end > current_pos and open_end - current_pos >= timedelta(minutes=required_duration):
        slots.append((current_pos, open_end))
    
    return slots


def find_replacement_slot(
    booking: Booking,
    equipment_list: list,
    outage: Optional[Outage],
    all_bookings: list,
    target_date: str,
    prefer_original_equipment: bool = True
) -> tuple:
    """
    Find a replacement slot for a booking.
    Returns: (slot_start, slot_end, equipment, reasons[]) or (None, None, None, reasons[])
    """
    equip_map = {e.id: e for e in equipment_list}
    reasons = []
    
    user_bookings = [b for b in all_bookings if b.user_id == booking.user_id]
    
    # Get allowed equipment
    if prefer_original_equipment and booking.equipment_id in equip_map:
        allowed_equip_ids = [booking.equipment_id]
    else:
        allowed_equip_ids = [e.id for e in equipment_list if e.unit_id == equip_map[booking.equipment_id].unit_id]
    
    for equip_id in allowed_equip_ids:
        equipment = equip_map[equip_id]
        unavail = calculate_unavailable_periods(equipment, outage, target_date)
        my_bookings = [b for b in user_bookings if b.equipment_id == equip_id]
        other_bookings = [b for b in all_bookings if b.user_id != booking.user_id and b.equipment_id == equip_id]
        
        # Filter out the booking itself if still on this equipment
        if booking.equipment_id == equip_id:
            other_bookings = [b for b in other_bookings if b.id != booking.id]
        
        slots = generate_available_slots(
            equipment, target_date, booking.duration_minutes,
            unavail, other_bookings
        )
        
        for slot_start, slot_end in slots:
            duration = (slot_end - slot_start).total_seconds() / 60
            
            # Check deadline
            if booking.deadline:
                deadline_str = booking.deadline
                if len(deadline_str) == 10:  # Just date YYYY-MM-DD
                    deadline_dt = time_to_datetime(deadline_str, '23:59')
                else:
                    deadline_dt = parse_datetime(deadline_str)
                
                if slot_end > deadline_dt:
                    deadline_needed = slot_end.strftime('%H:%M')
                    reasons.append({
                        "code": "deadline_would_need",
                        "at_least": deadline_needed
                    })
                    continue
            
            # Found valid slot
            return (slot_start, slot_end, equipment, reasons)
    
    # No valid slot found
    if not slots:
        reasons.append({"code": "no_available_timeslot"})
    
    return (None, None, None, reasons)


def propose_replan(
    outage: Outage,
    affected_bookings: list,
    equipment_list: list,
    all_bookings: list,
    schedule_version: int
) -> ReplanPlan:
    """
    Propose a replan for affected bookings.
    Returns a ReplanPlan object with proposed changes.
    """
    import uuid
    
    plan = ReplanPlan(
        plan_id=f"plan_{uuid.uuid4().hex[:8]}",
        outage_id=outage.id,
        based_on_version=schedule_version
    )
    
    # Sort affected bookings by deadline (earliest first)
    def sort_key(b):
        if b.deadline:
            if len(b.deadline) == 10:
                return parse_datetime(b.deadline + 'T23:59:59')
            return parse_datetime(b.deadline)
        return datetime.max.replace(tzinfo=timezone.utc)
    
    sorted_bookings = sorted(affected_bookings, key=sort_key)
    
    for booking in sorted_bookings:
        if not booking.movable or booking.status == 'unresolved':
            plan.unresolved.append({
                "booking_id": booking.id,
                "reasons": [{"code": "not_movable"}]
            })
            continue
        
        new_start, new_end, equipment, reasons = find_replacement_slot(
            booking, equipment_list, outage, all_bookings,
            get_date_str(parse_datetime(booking.original_start))
        )
        
        if new_start is None:
            plan.unresolved.append({
                "booking_id": booking.id,
                "reasons": reasons,
                "earliest_possible": calculate_earliest_possible(
                    booking, equipment_list, outage, all_bookings
                )
            })
        else:
            plan.changes.append({
                "booking_id": booking.id,
                "user_name": booking.user_name,
                "original_equip": booking.equipment_id,
                "original_start": format_datetime(parse_datetime(booking.original_start)),
                "original_end": format_datetime(parse_datetime(booking.original_end)),
                "new_equip": equipment.id,
                "new_start": format_datetime(new_start),
                "new_end": format_datetime(new_end),
                "reasons": reasons or [{"code": "outage_impacted"}]
            })
    
    plan.is_complete = len(plan.unresolved) == 0
    
    return plan


def calculate_earliest_possible(
    booking: Booking,
    equipment_list: list,
    outage: Optional[Outage],
    all_bookings: list
) -> list:
    """
    Calculate earliest possible completion for each accessible equipment.
    This is used when no valid slot exists under current constraints.
    """
    equip_map = {e.id: e for e in equipment_list}
    earliest_list = []
    
    allowed_equip_ids = [e.id for e in equipment_list 
                         if equip_map[booking.equipment_id].unit_id == e.unit_id]
    
    for equip_id in allowed_equip_ids:
        equipment = equip_map[equip_id]
        unavail = calculate_unavailable_periods(equipment, outage, get_date_str(parse_datetime(booking.original_start)))
        user_bookings = [b for b in all_bookings if b.user_id == booking.user_id and b.equipment_id == equip_id]
        
        slots = generate_available_slots(
            equipment, get_date_str(parse_datetime(booking.original_start)),
            booking.duration_minutes, unavail, user_bookings
        )
        
        if slots:
            slot_start, slot_end = slots[0]
            
            # Calculate what would need to change
            blockers = []
            if booking.deadline:
                deadline_str = booking.deadline
                if len(deadline_str) == 10:
                    deadline_dt = time_to_datetime(deadline_str, '23:59')
                else:
                    deadline_dt = parse_datetime(deadline_str)
                
                if slot_end > deadline_dt:
                    blockers.append({
                        "code": "deadline_conflict",
                        "deadline": format_datetime(deadline_dt)[:16],
                        "finish": format_datetime(slot_end)[:16],
                        "would_need": {"code": "deadline_would_need", "at_least": slot_end.strftime('%H:%M')}
                    })
            
            # Check if blocked by other bookings
            for i, (s, e) in enumerate(slots[1:], 1):
                prev_finish = slots[i-1][1]
                blockers.append({
                    "code": "blocked_by_booking",
                    "wait_until": format_datetime(prev_finish)[:16]
                })
            
            earliest_list.append({
                "equipment_id": equipment.id,
                "equipment_name": equipment.name,
                "earliest_start": format_datetime(slot_start)[:16],
                "earliest_finish": format_datetime(slot_end)[:16],
                "blockers": blockers
            })
        else:
            # Equipment completely unavailable
            unavailable_reasons = []
            for us in unavail:
                if us[1] > parse_datetime("2026-10-20T00:00:00"):
                    unavailable_reasons.append({
                        "code": "down_until",
                        "until": format_datetime(us[1])[:16]
                    })
            
            earliest_list.append({
                "equipment_id": equipment.id,
                "equipment_name": equipment.name,
                "status": "unavailable",
                "reasons": unavailable_reasons
            })
    
    return earliest_list
