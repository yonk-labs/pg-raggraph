"""Reusable ingestion tool: source -> chunker -> embedder -> extractor -> pgvector table."""
from chunkshop.config import CellConfig, load_config

__all__ = ["CellConfig", "load_config"]
