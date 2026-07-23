from __future__ import annotations

import re

import anyio

from continuity_core import mcp_server

# Anthropic API tool-name constraint; dots are rejected by MCP clients that
# pass names through verbatim.
TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

EXPECTED_TOOLS = {
    "continuity_core_resolve_project",
    "continuity_core_session_handoff",
    "continuity_core_get_resume_context",
    "continuity_core_record_decision",
    "continuity_core_record_blocker",
    "continuity_core_resolve_blocker",
    "continuity_core_complete_action",
    "continuity_core_distill_project",
    "continuity_core_search_observations",
    "continuity_core_review_project",
}


def test_all_tool_names_are_api_safe():
    tools = anyio.run(mcp_server.mcp.list_tools)
    for tool in tools:
        assert TOOL_NAME_PATTERN.fullmatch(tool.name), tool.name


def test_expected_tools_registered():
    tools = anyio.run(mcp_server.mcp.list_tools)
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
