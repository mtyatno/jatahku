"""is_private must survive the behavior cooling period (Plan C1).

A transaction the user marked private that is deferred by cooling must be
private again when confirmed — not silently public. These are mock-based unit
tests of the two service functions; no DB is touched.
"""
import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.behavior import create_pending_transaction, confirm_pending
from app.models.models import PendingTransactionStatus, TransactionSource


def _mock_db():
    """A db whose sync .add captures the added object; async methods are no-ops."""
    db = MagicMock()
    captured = {}
    db.add = MagicMock(side_effect=lambda obj: captured.__setitem__("obj", obj))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db, captured


class CreatePendingPrivacyTests(unittest.TestCase):
    def test_is_private_true_is_stored_on_pending(self):
        db, captured = _mock_db()
        asyncio.run(create_pending_transaction(
            envelope_id=uuid4(), user_id=uuid4(), amount=Decimal("500000"),
            description="beli", source=TransactionSource.telegram,
            cooling_hours=24, is_private=True, db=db,
        ))
        self.assertTrue(captured["obj"].is_private)

    def test_default_is_public(self):
        db, captured = _mock_db()
        asyncio.run(create_pending_transaction(
            envelope_id=uuid4(), user_id=uuid4(), amount=Decimal("1"),
            description="x", source=TransactionSource.telegram, db=db,
        ))
        self.assertFalse(captured["obj"].is_private)


class ConfirmPendingPrivacyTests(unittest.TestCase):
    def _pending(self, is_private):
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return SimpleNamespace(
            id=uuid4(), envelope_id=uuid4(), user_id=uuid4(),
            amount=Decimal("500000"), description="beli",
            source=TransactionSource.telegram,
            status=PendingTransactionStatus.pending,
            confirm_after=past, is_private=is_private,
        )

    def _run_confirm(self, pending):
        db = MagicMock()
        result_obj = MagicMock()
        result_obj.scalar_one_or_none = MagicMock(return_value=pending)
        db.execute = AsyncMock(return_value=result_obj)
        captured = {}
        db.add = MagicMock(side_effect=lambda obj: captured.__setitem__("txn", obj))
        db.commit = AsyncMock()
        out = asyncio.run(confirm_pending(pending.id, db))
        return out, captured

    def test_confirm_preserves_private_flag(self):
        out, captured = self._run_confirm(self._pending(is_private=True))
        self.assertEqual(out["status"], "confirmed")
        self.assertTrue(captured["txn"].is_private)

    def test_confirm_public_stays_public(self):
        out, captured = self._run_confirm(self._pending(is_private=False))
        self.assertEqual(out["status"], "confirmed")
        self.assertFalse(captured["txn"].is_private)


if __name__ == "__main__":
    unittest.main()
