from calc import safe_div


def test_regular_division():
    assert safe_div(10, 2) == 5


def test_division_by_zero():
    assert safe_div(10, 0) == 0
