# cobol-safe-translator

**Offline COBOL-to-Python translator that generates Python skeletons and analysis reports.**

> **This tool generates SKELETON code that requires manual review.** It does NOT produce production-ready translations. Generated code may be incomplete, incorrect, or miss critical business logic. **Always verify against the original COBOL source.**

> **Safety guarantee:** This tool NEVER modifies source files, NEVER touches production data, and generated file adapters are READ-ONLY by design.

## Why this exists

COBOL runs an estimated $3 trillion in daily financial transactions. Most of it is maintained by a shrinking pool of specialists, and it's completely opaque to modern developers and LLMs that have never seen a COBOL codebase.

This tool exists to change that. **Open source forever. No IBM lock-in. No cloud upload.**

Run it once against any `.cob`/`.cbl`/`.cobol` file and get:
- A readable Python skeleton with COBOL semantics preserved
- A sensitivity report flagging SSNs, balances, salaries, and other PII
- A token-efficient LLM brief for filling in the remaining TODOs

The goal: make this the obvious first tool any developer or LLM reaches for when inheriting COBOL code.

## Drop it on any project

```bash
pip install cobol-safe-translator        # once, zero runtime dependencies

cobol2py translate PAYROLL.cob           # single file
cobol2py translate ./src/ --output ./out # whole directory
cobol2py translate ./src/ --recursive    # descend into subdirs
```

Cross-platform (Linux, macOS, Windows). Works offline. Never modifies source files.

## Use with LLMs

The `prompt` command generates a compact brief designed for LLM consumption — paragraphs summarized, sensitivities listed, TODOs inventoried, Python skeleton attached:

```bash
# Step 1: generate brief
cobol2py prompt PAYROLL.cob > brief.md

# Step 2: paste brief.md into your LLM and ask it to fill the TODOs
# (Claude, GPT-4, local Ollama — any LLM that reads markdown)

# Step 3: verify the filled-in code
python -c "import ast; ast.parse(open('payroll.py').read()); print('OK')"
```

**Token comparison — BANKACCT.cob (430 lines):**

| Approach | Tokens (approx.) |
|----------|-----------------|
| Raw COBOL source | ~3,400 |
| `cobol2py prompt` brief | ~900 |
| `software-map.json` only | ~600 |

The brief includes only what an LLM needs: structure, sensitivities, TODOs, and the skeleton to fill in.

## Install

```bash
# Runtime — zero external dependencies
pip install -e .

# With dev tools (pytest)
pip install -e ".[dev]"
```

Requires **Python 3.11+**. No pip-installed runtime dependencies.

## Quick Start

Use the wrapper scripts to translate and generate reports in one step:

```bash
# Linux
./run.sh samples/payroll-calc.cob

# macOS (double-click from Finder or run from Terminal)
./run.command samples/payroll-calc.cob

# Windows
run.bat samples\payroll-calc.cob
```

This runs both `cobol2py translate` and `cobol2py map`, writing all output files to `output/<program-name>/`.

## Sample Programs

| File | Lines | Description | Expected Output |
|------|-------|-------------|-----------------|
| `samples/hello.cob` | ~15 | Minimal DISPLAY + ADD program | Clean Python, no TODOs |
| `samples/customer-report.cob` | ~110 | File I/O, EVALUATE, sensitive fields (SSN, BALANCE) | Python with WRITE/CALL TODOs |
| `samples/payroll-calc.cob` | ~200 | Payroll calculator using only supported constructs | Clean Python, minimal TODOs |
| `samples/BANKACCT.cob` | ~430 | Real-world banking system (inspired by [ak55m/cobol-banking-system](https://github.com/ak55m/cobol-banking-system)) | Python with WRITE/STRING/ACCEPT/REWRITE TODOs |

## Usage

### Translate COBOL to Python skeleton

```bash
cobol2py translate samples/hello.cob --output ./translated
```

Produces a Python file with:
- `@dataclass` for WORKING-STORAGE fields using `CobolDecimal`/`CobolString` adapters
- Methods for each COBOL paragraph
- `TODO(high)` comments for unsupported constructs
- `WARNING` comments on sensitive data fields

### Generate analysis reports

```bash
cobol2py map samples/customer-report.cob --output ./report
```

Produces:
- `software-map.md` — Overview, statistics, sensitivity report, Mermaid dependency graph, recommendations
- `software-map.json` — Machine-readable analysis for LLMs and tooling

### Generate LLM translation brief

```bash
cobol2py prompt samples/BANKACCT.cob             # stdout
cobol2py prompt samples/BANKACCT.cob -o brief.md # file
cobol2py prompt ./src/ --output ./briefs/        # batch (one brief per file)
```

### Options

```
cobol2py translate <path|dir> [--output <dir>] [--config protected.json] [--recursive]
cobol2py map <path|dir> [--output <dir>] [--config protected.json] [--recursive]
cobol2py prompt <path|dir> [--output <file|dir>] [--config protected.json] [--recursive]
cobol2py --version
```

### Sensitivity config

Default patterns detect 18 sensitive data categories (SSN, BALANCE, CREDIT, etc.) without any config file. To customize, copy `config/protected.json.example` and pass it via `--config`:

```bash
cp config/protected.json.example protected.json
# Edit protected.json to add/remove patterns
cobol2py translate program.cob --config protected.json
```

Format:

```json
{
    "sensitive_patterns": [
        {"pattern": "SSN", "level": "high", "reason": "Social Security Number"}
    ],
    "exclude_names": ["FILLER"]
}
```

If the config file is malformed or unreadable, the tool warns to stderr and falls back to built-in defaults.

## Supported COBOL subset

See [SUPPORTED_SUBSET.md](SUPPORTED_SUBSET.md) for the full reference.

**Supported:** MOVE, MOVE ALL (emits TODO), ADD, SUBTRACT, MULTIPLY, DIVIDE (INTO and BY forms), COMPUTE, DISPLAY, PERFORM (simple, UNTIL, TIMES with literal or variable count), PERFORM VARYING (single-variable FROM/BY/UNTIL — multi-VARYING falls back to TODO), PERFORM THRU (partial — calls first paragraph + TODO), IF/ELSE (multi-line: full `if`/`else` translation; inline: condition and body translated), EVALUATE TRUE/variable (multi-line: `if`/`elif`/`else` chain; WHEN OTHER → `else`), EVALUATE ALSO (emits TODO), OPEN INPUT (multi-file), CLOSE (filters WITH LOCK keywords), READ (with EOF detection), CALL, STOP RUN, INITIALIZE, PIC clauses (9, X, A, S, V, P, *, /, edited), level numbers (01-49, 77), SELECT/ASSIGN, GIVING clause on arithmetic verbs, ROUNDED/ON SIZE ERROR filtering, figurative constants (ZERO, SPACES, HIGH-VALUES, LOW-VALUES) in MOVE/arithmetic/conditions, MOVE CORRESPONDING (emits TODO), LINKAGE SECTION (parsed), SECTION headers in PROCEDURE DIVISION.

**Not supported (MVP):** COPY/REPLACE, GO TO (emits `NotImplementedError`), WRITE/OPEN OUTPUT (safety restriction), STRING/UNSTRING/INSPECT (emits TODO), ACCEPT/REWRITE (emits TODO with implementation hint), multi-VARYING PERFORM loops, nested programs, 66/88 level semantics, REDEFINES logic, OCCURS DEPENDING ON.

## Running tests

```bash
pytest tests/ -v
# 399 tests covering parser, analyzer, mapper, block_translator, exporters, adapters, CLI, batch, prompt
```

## Project structure

```
src/cobol_safe_translator/
  __init__.py              — Version export
  models.py                — Shared dataclasses (AST, analysis models)
  parser.py                — Regex/state-machine COBOL parser
  analyzer.py              — Sensitivity detection, dependency extraction
  adapters.py              — CobolDecimal, CobolString, FileAdapter (read-only)
  block_translator.py      — IF/EVALUATE block reconstruction from flat stmts
  mapper.py                — AST-to-Python code generator (orchestration)
  statement_translators.py — Individual verb translators
  exporters.py             — Markdown and JSON report exporters
  prompt_generator.py      — LLM translation brief generator
  batch.py                 — Batch/directory processing
  cli.py                   — argparse CLI (translate / map / prompt subcommands)
```

## Documentation

- [SUPPORTED_SUBSET.md](SUPPORTED_SUBSET.md) — Every supported COBOL construct with examples

## License

MIT
