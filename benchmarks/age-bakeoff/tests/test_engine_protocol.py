from age_bakeoff.engines.base import Engine, EngineInfo, RetrievalResponse


def test_engine_info_shape():
    info = EngineInfo(name="pgrg", embedding_model="BAAI/bge-small-en-v1.5", answer_model="gpt-5-mini", top_k=10, hop_budget=2)
    assert info.name == "pgrg"


def test_retrieval_response_shape():
    r = RetrievalResponse(retrieved_chunk_ids=["a::0"], retrieved_chunk_contents=["content"], retrieval_ms=12.5)
    assert r.retrieval_ms == 12.5


def test_engine_is_protocol():
    assert hasattr(Engine, "ingest")
    assert hasattr(Engine, "retrieve")
    assert hasattr(Engine, "generate_answer")
    assert hasattr(Engine, "info")
