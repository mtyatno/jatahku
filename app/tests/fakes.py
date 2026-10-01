"""Test doubles bersama untuk route/service async yang memanggil db.execute().

FakeResult meniru bentuk hasil SQLAlchemy yang dipakai kode app:
scalar(), scalar_one_or_none(), scalar_one(), scalars().all(), all().
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql


class FakeResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows if rows is not None else value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)

    def all(self):
        return self._rows


def db_with(*results):
    """db mock: db.execute() mengembalikan `results` berurutan."""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def sql(stmt) -> str:
    """Render statement SQLAlchemy ke SQL Postgres (untuk assert klausa WHERE)."""
    return str(stmt.compile(dialect=postgresql.dialect()))


def executed_sql(db) -> list[str]:
    return [sql(c.args[0]) for c in db.execute.call_args_list]
