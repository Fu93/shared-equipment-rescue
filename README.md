# Shared Equipment Rescue

**A voice-first Alexa+ style add-on that helps shared-facility managers recover a day's bookings when an instrument goes down — powered by a self-hosted MCP server that proposes rule-checked replans and never writes changes without human confirmation.**

## Overview

When critical shared equipment fails, it can disrupt multiple reservations across a facility. This tool automates the rebooking process by:

1. **Detecting** affected appointments when equipment goes down
2. **Proposing** optimal replacement times based on configurable rules (deadlines, preferences, availability)
3. **Validating** all suggestions follow stated policies before application
4. **Confirming** through structured elicitation (human-in-the-loop approval required)

Unlike simple wrapper APIs, this implements a multi-step agent workflow where the AI model orchestrates tool calls while strict rule enforcement ensures no suggestion violates policy constraints.

## Features

- ✅ **MCP 2025-11-25** compliant server with Streamable HTTP transport
- ✅ **Rule-based scheduling engine** with deadline awareness and buffer management  
- ✅ **Elicitation workflow** requiring explicit human confirmation before changes
- ✅ **Transaction-safe updates** with version control and rollback capability
- ✅ **Graceful degradation** when optimal scheduling is impossible under current constraints
- ✅ **Audit trail** via change logs for compliance tracking

## Quick Start

### Prerequisites

- Python 3.10 or higher
- pip package manager

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database with seed data
python -c "from mcp_server import init_database, seed_database; init_database(); seed_database()"

# Start MCP server
python -m mcp_server.server
```

Server will listen at `http://localhost:8000`

### API Usage

#### 1. View Current Schedule
```bash
curl http://localhost:8000/mcp/schedule_get?unit_id=lab-a&date=2026-10-20
```

Returns: Bookings, equipment list, active outages, pending plans

#### 2. Report Equipment Outage
```bash
curl http://localhost:8000/mcp/equipment_report_outage \
  -H "Content-Type: application/json" \
  -d '{
    "equipment_id": "confocal-a",
    "start": "2026-10-20T10:00:00",
    "end": "2026-10-20T16:00:00",
    "reason": "Laser failure - requires service call"
  }'
```

Returns: Affected bookings list

#### 3. Propose Replan
```bash
curl http://localhost:8000/mcp/schedule_propose_replan \
  -H "Content-Type: application/json" \
  -d '{
    "outage_id": "outage_abc123",
    "schedule_version": 5
  }'
```

Returns: Proposed changes with reasons, unresolved items

#### 4. Apply Replan (after confirmation)
```bash
curl http://localhost:8000/mcp/schedule_apply_replan \
  -H "Content-Type: application/json" \
  -d '{
    "plan_id": "plan_xyz789",
    "schedule_version": 6
  }'
```

Requires successful elicitation confirmation from user

## Architecture

```
┌─────────────────────────────────────┐
│        Browser UI (Optional)        │
│  • Voice input / Web Speech API     │
│  • Visual schedule cards            │
│  • Elicitation confirmation panels  │
└───────────────┬─────────────────────┘
                │ HTTP + SSE
┌───────────────┴─────────────┐
│ MCP Host (Agent Loop)       │
│ • Bedrock Converse API      │
│ • MCP Client Session        │
│ • Event Streaming           │
└───────────────┬─────────────┘
                │ Streamable HTTP
┌───────────────┴─────────────┐
│ MCP Server (This Project)   │
│ • FastMCP Framework         │
│ • Schedule Engine           │
│ • SQLite Database           │
└─────────────────────────────┘
```

## Scheduled Rules

The algorithm enforces these constraints when generating replacement slots:

1. Only affected and movable bookings are rescheduled
2. Process earliest deadlines first (FIFO per deadline urgency)
3. Each booking searches in 15-minute increments from original time
4. Validates against:
   - Equipment operating hours
   - User access permissions
   - Personal availability (no double-booking)
   - Hard deadlines
   - Required buffer time between sessions (default: 15 min)
5. Prefers original equipment when available
6. Uses greedy approach; may not find optimal solution but guarantees correctness

## Demo Scenario

Six bookings across two confocal microscopes (Confocal A & B):

| ID | User | Device | Original Time | Deadline | Movable |
|----|------|--------|---------------|----------|---------|
| B1 | Wang | Confocal A | 09:00-10:00 | — | Yes |
| B2 | Chen | Confocal A | 10:00-11:00 | 13:00 | Yes |
| B3 | Li | Confocal B | 10:00-11:00 | — | **No** |
| B4 | Wang | Confocal A | 11:00-12:00 | 18:00 | Yes |
| B5 | Li | Confocal B | 14:00-15:00 | — | Yes |
| B6 | Chen | Confocal B | 15:00-16:00 | — | Yes |

**Outage:** Confocal A unavailable 10:00-16:00

**Expected Reschedule:**
- **B2 → Confocal B** 11:15-12:15 (earliest slot after Li's fixed booking)
- **B4 → Confocal A** 16:00-17:00 (after outage resolution)

## Technology Choices

| Component | Selection | Rationale |
|-----------|-----------|-----------|
| MCP Server | FastMCP (Python SDK) | Official implementation, Streamable HTTP support |
| Database | SQLite | Lightweight, transactional, portable |
| Agent Model | Amazon Bedrock (Claude) | AWS Builder Challenge alignment |
| Transport | Streamable HTTP | Latest MCP specification (2025-11-25) |

## Contributing

This is a competition entry. For questions or issues, please open a GitHub issue.

## License

MIT License - see LICENSE file for details.

## Disclaimer

This prototype uses synthetic demo data. All user names, schedules, and equipment references are fictional and for demonstration purposes only. Not intended for production use without additional security hardening and integration testing.
