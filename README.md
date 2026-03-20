# cobol-safe-translator

**Translate COBOL to Python. Zero dependencies. Works offline.**

Produces valid Python from real enterprise COBOL — tested on 5,288 files across 32 projects with 100% syntax validity. Handles the structural heavy lifting of mainframe migration so developers and AI agents can focus on business logic and middleware integration.

Ships with an MCP server for AI coding assistants and a CLI for direct use.

> **This tool generates skeleton code that requires review.** COBOL data semantics (fixed-point arithmetic, string padding, FILE STATUS) are preserved through runtime adapters, but middleware (DB2, CICS, MQ, VSAM) must be wired up separately. Every untranslated construct is marked with `TODO(high)`.

## Why this exists

COBOL runs an estimated **$3 trillion in daily financial transactions**. The engineers who maintain it are retiring, and the systems they built are locked behind proprietary middleware and decades-old documentation.

This tool exists to make those systems readable, translatable, and migratable — without needing an IBM contract or a mainframe consultant. Open source, offline, no vendor dependency.

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

# Triage a project — categorize TODOs for team assignment
cobol2py triage ./src/ --recursive --output ./triage --json

# Translate with middleware interface stubs (DB2/CICS/DLI/MQ)
cobol2py translate ./src/ --recursive --package --stubs
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

The MCP server exposes 7 tools: `translate_cobol`, `analyze_cobol`, `generate_brief`, `list_sensitivities`, `discover_cobol_files`, `translate_directory`, `triage_project`.

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
| **Data attributes** | EXTERNAL, GLOBAL, JUSTIFIED RIGHT, BLANK WHEN ZERO, OCCURS DEPENDING ON (guard), SYNCHRONIZED |
| **Arithmetic** | ADD, SUBTRACT, MULTIPLY, DIVIDE (INTO/BY/GIVING/REMAINDER), COMPUTE (complex expressions), ON SIZE ERROR, ROUNDED (ROUND_HALF_UP) |
| **Control flow** | IF/ELSE (multi-line + inline), EVALUATE TRUE/variable/ALSO with WHEN THRU (range comparison), PERFORM (simple/UNTIL/TIMES/VARYING/THRU), nested loops, GO TO (method call + return, ALTER dynamic dispatch), GO TO DEPENDING ON, EXIT PERFORM |
| **String ops** | STRING (DELIMITED BY, WITH POINTER), UNSTRING (multi-delimiter, WITH POINTER, TALLYING), INSPECT (TALLYING/REPLACING/CONVERTING with BEFORE/AFTER INITIAL), MOVE (simple/ALL/CORRESPONDING/FUNCTION/group-level) |
| **Table ops** | SEARCH/SEARCH ALL, SORT/MERGE (USING/GIVING, INPUT/OUTPUT PROCEDURE), RELEASE, RETURN |
| **File I/O** | OPEN (INPUT/OUTPUT/EXTEND/I-O), CLOSE, READ (INTO + AT END/NOT AT END body), WRITE (FROM + AFTER/BEFORE ADVANCING), REWRITE, DELETE, START (KEY IS) |
| **FILE STATUS** | Tracked on FileAdapter ("00"/"10"/"35"/"30"), auto-updated after every I/O operation |
| **Report Writer** | RD, TYPE IS, LINE/COLUMN, SOURCE, SUM, GROUP INDICATE, INITIATE, GENERATE, TERMINATE |
| **Screen Section** | LINE, COL, PIC, VALUE, USING, FROM, TO, BLANK SCREEN, display attributes, ACCEPT/DISPLAY with screen names |
| **Intrinsics** | 41 FUNCTION intrinsics: LENGTH, NUMVAL, UPPER-CASE, LOWER-CASE, REVERSE, TRIM, MAX, MIN, MOD, ABS, SQRT, LOG, SIN, COS, CURRENT-DATE, RANDOM, MEAN, MEDIAN, FACTORIAL, SIGN, INTEGER-OF-DATE, DATE-OF-INTEGER, CONCATENATE, TEST-NUMVAL, PI, E, and more |
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

**Corpus validation: 5,288/5,288 files produce valid Python (100.00%)** across 32 test projects including NIST CCVS85 conformance suite (459 files), IBM CICS banking, enterprise DB2, French government tax code, GnuCOBOL test suite, AS/400 ILE, COBOL-in-24-Hours (118 files), and a Minecraft server written in COBOL.

## Test suite

```bash
pytest tests/ -v
# 1,033 tests covering parser, analyzer, mapper, conditions, blocks, SEARCH,
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
  preprocessor.py          — COPY resolution (recursive), EXEC block extraction
  line_preprocessor.py     — Fixed/free format line continuation handling
  analyzer.py              — Sensitivity detection, dependency extraction, statistics
  mapper.py                — Python code generator (core orchestration)
  mapper_codegen.py        — Code generation mixin (data class, program class, header)
  mapper_verbs.py          — Verb translation mixin (MOVE, GO TO, PERFORM, arithmetic)
  condition_translator.py  — Recursive descent COBOL condition → Python expression
  block_translator.py      — IF/EVALUATE/SEARCH block reconstruction
  evaluate_translator.py   — EVALUATE TRUE/variable/ALSO with WHEN THRU ranges
  statement_translators.py — PERFORM, MOVE, miscellaneous verb dispatch
  arithmetic_translators.py — ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE
  function_translators.py  — 41 FUNCTION intrinsic mappings
  string_translators.py    — STRING, UNSTRING, INSPECT, SET
  file_translators.py      — OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, CALL
  io_translators.py        — ACCEPT, DISPLAY, REWRITE
  sort_translators.py      — SORT, MERGE, RELEASE, RETURN
  report_parser.py         — REPORT SECTION parser
  report_translators.py    — INITIATE, GENERATE, TERMINATE
  screen_parser.py         — SCREEN SECTION parser
  screen_codegen.py        — Screen code generation (ANSI cursor positioning)
  sql_translator.py        — EXEC SQL → DB-API 2.0 Python code generator
  cics_translator.py       — EXEC CICS → Flask/hint translation
  dli_translator.py        — EXEC DLI (IMS database) translation
  exec_block_handler.py    — EXEC block extraction (SQL/CICS/DLI)
  cfg.py                   — Control flow graph (unreachable detection, ALTER)
  adapters.py              — CobolDecimal, CobolString, FileAdapter, GroupView, RedefinesAlias
  indexed_file_adapter.py  — Indexed (VSAM-style) file I/O runtime
  incremental.py           — AST-based + regex-fallback incremental translation
  validation.py            — Runtime import validation (syntax, import, instantiate)
  ebcdic.py                — EBCDIC collation (cp037)
  utils.py                 — Shared utilities (_to_python_name, numeric parsing)
  exporters.py             — Markdown and JSON report exporters
  prompt_generator.py      — LLM translation brief generator
  project_analyzer.py      — Multi-file project analysis and reporting
  test_generator.py        — Automatic test scaffolding for COBOL programs
  batch.py                 — Batch/directory processing
  triage.py                — Batch TODO triage for team assignment
  middleware_stubs.py      — Middleware interface stub generator (DB2/CICS/DLI/MQ)
  cli.py                   — CLI (translate / map / prompt / test / triage)
  cli_test_runner.py       — Interactive test execution engine
  mcp_server.py            — MCP server for AI coding assistants
  py.typed                 — PEP 561 type marker
```

## CLI reference

```
cobol2py translate <path|dir> [--output <dir>] [--recursive] [--validate] [--copybook-path <dir>] [--stubs] [--package]
cobol2py map       <path|dir> [--output <dir>] [--recursive] [--config protected.json]
cobol2py prompt    <path|dir> [--output <file|dir>] [--recursive]
cobol2py test      <path|dir> [--output <dir>] [--recursive] [--timeout N] [--no-execute]
cobol2py triage    <dir>      [--output <dir>] [--recursive] [--json]
cobol2py --version
```

## Team migration workflow

### Project triage

Scan an entire COBOL project and get a categorized TODO report for team assignment:

```bash
cobol2py triage ./cobol-src/ --recursive --output ./triage --json
```

Produces:
- **TRIAGE.md** — Markdown report with work streams (DB2/SQL, CICS, DLI, File I/O, etc.), per-program breakdown, and suggested skills per category
- **triage.json** — Machine-readable triage data for tooling integration
- **stubs/** — Middleware interface stubs (only for middleware the project actually uses)

### Middleware interface stubs

When translating with `--stubs`, the tool generates typed Python interface files for each detected middleware:

| Stub | Generated when | Purpose |
|------|---------------|---------|
| `db2_interface.py` | EXEC SQL detected | DB-API 2.0 connection contract |
| `cics_interface.py` | EXEC CICS detected | Transaction/screen runtime contract |
| `dli_interface.py` | EXEC DLI detected | Hierarchical DB access contract |
| `mq_interface.py` | MQPUT/MQGET detected | Message queue contract |

Each stub is a typed class with `NotImplementedError` methods and docstrings explaining what to replace them with. Multiple developers can work against these contracts in parallel before the middleware is wired up.

## What requires manual wiring

| Generated as hints | What you need to do |
|---|---|
| **EXEC CICS** (online transactions) | Flask template + RESP/RESP2 hints generated; wire to your transaction framework |
| **EXEC DLI** (IMS database) | DLI call structure generated; connect to your hierarchical DB or API |
| **MQ / messaging** | Use `ibm_mq`, `pika` (RabbitMQ), or your message broker |
| **VSAM runtime** | IndexedFileAdapter included; wire to SQLite or your indexed file library |
| **JCL job control** | Replace with cron, Airflow, Prefect, or your scheduler |
| **External CALL targets** | Implement or source the called programs separately |

EXEC SQL is now **generated as runnable DB-API 2.0 Python** with parameterized queries, cursor management, and SQLCODE tracking.

## Contributing

PRs welcome. Run `pytest tests/ -v` before submitting. The project follows a 500 LOC per file guideline.

## License

MIT — use it however you want, commercially or otherwise. No IBM required.
