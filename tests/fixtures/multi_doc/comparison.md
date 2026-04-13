# LightRAG vs Microsoft GraphRAG

## Cost
Microsoft GraphRAG uses approximately 610,000 tokens per query for community summary scanning. LightRAG uses fewer than 100 tokens per query — a 6,000x reduction in retrieval-phase token cost.

## Architecture
Microsoft GraphRAG builds hierarchical communities using the Leiden algorithm and generates bottom-up summaries. LightRAG skips community summaries entirely, using dual-level retrieval with keyword extraction instead.

## Incremental Updates
Microsoft GraphRAG requires full community hierarchy rebuild when documents change. LightRAG supports incremental updates — new entities and relationships merge into the existing graph without restructuring.

## PostgreSQL Support
Microsoft GraphRAG has no native PostgreSQL backend. LightRAG supports PostgreSQL through pgvector for vector storage and Apache AGE for graph queries, though users report performance issues with AGE including 17-hour migration times.

## Performance
LightRAG consistently outperforms Microsoft GraphRAG across agriculture, computer science, legal, and mixed domains in comprehensiveness, diversity, and empowerment metrics.
