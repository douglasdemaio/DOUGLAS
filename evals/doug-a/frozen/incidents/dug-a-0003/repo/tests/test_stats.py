from stats import largest


def test_largest():
    assert largest([3, 9, 2]) == 9


def test_largest_single():
    assert largest([4]) == 4
