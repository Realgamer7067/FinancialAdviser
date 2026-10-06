"""Tests for the V3 Phase 06 synthetic source-corpus fixture module
(`app/services/source_corpus_fixtures.py`). Pure fixture/data checks --
no network access, no real documents."""

from app.services.source_corpus_fixtures import (
    SYNTHETIC_ENTITY_MARKER,
    SYNTHETIC_URL_DOMAIN,
    malformed_pdf_bytes,
    oversized_response_generator,
    prompt_injection_attempt_text,
    representative_corpus,
    ssrf_attempt_urls,
)


def test_representative_corpus_size_and_sector_coverage():
    corpus = representative_corpus()
    assert 10 <= len(corpus) <= 15

    sectors = [d.sector for d in corpus]
    assert sectors.count("bank") >= 3
    assert sectors.count("non_financial") >= 3
    assert sectors.count("non_bank_financial") >= 2

    doc_types = {d.doc_type for d in corpus}
    assert doc_types == {
        "filing_excerpt",
        "news_item",
        "factsheet_excerpt",
        "macro_release",
    }


def test_every_entry_is_obviously_synthetic():
    corpus = representative_corpus()
    assert corpus, "corpus must not be empty"
    for doc in corpus:
        assert SYNTHETIC_ENTITY_MARKER in doc.company_or_entity, (
            f"entity {doc.company_or_entity!r} missing synthetic marker"
        )
        assert SYNTHETIC_URL_DOMAIN in doc.url, f"url {doc.url!r} missing fixture domain marker"


def test_numeric_claims_are_findable_in_raw_text():
    corpus = representative_corpus()
    for doc in corpus:
        assert doc.contains_numeric_claims, (
            f"{doc.company_or_entity} has no numeric claims"
        )
        for claim in doc.contains_numeric_claims:
            assert claim["text"] in doc.raw_text, (
                f"claim text {claim['text']!r} not found verbatim in "
                f"{doc.company_or_entity}'s raw_text"
            )


def test_malformed_pdf_bytes_looks_like_pdf_but_is_broken():
    data = malformed_pdf_bytes()
    assert data.startswith(b"%PDF-")
    assert not data.rstrip().endswith(b"%%EOF")
    assert b"xref" not in data
    # Shorter than a plausible minimal valid PDF with proper xref/trailer.
    assert len(data) < 400


def test_oversized_response_generator_deterministic_and_exact_size():
    a = oversized_response_generator(50_000)
    b = oversized_response_generator(50_000)
    assert len(a) == 50_000
    assert a == b


def test_oversized_response_generator_zero_and_small():
    assert oversized_response_generator(0) == b""
    small = oversized_response_generator(5)
    assert len(small) == 5


def test_prompt_injection_attempt_text_contains_obvious_phrase():
    text = prompt_injection_attempt_text()
    assert "IGNORE" in text
    assert "INSTEAD" in text


def test_ssrf_attempt_urls_cover_required_patterns():
    urls = ssrf_attempt_urls()
    assert any(u.startswith("http://127.0.0.1") or "localhost" in u for u in urls)
    assert any(u.startswith("http://127.0.0.1") for u in urls)
    assert any(u.startswith("http://localhost") for u in urls)
    assert any(
        u.startswith("http://10.")
        or u.startswith("http://172.16.")
        or u.startswith("http://192.168.")
        for u in urls
    )
    assert "http://169.254.169.254/" in urls
