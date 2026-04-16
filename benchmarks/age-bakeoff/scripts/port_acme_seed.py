"""Port Acme seed data from yonk-samples/graphrag-demo into our shared format.

Run once to capture. Run from /home/yonk/yonk-tools/pg-raggraph/benchmarks/age-bakeoff/.
Output: src/age_bakeoff/extraction/data/acme.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add graphrag-demo's app dir to path so we can import its seed module
DEMO_APP = Path("/home/yonk/yonk-samples/graphrag-demo/app")
sys.path.insert(0, str(DEMO_APP))

from seed.generate_data import generate_all  # type: ignore


def port() -> dict:
    raw = generate_all()
    # Normalize into our shared schema: entities, relationships, documents
    entities = []

    # People -> ExtractedEntity
    for p in raw["people"]:
        entities.append({
            "id": p["id"],
            "name": p["name"],
            "entity_type": "Person",
            "description": f"{p['title']} ({p['email']})",
            "properties": {"team_id": p["team_id"]},
        })

    # Teams -> ExtractedEntity
    for t in raw["teams"]:
        entities.append({
            "id": t["id"],
            "name": t["name"],
            "entity_type": "Team",
            "description": f"Team in {t['department']}",
            "properties": {"department": t["department"]},
        })

    # Projects -> ExtractedEntity
    for pr in raw["projects"]:
        entities.append({
            "id": pr["id"],
            "name": pr["name"],
            "entity_type": "Project",
            "description": pr["description"],
            "properties": {"status": pr["status"]},
        })

    # Services -> ExtractedEntity
    for s in raw["services"]:
        entities.append({
            "id": s["id"],
            "name": s["name"],
            "entity_type": "Service",
            "description": s["description"],
            "properties": {"tier": s["tier"]},
        })

    # Technologies -> ExtractedEntity (no description field — use category)
    for tech in raw["technologies"]:
        entities.append({
            "id": tech["id"],
            "name": tech["name"],
            "entity_type": "Technology",
            "description": f"{tech['category']} technology",
            "properties": {"category": tech["category"]},
        })

    relationships = []

    # Team membership: people -> teams (from PEOPLE.team_id)
    for p in raw["people"]:
        relationships.append({
            "src_id": p["id"],
            "dst_id": p["team_id"],
            "rel_type": "MEMBER_OF",
            "weight": 1.0,
            "description": f"{p['name']} is a member of {p['team_id']}",
            "properties": {},
        })

    # works_on: (person_id, project_id, role)
    for rel in raw["relationships"]["works_on"]:
        relationships.append({
            "src_id": rel["person_id"],
            "dst_id": rel["project_id"],
            "rel_type": "WORKS_ON",
            "weight": 1.0,
            "description": f"Role: {rel.get('role', '')}",
            "properties": {"role": rel.get("role", "")},
        })

    # reports_to: (person_id, manager_id)
    for rel in raw["relationships"]["reports_to"]:
        relationships.append({
            "src_id": rel["person_id"],
            "dst_id": rel["manager_id"],
            "rel_type": "REPORTS_TO",
            "weight": 1.0,
            "description": "",
            "properties": {},
        })

    # owns: (team_id, service_id)
    for rel in raw["relationships"]["owns"]:
        relationships.append({
            "src_id": rel["team_id"],
            "dst_id": rel["service_id"],
            "rel_type": "OWNS",
            "weight": 1.0,
            "description": "",
            "properties": {},
        })

    # depends_on: (source_id, target_id, dependency_type)
    for rel in raw["relationships"]["depends_on"]:
        relationships.append({
            "src_id": rel["source_id"],
            "dst_id": rel["target_id"],
            "rel_type": "DEPENDS_ON",
            "weight": 1.0,
            "description": f"Dependency type: {rel.get('dependency_type', '')}",
            "properties": {"dependency_type": rel.get("dependency_type", "")},
        })

    # knows_about: (person_id, tech_id, proficiency)
    for rel in raw["relationships"]["knows_about"]:
        relationships.append({
            "src_id": rel["person_id"],
            "dst_id": rel["tech_id"],
            "rel_type": "KNOWS_ABOUT",
            "weight": 1.0,
            "description": f"Proficiency: {rel.get('proficiency', '')}",
            "properties": {"proficiency": rel.get("proficiency", "")},
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
    out = Path(__file__).parent.parent / "src" / "age_bakeoff" / "extraction" / "data" / "acme.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True))
    print(f"wrote {out}")
    print(f"  entities: {len(data['entities'])}")
    print(f"  relationships: {len(data['relationships'])}")
    print(f"  documents: {len(data['documents'])}")


if __name__ == "__main__":
    main()
