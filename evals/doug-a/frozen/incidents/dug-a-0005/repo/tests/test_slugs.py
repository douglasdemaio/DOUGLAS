from slugs import valid_slug


def test_simple():
    assert valid_slug('release-notes')


def test_numbered():
    assert valid_slug('v2-release')


def test_rejects_uppercase():
    assert not valid_slug('Release')
