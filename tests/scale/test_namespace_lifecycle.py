"""Tests for namespace export and purge lifecycle."""

import pytest

pytestmark = pytest.mark.integration


class TinyEmbedder:
    @property
    def dimension(self) -> int:
        return 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.03] * self.dimension for _ in texts]


async def _count(scale_rag, query: str, *params) -> int:
    row = await scale_rag.db.fetch_one(query, params)
    return row["cnt"]


async def test_export_namespace_then_delete_cascades_namespace_rows(scale_rag):
    ns = "scale_k8"
    scale_rag._embedder = TinyEmbedder()

    await scale_rag.ingest_records(
        [
            {
                "text": "K8 lifecycle export and purge content.",
                "source_id": "scale_k8_doc",
                "metadata": {"version_label": "v1"},
                "entities": [
                    {"name": "Lifecycle Tenant", "entity_type": "Tenant"},
                    {"name": "Export Job", "entity_type": "Process"},
                ],
                "relationships": [
                    {
                        "src": "Lifecycle Tenant",
                        "dst": "Export Job",
                        "rel_type": "USES",
                    }
                ],
            }
        ],
        namespace=ns,
    )
    first_fact = await scale_rag.db.fetch_one(
        "INSERT INTO facts "
        "(namespace, source_chunk_id, subject, predicate, object, support_span, extractor) "
        "VALUES (%s, NULL, %s, %s, %s, %s, %s) "
        "RETURNING id",
        (ns, "Source-less fact A", "relates_to", "Source-less fact B", "manual support", "test"),
    )
    second_fact = await scale_rag.db.fetch_one(
        "INSERT INTO facts "
        "(namespace, source_chunk_id, subject, predicate, object, support_span, extractor) "
        "VALUES (%s, NULL, %s, %s, %s, %s, %s) "
        "RETURNING id",
        (ns, "Source-less fact B", "relates_to", "Source-less fact A", "manual support", "test"),
    )
    await scale_rag.db.execute(
        "INSERT INTO fact_edges (src_fact_id, dst_fact_id, edge_type, inferred_by) "
        "VALUES (%s, %s, %s, %s)",
        (first_fact["id"], second_fact["id"], "supports", "test"),
    )

    exported = [doc async for doc in scale_rag.export_namespace(ns)]
    assert len(exported) == 1
    assert exported[0]["namespace"] == ns
    assert exported[0]["source_path"] == "scale_k8_doc"
    assert exported[0]["version_label"] == "v1"
    assert exported[0]["chunks"][0]["content"] == "K8 lifecycle export and purge content."

    await scale_rag.delete(ns)

    assert (
        await _count(scale_rag, "SELECT count(*) AS cnt FROM documents WHERE namespace = %s", ns)
        == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM document_versions WHERE namespace = %s",
            ns,
        )
        == 0
    )
    assert (
        await _count(scale_rag, "SELECT count(*) AS cnt FROM entities WHERE namespace = %s", ns)
        == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM relationships WHERE namespace = %s",
            ns,
        )
        == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM chunks c "
            "JOIN documents d ON d.id = c.document_id WHERE d.namespace = %s",
            ns,
        )
        == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM entity_chunks ec "
            "JOIN chunks c ON c.id = ec.chunk_id "
            "JOIN documents d ON d.id = c.document_id WHERE d.namespace = %s",
            ns,
        )
        == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM relationship_chunks rc "
            "JOIN chunks c ON c.id = rc.chunk_id "
            "JOIN documents d ON d.id = c.document_id WHERE d.namespace = %s",
            ns,
        )
        == 0
    )
    assert (
        await _count(scale_rag, "SELECT count(*) AS cnt FROM facts WHERE namespace = %s", ns) == 0
    )
    assert (
        await _count(
            scale_rag,
            "SELECT count(*) AS cnt FROM fact_edges "
            "WHERE src_fact_id IN (%s, %s) OR dst_fact_id IN (%s, %s)",
            first_fact["id"],
            second_fact["id"],
            first_fact["id"],
            second_fact["id"],
        )
        == 0
    )
