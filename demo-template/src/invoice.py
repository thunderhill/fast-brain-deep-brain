"""Invoice totals for Northwind Cloud."""


def line_total(quantity: int, unit_price: float) -> float:
    return quantity * unit_price


def invoice_total(lines: list[tuple[int, float]], discount_pct: float = 0.0, tax_pct: float = 0.0) -> float:
    """Sum the lines, apply the discount, then add tax on the discounted amount."""
    subtotal = sum(line_total(q, p) for q, p in lines)
    discounted = subtotal - subtotal * discount_pct
    return round(discounted + subtotal * tax_pct / 100, 2)
