from docx_de_identifier.agents.merge import normalize_person, resolve_candidates
from docx_de_identifier.agents.regex_detect import detect_record
from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import EntityCandidate, EntityType, ParagraphRecord, TextRange


def test_relative_and_elapsed_timestamps_are_distinguished() -> None:
    record = ParagraphRecord(
        "p1", "Call lasted 47 minutes 7 seconds. Yesterday at 3:04 PM. Sent 2 hours ago."
    )

    candidates = detect_record(record, AppConfig()).candidates

    assert {(item.text, item.entity_type) for item in candidates} >= {
        ("47 minutes 7 seconds", EntityType.DURATION),
        ("Yesterday at 3:04 PM", EntityType.RELATIVE_TIMESTAMP),
        ("2 hours ago", EntityType.RELATIVE_TIMESTAMP),
    }


def test_plaintext_and_explicit_hyperlinks_are_excluded() -> None:
    text = "Visit https://example.test/Jane.Smith or Jane Smith"
    explicit_start = text.index("Jane Smith")
    record = ParagraphRecord(
        "p1",
        text,
        hyperlink_ranges=(TextRange(explicit_start, len(text)),),
    )

    result = detect_record(record, AppConfig())

    assert not result.candidates
    assert len(result.url_ranges["p1"]) == 2


def test_header_alias_email_phone_and_timestamp_detection() -> None:
    record = ParagraphRecord(
        "p1",
        "Doe, Jane (jdoe/jsmith) (abc) 3/13/2024 10:59 AM\n"
        "Contact jane@example.org or (202) 555-0198",
    )

    candidates = detect_record(record, AppConfig()).candidates

    types = {item.entity_type for item in candidates}
    assert {
        EntityType.PERSON,
        EntityType.ALIAS,
        EntityType.ABSOLUTE_TIMESTAMP,
        EntityType.EMAIL,
        EntityType.PHONE,
    } <= types


def test_reaction_line_wins_over_name_candidate() -> None:
    reaction = "Jane Smith and 2 others reacted with thumbs up"
    reaction_candidate = detect_record(ParagraphRecord("p1", reaction), AppConfig()).candidates[0]
    ner_candidate = EntityCandidate("p1", 0, 10, "Jane Smith", EntityType.PERSON, 0.9, "spacy.ner")

    resolved = resolve_candidates([ner_candidate, reaction_candidate], AppConfig())

    assert len(resolved) == 1
    assert resolved[0].candidate.entity_type is EntityType.REACTION_LINE
    assert resolved[0].placeholder == ""


def test_name_variants_receive_one_placeholder() -> None:
    assert normalize_person("Doe, Jane") == normalize_person("Jane Doe")
    candidates = [
        EntityCandidate("p1", 0, 9, "Doe, Jane", EntityType.PERSON, 1.0, "regex.header"),
        EntityCandidate("p2", 0, 8, "Jane Doe", EntityType.PERSON, 0.9, "spacy.ner"),
    ]

    resolved = resolve_candidates(candidates, AppConfig())

    assert {item.canonical_id for item in resolved} == {"person-01"}
    assert {item.placeholder for item in resolved} == {"[PERSON_01]"}
