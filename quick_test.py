"""Quick test script to verify MCP server functionality."""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_schedule_get():
    """Test 1: Get schedule"""
    print("\n=== Test 1: GET Schedule ===")
    try:
        response = requests.get(f"{BASE_URL}/mcp/schedule_get?unit_id=lab-a&date=2026-10-20")
        data = response.json()
        
        print(f"✅ Schedule loaded successfully")
        print(f"   Version: {data['schedule_version']}")
        print(f"   Bookings: {len(data['bookings'])}")
        print(f"   Equipment: {len(data['equipment'])}")
        
        for b in data['bookings']:
            status_icon = "✓" if b['status'] == 'confirmed' else "⛔"
            print(f"   [{status_icon}] {b['id']}: {b['user']} - {b['start'][:16]} on {b['equipment']}")
        
        return data
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_report_outage():
    """Test 2: Report equipment outage"""
    print("\n=== Test 2: Report Outage ===")
    try:
        response = requests.post(
            f"{BASE_URL}/mcp/equipment_report_outage",
            json={
                "equipment_id": "confocal-a",
                "start": "2026-10-20T10:00:00",
                "end": "2026-10-20T16:00:00",
                "reason": "Demo: Laser failure requiring service call"
            }
        )
        data = response.json()
        
        print(f"✅ Outage reported successfully")
        print(f"   Outage ID: {data['outage_id']}")
        print(f"   Affected bookings: {len(data['affected_bookings'])}")
        
        for affected in data['affected_bookings']:
            print(f"   - {affected['user']}: {affected['original_time']}")
        
        return data
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_propose_replan(outage_id):
    """Test 3: Propose replan"""
    print("\n=== Test 3: Propose Replan ===")
    try:
        # First get current schedule version
        schedule = test_schedule_get()
        if not schedule:
            return None
        
        response = requests.post(
            f"{BASE_URL}/mcp/schedule_propose_replan",
            json={
                "outage_id": outage_id,
                "schedule_version": schedule['schedule_version']
            }
        )
        data = response.json()
        
        print(f"✅ Replan proposed successfully")
        print(f"   Plan ID: {data['plan_id']}")
        print(f"   Changes: {len(data['changes'])} replacement slots found")
        
        for change in data['changes']:
            print(f"   → {change['user_name']}:")
            print(f"      From: {change['original_equip']} ({change['original_start'][11:16]})")
            print(f"      To:   {change['new_equip']} ({change['new_start'][11:16]})")
        
        if data['unresolved']:
            print(f"   ⚠️  Unresolved: {len(data['unresolved'])} booking(s) need manual attention")
            for u in data['unresolved']:
                print(f"      - {u['booking_id']}")
        
        print(f"   Is Complete: {data['is_complete']}")
        
        return data
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_reset():
    """Test 4: Reset to seed data"""
    print("\n=== Test 4: Reset Demo ===")
    try:
        response = requests.post(f"{BASE_URL}/mcp/reset_to_seed_data")
        data = response.json()
        
        print(f"✅ Demo reset successfully")
        print(f"   New version: {data['version']}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("SHARED EQUIPMENT RESCUE - QUICK DEMO TEST")
    print("=" * 60)
    
    # Test 1: Initial state
    initial_state = test_schedule_get()
    
    if not initial_state:
        print("\n❌ Cannot proceed without initial schedule")
        return
    
    # Wait a bit before testing outage
    import time
    time.sleep(0.5)
    
    # Test 2: Report outage
    outage = test_report_outage()
    if not outage:
        print("\n❌ Outage reporting failed")
        return
    
    # Test 3: Propose replan
    replan = test_propose_replan(outage['outage_id'])
    if not replan:
        print("\n❌ Replan proposal failed")
        return
    
    # Test 4: Reset
    test_reset()
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED SUCCESSFULLY! ✅")
    print("=" * 60)
    print("\n🎉 The MCP server is working correctly!")
    print("\nYou can now:")
    print("  1. Open http://localhost:8000 in your browser to see the UI")
    print("  2. Run python web/app.py to start the web interface")
    print("  3. Report outages and propose reschedules automatically")

if __name__ == "__main__":
    main()
