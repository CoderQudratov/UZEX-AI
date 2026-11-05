"""Internal read-only connection lease. This is not an unrestricted query API."""

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import duckdb

from app.core.config import Settings

# Identical settings for every lease: DuckDB may share the database instance internally,
# but every lease has an independent connection/cursor and execution state.
RUNTIME_CONFIG = {
    "enable_external_access": False,
    "autoload_known_extensions": False,
    "autoinstall_known_extensions": False,
    "allow_community_extensions": False,
    "allow_unsigned_extensions": False,
    "threads": 1,
    "memory_limit": "128MB",
    "temp_directory": "",
    "max_temp_directory_size": "0B",
    "lock_configuration": True,
}


class DatabaseUnavailable(RuntimeError):
    """Safe error with no underlying SQL, path, identifier or exception payload."""


class DatabaseBusy(DatabaseUnavailable):
    """The bounded in-process lease capacity is exhausted."""


class DatabaseTimeout(DatabaseUnavailable):
    """An internal read exceeded its fixed execution window."""


class ReadOnlyLease:
    """Small internal connection interface with an absolute deadline.

    No connection/cursor escapes its owning lease. Phase 3 must supply only compiler SQL.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, deadline: float):
        self._connection = connection
        self._deadline = deadline

    def _check_deadline(self):
        if time.monotonic() >= self._deadline:
            raise DatabaseTimeout("Database time budget exceeded")

    def execute(self, sql: str, parameters=None):
        self._check_deadline()
        self._connection.execute(sql, parameters or [])
        self._check_deadline()
        return self

    def fetchone(self):
        self._check_deadline()
        return self._connection.fetchone()

    def fetchmany(self, size=4096):
        self._check_deadline()
        return self._connection.fetchmany(size)

    def fetchall(self):
        self._check_deadline()
        return self._connection.fetchall()


class ReadOnlyWarehouse:
    """Create once per process; reuses safe, initialized read-only connection leases.

    The path comes only from trusted deployment settings. A future deterministic compiler
    owns all SQL; user/LLM text must never be passed directly to the returned connection.
    """

    def __init__(self, settings: Settings, *, query_budget_seconds: float = 5):
        if not math.isfinite(query_budget_seconds) or not 0 < query_budget_seconds <= 30:
            raise ValueError("Invalid database time budget")
        self._query_budget_seconds = query_budget_seconds
        self._path = settings.database_path
        self._max_capacity = settings.max_concurrent_queries
        import queue

        self._pool: queue.Queue[duckdb.DuckDBPyConnection] = queue.Queue(maxsize=self._max_capacity)
        self._created = 0
        self._lock = threading.Lock()

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        try:
            path: Path = self._path.resolve(strict=True)
            if not path.is_file():
                raise DatabaseUnavailable("Prepared database is unavailable")
        except (FileNotFoundError, OSError):
            raise DatabaseUnavailable("Prepared database is unavailable") from None
        try:
            conn = duckdb.connect(str(path), read_only=True, config=RUNTIME_CONFIG)
            if conn.execute("SELECT current_setting('enable_logging')::BOOLEAN").fetchone()[0]:
                conn.close()
                raise DatabaseUnavailable("Database logging policy is invalid")
            return conn
        except duckdb.Error as err:
            raise DatabaseUnavailable("Prepared database is unavailable") from err

    @contextmanager
    def connection(self) -> Iterator[ReadOnlyLease]:
        import queue

        conn = None
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._max_capacity:
                    conn = self._create_connection()
                    self._created += 1
        if conn is None:
            try:
                conn = self._pool.get(timeout=1)
            except queue.Empty:
                raise DatabaseBusy("Database capacity is temporarily exhausted") from None

        timer = None
        deadline = time.monotonic() + self._query_budget_seconds
        interrupted = False
        try:
            timer = threading.Timer(self._query_budget_seconds, conn.interrupt)
            timer.daemon = True
            timer.start()
            yield ReadOnlyLease(conn, deadline)
        except duckdb.InterruptException:
            interrupted = True
            if deadline is not None and time.monotonic() >= deadline:
                raise DatabaseTimeout("Database time budget exceeded") from None
            raise DatabaseUnavailable("Database operation could not be completed") from None
        except (OSError, duckdb.Error):
            interrupted = True
            raise DatabaseUnavailable("Database operation could not be completed") from None
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if interrupted:
                with suppress(Exception):
                    conn.close()
                with self._lock:
                    self._created -= 1
            else:
                self._pool.put(conn)

    def close(self) -> None:
        while not self._pool.empty():
            with suppress(Exception):
                self._pool.get_nowait().close()
