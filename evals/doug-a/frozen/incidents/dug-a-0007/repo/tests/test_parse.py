from parse import parse_int


def test_valid():
    assert parse_int('42') == 42


def test_invalid():
    assert parse_int('nope') is None
