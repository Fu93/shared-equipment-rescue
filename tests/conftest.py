"""Pytest defaults for this suite.

A developer shell may export AWS_BEARER_TOKEN_BEDROCK. The servers started
by these tests inherit the environment, and schedule_get would then call
Amazon Bedrock and change the scripted narration the contract tests lock.
Force the scripted path for the whole suite. The one live Converse test
opts back in.
"""
import os

os.environ["SER_LLM_MODE"] = "scripted"
