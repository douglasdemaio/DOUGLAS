from tags import append_tag


def test_first_call():
    assert append_tag('a') == ['a']


def test_calls_are_independent():
    assert append_tag('a') == ['a']
    assert append_tag('b') == ['b']
