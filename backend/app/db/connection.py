from __future__ import annotations

from collections.abc import Callable, Generator


_connection_factory: Callable[[], object] | None = None


def configure_connection_factory(factory: Callable[[], object]) -> None:
    global _connection_factory
    _connection_factory = factory


def get_db_connection() -> Generator[object, None, None]:
    if _connection_factory is None:
        raise RuntimeError("Database connection factory has not been configured.")

    conn = _connection_factory()
    try:
        yield conn
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()
