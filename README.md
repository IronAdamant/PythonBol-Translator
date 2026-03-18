# cobol-safe-translator

**Offline COBOL-to-Python translator that generates Python skeletons and analysis reports.**

**100% syntax-valid output across 4,542 real-world COBOL files from 29 test projects** — including NIST conformance suites, IBM CICS banking, French government tax code, a Minecraft server, DB2 stored procedures, and a Lisp interpreter written in COBOL.

> **This tool generates SKELETON code that requires manual review.** It does NOT produce production-ready translations. Generated code may be incomplete, incorrect, or miss critical business logic. **Always verify against the original COBOL source.**

> **Safety guarantee:** This tool NEVER modifies source files, NEVER touches production data, and generated file adapters are READ-ONLY by design.

> [!CAUTION]
> ### What this tool does — and does not do
>
> **cobol-safe-translator translates COBOL source code into Python.** It handles data divisions, control flow, arithmetic, conditions, file I/O, string operations, SEARCH/SORT/MERGE, REPORT WRITER, 30+ FUNCTION intrinsics, and procedure logic. This is the heavy lifting of COBOL migration — converting the language itself.
>
> **It does NOT translate or provide the surrounding infrastructure.** Specifically:
>
> | Not included | What you need to do |
> |---|---|
> | **EXEC CICS** (transaction processing) | Re-implement using Flask, FastAPI, or your transaction framework |
> | **EXEC SQL / DB2** (database access) | Replace with SQLAlchemy, psycopg2, or your database layer |
> | **EXEC DLI** (IMS database) | Replace with your hierarchical DB or API equivalent |
> | **MQ / messaging** (MQOPEN, MQGET, etc.) | Use `ibm_mq`, `pika` (RabbitMQ), or your message broker client |
> | **VSAM file handling** | Replace with standard file I/O, SQLite, or a key-value store |
> | **JCL job control** | Replace with cron, Airflow, or your job scheduler |
> | **External CALL targets** | Implement or source the called programs separately |
>
> **Every untranslated construct is marked with `TODO(high)` in the generated code.** Search for these markers to find everything that needs manual attention.

## Why this exists

COBOL runs an estimated $3 trillion in daily financial transactions. Most of it is maintained by a shrinking pool of specialists, and it's completely opaque to modern developers and LLMs that have never seen a COBOL codebase.

This tool exists to change that. **Open source forever. No IBM lock-in. No cloud upload.**

Run it once against any `.cob`/`.cbl`/`.cobol` file and get:
- A readable Python skeleton with COBOL semantics preserved
- A sensitivity report flagging SSNs, balances, salaries, and other PII
- A token-efficient LLM brief for filling in the remaining TODOs

## Install

```bash
pip install cobol-safe-translator   # zero runtime dependencies

# Or from source
pip install -e .

# With dev tools (pytest)
pip install -e ".[dev]"
```

Requires **Python 3.11+**. Zero pip-installed runtime dependencies. Cross-platform (Linux, macOS, Windows). Works offline.

## Quick start

```bash
cobol2py translate PAYROLL.cob                    # single file
cobol2py translate ./src/ --output ./out          # whole directory
cobol2py translate ./src/ --recursive             # descend into subdirs
cobol2py translate ./src/ --validate              # syntax + import validation
cobol2py translate ./src/ --copybook-path ./cpy   # specify copybook directories
```

## Use with LLMs

The `prompt` command generates a compact brief designed for LLM consumption:

```bash
cobol2py prompt PAYROLL.cob > brief.md
# Paste brief.md into your LLM and ask it to fill the TODOs
```

**Token comparison — BANKACCT.cob (430 lines):**

| Approach | Tokens (approx.) |
|----------|-----------------|
| Raw COBOL source | ~3,400 |
| `cobol2py prompt` brief | ~900 |
| `software-map.json` only | ~600 |

## Supported COBOL features

### Fully translated
- **Data Division**: PIC clauses (9, X, A, S, V, P, edited), levels 01-49/77, OCCURS (multi-dimensional), 88-level conditions, WORKING-STORAGE, FILE SECTION, LINKAGE SECTION, REPORT SECTION
- **Arithmetic**: ADD, SUBTRACT, MULTIPLY, DIVIDE (INTO/BY/GIVING/REMAINDER), COMPUTE (complex expressions), ON SIZE ERROR wrapping, ROUNDED
- **Control flow**: IF/ELSE (multi-line and inline), EVALUATE TRUE/variable/ALSO (multi-subject), PERFORM (simple, UNTIL, TIMES, VARYING, THRU), PERFORM VARYING with AFTER (multi-level nested loops)
- **String operations**: STRING (DELIMITED BY), UNSTRING (multi-delimiter), INSPECT (TALLYING/REPLACING/CONVERTING), MOVE (simple, ALL, CORRESPONDING)
- **Table operations**: SEARCH/SEARCH ALL (for-loop with AT END/WHEN), SORT/MERGE (USING/GIVING, INPUT/OUTPUT PROCEDURE), RELEASE, RETURN
- **REPORT WRITER**: REPORT SECTION parsing (RD, TYPE IS, LINE/COLUMN, SOURCE, SUM, GROUP INDICATE), INITIATE, GENERATE, TERMINATE
- **FUNCTION intrinsics**: 30+ functions — LENGTH, NUMVAL, UPPER-CASE, LOWER-CASE, REVERSE, TRIM, MAX, MIN, MOD, ABS, SQRT, LOG, LOG10, SIN, COS, INTEGER, ORD, CHAR, CURRENT-DATE, RANDOM, ANNUITY, MEAN, MEDIAN, and more
- **File I/O**: OPEN (INPUT/OUTPUT/EXTEND/I-O), CLOSE, READ (AT END), WRITE (FROM), REWRITE, ACCEPT (FROM DATE/TIME/ENVIRONMENT), DELETE, START
- **Other**: SET (88-level, UP/DOWN BY), GO TO (raises NotImplementedError), EXIT, STOP RUN, GOBACK, CONTINUE, NEXT SENTENCE
- **Preprocessing**: COPY resolution with search paths (`--copybook-path`), COPY REPLACING (pseudo-text), recursive COPY expansion, EXEC CICS/SQL/DLI stripping with 25 Python-equivalent hints
- **Bitwise**: B-AND, B-OR, B-XOR, B-NOT, B-SHIFT-L, B-SHIFT-R
- **Literals**: Hex (X"FF", H'0F'), binary (B"01"), figurative constants, EBCDIC collation (opt-in `--ebcdic`)
- **Format detection**: Auto-detects free-format vs fixed-format COBOL

### Translated as TODO stubs
- GO TO (raises `NotImplementedError` — requires manual restructuring)
- Unknown FUNCTION intrinsics (safe `0` fallback)

## Validation

```bash
# Syntax check + import validation
cobol2py translate program.cob --validate

# The --validate flag performs:
# 1. ast.parse() — syntax check
# 2. compile() — bytecode compilation
# 3. importlib import + Program class instantiation — catches NameError, ImportError
```

**Test results across 29 projects (4,542 COBOL files):**

| Project | Files | Result |
|---------|-------|--------|
| proleap-cobol-parser (NIST + edge cases) | 759 | 100% |
| che-che4z-lsp-for-cobol (Eclipse LSP tests) | 982 | 100% |
| TypeCobol (French enterprise insurance) | 908 | 99.9% |
| opensourcecobol4j (NIST COBOL-85) | 416 | 100% |
| mapa (CICS+DB2+IMS enterprise) | 324 | 100% |
| CobolCraft (Minecraft server) | 206 | 100% |
| Cobol-Projects (MVS/z/OS dual-target) | 164 | 100% |
| 22 more projects | 783 | 100% |
| **Total** | **4,542** | **99.98%** |

## Running tests

```bash
pytest tests/ -v
# 717 tests covering parser, analyzer, mapper, conditions, blocks, SEARCH,
# SORT/MERGE, FUNCTION intrinsics, REPORT WRITER, COPY expansion, adapters,
# CLI, batch, validation, and 33 behavioral end-to-end tests
```

**Behavioral tests** translate COBOL → execute generated Python in subprocess → verify stdout matches expected output. Covers: DISPLAY, arithmetic, MOVE, IF/ELSE, nested IF, PERFORM loops, PERFORM VARYING, PERFORM UNTIL, STRING, INSPECT, EVALUATE, 88-level conditions, COMPUTE expressions, FUNCTION LENGTH/UPPER-CASE, SUBTRACT GIVING, DIVIDE GIVING.

## Project structure

```
src/cobol_safe_translator/
  __init__.py              — Version export
  models.py                — Shared dataclasses (AST, analysis models)
  parser.py                — COBOL parser with free/fixed format detection
  pic_parser.py            — PIC clause parsing
  procedure_parser.py      — PROCEDURE DIVISION statement splitting
  preprocessor.py          — COPY resolution (with search paths), EXEC stripping
  analyzer.py              — Sensitivity detection, dependency extraction
  adapters.py              — CobolDecimal, CobolString, FileAdapter
  mapper.py                — AST-to-Python code generator (orchestration)
  condition_translator.py  — Two-pass COBOL condition → Python expression
  statement_translators.py — Arithmetic, PERFORM, I/O verb translators
  function_translators.py  — COMPUTE FUNCTION intrinsic mapping (30+ functions)
  sort_translators.py      — SORT, MERGE, RELEASE, RETURN
  report_parser.py         — REPORT SECTION parser
  report_translators.py    — INITIATE, GENERATE, TERMINATE
  string_translators.py    — STRING, UNSTRING, INSPECT, SET
  io_translators.py        — ACCEPT, REWRITE, ON SIZE ERROR
  block_translator.py      — IF/EVALUATE/SEARCH block reconstruction
  validation.py            — Runtime import validation
  ebcdic.py                — EBCDIC collation (cp037)
  exporters.py             — Markdown and JSON report exporters
  prompt_generator.py      — LLM translation brief generator
  batch.py                 — Batch/directory processing
  cli.py                   — CLI (translate / map / prompt subcommands)
  mcp_server.py            — MCP server for AI coding assistants
```

## CLI reference

```
cobol2py translate <path|dir> [--output <dir>] [--config protected.json]
                               [--recursive] [--validate] [--copybook-path <dir>]
cobol2py map <path|dir> [--output <dir>] [--config protected.json] [--recursive]
cobol2py prompt <path|dir> [--output <file|dir>] [--config protected.json] [--recursive]
cobol2py --version
```

## License

MIT
