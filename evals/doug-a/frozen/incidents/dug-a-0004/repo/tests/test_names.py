from names import normalize


def test_normalize():
    assert normalize('  ada lovelace ') == 'Ada Lovelace'


def test_none():
    assert normalize(None) == ''
