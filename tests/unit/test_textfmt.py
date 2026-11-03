import pytest

from khataiq.textfmt import inr


@pytest.mark.parametrize("paise, text", [
    (0, "₹0"), (50, "₹0.50"), (9_000_000, "₹90,000"), (12_345_678, "₹1,23,456.78"),
    (1_000_000_000, "₹1,00,00,000"), (-250_000, "-₹2,500"), (99_999, "₹999.99"),
])
def test_inr(paise, text):
    assert inr(paise) == text
