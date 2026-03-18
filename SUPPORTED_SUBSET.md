# Supported COBOL Subset Reference

This document lists every COBOL construct handled by cobol-safe-translator, with examples and known limitations.

> [!IMPORTANT]
> **This tool translates COBOL language constructs to Python.** It does not translate or provide runtime infrastructure such as CICS transaction processing, DB2/SQL database access, IMS/DLI, MQ messaging, VSAM file systems, or JCL job control. These are stripped from the source and replaced with `TODO(high)` hints indicating what Python libraries or services are needed as replacements.
>
> **All untranslated constructs are marked with `TODO(high)`.** Review every marker before production use.

## Source Format

| Format | Support | Notes |
|--------|---------|-------|
| Fixed-format (cols 1-6, 7, 8-72, 73-80) | Full | Auto-detected; sequence numbers and identification area stripped |
| Free-format (GnuCOBOL, Micro Focus) | Full | Auto-detected; `*>` comments, no column limits, `>>` directives handled |

The parser auto-detects format by examining the first 80 lines. Ambiguous files (no sequence numbers, no col-7 indicators) default to free-format to avoid stripping code past column 72.

## Divisions

| Division | Support | Notes |
|----------|---------|-------|
| IDENTIFICATION | Full | PROGRAM-ID, AUTHOR extracted |
| ENVIRONMENT | Partial | SELECT/ASSIGN parsed; other clauses ignored |
| DATA | Full | WORKING-STORAGE, FILE SECTION, LINKAGE SECTION, REPORT SECTION |
| PROCEDURE | Full | See verb table below |

## Data Division

### Level Numbers

| Level | Support | Notes |
|-------|---------|-------|
| 01-49 | Full | Full hierarchy building with group/elementary detection |
| 66 | Not supported | RENAMES ignored |
| 77 | Full | Root-level standalone item |
| 88 | Full | Condition names parsed; used in SET TO TRUE, IF conditions, EVALUATE |

### PIC Clauses

| PIC Pattern | Example | Category | Supported |
|-------------|---------|----------|-----------|
| `9(n)` | `PIC 9(5)` | NUMERIC | Yes |
| `X(n)` | `PIC X(30)` | ALPHANUMERIC | Yes |
| `A(n)` | `PIC A(10)` | ALPHABETIC | Yes |
| `S9(n)` | `PIC S9(7)` | SIGNED NUMERIC | Yes |
| `9(n)V9(n)` | `PIC 9(5)V99` | NUMERIC w/ implied decimal | Yes |
| `Z(n)9` | `PIC ZZZ,ZZ9.99` | EDITED | Yes |

### Other Data Clauses

| Clause | Support | Notes |
|--------|---------|-------|
| VALUE | Full | Initial value extracted, figurative constants resolved |
| OCCURS | Full | Fixed count; multi-dimensional subscripts with chained `[i][j]` indexing |
| OCCURS DEPENDING ON | Partial | Fixed count extracted; variable-length not modeled |
| REDEFINES | Parsed | Name stored but no memory overlay modeled |

### REPORT SECTION

| Clause | Support | Notes |
|--------|---------|-------|
| RD (Report Description) | Full | CONTROLS, PAGE LIMIT, HEADING, FIRST/LAST DETAIL, FOOTING |
| TYPE IS | Full | REPORT HEADING, PAGE HEADING, DETAIL, CONTROL HEADING/FOOTING, PAGE/REPORT FOOTING |
| LINE NUMBER | Full | Absolute and PLUS (relative) |
| COLUMN NUMBER | Full | Column positioning for formatted output |
| SOURCE | Full | Data field reference for detail lines |
| SUM | Full | Accumulator fields with automatic summation during GENERATE |
| VALUE | Full | Literal text in report lines |
| GROUP INDICATE | Parsed | Flagged in report structure |
| NEXT GROUP | Parsed | Flagged in report structure |

## Procedure Division

### Verb Translation Table

| COBOL Verb | Python Translation | Notes |
|------------|-------------------|-------|
| `MOVE x TO y` | `self.data.y.set(x)` | Literal, field-to-field, figurative constants |
| `MOVE ALL "X" TO y` | `self.data.y.set("X" * size)` | Character fill |
| `MOVE CORRESPONDING` | Field-matched `.set()` calls | Finds common child names between groups |
| `ADD x TO y` | `self.data.y.add(x)` | Supports GIVING clause |
| `SUBTRACT x FROM y` | `self.data.y.subtract(x)` | Supports GIVING clause |
| `MULTIPLY x BY y` | `self.data.y.multiply(x)` | Supports GIVING clause |
| `DIVIDE x INTO y` | `self.data.y.divide(x)` | Supports GIVING and REMAINDER |
| `COMPUTE y = expr` | `self.data.y.set(expr)` | Full expression translation with FUNCTION intrinsics |
| `DISPLAY items` | `print(items)` | `WITH NO ADVANCING` → `end=''`; UPON filtered |
| `PERFORM para` | `self.para()` | Simple perform |
| `PERFORM para N TIMES` | `for _ in range(N): self.para()` | Literal or variable count |
| `PERFORM para UNTIL cond` | `while not (cond): self.para()` | Full condition translation |
| `PERFORM para THRU end` | Sequential calls to each paragraph in range | Range resolved from AST |
| `PERFORM VARYING` | `while not (cond):` with init/step | Single-variable FROM/BY/UNTIL |
| `PERFORM VARYING ... AFTER` | Nested `while` loops | Multi-level (2-3 levels) with correct nesting |
| `SEARCH table` | `for _idx in range(...):` with break | Serial search with AT END and WHEN clauses |
| `SEARCH ALL table` | Linear scan (approximated) | Binary search approximated as linear with comment |
| `SORT file ON KEY` | `list.sort(key=...)` | USING/GIVING, INPUT/OUTPUT PROCEDURE |
| `MERGE file ON KEY` | `heapq.merge(...)` | Multiple USING files, GIVING or OUTPUT PROCEDURE |
| `RELEASE record` | `work_list.append(...)` | Within INPUT PROCEDURE |
| `RETURN file` | `sorted_list.pop(0)` | Within OUTPUT PROCEDURE, with AT END |
| `INITIATE report` | Buffer setup + heading output | REPORT WRITER verb |
| `GENERATE detail` | SUM accumulation + formatted detail line | REPORT WRITER verb |
| `TERMINATE report` | Control footings + report footing + write | REPORT WRITER verb |
| `STRING` | `target.set(src1 + src2)` | DELIMITED BY SIZE and literal delimiters |
| `UNSTRING` | `str.split()` into targets | Single and multiple delimiters |
| `INSPECT TALLYING` | `str.count()` | ALL, LEADING, CHARACTERS |
| `INSPECT REPLACING` | `str.replace()` | ALL, LEADING, FIRST |
| `SET flag TO TRUE` | `self.data.parent.set(val)` | 88-level condition lookup |
| `SET idx UP/DOWN BY` | `self.data.idx.add/subtract(n)` | Index increment/decrement |
| `ACCEPT var` | `input()` | Plain user input |
| `ACCEPT FROM DATE/TIME` | `datetime.now().strftime(...)` | DATE, DAY, TIME formats |
| `ACCEPT FROM ENVIRONMENT` | `os.environ.get(...)` | ENVIRONMENT-NAME/VALUE |
| `ACCEPT FROM COMMAND-LINE` | `sys.argv[1:]` | ARGUMENT-NUMBER/VALUE |
| `OPEN INPUT/OUTPUT/EXTEND/I-O` | `self.file.open_*()` | All four modes |
| `CLOSE file` | `self.file.close()` | WITH LOCK/NO REWIND filtered |
| `READ file` | `self.file.read()` | With AT END/EOF detection |
| `WRITE record` | `self.file.write(...)` | FROM clause supported |
| `REWRITE record` | `self.file.write(...)` | Approximated as write |
| `DELETE file` | TODO stub | File record deletion |
| `START file` | TODO stub | File positioning |
| `CALL "prog"` | TODO comment | External dependency flagged |
| `STOP RUN` / `GOBACK` | `return` | |
| `EXIT PROGRAM/PERFORM` | `return` / `break` | |
| `GO TO` | `raise NotImplementedError` | Requires manual restructuring |

### COMPUTE FUNCTION Intrinsics (30+)

| COBOL Function | Python | Notes |
|---------------|--------|-------|
| `FUNCTION LENGTH(x)` | `len(str(x))` | |
| `FUNCTION NUMVAL(x)` | `float(x)` | |
| `FUNCTION NUMVAL-C(x, "$")` | `float(x.replace(',','').replace('$',''))` | Currency stripping |
| `FUNCTION UPPER-CASE(x)` | `str(x).upper()` | |
| `FUNCTION LOWER-CASE(x)` | `str(x).lower()` | |
| `FUNCTION REVERSE(x)` | `str(x)[::-1]` | |
| `FUNCTION TRIM(x)` | `str(x).strip()` | LEADING/TRAILING supported |
| `FUNCTION MAX(a, b, c)` | `max(a, b, c)` | Variadic, comma-separated args |
| `FUNCTION MIN(a, b, c)` | `min(a, b, c)` | Variadic |
| `FUNCTION MOD(a, b)` | `a % b` | |
| `FUNCTION ABS(x)` | `abs(x)` | |
| `FUNCTION SQRT(x)` | `x ** 0.5` | |
| `FUNCTION INTEGER(x)` | `int(x)` | |
| `FUNCTION LOG(x)` / `LOG10(x)` | `math.log(x)` / `math.log10(x)` | |
| `FUNCTION SIN/COS/TAN(x)` | `math.sin/cos/tan(x)` | Also ASIN, ACOS, ATAN |
| `FUNCTION CURRENT-DATE` | `datetime.now().strftime(...)` | 21-char format |
| `FUNCTION RANDOM` | `random.random()` | |
| `FUNCTION ANNUITY(r, n)` | Annuity formula | |
| `FUNCTION MEAN/MEDIAN(...)` | `statistics.mean/median(...)` | Variadic |
| `FUNCTION ORD/CHAR(x)` | `ord(x)` / `chr(x)` | |

Expression arguments are fully supported, including nested `FUNCTION` calls, comma-separated args, and arithmetic inside function arguments.

### Bitwise Operators (in COMPUTE)

| COBOL | Python |
|-------|--------|
| `B-AND` | `&` |
| `B-OR` | `\|` |
| `B-XOR` | `^` |
| `B-NOT` | `~` |
| `B-SHIFT-L` | `<<` |
| `B-SHIFT-R` | `>>` |

### Arithmetic ON SIZE ERROR

All arithmetic verbs support `ON SIZE ERROR` / `NOT ON SIZE ERROR`. The arithmetic is wrapped in `try`/`except (OverflowError, ZeroDivisionError)`.

## Copybook Handling

| Feature | Support |
|---------|---------|
| `COPY copybook` | Full — recursive resolution, up to 10 passes |
| `COPY ... REPLACING` | Full — pseudo-text and token substitution |
| `--copybook-path` | Full — multiple search directories |
| Search order | Source dir → `--copybook-path` dirs → subdirectories |
| Extensions searched | `.cpy`, `.cbl`, `.cob`, `.cobol`, `.copy` (+ uppercase) |
| EXEC CICS/SQL/DLI | Stripped with 25 Python-equivalent hint comments |

## Condition Translation

The two-pass condition translator handles:
- Basic comparisons (=, >, <, >=, <=, NOT)
- Multi-word phrases (NOT GREATER THAN OR EQUAL TO, etc.)
- Compound conditions (AND, OR with implied subjects)
- Abbreviated combined relations (AND NOT =, OR >)
- Class conditions (NUMERIC, ALPHABETIC)
- Sign conditions (POSITIVE, NEGATIVE, ZERO)
- 88-level condition names (single values and THRU ranges)
- Figurative constants (SPACES, ZEROS, HIGH-VALUES, LOW-VALUES)
- Arithmetic in conditions (X + Y > Z)
- Parenthesized groups
- Safety valve: invalid conditions compile-checked and fall back to `True`

## Known Limitations

1. **GO TO** — Emits `raise NotImplementedError`; requires manual restructuring
2. **Nested programs** — Only single-program files supported
3. **REDEFINES logic** — Field name stored but no memory overlay modeled
4. **OCCURS DEPENDING ON** — Fixed count only; variable-length arrays not supported
5. **INSPECT CONVERTING** — Emits TODO; TALLYING and REPLACING are translated
6. **EVALUATE WHEN THRU/THROUGH** — Range comparisons emit placeholder `if True:`
7. **SET TO FALSE** — Non-standard extension; emits TODO
8. **Nested OCCURS data initialization** — Multi-dimensional tables generate TODO for nested list structures; subscript translation works correctly
