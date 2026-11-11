"""The report of an order."""

from pricing import total_price


def render(prices: list[int]) -> str:
    """The report of a list of prices."""
    return f"Total: {total_price(prices)}"
