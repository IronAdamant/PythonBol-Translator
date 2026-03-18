# Supported COBOL Subset Reference

This document lists every COBOL construct handled by cobol-safe-translator, with examples and known limitations.

> [!IMPORTANT]
> **This tool translates COBOL language constructs to Python.** It does not translate or provide runtime infrastructure such as CICS transaction processing, DB2/SQL database access, IMS/DLI, MQ messaging, VSAM file systems, or JCL job control. These are stripped from the source and replaced with `TODO(high)` hints indicating what Python libraries or services are needed as replacements.
>
> The generated code is a **migration accelerator** — it handles the heavy lifting of converting COBOL syntax, data structures, and procedure logic to Python, but the middleware and platform integrations must be implemented separately using appropriate Python libraries (e.g. SQLAlchemy for DB2, Flask/FastAPI for CICS, ibm_mq for MQ).
>
> **All untranslated constructs are marked with `TODO(high)`.** Review every marker before production use.

> **Known parser limitation:** Statements that span multiple physical COBOL lines (without a column-7 continuation `-`) are not joined by the parser. Each physical line is treated as a separate statement. As a result, a DIVIDE or MULTIPLY whose `GIVING` clause is on the next line will produce two separate statements instead of one complete translation. Write all statement clauses on a single line (or use the column-7 `-` continuation character) to get the best translation results.

## Source Format

| Format | Support | Notes |
|--------|---------|-------|
| Fixed-format (cols 1-6, 7, 8-72) | Full | Auto-detected; standard mainframe layout |
| Free-format (GnuCOBOL, Micro Focus) | Supported | Auto-detected; `*>` comments, no column limits |

The parser auto-detects whether source uses fixed-format or free-format COBOL by examining the first 80 lines. Free-format files use `*>` for comments (anywhere on line), have no sequence numbers in columns 1-6, and have no column 72 limit.

## Divisions

| Division | Support | Notes |
|----------|---------|-------|
| IDENTIFICATION | Full | PROGRAM-ID, AUTHOR extracted |
| ENVIRONMENT | Partial | SELECT/ASSIGN parsed; other clauses ignored |
| DATA | Partial | FILE SECTION, WORKING-STORAGE SECTION, LINKAGE SECTION (parsed and stored) |
| PROCEDURE | Partial | See verb table below |

## Data Division

### Level Numbers

| Level | Support | Notes |
|-------|---------|-------|
| 01-49 | Supported | Full hierarchy building |
| 66 | Not supported | RENAMES ignored |
| 77 | Parsed | Root-level standalone item (never nested under groups) |
| 88 | Supported | Condition names parsed; used in SET TO TRUE and condition translation |

### PIC Clauses

| PIC Pattern | Example | Category | Supported |
|-------------|---------|----------|-----------|
| `9(n)` | `PIC 9(5)` | NUMERIC | Yes |
| `X(n)` | `PIC X(30)` | ALPHANUMERIC | Yes |
| `A(n)` | `PIC A(10)` | ALPHABETIC | Yes |
| `S9(n)` | `PIC S9(7)` | SIGNED NUMERIC | Yes |
| `9(n)V9(n)` | `PIC 9(5)V99` | NUMERIC w/ implied decimal | Yes |
| `Z(n)9` | `PIC ZZZ,ZZ9.99` | EDITED | Yes (classified, not fully modeled) |

**Expansion:** `9(5)` is expanded to `99999`. Mixed patterns like `S9(7)V99` are fully expanded.

### Other Data Clauses

| Clause | Support | Notes |
|--------|---------|-------|
| VALUE | Supported | Initial value extracted |
| OCCURS | Partial | Fixed count extracted; DEPENDING ON clauses ignored |
| REDEFINES | Parsed | Name stored but no logic applied |

## Procedure Division

### Verb Translation Table

| COBOL Verb | Python Translation | Notes |
|------------|-------------------|-------|
| `MOVE x TO y` | `self.data.y.set(x)` | Literal, field-to-field, figurative constants |
| `MOVE ALL "X" TO y` | `self.data.y.set("X" * self.data.y.size)` | Character fill with repeated character |
| `MOVE CORRESPONDING` | Field-matched `.set()` calls | Finds common child names between source and target groups |
| `ADD x TO y` | `self.data.y.add(x)` | Supports GIVING clause |
| `SUBTRACT x FROM y` | `self.data.y.subtract(x)` | Supports GIVING clause |
| `MULTIPLY x BY y` | `self.data.y.multiply(x)` | Supports GIVING clause |
| `DIVIDE x INTO y` | `self.data.y.divide(x)` | Supports GIVING; REMAINDER emits TODO |
| `DIVIDE x BY y GIVING z` | `self.data.z.set(x / y)` | BY form (x is dividend) |
| `COMPUTE y = expr` | `self.data.y.set(expr)` | Expression needs manual review; LENGTH OF translated to `len()` |
| `DISPLAY items` | `print(items)` | `WITH NO ADVANCING` -> `end=''` |
| `PERFORM para` | `self.para()` | Simple perform |
| `PERFORM para N TIMES` | `for _ in range(N): self.para()` | Literal or variable count |
| `PERFORM para UNTIL cond` | `while not (cond): self.para()` | Best-effort condition translation |
| `PERFORM para THRU end` | Sequential calls to each paragraph in range | Paragraph range resolved from AST; UNTIL after THRU also supported |
| `PERFORM para VARYING` | `while not (cond): self.para()` | Single-variable FROM/BY/UNTIL translated; multi-VARYING falls back to TODO |
| `INITIALIZE x` | Commented-out `.set(0)` | Numeric/alphanumeric reset |
| `IF condition` | `if cond:` / `else:` | Multi-line: full block translation; inline: condition, body, and ELSE translated |
| `EVALUATE TRUE` | `if`/`elif`/`else` chain | WHEN conditions translated; WHEN OTHER -> else; fall-through merged as OR |
| `EVALUATE variable` | `if subj == val:` chain | Equality comparisons; WHEN OTHER -> else; WHEN x OR y supported |
| `EVALUATE ALSO` | `if cond1 and cond2:` chain | Multi-subject EVALUATE with per-subject conditions; ANY matches all |
| `STRING` | `target.set(src1 + src2)` | DELIMITED BY SIZE and literal delimiters; WITH POINTER emits TODO |
| `UNSTRING` | `str.split()` into targets | Single and multiple delimiters (re.split for multi); TALLYING emits TODO |
| `INSPECT` | `str.count()` / `str.replace()` | TALLYING (ALL/LEADING/CHARACTERS), REPLACING (ALL/LEADING/FIRST); CONVERTING emits TODO |
| `SET flag TO TRUE` | `self.data.parent.set(val)` | 88-level condition lookup sets parent field to first value |
| `SET idx UP/DOWN BY n` | `self.data.idx.add(n)` / `.subtract(n)` | Index increment/decrement |
| `SET idx TO value` | `self.data.idx.set(value)` | Index assignment |
| `ACCEPT var` | `self.data.var.set(input())` | Plain user input |
| `ACCEPT var FROM DATE` | `datetime.now().strftime(...)` | DATE, DAY, TIME formats translated |
| `ACCEPT var FROM ENVIRONMENT` | `os.environ.get(...)` | ENVIRONMENT-NAME/VALUE supported |
| `ACCEPT var FROM COMMAND-LINE` | `sys.argv[1:]` | ARGUMENT-NUMBER/VALUE also supported |
| `REWRITE record` | `self.file.write(str(record))` | Approximated as write; FROM clause supported |
| `OPEN INPUT file` | `self.file.open_input()` | |
| `OPEN OUTPUT file` | `self.file.open_output()` | Translated to `open_output()` call |
| `OPEN EXTEND file` | `self.file.open_extend()` | Translated to `open_extend()` call |
| `OPEN I-O file` | `self.file.open_io()` | Translated to `open_io()` call |
| `CLOSE file` | `self.file.close()` | WITH LOCK/NO REWIND keywords filtered |
| `READ file` | `self.file.read()` | With EOF detection |
| `WRITE record` | `self.file.write(str(record))` | FROM clause supported; file name inferred from record name |
| `CALL "prog"` | TODO comment | External dependency flagged with USING args |
| `STOP RUN` | `return` | |
| `GOBACK` | `return` | Returns from current program |
| `EXIT PROGRAM` | `return` | Returns from called program |
| `EXIT PERFORM` | `break` | Exits current PERFORM loop |
| `CONTINUE` | `pass` | |
| `GO TO` | `raise NotImplementedError` | Requires manual restructuring |

### Arithmetic ON SIZE ERROR

All arithmetic verbs (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE) support `ON SIZE ERROR` / `NOT ON SIZE ERROR` clauses. The arithmetic is wrapped in a `try`/`except (OverflowError, ZeroDivisionError)` block with the error/success actions noted as comments.

### Unsupported Verbs

These emit `# TODO(high)` comments in generated code:

- `SORT` / `MERGE` -- file sorting
- `SEARCH` -- table searching
- `FUNCTION` -- intrinsic functions (emits TODO in MOVE FUNCTION and COMPUTE FUNCTION)

## Copybook Handling

- `COPY` statements are resolved by the preprocessor (recursive, up to 10 passes)
- `COPY ... REPLACING` is supported with token substitution
- Copybook search paths are configurable via `--copybook-path`
- `EXEC CICS/SQL/DLI` blocks are stripped with Python-equivalent hint comments (25 patterns)

## File Handling

- `SELECT/ASSIGN` is parsed and file controls are recorded
- `OPEN INPUT` creates a read-only `FileAdapter`
- `OPEN OUTPUT` creates a write `FileAdapter` via `open_output()`
- `OPEN EXTEND` opens for append via `open_extend()`
- `OPEN I-O` opens for read/write via `open_io()`
- `WRITE` translates to `file.write()` with FROM clause support
- `REWRITE` approximated as `file.write()` (in-place update semantics not modeled)
- `CLOSE` is translated directly
- `READ` with AT END is translated with EOF detection

## Sensitivity Detection

Default patterns (configurable via `protected.json`):

| Pattern | Level | Reason |
|---------|-------|--------|
| SSN, SOCIAL-SEC | HIGH | Social Security Number |
| TAX-ID | HIGH | Tax Identifier |
| DOB, BIRTH | HIGH | Date of Birth |
| PASSWORD, PIN | HIGH | Credentials |
| ACCOUNT | MEDIUM | Account number |
| BALANCE | MEDIUM | Financial balance |
| SALARY, WAGE | MEDIUM | Compensation data |
| CREDIT, PAYMENT | MEDIUM | Financial data |
| CUST-, EMP- | LOW | Customer/Employee prefix |
| ADDR, PHONE, EMAIL | LOW | Contact information |

## Known Limitations

1. **No GO TO translation** -- Emits `raise NotImplementedError`; requires manual restructuring
2. **Inline EVALUATE** -- Single-line EVALUATE (all packed in one statement) emits TODO
3. **No nested programs** -- Only single-program files supported
4. **No REDEFINES logic** -- Field name stored but no memory overlay modeled
5. **OCCURS DEPENDING ON** -- Fixed count only; variable-length arrays not supported
6. **Inline PERFORM** -- `PERFORM ... END-PERFORM` blocks may not be fully captured
7. **Multi-statement lines** -- Complex lines with multiple statements may be parsed as one
8. **Free-format edge cases** -- Auto-detected and supported, but complex free-format patterns (hex literals like `X"0A"`, inline PERFORM with multi-line conditions) may produce invalid Python
9. **Multi-VARYING** -- Nested VARYING loops (multiple loop variables) fall back to TODO
10. **INSPECT CONVERTING** -- Emits TODO; TALLYING and REPLACING are translated
11. **EVALUATE WHEN THRU/THROUGH** -- Range comparisons in WHEN clauses emit TODO
12. **SET TO FALSE** -- Non-standard extension; emits TODO
