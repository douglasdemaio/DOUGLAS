import re


def valid_slug(value):
    return bool(re.fullmatch(r'[a-z]+', value))
