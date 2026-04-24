"""Unit tests for evolution-related DTOs."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pg_raggraph.models import Document, DocumentVersion, Fact, FactEdge


def test_document_has_evolution_fields():
    d = Document(
        namespace="ns",
        content_hash="abc",
        effective_from=datetime(2024, 6, 22, tzinfo=timezone.utc),
        retracted=True,
        version_label="v1.2",
    )
    assert d.effective_from.year == 2024
    assert d.retracted is True
    assert d.version_label == "v1.2"


def test_document_evolution_fields_optional():
    d = Document(namespace="ns", content_hash="abc")
    assert d.effective_from is None
    assert d.retracted is False      # default
    assert d.version_label is None


def test_document_version_basic():
    dv = DocumentVersion(
        namespace="ns",
        document_id=1,
        version_label="Python 3.12",
        effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
        supersedes_document_id=2,
    )
    assert dv.supersedes_document_id == 2
    assert dv.retracted is False
    assert dv.namespace == "ns"


def test_document_version_requires_namespace():
    """namespace is required on DocumentVersion — it's NOT NULL in the schema."""
    with pytest.raises(ValidationError):
        DocumentVersion(document_id=1)  # no namespace


def test_fact_shape():
    f = Fact(
        namespace="ns",
        source_chunk_id=1,
        subject="statins",
        predicate="prevent",
        object="cardiovascular events",
        support_span="statins prevent cardiovascular events",
        extractor="llm",
    )
    assert f.confidence == 1.0
    assert f.retracted is False
    assert f.properties == {}


def test_fact_edge_edge_type_required():
    with pytest.raises(ValidationError):
        FactEdge(src_fact_id=1, dst_fact_id=2, inferred_by="llm")  # no edge_type


def test_fact_edge_basic():
    fe = FactEdge(
        src_fact_id=1,
        dst_fact_id=2,
        edge_type="SUPERSEDES",
        inferred_by="document_hint",
    )
    assert fe.edge_type == "SUPERSEDES"
    assert fe.confidence == 1.0
