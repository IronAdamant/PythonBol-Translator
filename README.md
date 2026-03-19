# cobol-safe-translator

**COBOL-to-Python translator for AI-assisted mainframe migration.**

**100% valid Python output across 4,705 real-world COBOL files** — zero runtime dependencies, works offline, runs on any Python 3.11+ system.

Built for LLM agents (Claude, GPT, Gemini, Llama, Mistral) and human developers migrating enterprise COBOL off IBM mainframes. Includes an MCP server so AI coding assistants can use it as a tool directly.

> **This tool generates SKELETON code that requires review.** Generated code preserves COBOL data semantics (fixed-point arithmetic, string padding, FILE STATUS codes) through runtime adapters, but middleware integration (DB2, CICS, MQ, VSAM) must be implemented separately. Every untranslated construct is marked with `TODO(high)`.

## Why this exists

COBOL runs an estimated **$3 trillion in daily financial transactions**. The engineers who maintain it are retiring. The systems are locked behind IBM licensing, proprietary middleware, and documentation that hasn't been updated since the 1990s.

This tool exists to **break that lock-in**. Open source forever. No cloud upload. No vendor dependency. Zero pip-installed runtime dependencies.

Run it against any `.cob`/`.cbl`/`.cobol` file and get:
- A **runnable Python skeleton** with COBOL semantics preserved
- **EXEC SQL code generation** (DB-API 2.0 with parameterized queries)
- A **sensitivity report** flagging SSNs, balances, and PII
- A **token-efficient LLM brief** for AI agents to finish the migration
- An **interactive test** that validates and executes the translation

## Install

```bash
pip install cobol-safe-translator   # zero runtime dependencies

# Or from source
git clone https://github.com/IronAdamant/PythonBol-Translator.git
cd PythonBol-Translator && pip install -e ".[dev]"
```

Requires **Python 3.11+**. No pip dependencies at runtime. Cross-platform (Linux, macOS, Windows). Works fully offline.

## Quick start

```bash
# Translate a single file
cobol2py translate PAYROLL.cob

# Translate a directory recursively with copybook paths
cobol2py translate ./src/ --recursive --copybook-path ./cpy --output ./out

# Validate generated Python (syntax + import + instantiation)
cobol2py translate PAYROLL.cob --validate

# Full pipeline test (translate + validate + execute)
cobol2py test PAYROLL.cob

# Batch test an entire directory
cobol2py test ./src/ --recursive --timeout 30

# Generate analysis reports (Markdown + JSON)
cobol2py map PAYROLL.cob

# Generate LLM translation brief
cobol2py prompt PAYROLL.cob > brief.md
```

## Use with AI agents

### MCP Server (Claude Code, Cursor, Windsurf, etc.)

```json
{
  "mcpServers": {
    "cobol-translator": {
      "command": "python",
      "args": ["-m", "cobol_safe_translator", "--mcp"]
    }
  }
}
```

The MCP server exposes 6 tools: `translate_cobol`, `analyze_cobol`, `generate_brief`, `list_sensitivities`, `discover_cobol_files`, `translate_directory`.

### LLM Prompt Brief

```bash
cobol2py prompt PAYROLL.cob > brief.md
# Feed brief.md to any LLM and ask it to fill the TODOs
```

The prompt brief is 3-4x more token-efficient than raw COBOL source, containing only what the LLM needs: data structure, control flow, sensitivities, and the Python skeleton.

## Supported COBOL features

### Fully translated to Python

| Category | Features |
|----------|----------|
| **Data Division** | PIC clauses (9/X/A/S/V/P/edited), levels 01-49/77/88, OCCURS (multi-dimensional), REDEFINES, WORKING-STORAGE, FILE SECTION, LINKAGE SECTION, LOCAL-STORAGE, REPORT SECTION, SCREEN SECTION |
| **Data types** | USAGE COMP/COMP-3/BINARY (CobolDecimal), COMP-1/COMP-2 (float), COMP-5 (int), INDEX (int), DISPLAY (default) |
| **Data attributes** | EXTERNAL, GLOBAL, JUSTIFIED RIGHT, BLANK WHEN ZERO, OCCURS DEPENDING ON, SYNCHRONIZED |
| **Arithmetic** | ADD, SUBTRACT, MULTIPLY, DIVIDE (INTO/BY/GIVING/REMAINDER), COMPUTE (complex expressions), ON SIZE ERROR, ROUNDED (ROUND_HALF_UP) |
| **Control flow** | IF/ELSE (multi-line + inline), EVALUATE TRUE/variable/ALSO with WHEN THRU, PERFORM (simple/UNTIL/TIMES/VARYING/THRU), nested loops, GO TO (method call + return), GO TO DEPENDING ON, EXIT PERFORM |
| **String ops** | STRING (DELIMITED BY), UNSTRING (multi-delimiter), INSPECT (TALLYING/REPLACING/CONVERTING), MOVE (simple/ALL/CORRESPONDING/FUNCTION/group-level) |
| **Table ops** | SEARCH/SEARCH ALL, SORT/MERGE (USING/GIVING, INPUT/OUTPUT PROCEDURE), RELEASE, RETURN |
| **File I/O** | OPEN (INPUT/OUTPUT/EXTEND/I-O), CLOSE, READ (INTO + AT END/NOT AT END body), WRITE (FROM + AFTER/BEFORE ADVANCING), REWRITE, DELETE, START (KEY IS) |
| **FILE STATUS** | Tracked on FileAdapter ("00"/"10"/"35"/"30"), auto-updated after every I/O operation |
| **Report Writer** | RD, TYPE IS, LINE/COLUMN, SOURCE, SUM, GROUP INDICATE, INITIATE, GENERATE, TERMINATE |
| **Screen Section** | LINE, COL, PIC, VALUE, USING, FROM, TO, BLANK SCREEN, display attributes, ACCEPT/DISPLAY with screen names |
| **Intrinsics** | 30+ FUNCTION intrinsics: LENGTH, NUMVAL, UPPER-CASE, LOWER-CASE, REVERSE, TRIM, MAX, MIN, MOD, ABS, SQRT, LOG, SIN, COS, CURRENT-DATE, RANDOM, MEAN, MEDIAN, FACTORIAL, and more |
| **Preprocessing** | COPY resolution with recursive expansion, REPLACING (pseudo-text + LEADING/TRAILING + non-pseudo-text), cycle detection, case-insensitive copybook lookup |
| **EXEC SQL** | DB-API 2.0 code generation: DECLARE/OPEN/FETCH/CLOSE cursors, SELECT INTO, INSERT/UPDATE/DELETE, COMMIT/ROLLBACK, SQLCA/SQLCODE, host variable parameterization |
| **EXEC CICS** | Enhanced hints: MAP, TRANSID, COMMAREA, RESP/RESP2 extraction |
| **Declaratives** | USE AFTER ERROR/EXCEPTION, USE BEFORE REPORTING, USE FOR DEBUGGING — parsed and translated as handler methods |
| **Nested programs** | Multiple PROGRAM-ID per source, separate Python classes, GLOBAL data hints |
| **Other** | SET (88-level, UP/DOWN BY), CANCEL, INITIALIZE (with REPLACING), ADD/SUBTRACT CORRESPONDING, JSON/XML GENERATE stubs, communication verbs, ENTRY, MicroFocus directives |
| **Literals** | Hex (X"FF"), binary (B"01"), figurative constants (ZERO/SPACE/HIGH-VALUE/LOW-VALUE), EBCDIC collation |

### Runtime adapters (included, zero deps)

| Adapter | Purpose |
|---------|---------|
| `CobolDecimal` | Fixed-point arithmetic with truncation, ROUNDED mode, signed/unsigned, overflow handling |
| `CobolString` | Fixed-length strings with right-padding, truncation, EBCDIC collation |
| `FileAdapter` | File I/O with OPEN modes, FILE STATUS codes, EOF tracking |
| `GroupView` | Concatenated view of group item fields for group-level MOVE semantics |

## Validation

```bash
# Interactive test — translate, validate, and execute
cobol2py test program.cob

# Output:
# Testing: program.cob
#   Parse:      OK  (PROG-ID, 15 paragraphs, 0.12s)
#   Analyze:    OK  (3 sensitivities, 2 dependencies)
#   Generate:   OK  (245 lines)
#   Syntax:     OK  (ast.parse passed)
#   Validate:   OK  (import + instantiate passed)
#   Execute:    OK  (exit 0, 0.03s)
#   Output:     "HELLO WORLD"
#   Result: 6/6 checks passed
```

**Corpus validation: 4,705/4,705 files produce valid Python (100.00%)** across 42 test projects including NIST conformance suites, IBM CICS banking, enterprise DB2, French government tax code, GnuCOBOL test suite, AS/400 ILE, and a Minecraft server written in COBOL.

## Test suite

```bash
pytest tests/ -v
# 889 tests covering parser, analyzer, mapper, conditions, blocks, SEARCH,
# SORT/MERGE, FUNCTION intrinsics, REPORT WRITER, SCREEN SECTION, COPY expansion,
# nested programs, group MOVE, SQL translation, adapters, CLI, batch, validation,
# and 60+ behavioral end-to-end tests
```

## Project structure

```
src/cobol_safe_translator/
  models.py                — Shared dataclasses (AST, SqlBlock, UseDeclaration, ScreenField)
  parser.py                — COBOL parser (free/fixed format, nested programs, screen section)
  pic_parser.py            — PIC clause parsing and classification
  procedure_parser.py      — PROCEDURE DIVISION + DECLARATIVES splitting
  preprocessor.py          — COPY resolution (recursive), EXEC SQL/CICS extraction
  analyzer.py              — Sensitivity detection, dependency extraction, statistics
  mapper.py                — Python code generator (core orchestration)
  mapper_codegen.py        — Code generation mixin (data class, program class, header)
  mapper_verbs.py          — Verb translation mixin (MOVE, GO TO, PERFORM, arithmetic)
  condition_translator.py  — Two-pass COBOL condition → Python expression
  statement_translators.py — Arithmetic, PERFORM, READ, WRITE, I/O verbs
  function_translators.py  — 30+ FUNCTION intrinsic mappings
  sql_translator.py        — EXEC SQL → DB-API 2.0 Python code generator
  sort_translators.py      — SORT, MERGE, RELEASE, RETURN
  report_parser.py         — REPORT SECTION parser
  report_translators.py    — INITIATE, GENERATE, TERMINATE
  string_translators.py    — STRING, UNSTRING, INSPECT, SET
  io_translators.py        — ACCEPT, REWRITE, ON SIZE ERROR
  block_translator.py      — IF/EVALUATE/SEARCH block reconstruction
  adapters.py              — CobolDecimal, CobolString, FileAdapter, GroupView
  validation.py            — Runtime import validation
  ebcdic.py                — EBCDIC collation (cp037)
  exporters.py             — Markdown and JSON report exporters
  prompt_generator.py      — LLM translation brief generator
  batch.py                 — Batch/directory processing
  cli.py                   — CLI (translate / map / prompt / test)
  mcp_server.py            — MCP server for AI coding assistants
  py.typed                 — PEP 561 type marker
```

## CLI reference

```
cobol2py translate <path|dir> [--output <dir>] [--recursive] [--validate] [--copybook-path <dir>]
cobol2py map       <path|dir> [--output <dir>] [--recursive] [--config protected.json]
cobol2py prompt    <path|dir> [--output <file|dir>] [--recursive]
cobol2py test      <path|dir> [--output <dir>] [--recursive] [--timeout N] [--no-execute]
cobol2py --version
```

## What this tool does NOT include

| Not included | What you need to do |
|---|---|
| **EXEC CICS** (online transactions) | Re-implement using Flask, FastAPI, or your transaction framework |
| **EXEC DLI** (IMS database) | Replace with your hierarchical DB or API equivalent |
| **MQ / messaging** | Use `ibm_mq`, `pika` (RabbitMQ), or your message broker |
| **VSAM runtime** | Replace with SQLite, key-value store, or indexed file library |
| **JCL job control** | Replace with cron, Airflow, Prefect, or your scheduler |
| **External CALL targets** | Implement or source the called programs separately |

EXEC SQL is now **generated as runnable DB-API 2.0 Python** with parameterized queries, cursor management, and SQLCODE tracking.

## Contributing

PRs welcome. Run `pytest tests/ -v` before submitting. The project follows a 500 LOC per file guideline.

## License

MIT — use it however you want, commercially or otherwise. No IBM required.
