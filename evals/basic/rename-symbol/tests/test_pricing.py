from pricing import grand_total


def test_grand_total():
    assert grand_total([2, 3]) == 5
