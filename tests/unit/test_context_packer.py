from pg_raggraph.context import SelectedDocument, assemble_context
from pg_raggraph.models import ChunkResult, QueryResult
from pg_raggraph.profiles import resolve_profile


def _result() -> QueryResult:
    return QueryResult(
        chunks=[
            ChunkResult(content="raw chunk one", score=0.9, document_source="doc1", chunk_id=1),
            ChunkResult(content="raw chunk two", score=0.8, document_source="doc2", chunk_id=2),
            ChunkResult(content="raw chunk three", score=0.7, document_source="doc1", chunk_id=3),
        ]
    )


def _docs() -> list[SelectedDocument]:
    return [
        SelectedDocument(
            source_id="doc1", text="full doc one\n\nraw chunk one\n\nraw chunk three"
        ),
        SelectedDocument(source_id="doc2", text="full doc two\n\nraw chunk two"),
    ]


def test_raw_profile_is_byte_equivalent_to_legacy_chunks():
    packed = assemble_context(
        question="what happened?",
        result=_result(),
        documents=_docs(),
        profile=resolve_profile("raw"),
    )

    assert packed.context_strategy == "classic_chunks"
    assert packed.chunks == ("raw chunk one", "raw chunk two", "raw chunk three")
    assert packed.text == "raw chunk one\n\nraw chunk two\n\nraw chunk three"
    assert packed.selected_documents == ("doc1", "doc2")


def test_full_selected_docs_uses_top_n_parent_documents():
    packed = assemble_context(
        question="what happened?",
        result=_result(),
        documents=_docs(),
        profile=resolve_profile("full_selected_docs@3"),
    )

    assert packed.context_strategy == "full_selected_docs@3"
    assert packed.chunks == (
        "full doc one\n\nraw chunk one\n\nraw chunk three",
        "full doc two\n\nraw chunk two",
    )


def test_balanced_profile_includes_summary_markers_and_top_raw_chunks(monkeypatch):
    monkeypatch.setattr(
        "pg_raggraph.context._summarize_facts",
        lambda text, question, **kwargs: f"summary<{text[:8]}>",
    )

    packed = assemble_context(
        question="what happened?",
        result=_result(),
        documents=_docs(),
        profile=resolve_profile("balanced"),
    )

    assert packed.context_strategy == "doc_and_chunk_summary_toc_facts_plus_top5"
    assert "Document summary:" in packed.text
    assert "Retrieved-chunk summary:" in packed.text
    assert "Top 5 chunks:" in packed.text
    assert "raw chunk one" in packed.text


def test_stacked_profile_includes_per_doc_summaries_chunk_summary_and_raw(monkeypatch):
    monkeypatch.setattr(
        "pg_raggraph.context._summarize_facts",
        lambda text, question, **kwargs: f"summary<{text[:8]}>",
    )

    packed = assemble_context(
        question="what happened?",
        result=_result(),
        documents=_docs(),
        profile=resolve_profile("stacked"),
    )

    assert packed.context_strategy == "per_doc5_chunksum_top5"
    assert "[doc1]" in packed.text
    assert "[doc2]" in packed.text
    assert "Retrieved-chunk summary:" in packed.text
    assert "Top 5 chunks:" in packed.text
    assert "raw chunk two" in packed.text
