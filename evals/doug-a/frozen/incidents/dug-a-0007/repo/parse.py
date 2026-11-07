def parse_int(text):
    try:
        return int(text)
    except TypeError:
        return None
