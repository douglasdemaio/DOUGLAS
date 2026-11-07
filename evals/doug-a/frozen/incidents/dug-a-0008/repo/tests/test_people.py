from people import sort_by_age


def test_sort_by_age():
    people = [{'name': 'zoe', 'age': 24}, {'name': 'amy', 'age': 31}]
    assert [p['name'] for p in sort_by_age(people)] == ['zoe', 'amy']


def test_ties_by_name():
    people = [{'name': 'bob', 'age': 30}, {'name': 'ann', 'age': 30}]
    assert [p['name'] for p in sort_by_age(people)] == ['ann', 'bob']
