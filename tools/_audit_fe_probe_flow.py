# -*- coding: utf-8 -*-
"""Audit probe 2: full demo flow (report -> propose -> apply/elicitation) through
the web proxy on :8080, capturing the exact JSON payload shapes the UI parses.

Also checks the elicitation server->client round trip on the POST SSE stream.
"""
import json
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB = "http://127.0.0.1:8080"
BASE_H = {
    "authorization": "Bearer tok-manager",
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def parse_sse(text):
    out = []
    ev, data = None, []
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "":
            if data:
                try:
                    out.append((ev, json.loads("\n".join(data))))
                except Exception:
                    out.append((ev, "\n".join(data)))
            ev, data = None, []
    if data:
        try:
            out.append((ev, json.loads("\n".join(data))))
        except Exception:
            out.append((ev, "\n".join(data)))
    return out


class Sess:
    def __init__(self):
        self.h = dict(BASE_H)
        self.sid = None

    def call(self, method, params=None, rid=1, timeout=60):
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        h = dict(self.h)
        if self.sid:
            h["mcp-session-id"] = self.sid
        r = httpx.post(WEB + "/mcp", headers=h, json=payload, timeout=timeout)
        if not self.sid:
            self.sid = r.headers.get("mcp-session-id")
            if self.sid:
                self.h["mcp-session-id"] = self.sid
        return r

    def tool(self, name, args, rid=1, timeout=60):
        return self.call("tools/call", {"name": name, "arguments": args}, rid, timeout)


def sc_of(resp):
    """Extract structuredContent from a tools/call SSE response."""
    for ev, d in parse_sse(resp.text):
        if isinstance(d, dict) and "result" in d:
            r = d["result"]
            if "structuredContent" in r:
                return r["structuredContent"]
    return None


s = Sess()
r = s.call("initialize", {"protocolVersion": "2025-06-18",
                           "capabilities": {"elicitation": {}},
                           "clientInfo": {"name": "audit", "version": "1"}})
print("init:", r.status_code, "sid:", s.sid)
s.call("notifications/initialized", rid=None) if False else httpx.post(
    WEB + "/mcp", headers=s.h, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)

print()
print("=" * 70)
print("STEP 1: report outage")
print("=" * 70)
r = s.tool("equipment_report_outage", {
    "equipment_id": "confocal-a",
    "start": "2026-10-20T10:00:00+01:00",
    "end": "2026-10-20T16:00:00+01:00",
    "reason": "Laser failure — reported by facility"}, rid=10)
sc = sc_of(r)
print(json.dumps(sc, indent=1, ensure_ascii=False)[:1200])
outage_id = sc.get("outage_id")
version = sc.get("schedule_version")

print()
print("=" * 70)
print("STEP 2: propose replan")
print("=" * 70)
r = s.tool("schedule_propose_replan", {"outage_id": outage_id, "schedule_version": version}, rid=11)
sc = sc_of(r)
print("status:", sc.get("status"), "plan_id:", sc.get("plan_id"), "sched_version:", sc.get("schedule_version"))
print("summary:", sc.get("summary"))
print()
print("--- changes[0] RAW (field names the UI reads) ---")
ch = (sc.get("changes") or [{}])[0]
print(json.dumps(ch, indent=1, ensure_ascii=False))
print()
print("--- reasons of changes[0] RAW (note 'from' vs 'from_') ---")
for c in (sc.get("changes") or [])[:2]:
    for rr in (c.get("reasons") or []):
        print("  reason keys:", sorted(rr.keys()))
        print("  reason:", json.dumps(rr, ensure_ascii=False))
print()
print("--- unresolved[0] RAW ---")
un = sc.get("unresolved") or []
if un:
    print(json.dumps(un[0], indent=1, ensure_ascii=False)[:1500])
else:
    print("  (none)")
plan_id = sc.get("plan_id")

print()
print("=" * 70)
print("STEP 3: apply with elicitation (server->client on the POST SSE stream)")
print("=" * 70)
h = dict(s.h)
h["accept"] = "application/json, text/event-stream"
payload = {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
           "params": {"name": "schedule_apply_replan",
                      "arguments": {"plan_id": plan_id, "schedule_version": version}}}
elicit_id = None
with httpx.stream("POST", WEB + "/mcp", headers=h, json=payload, timeout=40) as resp:
    print("status:", resp.status_code, "ct:", resp.headers.get("content-type"))
    buf = ""
    t0 = time.time()
    for chunk in resp.iter_text():
        buf += chunk
        if '"elicitation/create"' in buf and elicit_id is None:
            for ev, d in parse_sse(buf):
                if isinstance(d, dict) and d.get("method") == "elicitation/create":
                    elicit_id = d.get("id")
                    print(f"[{time.time()-t0:.2f}s] ELICITATION received: id={elicit_id}")
                    print(json.dumps(d, indent=1, ensure_ascii=False))
                    break
            if elicit_id is not None:
                # respond to the elicitation on the same session
                resp_msg = {"jsonrpc": "2.0", "id": elicit_id,
                            "result": {"action": "accept", "content": {"confirm": True}}}
                rr = httpx.post(WEB + "/mcp", headers=h, json=resp_msg, timeout=20)
                print(f"[{time.time()-t0:.2f}s] elicit response POST -> {rr.status_code} {rr.text[:200]}")
        if '"id":12' in buf and '"result"' in buf and elicit_id:
            print(f"[{time.time()-t0:.2f}s] final chunk")
            break
    print()
    print("RAW STREAM (first 3000 chars):")
    print(buf[:3000])

print()
print("=" * 70)
print("STEP 4: schedule_get after apply (what the board renders)")
print("=" * 70)
r = s.tool("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"}, rid=13)
sc = sc_of(r)
print("version:", sc.get("schedule_version"))
for b in sc.get("bookings", []):
    print(f"  {b['id']:3} {b['user']:6} {b['equipment']:11} {b['start'][11:16]}-{b['end'][11:16]} {b['status']}")

print()
print("=" * 70)
print("STEP 5: audit rows (what the Audit tab renders)")
print("=" * 70)
r = s.tool("schedule_audit_get", {"limit": 20}, rid=14)
sc = sc_of(r)
print("status:", sc.get("status"), "next_before_id:", sc.get("next_before_id"), "n:", len(sc.get("entries") or []))
for e in (sc.get("entries") or [])[:8]:
    print(f"  at={e['at']} tool={e['tool']:26} result={e['result']:16} actor={e['actor_name']!r} detail={e['detail'][:70]!r} dj={'Y' if e.get('detail_json') else 'N'}")
print()
print("audit entry raw keys:", sorted((sc.get("entries") or [{}])[0].keys()))
