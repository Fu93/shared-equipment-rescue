"""Shared Equipment Rescue MCP server package.

Importing submodules explicitly (server, db, seed, engine) keeps startup import
order deterministic; no eager heavy imports here.
"""

__version__ = "1.0.0"
