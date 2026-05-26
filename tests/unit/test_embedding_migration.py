from pg_raggraph import embedding_migration as em


def test_dim_regex_parses_vector_type():
    assert em._DIM_RE.search("vector(768)").group(1) == "768"
    assert em._DIM_RE.search("vector") is None  # unconstrained vector has no dim


def test_text_source_map_covers_all_tables():
    assert set(em._TEXT_SOURCE) == set(em.TABLES)
    assert "embedded_content" in em._TEXT_SOURCE["chunks"]
    assert "description" in em._TEXT_SOURCE["entities"]


def test_index_name_maps_cover_all_tables():
    assert set(em._LIVE_INDEX) == set(em.TABLES)
    assert set(em._TMP_INDEX) == set(em.TABLES)
