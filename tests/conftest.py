"""Pytest defaults for this suite.

A developer shell may export AWS_BEARER_TOKEN_BEDROCK. The servers started
by these tests inherit the environment, and schedule_get would then call
Amazon Bedrock and change the scripted narration the contract tests lock.
Force the scripted path for the whole suite. The one live Converse test
opts back in.

SER_DEMO_DATE is read when mcp_server.constants is first imported. Pin it
here, before any test module imports the server, so the frozen 2026-10-20
examples stay on that day. Audit timestamps are not pinned.
"""
import os

os.environ["SER_LLM_MODE"] = "scripted"
os.environ["SER_DEMO_DATE"] = "2026-10-20"
os.environ["SER_DEMO_TZ"] = "Europe/London"
