# Database Technologies for RAG

## PostgreSQL
PostgreSQL is the most popular open-source relational database. With the pgvector extension, it supports vector similarity search using HNSW and IVFFlat indexes. The pg_trgm extension enables fuzzy text matching.

## Neo4j
Neo4j is a graph database that uses the Cypher query language. It is commonly used for knowledge graph storage in GraphRAG implementations. Neo4j added native vector indexes in version 5.11.

## pgvector
pgvector is a PostgreSQL extension that adds vector similarity search. It supports exact and approximate nearest neighbor search with HNSW and IVFFlat index types. pgvector has over 13,000 GitHub stars.

## Apache AGE
Apache AGE is a PostgreSQL extension that adds openCypher graph query support. While promising, it has limited cloud provider support — only Azure Database for PostgreSQL supports it among managed providers.
