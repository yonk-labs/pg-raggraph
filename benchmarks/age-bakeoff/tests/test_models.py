"""Round-trip tests for the shared pydantic models."""
from __future__ import annotations

from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
    Question,
    QuestionClass,
    RunResult,
)


def test_chunk_round_trip():
    c = Chunk(
        id="doc1::0",
        document_id="doc1",
        content="hello world",
        sequence=0,
        metadata={"source_path": "docs/intro.md"},
    )
    assert c.model_dump()["id"] == "doc1::0"
    assert Chunk.model_validate(c.model_dump()) == c


def test_extracted_entity_round_trip():
    e = ExtractedEntity(
        id="ent_person_alice",
        name="Alice",
        entity_type="Person",
        description="A person",
        properties={"team": "platform"},
    )
    assert ExtractedEntity.model_validate(e.model_dump()) == e


def test_extracted_relationship_round_trip():
    r = ExtractedRelationship(
        src_id="ent_person_alice",
        dst_id="ent_project_ingest",
        rel_type="WORKS_ON",
        weight=0.9,
        description="Alice works on Ingest",
        properties={},
    )
    assert ExtractedRelationship.model_validate(r.model_dump()) == r


def test_extraction_output_matches_contract():
    out = ExtractionOutput(
        corpus="acme",
        chunks=[],
        entities=[],
        relationships=[],
    )
    assert out.corpus == "acme"


def test_question_requires_bridging_class_enum():
    q = Question(
        id="acme-q-001",
        question="Who works on Ingest?",
        gold_answer="Alice and Bob.",
        required_facts=["Alice", "Bob"],
        required_entities=["ent_person_alice", "ent_person_bob"],
        question_class=QuestionClass.single_hop,
    )
    assert q.question_class == QuestionClass.single_hop


def test_run_result_schema():
    r = RunResult(
        engine="pgrg",
        corpus="acme",
        question_id="acme-q-001",
        run_number=1,
        cold=True,
        retrieval_ms=42.0,
        answer_ms=800.0,
        retrieved_chunk_ids=["doc1::0"],
        generated_answer="Alice and Bob.",
    )
    assert r.retrieval_ms == 42.0
    assert RunResult.model_validate(r.model_dump()) == r
