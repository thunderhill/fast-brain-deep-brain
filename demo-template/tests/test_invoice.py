from src.invoice import invoice_total


def test_plain_total():
    assert invoice_total([(2, 10.0), (1, 5.0)]) == 25.0


def test_discount_then_tax():
    # 100 - 10% = 90, plus 20% tax on 90 = 108
    assert invoice_total([(1, 100.0)], discount_pct=10, tax_pct=20) == 108.0
