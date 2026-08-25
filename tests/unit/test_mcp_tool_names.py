from __future__ import annotations

import re

import anyio

from chrono_core import mcp_server

# Anthropic API tool-name constraint; dots are rejected by MCP clients that
# pass names through verbatim.
TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

EXPECTED_TOOLS = {
    "chrono_core_resolve_project",
    "chrono_core_session_handoff",
    "chrono_core_get_resume_context",
    "chrono_core_record_decision",
    "chrono_core_record_blocker",
    "chrono_core_resolve_blocker",
    "chrono_core_complete_action",
    "chrono_core_cancel_action",
    "chrono_core_edit_action",
    "chrono_core_reopen_action",
    "chrono_core_supersede_action",
    "chrono_core_cancel_blocker",
    "chrono_core_edit_blocker",
    "chrono_core_reopen_blocker",
    "chrono_core_distill_project",
    "chrono_core_search_observations",
    "chrono_core_review_project",
}


def test_all_tool_names_are_api_safe():
    tools = anyio.run(mcp_server.mcp.list_tools)
    for tool in tools:
        assert TOOL_NAME_PATTERN.fullmatch(tool.name), tool.name


def test_expected_tools_registered():
    tools = anyio.run(mcp_server.mcp.list_tools)
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
