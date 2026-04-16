"""LLM extraction prompts — frozen for reproducibility."""

EXTRACTION_SYSTEM = """You are extracting a knowledge graph from source code or technical documentation.

Given a chunk of text, identify:
1. ENTITIES: functions, structs, types, files, concepts, algorithms
2. RELATIONSHIPS: CALLS, DEFINED_IN, INHERITS, IMPLEMENTS, REFERENCES, RELATES_TO

Return strict JSON matching this schema:
{
  "entities": [
    {"name": "string", "entity_type": "Function|Struct|Type|File|Concept|Algorithm", "description": "1-sentence purpose"}
  ],
  "relationships": [
    {"src": "entity name", "dst": "entity name", "rel_type": "CALLS|DEFINED_IN|INHERITS|IMPLEMENTS|REFERENCES|RELATES_TO", "description": "1-sentence rationale"}
  ]
}

Rules:
- Entity names must be exact (e.g., ExecSeqScan, Plan, costsize.c)
- Only include entities you can point to in the text
- Relationship endpoints must be names you listed in entities
- Skip purely syntactic things (local variables, return types of trivial accessors)
- Maximum 15 entities and 15 relationships per chunk
"""

EXTRACTION_USER_TEMPLATE = """Chunk from {source_path}:

```
{content}
```

Return only JSON, no prose."""
