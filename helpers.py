import collections
import re

QUESTION_PATTERN = re.compile(r"(?P<question>.*) \[(?P<option>.*)\]")
QuestionInfo = collections.namedtuple("QuestionInfo", ["question", "options", "slice"])


def parse_header(header):
    current_question = None
    current_options = []

    questions = []
    options = []
    starts = []
    ends = []
    for col_idx, col in enumerate(header):
        match = QUESTION_PATTERN.match(col)
        if match:
            question = match.group("question")
            option = match.group("option")
            if question != current_question:
                if current_question is not None:
                    ends.append(col_idx)
                    options.append(current_options)
                    current_options = []
                questions.append(question)
                starts.append(col_idx)
                current_question = question
            current_options.append(option)
        else:
            if current_question is not None:
                current_question = None
                ends.append(col_idx)
                options.append(current_options)
                current_options = []

    if current_question is not None:
        ends.append(col_idx + 1)
        options.append(current_options)

    num_questions = len(questions)
    assert len(options) == num_questions, options
    assert len(starts) == num_questions, starts
    assert len(ends) == num_questions, ends

    return [
        QuestionInfo(q, o, slice(s, e))
        for q, o, s, e in zip(questions, options, starts, ends)
    ]
