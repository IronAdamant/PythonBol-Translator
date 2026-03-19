"""MCP (Model Context Protocol) server for the COBOL-to-Python translator.

Exposes translator tools over stdio using JSON-RPC 2.0.
Zero external dependencies -- stdlib only.

Run as:
    python -m cobol_safe_translator --mcp
    python -m cobol_safe_translator.mcp_server
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

from .analyzer import analyze
from .batch import discover_cobol_files
from .exporters import export_json, export_markdown
from .mapper import generate_python
from .parser import parse_cobol_file
from .prompt_generator import generate_prompt
from .utils import _to_python_name

from . import __version__

_SERVER_NAME = "cobol-safe-translator"
_SERVER_VERSION = __version__
_PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "translate_cobol",
        "description": (
            "Parse a COBOL source file, analyze it, and generate a Python "
            "skeleton translation. Returns the Python source code as text. "
            "If output_path is given, also writes the result to that file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the COBOL source file",
                },
                "copybook_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of copybook search paths (reserved for future use)",
                },
                "output_path": {
                    "type": "string",
                    "description": "If given, write the generated Python to this file path",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "analyze_cobol",
        "description": (
            "Parse and analyze a COBOL source file, returning a structured "
            "analysis report in Markdown or JSON format."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the COBOL source file",
                },
                "copybook_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of copybook search paths (reserved for future use)",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Report format (default: markdown)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "generate_brief",
        "description": (
            "Generate a compact LLM translation brief for a COBOL program. "
            "Includes metadata, sensitivities, TODO inventory, and the Python "
            "skeleton -- designed to give an LLM exactly what it needs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the COBOL source file",
                },
                "copybook_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of copybook search paths (reserved for future use)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_sensitivities",
        "description": (
            "Scan a COBOL source file for sensitive data fields (SSN, passwords, "
            "account numbers, etc.) and return a JSON list of findings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the COBOL source file",
                },
                "copybook_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of copybook search paths (reserved for future use)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "discover_cobol_files",
        "description": (
            "Find COBOL source files (.cob, .cbl, .cobol) in a directory. "
            "Returns a JSON list of absolute file paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to search",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search subdirectories (default: false)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "translate_directory",
        "description": (
            "Batch translate all COBOL files in a directory to Python. "
            "Each file gets its own subdirectory under output_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing COBOL source files",
                },
                "output_path": {
                    "type": "string",
                    "description": "Root output directory for translated files",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search subdirectories (default: false)",
                },
                "copybook_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of copybook search paths (reserved for future use)",
                },
            },
            "required": ["path", "output_path"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _validate_file(path_str: str) -> Path:
    """Resolve and validate that a file exists."""
    p = Path(path_str).resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise IsADirectoryError(f"Not a file: {p}")
    return p


def _validate_dir(path_str: str) -> Path:
    """Resolve and validate that a directory exists."""
    p = Path(path_str).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {p}")
    return p


def _parse_and_analyze_file(params: dict):
    """Parse and analyze a COBOL file from tool params. Returns the SoftwareMap."""
    p = _validate_file(params["path"])
    program = parse_cobol_file(p)
    return analyze(program)


def _handle_translate_cobol(params: dict) -> str:
    smap = _parse_and_analyze_file(params)
    python_source = generate_python(smap)

    output_path = params.get("output_path")
    if output_path:
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(python_source, encoding="utf-8")

    return python_source


def _handle_analyze_cobol(params: dict) -> str:
    smap = _parse_and_analyze_file(params)

    fmt = params.get("format", "markdown")
    if fmt == "json":
        return export_json(smap)
    return export_markdown(smap)


def _handle_generate_brief(params: dict) -> str:
    smap = _parse_and_analyze_file(params)
    python_source = generate_python(smap)
    return generate_prompt(smap, python_source)


def _handle_list_sensitivities(params: dict) -> str:
    smap = _parse_and_analyze_file(params)

    result = [
        {
            "data_name": s.data_name,
            "pattern": s.pattern_matched,
            "level": s.level.value,
            "reason": s.reason,
        }
        for s in smap.sensitivities
    ]
    return json.dumps(result, indent=2)


def _handle_discover_cobol_files(params: dict) -> str:
    d = _validate_dir(params["path"])
    recursive = params.get("recursive", False)
    files = discover_cobol_files(d, recursive=recursive)
    return json.dumps([str(f) for f in files], indent=2)


def _handle_translate_directory(params: dict) -> str:
    src_dir = _validate_dir(params["path"])
    out_root = Path(params["output_path"]).resolve()
    recursive = params.get("recursive", False)

    files = discover_cobol_files(src_dir, recursive=recursive)
    if not files:
        return json.dumps({"successes": 0, "failures": 0, "errors": []})

    successes = 0
    failures = 0
    errors: list[dict[str, str]] = []

    for src in files:
        try:
            program = parse_cobol_file(src)
            smap = analyze(program)
            python_source = generate_python(smap)

            out_dir = out_root / src.stem
            out_dir.mkdir(parents=True, exist_ok=True)

            name = _to_python_name(program.program_id) or "unnamed"
            out_file = out_dir / f"{name}.py"
            out_file.write_text(python_source, encoding="utf-8")
            successes += 1
        except Exception as exc:
            failures += 1
            errors.append({"file": str(src), "error": str(exc)})

    result = {
        "successes": successes,
        "failures": failures,
        "total": len(files),
        "output_path": str(out_root),
        "errors": errors,
    }
    return json.dumps(result, indent=2)


_TOOL_HANDLERS: dict[str, Callable] = {
    "translate_cobol": _handle_translate_cobol,
    "analyze_cobol": _handle_analyze_cobol,
    "generate_brief": _handle_generate_brief,
    "list_sensitivities": _handle_list_sensitivities,
    "discover_cobol_files": _handle_discover_cobol_files,
    "translate_directory": _handle_translate_directory,
}

# ---------------------------------------------------------------------------
# MCP JSON-RPC server
# ---------------------------------------------------------------------------


class CobolMcpServer:
    """Minimal MCP server over stdio (JSON-RPC 2.0, one message per line)."""

    def _log(self, msg: str) -> None:
        """Log to stderr (stdout is the protocol channel)."""
        print(f"[cobol-mcp] {msg}", file=sys.stderr, flush=True)

    def _send(self, message: dict) -> None:
        """Write a JSON-RPC message to stdout."""
        line = json.dumps(message, separators=(",", ":"))
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def _send_result(self, req_id: int | str | None, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(
        self,
        req_id: int | str | None,
        code: int,
        message: str,
        data: str | None = None,
    ) -> None:
        err: dict = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        self._send({"jsonrpc": "2.0", "id": req_id, "error": err})

    # --- Method handlers ---

    def _handle_initialize(self, req_id: int | str | None, params: dict) -> None:
        self._send_result(req_id, {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": _SERVER_NAME,
                "version": _SERVER_VERSION,
            },
        })

    def _handle_tools_list(self, req_id: int | str | None, params: dict) -> None:
        self._send_result(req_id, {"tools": TOOLS})

    def _handle_tools_call(self, req_id: int | str | None, params: dict) -> None:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = _TOOL_HANDLERS.get(tool_name)
        if handler is None:
            self._send_error(req_id, -32601, f"Unknown tool: {tool_name}")
            return

        try:
            result_text = handler(arguments)
            self._send_result(req_id, {
                "content": [{"type": "text", "text": result_text}],
            })
        except FileNotFoundError as exc:
            self._send_error(req_id, -32000, str(exc))
        except (IsADirectoryError, NotADirectoryError) as exc:
            self._send_error(req_id, -32000, str(exc))
        except Exception as exc:
            tb = traceback.format_exc()
            self._log(f"Tool error ({tool_name}): {tb}")
            self._send_error(req_id, -32000, f"Tool error: {exc}", data=tb)

    # --- Main loop ---

    def _dispatch(self, message: dict) -> None:
        """Route a single JSON-RPC message to the appropriate handler."""
        method = message.get("method", "")
        req_id = message.get("id")
        params = message.get("params", {})

        if method == "initialize":
            self._handle_initialize(req_id, params)
        elif method == "notifications/initialized":
            # Notification -- no response needed
            pass
        elif method == "tools/list":
            self._handle_tools_list(req_id, params)
        elif method == "tools/call":
            self._handle_tools_call(req_id, params)
        elif req_id is not None:
            # Unknown method with an id -> respond with error
            self._send_error(req_id, -32601, f"Method not found: {method}")
        # Notifications without id for unknown methods are silently ignored

    def run(self) -> None:
        """Run the server loop, reading from stdin until EOF."""
        self._log("Server starting")

        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._send_error(None, -32700, f"Parse error: {exc}")
                    continue

                self._dispatch(message)

        except (BrokenPipeError, IOError):
            pass
        except KeyboardInterrupt:
            pass

        self._log("Server stopped")


def main() -> None:
    """Entry point for the MCP server."""
    server = CobolMcpServer()
    server.run()


if __name__ == "__main__":
    main()
