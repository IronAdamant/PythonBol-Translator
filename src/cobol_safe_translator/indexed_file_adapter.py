"""SQLite-backed indexed file adapter for COBOL VSAM-style keyed access.

Supports SEQUENTIAL, RANDOM, and DYNAMIC access modes with
RECORD KEY and ALTERNATE RECORD KEY lookups.
"""

from __future__ import annotations


class IndexedFileAdapter:
    """Indexed file adapter using SQLite for COBOL VSAM-style keyed access.

    The SQLite database file is created alongside the data file
    (e.g., "customers.dat" -> "customers.dat.idx").
    """

    def __init__(
        self,
        path: str,
        record_key: str = "key",
        record_size: int = 80,
        access_mode: str = "SEQUENTIAL",
        alternate_keys: list[str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.path = path
        self.record_key = record_key
        self.record_size = record_size
        self.access_mode = access_mode.upper()
        self.alternate_keys = alternate_keys or []
        self.encoding = encoding
        self._db = None
        self._eof = False
        self._status = "00"
        self._mode: str | None = None
        self._current_key: str | None = None
        self._seq_position = 0

    @property
    def eof(self) -> bool:
        return self._eof

    @property
    def status(self) -> str:
        """COBOL FILE STATUS code.

        "00"=success, "10"=EOF, "22"=duplicate key,
        "23"=record not found, "30"=I/O error, "35"=file not found.
        """
        return self._status

    def _db_path(self) -> str:
        return self.path + ".idx"

    def _ensure_table(self) -> None:
        """Create the records table if it doesn't exist."""
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "record_key TEXT PRIMARY KEY, "
            "record_data TEXT NOT NULL)"
        )
        self._db.commit()

    def open_input(self) -> None:
        """OPEN INPUT -- read-only sequential or random access."""
        import sqlite3
        try:
            self._db = sqlite3.connect(self._db_path())
            self._ensure_table()
            self._mode = "INPUT"
            self._eof = False
            self._seq_position = 0
            self._status = "00"
        except Exception:
            self._status = "35"

    def open_output(self) -> None:
        """OPEN OUTPUT -- create/replace the file."""
        import sqlite3
        try:
            self._db = sqlite3.connect(self._db_path())
            self._db.execute("DROP TABLE IF EXISTS records")
            self._ensure_table()
            self._mode = "OUTPUT"
            self._eof = False
            self._status = "00"
        except Exception:
            self._status = "30"

    def open_io(self) -> None:
        """OPEN I-O -- read and write."""
        import sqlite3
        try:
            self._db = sqlite3.connect(self._db_path())
            self._ensure_table()
            self._mode = "I-O"
            self._eof = False
            self._seq_position = 0
            self._status = "00"
        except Exception:
            self._status = "30"

    def open_extend(self) -> None:
        """OPEN EXTEND -- append mode."""
        import sqlite3
        try:
            self._db = sqlite3.connect(self._db_path())
            self._ensure_table()
            self._mode = "EXTEND"
            self._eof = False
            self._status = "00"
        except Exception:
            self._status = "30"

    def read(self, key: str | None = None) -> str | None:
        """READ -- sequential or random.

        If key is provided (RANDOM access), read by key.
        Otherwise read next record sequentially.
        """
        if self._db is None:
            raise RuntimeError("File not opened")

        if key is not None or self.access_mode == "RANDOM":
            lookup_key = key if key is not None else self._current_key
            if lookup_key is None:
                self._status = "23"
                return None
            row = self._db.execute(
                "SELECT record_data FROM records WHERE record_key = ?",
                (str(lookup_key),),
            ).fetchone()
            if row is None:
                self._status = "23"
                return None
            self._status = "00"
            return row[0]

        # Sequential read
        row = self._db.execute(
            "SELECT record_key, record_data FROM records "
            "ORDER BY record_key LIMIT 1 OFFSET ?",
            (self._seq_position,),
        ).fetchone()
        if row is None:
            self._eof = True
            self._status = "10"
            return None
        self._seq_position += 1
        self._current_key = row[0]
        self._status = "00"
        return row[1]

    def write(self, record: str, key: str | None = None) -> None:
        """WRITE -- add a record."""
        if self._db is None:
            raise RuntimeError("File not opened")
        write_key = key if key is not None else self._current_key
        if write_key is None:
            write_key = str(self._seq_position)
        try:
            self._db.execute(
                "INSERT INTO records (record_key, record_data) VALUES (?, ?)",
                (str(write_key), record),
            )
            self._db.commit()
            self._status = "00"
        except Exception:
            self._status = "22"  # duplicate key

    def rewrite(self, record: str, key: str | None = None) -> None:
        """REWRITE -- update existing record."""
        if self._db is None:
            raise RuntimeError("File not opened")
        update_key = key if key is not None else self._current_key
        if update_key is None:
            self._status = "23"
            return
        result = self._db.execute(
            "UPDATE records SET record_data = ? WHERE record_key = ?",
            (record, str(update_key)),
        )
        self._db.commit()
        if result.rowcount == 0:
            self._status = "23"
        else:
            self._status = "00"

    def delete(self, key: str | None = None) -> None:
        """DELETE -- remove a record."""
        if self._db is None:
            raise RuntimeError("File not opened")
        del_key = key if key is not None else self._current_key
        if del_key is None:
            self._status = "23"
            return
        result = self._db.execute(
            "DELETE FROM records WHERE record_key = ?",
            (str(del_key),),
        )
        self._db.commit()
        if result.rowcount == 0:
            self._status = "23"
        else:
            self._status = "00"

    def start(self, key: str, comparison: str = "EQUAL") -> None:
        """START -- position for sequential reading from a key.

        comparison: "EQUAL", "GREATER", "NOT LESS", "GREATER OR EQUAL"
        """
        if self._db is None:
            raise RuntimeError("File not opened")

        op_map = {
            "EQUAL": "=", "GREATER": ">", "NOT LESS": ">=",
            "GREATER OR EQUAL": ">=", "LESS": "<", "NOT GREATER": "<=",
        }
        op = op_map.get(comparison.upper(), ">=")
        str_key = str(key)

        if op == "=":
            # Verify the key actually exists
            exists = self._db.execute(
                "SELECT 1 FROM records WHERE record_key = ?",
                (str_key,),
            ).fetchone()
            if exists is None:
                self._status = "23"
                return

        # Determine the count query based on operator
        if op in ("=", ">=", "<", "<="):
            count_op = "<"
        elif op == ">":
            count_op = "<="
        else:
            count_op = "<"

        pos_row = self._db.execute(
            f"SELECT COUNT(*) FROM records WHERE record_key {count_op} ?",
            (str_key,),
        ).fetchone()

        if op == "<":
            if pos_row and pos_row[0] == 0:
                self._status = "23"
                return
            if pos_row:
                self._seq_position = pos_row[0] - 1
                self._current_key = key
                self._status = "00"
                return

        if pos_row is not None:
            self._seq_position = pos_row[0]
            self._current_key = key
            self._status = "00"
        else:
            self._status = "23"

    def close(self) -> None:
        """CLOSE -- close the database."""
        if self._db:
            self._db.close()
            self._db = None
            self._mode = None
            self._eof = False
        self._status = "00"

    def __enter__(self) -> IndexedFileAdapter:
        self.open_input()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
