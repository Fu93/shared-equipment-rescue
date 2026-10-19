"""Database operations using SQLite."""

import sqlite3
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime


@contextmanager
def get_db_connection(db_path: str = 'equipment.db'):
    """Context manager for database connections."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_database(db_path: str = 'equipment.db'):
    """Initialize database schema."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS units (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                timezone TEXT DEFAULT 'Europe/London'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('manager', 'researcher')),
                accessible_equipment TEXT NOT NULL,  -- JSON array
                token TEXT UNIQUE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS equipment (
                id TEXT PRIMARY KEY,
                unit_id TEXT NOT NULL,
                name TEXT NOT NULL,
                available_start TEXT NOT NULL,
                available_end TEXT NOT NULL,
                buffer_minutes INTEGER DEFAULT 15,
                FOREIGN KEY (unit_id) REFERENCES units(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                equipment_id TEXT NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                original_start TEXT NOT NULL,
                original_end TEXT NOT NULL,
                current_start TEXT NOT NULL,
                current_end TEXT NOT NULL,
                deadline TEXT,
                movable INTEGER DEFAULT 1 CHECK(movable IN (0, 1)),
                status TEXT DEFAULT 'confirmed' CHECK(status IN ('confirmed', 'blocked', 'unresolved')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (equipment_id) REFERENCES equipment(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS outages (
                id TEXT PRIMARY KEY,
                equipment_id TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                reason TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (equipment_id) REFERENCES equipment(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                outage_id TEXT NOT NULL,
                based_on_version INTEGER NOT NULL,
                changes TEXT NOT NULL,  -- JSON
                unresolved TEXT NOT NULL,  -- JSON
                status TEXT DEFAULT 'proposed' CHECK(status IN ('proposed', 'applied', 'stale')),
                confirmed_by TEXT,
                confirmed_at TEXT,
                FOREIGN KEY (outage_id) REFERENCES outages(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS change_log (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                booking_id TEXT NOT NULL,
                before_change TEXT NOT NULL,  -- JSON
                after_change TEXT NOT NULL,  -- JSON
                confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                FOREIGN KEY (plan_id) REFERENCES plans(id),
                FOREIGN KEY (booking_id) REFERENCES bookings(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        # Initialize version counter
        cursor.execute('''
            INSERT OR IGNORE INTO meta (key, value) VALUES ('schedule_version', '0')
        ''')


def get_schedule_version(db_path: str = 'equipment.db') -> int:
    """Get current schedule version."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        return int(row['value']) if row else 0


def increment_schedule_version(db_path: str = 'equipment.db') -> int:
    """Increment and return new schedule version."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
        cursor.execute("SELECT value FROM meta WHERE key = 'schedule_version'")
        row = cursor.fetchone()
        return int(row['value']) if row else 1


# Query functions

def get_unit(unit_id: str, db_path: str = 'equipment.db') -> Optional[Dict]:
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM units WHERE id = ?", (unit_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_bookings(
    db_path: str = 'equipment.db',
    unit_id: Optional[str] = None,
    date: Optional[str] = None,
    user_id: Optional[str] = None
) -> List[Dict]:
    """List bookings with optional filters."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        query = "SELECT b.*, u.name as user_name, u.role from bookings b join users u on b.user_id = u.id"
        params = []
        
        conditions = []
        if unit_id:
            conditions.append("e.unit_id = ?")
            params.append(unit_id)
        if date:
            conditions.append("DATE(b.current_start) = ?")
            params.append(date)
        if user_id:
            conditions.append("b.user_id = ?")
            params.append(user_id)
        
        if conditions:
            query += " JOIN equipment e ON b.equipment_id = e.id WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY b.current_start"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_outages(
    db_path: str = 'equipment.db',
    equipment_id: Optional[str] = None,
    date: Optional[str] = None
) -> List[Dict]:
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM outages WHERE 1=1"
        params = []
        
        if equipment_id:
            query += " AND equipment_id = ?"
            params.append(equipment_id)
        if date:
            query += " AND DATE(start) <= ? AND DATE(end) >= ?"
            params.extend([date, date])
        
        query += " ORDER BY start DESC"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_plans(
    db_path: str = 'equipment.db',
    outage_id: Optional[str] = None,
    status: Optional[str] = None
) -> List[Dict]:
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM plans WHERE 1=1"
        params = []
        
        if outage_id:
            query += " AND outage_id = ?"
            params.append(outage_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY confirmed_at DESC"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def create_outage(
    equipment_id: str,
    start: str,
    end: str,
    reason: Optional[str] = None,
    created_by: Optional[str] = None,
    db_path: str = 'equipment.db'
) -> Dict:
    """Create a new outage record."""
    import uuid
    
    outage_id = f"outage_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO outages (id, equipment_id, start, end, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (outage_id, equipment_id, start, end, reason, created_by, now))
        
        return {
            "id": outage_id,
            "equipment_id": equipment_id,
            "start": start,
            "end": end,
            "reason": reason,
            "created_by": created_by,
            "created_at": now
        }


def create_plan(
    outage_id: str,
    based_on_version: int,
    changes: list,
    unresolved: list,
    db_path: str = 'equipment.db'
) -> Dict:
    """Create a new replan proposal."""
    import json
    import uuid
    
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO plans (id, outage_id, based_on_version, changes, unresolved, status)
            VALUES (?, ?, ?, ?, ?, 'proposed')
        ''', (
            plan_id, outage_id, based_on_version,
            json.dumps(changes), json.dumps(unresolved)
        ))
        
        return {
            "id": plan_id,
            "outage_id": outage_id,
            "based_on_version": based_on_version,
            "changes": changes,
            "unresolved": unresolved,
            "status": "proposed"
        }


def update_plan_status(
    plan_id: str,
    status: str,
    confirmed_by: Optional[str] = None,
    confirmed_at: Optional[str] = None,
    db_path: str = 'equipment.db'
):
    """Update plan status."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE plans SET status = ?, confirmed_by = ?, confirmed_at = ?
            WHERE id = ?
        ''', (status, confirmed_by, confirmed_at, plan_id))


def log_change(
    plan_id: str,
    booking_id: str,
    before_change: dict,
    after_change: dict,
    confirmed_by: str,
    confirmed_at: str,
    db_path: str = 'equipment.db'
):
    """Log a booking change."""
    import uuid
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO change_log (id, plan_id, booking_id, before_change, after_change, confirmed_by, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            f"change_{uuid.uuid4().hex[:8]}", plan_id, booking_id,
            json.dumps(before_change), json.dumps(after_change),
            confirmed_by, confirmed_at
        ))


def apply_replan_changes(
    plan: dict,
    confirmed_by: str,
    db_path: str = 'equipment.db'
):
    """Apply all changes from a plan to the database."""
    import json
    
    confirmed_at = datetime.now().isoformat()
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Update each booking
        for change in plan.get('changes', []):
            # Log before state
            before = {
                "equipment_id": change['original_equip'],
                "start": change['original_start'],
                "end": change['original_end']
            }
            
            # After state will be updated in database
            cursor.execute('''
                UPDATE bookings SET
                    current_start = ?,
                    current_end = ?,
                    equipment_id = ?,
                    status = 'confirmed'
                WHERE id = ?
            ''', (
                change['new_start'],
                change['new_end'],
                change['new_equip'],
                change['booking_id']
            ))
            
            # Log the change
            after = {
                "equipment_id": change['new_equip'],
                "start": change['new_start'],
                "end": change['new_end']
            }
            
            cursor.execute('''
                INSERT INTO change_log (id, plan_id, booking_id, before_change, after_change, confirmed_by, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                f"change_{uuid.uuid4().hex[:8]}", plan['id'], change['booking_id'],
                json.dumps(before), json.dumps(after),
                confirmed_by, confirmed_at
            ))
        
        # Update plan status
        cursor.execute('''
            UPDATE plans SET status = 'applied', confirmed_by = ?, confirmed_at = ?
            WHERE id = ? AND status = 'proposed'
        ''', (confirmed_by, confirmed_at, plan['id']))
        
        # Increment schedule version
        cursor.execute("UPDATE meta SET value = value + 1 WHERE key = 'schedule_version'")
