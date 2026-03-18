"""Tests for the MCP server (JSON-RPC over stdio)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
HELLO_COB = SAMPLES_DIR / "hello.cob"


def _run_mcp(messages: list[dict], timeout: float = 15) -> list[dict]:
    """Send JSON-RPC messages to the MCP server and collect responses."""
    stdin_text = "\n".join(json.dumps(m) for m in messages) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "cobol_safe_translator.mcp_server"],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    responses = []
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if line:
            responses.append(json.loads(line))
    return responses


def test_initialize():
    """Server responds to initialize with correct protocol version."""
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test"},
            },
        },
    ]
    responses = _run_mcp(msgs)
    assert len(responses) == 1
    r = responses[0]
    assert r["id"] == 1
    assert "result" in r
    assert r["result"]["protocolVersion"] == "2024-11-05"
    assert r["result"]["serverInfo"]["name"] == "cobol-safe-translator"


def test_tools_list_returns_all_tools():
    """tools/list returns all 6 tools."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    responses = _run_mcp(msgs)
    assert len(responses) == 2
    tools_resp = responses[1]
    assert "result" in tools_resp
    tools = tools_resp["result"]["tools"]
    assert len(tools) == 6
    names = {t["name"] for t in tools}
    assert names == {
        "translate_cobol",
        "analyze_cobol",
        "generate_brief",
        "list_sensitivities",
        "discover_cobol_files",
        "translate_directory",
    }


@pytest.mark.skipif(not HELLO_COB.exists(), reason="hello.cob sample not found")
def test_translate_cobol_tool():
    """translate_cobol returns Python source containing the program class."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "translate_cobol",
                    "arguments": {"path": str(HELLO_COB)}}},
    ]
    responses = _run_mcp(msgs)
    assert len(responses) == 2
    tool_resp = responses[1]
    assert "result" in tool_resp, f"Expected result, got: {tool_resp}"
    content = tool_resp["result"]["content"]
    assert len(content) == 1
    text = content[0]["text"]
    assert "def run(self)" in text


@pytest.mark.skipif(not HELLO_COB.exists(), reason="hello.cob sample not found")
def test_analyze_cobol_json():
    """analyze_cobol with format=json returns valid JSON report."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "analyze_cobol",
                    "arguments": {"path": str(HELLO_COB), "format": "json"}}},
    ]
    responses = _run_mcp(msgs)
    tool_resp = responses[1]
    text = tool_resp["result"]["content"][0]["text"]
    report = json.loads(text)
    assert "program_id" in report
    assert "statistics" in report


@pytest.mark.skipif(not SAMPLES_DIR.exists(), reason="samples dir not found")
def test_discover_cobol_files_tool():
    """discover_cobol_files finds .cob files in samples/."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "discover_cobol_files",
                    "arguments": {"path": str(SAMPLES_DIR)}}},
    ]
    responses = _run_mcp(msgs)
    tool_resp = responses[1]
    text = tool_resp["result"]["content"][0]["text"]
    files = json.loads(text)
    assert len(files) >= 1
    assert any(f.endswith(".cob") for f in files)


def test_tool_call_missing_file():
    """Calling a tool with a nonexistent file returns an error response."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "test"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "translate_cobol",
                    "arguments": {"path": "/nonexistent/file.cob"}}},
    ]
    responses = _run_mcp(msgs)
    tool_resp = responses[1]
    assert "error" in tool_resp
    assert tool_resp["error"]["code"] == -32000
