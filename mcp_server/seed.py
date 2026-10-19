"""Seed data for Shared Equipment Rescue demo."""

import sqlite3
from datetime import datetime


def seed_database(db_path='equipment.db'):
    """Populate database with demo data."""
    
    # Connect directly to avoid nested context managers
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Clear existing data
        cursor.execute("DELETE FROM change_log")
        cursor.execute("DELETE FROM plans")
        cursor.execute("DELETE FROM outages")
        cursor.execute("DELETE FROM bookings")
        cursor.execute("DELETE FROM equipment")
        cursor.execute("DELETE FROM users")
        
        # Create units
        cursor.execute("""
            INSERT INTO units (id, name, timezone) VALUES (?, ?, ?)
        """, ("lab-a", "Research Lab A", "Europe/London"))
        
        # Create users
        users_data = [
            ("user-chen", "Chen", "manager", '["confocal-a", "confocal-b"]'),
            ("user-wang", "Wang", "researcher", '["confocal-a", "confocal-b"]'),
            ("user-li", "Li", "researcher", '["confocal-b"]'),
        ]
        
        for user_id, name, role, equipment in users_data:
            token = f"token_{user_id}"
            cursor.execute("""
                INSERT INTO users (id, name, role, accessible_equipment, token)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, name, role, equipment, token))
        
        # Create equipment
        equipment_data = [
            ("confocal-a", "lab-a", "Confocal Microscope A", "09:00", "18:00", 15),
            ("confocal-b", "lab-a", "Confocal Microscope B", "09:00", "18:00", 15),
        ]
        
        for equip_id, unit_id, name, start, end, buffer in equipment_data:
            cursor.execute("""
                INSERT INTO equipment (id, unit_id, name, available_start, available_end, buffer_minutes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (equip_id, unit_id, name, start, end, buffer))
        
        # Create bookings (based on the plan's scenario table)
        # Format: booking_id, user_id, equip_id, start_time, end_time, duration, deadline, movable, status
        bookings_data = [
            # B1: Wang on Confocal A, 09:00-10:00 (unaffected by outage)
            ("B1", "user-wang", "confocal-a", "2026-10-20T09:00:00", "2026-10-20T10:00:00", 60, None, True, "confirmed"),
            
            # B2: Chen on Confocal A, 10:00-11:00 (affected, deadline 13:00)
            ("B2", "user-chen", "confocal-a", "2026-10-20T10:00:00", "2026-10-20T11:00:00", 60, "2026-10-20T13:00:00", True, "confirmed"),
            
            # B3: Li on Confocal B, 10:00-11:00 (not movable)
            ("B3", "user-li", "confocal-b", "2026-10-20T10:00:00", "2026-10-20T11:00:00", 60, None, False, "confirmed"),
            
            # B4: Wang on Confocal A, 11:00-12:00 (affected, deadline 18:00)
            ("B4", "user-wang", "confocal-a", "2026-10-20T11:00:00", "2026-10-20T12:00:00", 60, "2026-10-20T18:00:00", True, "confirmed"),
            
            # B5: Li on Confocal B, 14:00-15:00 (unaffected)
            ("B5", "user-li", "confocal-b", "2026-10-20T14:00:00", "2026-10-20T15:00:00", 60, None, True, "confirmed"),
            
            # B6: Chen on Confocal B, 15:00-16:00 (unaffected)
            ("B6", "user-chen", "confocal-b", "2026-10-20T15:00:00", "2026-10-20T16:00:00", 60, None, True, "confirmed"),
        ]
        
        for b_id, u_id, e_id, start, end, duration, deadline, movable, status in bookings_data:
            m_val = 1 if movable else 0
            dl_val = deadline if deadline else None
            cursor.execute("""
                INSERT INTO bookings 
                (id, user_id, equipment_id, original_start, original_end, current_start, current_end, 
                 duration_minutes, deadline, movable, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (b_id, u_id, e_id, start, end, start, end, duration, dl_val, m_val, status))
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
    
    return {
        "status": "success",
        "message": f"Seeded {len(bookings_data)} bookings, {len(users_data)} users, {len(equipment_data)} equipment"
    }


if __name__ == "__main__":
    result = seed_database()
    print(f"Database seeded: {result['message']}")
