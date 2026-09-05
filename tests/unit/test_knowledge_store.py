from app.knowledge.store import KnowledgeStore


def test_search_finds_the_right_topic_for_a_clear_english_question() -> None:
    store = KnowledgeStore()

    result = store.search("How do I get a salary certificate?", "en", top_k=1)[0]

    assert result.chunk.topic == "salary_certificate"
    assert result.chunk.language == "en"


def test_search_finds_the_right_topic_for_a_clear_arabic_question() -> None:
    store = KnowledgeStore()

    result = store.search("كيف أحصل على شهادة الراتب؟", "ar", top_k=1)[0]

    assert result.chunk.topic == "salary_certificate"
    assert result.chunk.language == "ar"


def test_search_only_returns_chunks_in_the_requested_language() -> None:
    store = KnowledgeStore()

    results = store.search("salary certificate", "ar", top_k=5)

    assert all(r.chunk.language == "ar" for r in results)


def test_two_unrelated_questions_score_near_zero() -> None:
    # These are the "no matching SOP" cases this corpus is meant to
    # demonstrate -- chosen for having essentially no lexical overlap
    # with any corpus content, not as an adversarial edge case.
    store = KnowledgeStore()

    for question in ("Do we have a parking garage?", "Is there a free shuttle bus?"):
        result = store.search(question, "en", top_k=1)[0]
        assert result.score < 1.0, (question, result.score)


def test_get_chunk_returns_the_parallel_language_rendering() -> None:
    # Sections are paired by position, not by title text: the Arabic
    # corpus files use native-language section titles ("ما هي", not
    # "What It Is"), so a title string could never match across
    # languages -- see the comment on KnowledgeStore._by_topic_index_language.
    store = KnowledgeStore()

    en_chunk = store.get_chunk("salary_certificate", 0, "en")
    ar_chunk = store.get_chunk("salary_certificate", 0, "ar")

    assert en_chunk is not None
    assert ar_chunk is not None
    assert en_chunk.language == "en"
    assert ar_chunk.language == "ar"
    assert en_chunk.section == "What It Is"
    assert ar_chunk.section == "ما هي"


def test_get_chunk_returns_none_for_an_unknown_section() -> None:
    store = KnowledgeStore()

    assert store.get_chunk("salary_certificate", 99, "en") is None


def test_corpus_covers_all_ten_expected_topics_in_both_languages() -> None:
    store = KnowledgeStore()

    expected_topics = {
        "transfer_request",
        "salary_certificate",
        "exit_reentry_visa",
        "housing_allowance",
        "annual_leave_policy",
        "sick_leave_medical_certificate",
        "end_of_service",
        "iqama_renewal",
        "nitaqat_saudization",
        "grievance_procedure",
    }
    topics_by_language: dict[str, set[str]] = {"en": set(), "ar": set()}
    for chunk in store._chunks:
        topics_by_language[chunk.language].add(chunk.topic)

    assert topics_by_language["en"] == expected_topics
    assert topics_by_language["ar"] == expected_topics
