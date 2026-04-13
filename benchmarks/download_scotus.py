"""Download US Supreme Court cases from the Oyez API.

Fetches cases from multiple terms, extracting:
- Case name, citation, docket number
- Question presented
- Decision/conclusion
- Parties, justices, votes
- Related cases (for graph structure)
"""

import os
import re
import time

import httpx

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "scotus")
TERMS = ["2018", "2019", "2020", "2021", "2022", "2023"]  # 6 recent terms


def slugify(text: str) -> str:
    """Convert a string to a safe filename."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:80]


def strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", "", text)
    return text.strip()


def fetch_case_list(term: str) -> list:
    """Fetch all cases from a specific term."""
    url = f"https://api.oyez.org/cases?filter=term:{term}&per_page=200"
    resp = httpx.get(url, timeout=30, headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return []
    return resp.json()


def fetch_case_detail(case_url: str) -> dict | None:
    """Fetch full details of a single case."""
    try:
        resp = httpx.get(case_url, timeout=30, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def case_to_markdown(case: dict) -> str:
    """Convert a case dict to a rich markdown document."""
    lines = []

    name = case.get("name", "Unnamed Case")
    lines.append(f"# {name}")
    lines.append("")

    docket = case.get("docket_number", "")
    if docket:
        lines.append(f"**Docket Number:** {docket}")

    citation = case.get("citation", {}) or {}
    if citation:
        vol = citation.get("volume", "")
        year = citation.get("year", "")
        page = citation.get("page", "")
        if vol or year:
            lines.append(f"**Citation:** {vol} U.S. {page or '___'} ({year})")

    term = case.get("term", "")
    if term:
        lines.append(f"**Term:** {term}")

    # Parties
    first_party = case.get("first_party", "")
    second_party = case.get("second_party", "")
    if first_party and second_party:
        lines.append(f"**Petitioner:** {first_party}")
        lines.append(f"**Respondent:** {second_party}")

    lines.append("")

    # Question presented
    question = strip_html(case.get("question", ""))
    if question:
        lines.append("## Question Presented")
        lines.append("")
        lines.append(question)
        lines.append("")

    # Description
    description = strip_html(case.get("description", ""))
    if description:
        lines.append("## Summary")
        lines.append("")
        lines.append(description)
        lines.append("")

    # Facts of the case
    facts = strip_html(case.get("facts_of_the_case", ""))
    if facts:
        lines.append("## Facts of the Case")
        lines.append("")
        lines.append(facts)
        lines.append("")

    # Conclusion / decision
    conclusion = strip_html(case.get("conclusion", ""))
    if conclusion:
        lines.append("## Decision")
        lines.append("")
        lines.append(conclusion)
        lines.append("")

    # Decisions and votes
    decisions = case.get("decisions") or []
    if decisions:
        lines.append("## Vote Breakdown")
        lines.append("")
        for d in decisions:
            majority_vote = d.get("majority_vote", "")
            minority_vote = d.get("minority_vote", "")
            winning_party = d.get("winning_party", "")
            if majority_vote is not None or minority_vote is not None:
                lines.append(
                    f"- Majority: {majority_vote} | Minority: {minority_vote} | "
                    f"Winning party: {winning_party}"
                )

            # Justice votes (this is the GRAPH GOLD — who voted with whom)
            votes = d.get("votes", []) or []
            if votes:
                lines.append("")
                lines.append("### Justices")
                for v in votes:
                    justice = v.get("member", {})
                    justice_name = justice.get("name", "") if isinstance(justice, dict) else ""
                    vote = v.get("vote", "")
                    opinion_type = v.get("opinion_type", "")
                    if justice_name:
                        line = f"- **{justice_name}**"
                        if vote:
                            line += f" — voted {vote}"
                        if opinion_type and opinion_type != "none":
                            line += f" ({opinion_type})"
                        lines.append(line)
        lines.append("")

    # Related cases
    related = case.get("related_cases") or []
    if related:
        lines.append("## Related Cases")
        lines.append("")
        for rc in related[:10]:
            rc_name = rc.get("description", "") if isinstance(rc, dict) else str(rc)
            if rc_name:
                lines.append(f"- {rc_name}")
        lines.append("")

    # Written opinions text if available (huge!)
    opinions = case.get("written_opinion", []) or []
    if opinions:
        lines.append("## Written Opinions")
        lines.append("")
        for op in opinions[:3]:  # Limit to 3 to keep files manageable
            if isinstance(op, dict):
                op_type = (
                    op.get("type", {}).get("value", "") if isinstance(op.get("type"), dict) else ""
                )
                author = op.get("author", {})
                author_name = author.get("name", "") if isinstance(author, dict) else ""
                if op_type or author_name:
                    lines.append(f"### {op_type or 'Opinion'} by {author_name or 'Unknown'}")
                    lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Phase 1: get case lists for each term
    print("Phase 1: Fetching case lists from Oyez API...")
    all_cases = []
    for term in TERMS:
        print(f"  Term {term}: ", end="", flush=True)
        cases = fetch_case_list(term)
        print(f"{len(cases)} cases")
        all_cases.extend(cases)
        time.sleep(0.5)

    print(f"\nTotal cases: {len(all_cases)}")

    # Phase 2: fetch full details and write as markdown
    print("\nPhase 2: Fetching full case details and writing markdown...")
    ok = 0
    failed = 0
    for i, case_summary in enumerate(all_cases, 1):
        case_url = case_summary.get("href", "")
        if not case_url:
            continue

        name = case_summary.get("name", f"case_{i}")
        slug = slugify(name)
        term = case_summary.get("term", "unknown")
        filename = f"{term}_{slug}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        if os.path.exists(filepath):
            ok += 1
            continue

        case_detail = fetch_case_detail(case_url)
        if not case_detail:
            failed += 1
            continue

        md = case_to_markdown(case_detail)
        if len(md) < 200:
            failed += 1
            continue

        with open(filepath, "w") as f:
            f.write(md)

        ok += 1
        if i % 20 == 0:
            print(f"  Progress: {i}/{len(all_cases)} ({ok} OK, {failed} failed)")
        time.sleep(0.2)  # Be polite to Oyez API

    print(f"\nDone: {ok} SCOTUS cases downloaded to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
