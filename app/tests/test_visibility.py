import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.visibility import (
    PRIVATE_PLACEHOLDER,
    can_view_description,
    masked_description,
    present_transaction,
)

ME = uuid4()
OTHER = uuid4()


def txn(user_id, is_private=False, description="kopi kenangan"):
    return SimpleNamespace(
        id=uuid4(), envelope_id=uuid4(), user_id=user_id,
        amount=35000, description=description, source="webapp",
        transaction_date="2026-07-01", created_at="2026-07-01T10:00:00",
        is_deleted=False, is_private=is_private,
    )


class TestContractMatrix(unittest.TestCase):
    def test_own_public_visible(self):
        self.assertTrue(can_view_description(ME, txn(ME, is_private=False)))

    def test_own_private_visible(self):
        # Pemilik SELALU melihat transaksinya sendiri penuh.
        self.assertTrue(can_view_description(ME, txn(ME, is_private=True)))

    def test_other_public_visible(self):
        self.assertTrue(can_view_description(ME, txn(OTHER, is_private=False)))

    def test_other_private_hidden(self):
        self.assertFalse(can_view_description(ME, txn(OTHER, is_private=True)))

    def test_uuid_vs_string_viewer_id(self):
        # route bisa mengoper UUID atau str — keduanya harus cocok
        self.assertTrue(can_view_description(str(ME), txn(ME, is_private=True)))


class TestFailClosed(unittest.TestCase):
    def test_viewer_none_hidden(self):
        self.assertFalse(can_view_description(None, txn(OTHER)))

    def test_txn_without_user_id_hidden(self):
        t = txn(OTHER)
        t.user_id = None
        self.assertFalse(can_view_description(ME, t))

    def test_missing_is_private_attr_hidden_for_other(self):
        t = txn(OTHER)
        del t.is_private
        self.assertFalse(can_view_description(ME, t))

    def test_missing_is_private_attr_visible_for_owner(self):
        t = txn(ME)
        del t.is_private
        self.assertTrue(can_view_description(ME, t))


class TestMaskedDescription(unittest.TestCase):
    def test_masked_returns_placeholder(self):
        self.assertEqual(
            masked_description(ME, txn(OTHER, is_private=True)),
            PRIVATE_PLACEHOLDER,
        )

    def test_visible_returns_original(self):
        self.assertEqual(
            masked_description(ME, txn(OTHER, is_private=False)),
            "kopi kenangan",
        )


class TestPresentTransaction(unittest.TestCase):
    def test_private_other_masks_description_keeps_rest(self):
        t = txn(OTHER, is_private=True)
        out = present_transaction(ME, t)
        # Kontrak: nominal, tanggal, amplop, pencatat TETAP terlihat.
        self.assertEqual(out["description"], PRIVATE_PLACEHOLDER)
        self.assertEqual(out["amount"], t.amount)
        self.assertEqual(out["transaction_date"], t.transaction_date)
        self.assertEqual(out["envelope_id"], t.envelope_id)
        self.assertEqual(out["user_id"], t.user_id)
        self.assertTrue(out["is_private"])
        self.assertFalse(out["is_own"])

    def test_own_transaction_full(self):
        t = txn(ME, is_private=True, description="kado ultah istri")
        out = present_transaction(ME, t)
        self.assertEqual(out["description"], "kado ultah istri")
        self.assertTrue(out["is_own"])


if __name__ == "__main__":
    unittest.main()
