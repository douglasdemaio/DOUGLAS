from slices import last_n


def test_last_two():
    assert last_n([1, 2, 3], 2) == [2, 3]


def test_last_three():
    assert last_n(['a', 'b', 'c', 'd'], 3) == ['b', 'c', 'd']
