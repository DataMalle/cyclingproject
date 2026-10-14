import pandas as pd
import pytest

from llm import CannotAnswerError, SqlAgent, normalize_question, strip_fences


def test_normalize_question_is_case_and_space_insensitive():
    assert normalize_question("  Vilka   STATIONER har flest resor? ") == "vilka stationer har flest resor?"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("  SELECT 1  ", "SELECT 1"),
    ],
)
def test_strip_fences(raw, expected):
    assert strip_fences(raw) == expected


def test_generate_sql_returns_clean_sql():
    agent = SqlAgent(chat=lambda system, user: "```sql\nSELECT 1\n```")
    assert agent.generate_sql("fråga") == "SELECT 1"


def test_cannot_answer_raises():
    agent = SqlAgent(chat=lambda system, user: "CANNOT_ANSWER")
    with pytest.raises(CannotAnswerError):
        agent.generate_sql("Vad är vädret?")


def test_retry_prompt_contains_previous_sql_and_error():
    seen = {}

    def chat(system, user):
        seen["user"] = user
        return "SELECT 2"

    SqlAgent(chat).generate_sql("fråga", previous_sql="SELECT bad", error="Column not found")
    assert "SELECT bad" in seen["user"] and "Column not found" in seen["user"]


def test_summarize_sends_a_sample_not_everything():
    seen = {}

    def chat(system, user):
        seen["user"] = user
        return "ok"

    df = pd.DataFrame({"n": range(100)})
    assert SqlAgent(chat).summarize("q", "SELECT n", df) == "ok"
    assert "100 rader" in seen["user"] and "29" in seen["user"] and "30" not in seen["user"].split("första 30)")[1]


def test_describe_result_formats_big_numbers_and_precomputes_facts():
    from llm import describe_result

    df = pd.DataFrame({"start_hour": [16, 17, 18], "trips": [47268, 66497, 63577]})
    text = describe_result(df)
    assert "66 497" in text and "66497" not in text  # tusentalsavgränsare
    assert "högst 66 497 (start_hour = 17)" in text
    assert "lägst 47 268 (start_hour = 16)" in text
    assert "summa 177 342" in text


def test_describe_result_handles_empty_and_text_only():
    from llm import describe_result

    assert "inga rader" in describe_result(pd.DataFrame({"a": []}))
    assert "Förräknade fakta" in describe_result(pd.DataFrame({"name": ["x", "y"]}))
