"""Port SCOTUS seed data from yonk-samples/graphrag-demo into our shared format.

Run once to capture. Run from /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff/.
Output: src/age_bakeoff/extraction/data/scotus.json

Requires SCOTUS markdown case files at benchmarks/scotus/ (391 files).
The scotus_data module reads from SCOTUS_SOURCE_DIR env var.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Point scotus_data at the correct source directory BEFORE importing
os.environ["SCOTUS_SOURCE_DIR"] = str(
    Path(__file__).resolve().parent.parent.parent / "scotus"
)

# Add graphrag-demo's app dir to path so we can import its seed module
DEMO_APP = Path("/home/yonk/yonk-samples/graphrag-demo/app")
sys.path.insert(0, str(DEMO_APP))

from seed.scotus_data import generate_all  # type: ignore


def port() -> dict:
    raw = generate_all()
    entities = []

    # Justices -> ExtractedEntity
    for j in raw["justices"]:
        entities.append({
            "id": j["id"],
            "name": j["name"],
            "entity_type": "Justice",
            "description": f"SCOTUS Justice, terms {j['first_term']}-{j['last_term']}",
            "properties": {
                "first_term": j["first_term"],
                "last_term": j["last_term"],
            },
        })

    # Cases -> ExtractedEntity
    for c in raw["cases"]:
        entities.append({
            "id": c["id"],
            "name": c["name"],
            "entity_type": "Case",
            "description": c.get("summary", "")[:500] or c.get("question", "")[:500],
            "properties": {
                "docket": c["docket"],
                "term": c["term"],
                "vote_split": c["vote_split"],
                "petitioner": c["petitioner"],
                "respondent": c["respondent"],
            },
        })

    # Issues -> ExtractedEntity
    for iss in raw["issues"]:
        entities.append({
            "id": iss["id"],
            "name": iss["name"],
            "entity_type": "Issue",
            "description": f"Legal issue: {iss['name']}",
            "properties": {"category": iss["category"]},
        })

    # Build entity ID set for relationship validation
    entity_ids = {e["id"] for e in entities}

    relationships = []

    # Citations: case -> case (CITED)
    for cit in raw["citations"]:
        relationships.append({
            "src_id": cit["from_id"],
            "dst_id": cit["to_id"],
            "rel_type": "CITED",
            "weight": 1.0,
            "description": "",
            "properties": {},
        })

    # Per-case relationships from votes and opinion authorship
    for c in raw["cases"]:
        # WROTE_OPINION: majority author -> case
        if c["majority_author_id"] and c["majority_author_id"] in entity_ids:
            relationships.append({
                "src_id": c["majority_author_id"],
                "dst_id": c["id"],
                "rel_type": "WROTE_OPINION",
                "weight": 1.0,
                "description": "majority opinion",
                "properties": {"opinion_type": "majority"},
            })

        # WROTE_OPINION: dissent authors -> case
        for did in c["dissent_author_ids"]:
            if did in entity_ids:
                relationships.append({
                    "src_id": did,
                    "dst_id": c["id"],
                    "rel_type": "WROTE_OPINION",
                    "weight": 1.0,
                    "description": "dissenting opinion",
                    "properties": {"opinion_type": "dissent"},
                })

        # Vote relationships: justice -> case
        for vote in c["votes"]:
            jid = vote["justice_id"]
            if jid not in entity_ids:
                continue
            side = vote["side"]
            role = vote.get("role")
            if side == "majority":
                rel_type = "VOTED_MAJORITY"
            elif role and "concur" in role.lower():
                rel_type = "VOTED_CONCURRING"
            else:
                rel_type = "VOTED_DISSENT"
            relationships.append({
                "src_id": jid,
                "dst_id": c["id"],
                "rel_type": rel_type,
                "weight": 1.0,
                "description": f"{vote['justice_name']} voted {side}",
                "properties": {"role": role or ""},
            })

        # CONCERNS: case -> issue
        for issue_id in c["issue_ids"]:
            if issue_id in entity_ids:
                relationships.append({
                    "src_id": c["id"],
                    "dst_id": issue_id,
                    "rel_type": "CONCERNS",
                    "weight": 1.0,
                    "description": "",
                    "properties": {},
                })

    documents = []
    for doc in raw["documents"]:
        documents.append({
            "id": doc["id"],
            "author_id": doc.get("author_id"),
            "project_id": doc.get("project_id"),
            "title": doc.get("title", ""),
            "doc_type": doc.get("doc_type", ""),
            "content": doc["content"],
        })

    return {
        "entities": entities,
        "relationships": relationships,
        "documents": documents,
    }


def main():
    data = port()
    out = Path(__file__).parent.parent / "src" / "age_bakeoff" / "extraction" / "data" / "scotus.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True))
    print(f"wrote {out}")
    print(f"  entities: {len(data['entities'])}")
    print(f"  relationships: {len(data['relationships'])}")
    print(f"  documents: {len(data['documents'])}")


if __name__ == "__main__":
    main()
