# Supported COBOL Subset Reference

This document lists every COBOL construct handled by cobol-safe-translator, with examples and known limitations.

## Divisions

| Division | Support | Notes |
|----------|---------|-------|
| IDENTIFICATION | Full | PROGRAM-ID, AUTHOR extracted |
| ENVIRONMENT | Partial | SELECT/ASSIGN parsed; other clauses ignored |
| DATA | Partial | FILE SECTION, WORKING-STORAGE SECTION; LINKAGE SECTION skipped |
| PROCEDURE | Partial | See verb table below |

## Data Division

### Level Numbers

| Level | Support | Notes |
|-------|---------|-------|
| 01-49 | Supported | Full hierarchy building |
| 66 | Not supported | RENAMES ignored |
| 77 | Parsed | Treated as 01-level |
| 88 | Skipped | Condition names not translated |

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
| OCCURS | Supported | Count extracted; DEPENDING ON not supported |
| REDEFINES | Parsed | Name stored but no logic applied |

## Procedure Division

### Verb Translation Table

| COBOL Verb | Python Translation | Notes |
|------------|-------------------|-------|
| `MOVE x TO y` | `self.data.y.set(x)` | Literal and field-to-field |
| `ADD x TO y` | `self.data.y.add(x)` | |
| `SUBTRACT x FROM y` | `self.data.y.subtract(x)` | |
| `MULTIPLY x BY y` | `self.data.y.multiply(x)` | |
| `DIVIDE x INTO y` | `self.data.y.divide(x)` | |
| `COMPUTE y = expr` | `self.data.y.set(expr)` | Expression needs manual review |
| `DISPLAY items` | `print(items)` | |
| `PERFORM para` | `self.para()` | Simple perform |
| `PERFORM para UNTIL cond` | `while not (cond): self.para()` | Best-effort condition translation |
| `IF condition` | TODO comment | Manual translation required |
| `EVALUATE` | TODO comment | if/elif chain recommended |
| `OPEN INPUT file` | `self.file.open_input()` | |
| `OPEN OUTPUT file` | TODO comment | Write not supported (safety) |
| `CLOSE file` | `self.file.close()` | |
| `READ file` | `self.file.read()` | With EOF detection |
| `WRITE` | TODO comment | Write not supported (safety) |
| `CALL "prog"` | TODO comment | External dependency flagged |
| `STOP RUN` | `return` | |
| `GO TO` | `raise NotImplementedError` | Requires manual restructuring |

### Unsupported Verbs

These emit `# TODO(high)` comments in generated code:

- `STRING` / `UNSTRING` — string manipulation
- `INSPECT` — character inspection/replacement
- `SET` — condition/index setting
- `COPY` / `REPLACE` — copybook expansion (parser error message)
- `SORT` / `MERGE` — file sorting
- `SEARCH` — table searching

## File Handling

- `SELECT/ASSIGN` is parsed and file controls are recorded
- `OPEN INPUT` creates a read-only `FileAdapter`
- `OPEN OUTPUT` / `WRITE` are flagged as TODO (safety restriction)
- `CLOSE` is translated directly
- `READ` with AT END is translated with EOF detection

## Sensitivity Detection

Default patterns (configurable via `protected.json`):

| Pattern | Level | Reason |
|---------|-------|--------|
| SSN | HIGH | Social Security Number |
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

1. **No copybook expansion** — COPY/REPLACE statements are not processed
2. **No GO TO translation** — Emits `raise NotImplementedError`; requires manual restructuring
3. **No WRITE support** — File output is a safety restriction by design
4. **Simplified IF/EVALUATE** — Complex conditions need manual review
5. **No nested programs** — Only single-program files supported
6. **No REDEFINES logic** — Field name stored but no memory overlay modeled
7. **88-level conditions** — Skipped; not translated to boolean checks
8. **OCCURS DEPENDING ON** — Fixed count only; variable-length arrays not supported
9. **Inline PERFORM** — `PERFORM ... END-PERFORM` blocks may not be fully captured
10. **Multi-statement lines** — Complex lines with multiple statements may be parsed as one
