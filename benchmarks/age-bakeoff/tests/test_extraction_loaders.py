from age_bakeoff.extraction.loaders import load_acme_extraction, load_scotus_extraction
from age_bakeoff.models import ExtractionOutput


def test_acme_loader_shape():
    out = load_acme_extraction()
    assert isinstance(out, ExtractionOutput)
    assert out.corpus == "acme"
    assert len(out.chunks) > 50
    assert len(out.entities) >= 20
    assert len(out.relationships) >= 20
    eids = {e.id for e in out.entities}
    for r in out.relationships:
        assert r.src_id in eids, f"dangling src {r.src_id}"
        assert r.dst_id in eids, f"dangling dst {r.dst_id}"


def test_scotus_loader_shape():
    out = load_scotus_extraction()
    assert out.corpus == "scotus"
    assert len(out.chunks) > 20
    assert any(e.entity_type == "Justice" for e in out.entities)
    assert any(r.rel_type == "CITED" for r in out.relationships)


def test_loader_deterministic():
    a = load_acme_extraction()
    b = load_acme_extraction()
    assert [c.model_dump() for c in a.chunks] == [c.model_dump() for c in b.chunks]
    assert [e.model_dump() for e in a.entities] == [e.model_dump() for e in b.entities]
