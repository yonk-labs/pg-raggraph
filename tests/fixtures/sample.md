# GraphRAG Overview

GraphRAG is a retrieval-augmented generation technique that uses knowledge graphs to enhance LLM responses. It was pioneered by Microsoft Research in 2024.

## Key Concepts

### Entity Extraction
Entity extraction uses large language models to identify entities like people, organizations, and concepts from documents. The extracted entities become nodes in the knowledge graph.

### Relationship Discovery
Relationships between entities are discovered during the extraction process. For example, "Microsoft Research developed GraphRAG" creates a relationship between Microsoft Research and GraphRAG.

### Community Detection
The Leiden algorithm is commonly used to detect communities within the knowledge graph. These communities help with global queries that span multiple topics.

## Implementations

### Microsoft GraphRAG
Microsoft released the original GraphRAG implementation as open source. It uses Leiden community detection and hierarchical summarization. The main limitation is cost — indexing large datasets can cost $33,000 or more.

### LightRAG
LightRAG by HKUDS is a lightweight alternative that uses dual-level retrieval instead of community summaries. It was published at EMNLP 2025 and has over 33,000 GitHub stars. LightRAG supports PostgreSQL as a backend through pgvector and Apache AGE.

### postgres-graph-rag
postgres-graph-rag by Hagen Hoferichter demonstrates that GraphRAG can work entirely within PostgreSQL using recursive CTEs and pgvector, without Apache AGE.

## PostgreSQL as a Backend

PostgreSQL with pgvector provides vector similarity search. Combined with recursive CTEs for graph traversal and pg_trgm for fuzzy matching, PostgreSQL can serve as a complete GraphRAG backend. This eliminates the need for separate graph databases like Neo4j.
