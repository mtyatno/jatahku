"""build_allocation_recommendation response-shape guard (Plan B2 §6b)."""
import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.advisor.allocation import build_allocation_recommendation


class AllocationResponsePurposeTests(unittest.TestCase):
    def test_items_include_purpose(self):
        env = SimpleNamespace(
            id="e1", name="Makan", emoji="🍔", purpose="expense",
            budget_amount=Decimal("0"), is_locked=False,
        )
        fake_context = {
            "envelopes": [env],
            "stats": {"e1": [
                {"allocated": Decimal("0"), "spent": Decimal("0"), "reserved": Decimal("0"),
                 "rollover": Decimal("0"), "transaction_count": 0},
            ]},
        }
        with patch(
            "app.services.advisor.allocation.load_advisor_context",
            new=AsyncMock(return_value=fake_context),
        ):
            result = asyncio.run(build_allocation_recommendation(SimpleNamespace(id="u1"), Decimal("1000000"), db=None))
        self.assertTrue(result["items"])
        self.assertEqual(result["items"][0]["purpose"], "expense")
        self.assertIn("confidence", result)
        self.assertIsInstance(result["confidence"], str)
        self.assertIsInstance(result["confidence_reasons"], list)


if __name__ == "__main__":
    unittest.main()
