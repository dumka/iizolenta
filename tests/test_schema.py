import pytest

from izolenta.schema import Skip, Summary, ValidationError, validate_summary

PARAGRAPH = "Компания представила новую модель, которая работает быстрее и стоит дешевле предыдущей."


def ok(**overrides):
    raw = {
        "id": "abc123",
        "status": "ok",
        "category": "ai",
        "importance": 2,
        "title": "OpenAI выпустила GPT-7",
        "lead": "Новая модель вдвое быстрее и заметно дешевле для разработчиков.",
        "body": [PARAGRAPH, PARAGRAPH, PARAGRAPH],
    }
    raw.update(overrides)
    return raw


def reasons(raw) -> str:
    with pytest.raises(ValidationError) as info:
        validate_summary(raw)
    return " | ".join(info.value.reasons)


def test_valid_ok_summary_accepted_and_normalized():
    result = validate_summary(
        ok(
            title="  OpenAI   выпустила\nGPT-7 ",
            body=[PARAGRAPH + "\n  Вторая строка абзаца.", PARAGRAPH, PARAGRAPH],
        )
    )
    assert isinstance(result, Summary)
    assert result.title == "OpenAI выпустила GPT-7"
    assert result.body[0] == PARAGRAPH + " Вторая строка абзаца."
    assert (result.id, result.category, result.importance) == ("abc123", "ai", 2)


def test_valid_skip_accepted():
    result = validate_summary({"id": "abc123", "status": "skip", "reason": "не про AI/IT"})
    assert result == Skip(id="abc123", reason="не про AI/IT")


def test_unknown_category_rejected():
    assert "category" in reasons(ok(category="hardware"))


@pytest.mark.parametrize("value", [0, 4, "2", True, None])
def test_importance_out_of_range_or_not_int_rejected(value):
    assert "importance" in reasons(ok(importance=value))


@pytest.mark.parametrize("count", [2, 6])
def test_body_with_2_or_6_paragraphs_rejected(count):
    assert "body" in reasons(ok(body=[PARAGRAPH] * count))


def test_body_not_a_list_rejected():
    assert "body" in reasons(ok(body=PARAGRAPH))


def test_short_paragraph_rejected():
    assert "body[1]" in reasons(ok(body=[PARAGRAPH, "Коротко.", PARAGRAPH]))


def test_untranslated_english_title_rejected():
    assert "title" in reasons(ok(title="OpenAI ships GPT-7 with a new API"))


def test_untranslated_english_paragraph_rejected():
    english = "The company released a new model that is faster and cheaper than before."
    assert "body[2]" in reasons(ok(body=[PARAGRAPH, PARAGRAPH, english]))


def test_html_in_text_rejected():
    assert "lead" in reasons(ok(lead="Новая модель <b>вдвое</b> быстрее и дешевле для всех."))


def test_too_long_title_rejected():
    assert "title" in reasons(ok(title="Заголовок " * 30))


def test_empty_skip_reason_rejected():
    assert "reason" in reasons({"id": "abc123", "status": "skip", "reason": "   "})


def test_unknown_status_rejected():
    assert "status" in reasons(ok(status="done"))


def test_non_string_id_rejected():
    assert "id" in reasons(ok(id=123))


def test_non_dict_entry_rejected():
    assert "object" in reasons(["not", "a", "dict"])


def test_all_errors_reported_together():
    with pytest.raises(ValidationError) as info:
        validate_summary(ok(category="x", importance=9, title="English title only"))
    text = " | ".join(info.value.reasons)
    assert "category" in text and "importance" in text and "title" in text
    assert len(info.value.reasons) == 3


# posts from X

from izolenta.schema import PostSummary, validate_post  # noqa: E402

POST_TEXT = "Карпаты пишет, что модели неплохо знают географию: достаточно спросить координаты."


def test_valid_post_ok_keeps_paragraphs():
    result = validate_post({"id": "x:123", "status": "ok", "text": "  Первый   абзац поста про модели.\n\n Второй\nабзац с выводом. "})
    assert result == PostSummary(id="x:123", text="Первый абзац поста про модели.\n\nВторой абзац с выводом.")


@pytest.mark.parametrize(
    "text, field",
    [
        ("Коротко.", "text"),
        ("Слово " * 130, "text"),
        ("Models know geography surprisingly well, just ask them.", "text"),
        ("Смотрите <a href='x'>ссылку</a> на исследование про модели.", "text"),
        ("\n\n".join(["Абзац про модели номер один."] * 4), "text"),
    ],
)
def test_post_too_long_or_untranslated_rejected(text, field):
    with pytest.raises(ValidationError) as info:
        validate_post({"id": "x:1", "status": "ok", "text": text})
    assert any(field in reason for reason in info.value.reasons)


@pytest.mark.parametrize("post_id", ["123", "x:", "x:12a", "92be971aec513c1f", 5])
def test_post_id_without_x_prefix_rejected(post_id):
    with pytest.raises(ValidationError) as info:
        validate_post({"id": post_id, "status": "ok", "text": POST_TEXT})
    assert any("id" in reason for reason in info.value.reasons)


def test_post_skip_accepted():
    assert validate_post({"id": "x:9", "status": "skip", "reason": "личное"}) == Skip(id="x:9", reason="личное")


# Hacker News discussions

from izolenta.schema import DiscussionSummary, validate_discussion  # noqa: E402

DISCUSSION_SUMMARY = (
    "Участники спорят, можно ли доверять моделям в математических доказательствах. "
    "Большинство сходится на том, что без формальной проверки результатам верить рано."
)


def test_valid_discussion_accepted():
    result = validate_discussion({"id": "hn:123", "status": "ok", "title": "Математики спорят о доказательствах ИИ", "summary": DISCUSSION_SUMMARY})
    assert result == DiscussionSummary(id="hn:123", title="Математики спорят о доказательствах ИИ", summary=DISCUSSION_SUMMARY)


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"summary": "Коротко."}, "summary"),
        ({"summary": "People argue about whether models can be trusted with proofs at all here."}, "summary"),
        ({"summary": DISCUSSION_SUMMARY + "\n\n" + DISCUSSION_SUMMARY}, "summary"),
        ({"title": "English title only here"}, "title"),
        ({"id": "x:123"}, "id"),
    ],
)
def test_invalid_discussion_rejected(overrides, field):
    raw = {"id": "hn:1", "status": "ok", "title": "Заголовок обсуждения на HN", "summary": DISCUSSION_SUMMARY, **overrides}
    with pytest.raises(ValidationError) as info:
        validate_discussion(raw)
    assert any(field in reason for reason in info.value.reasons)


def test_discussion_skip_accepted():
    assert validate_discussion({"id": "hn:5", "status": "skip", "reason": "политика"}) == Skip(id="hn:5", reason="политика")
