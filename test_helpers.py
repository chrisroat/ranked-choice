import pytest

from helpers import QuestionInfo, parse_header

PARSE_HEADER_DATA = [
    (["Q0 [A00]"], [("Q0", ["A00"], slice(0, 1))]),
    (["Q0 [A00]", "Q0 [A01]"], [("Q0", ["A00", "A01"], slice(0, 2))]),
    (
        ["Q0 [A00]", "Q0 [A01]", "Q1 [A10]", "Q1 [A11]"],
        [("Q0", ["A00", "A01"], slice(0, 2)), ("Q1", ["A10", "A11"], slice(2, 4))],
    ),
    (["T", "Q0 [A00]", "Q0 [A01]"], [("Q0", ["A00", "A01"], slice(1, 3))]),
    (
        ["T", "Q0 [A00]", "Q0 [A01]", "T", "Q1 [A10]", "Q1 [A11]", "T"],
        [("Q0", ["A00", "A01"], slice(1, 3)), ("Q1", ["A10", "A11"], slice(4, 6))],
    ),
]


@pytest.mark.parametrize("header,expected", PARSE_HEADER_DATA)
def test_parse_header(header, expected):
    assert parse_header(header) == [QuestionInfo(*e) for e in expected]
