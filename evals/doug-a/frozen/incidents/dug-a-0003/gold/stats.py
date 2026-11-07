def largest(values):
    best = values[0]
    for value in values:
        if value > best:
            best = value
    return best
