import textwrap
import pytest
from chunkshop.config import CellConfig, load_config


def test_loads_minimal_yaml(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: test_a_bge_small
        source:
          type: json_corpus
          path: /data/scotus.json
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: BAAI/bge-small-en-v1.5
          dim: 384
        target:
          dsn_env: AGE_BAKEOFF_PGRG_DSN
          schema: factorial
          table: test_a_bge_small
        """))
    cfg = load_config(yaml)
    assert cfg.cell_name == "test_a_bge_small"
    assert cfg.source.type == "json_corpus"
    assert cfg.embedder.dim == 384
    assert cfg.target.table == "test_a_bge_small"
    assert cfg.extractor.type == "none"  # default
    assert cfg.runtime.omp_num_threads == 1  # default
    assert cfg.runtime.doc_limit is None  # default: all docs


def test_rejects_unknown_source_type(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: bad
        source:
          type: ftp
          url: ftp://bad
        chunker:
          type: sentence_aware
        embedder:
          type: fastembed
          model_name: x
          dim: 1
        target:
          dsn_env: X
          schema: factorial
          table: bad
        """))
    with pytest.raises(ValueError, match="ftp"):
        load_config(yaml)


def test_table_name_validated(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(textwrap.dedent("""
        cell_name: bad_table
        source: {type: json_corpus, path: /x}
        chunker: {type: sentence_aware}
        embedder: {type: fastembed, model_name: x, dim: 1}
        target:
          dsn_env: X
          schema: factorial
          table: "weird name!"
        """))
    with pytest.raises(ValueError, match="table"):
        load_config(yaml)
