"""Download PostgreSQL documentation pages as markdown files.

Fetches key sections from official PG 16 docs, EDB blog posts,
and pgvector/extension docs. Each page becomes a separate .md file.
"""

import os
import re
import time

import httpx

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "postgres-docs")

# Key PostgreSQL 16 doc pages (most useful for a GraphRAG demo)
PG_DOC_PAGES = [
    # Core concepts
    ("pg-overview", "https://www.postgresql.org/docs/16/intro-whatis.html"),
    ("pg-sql-syntax", "https://www.postgresql.org/docs/16/sql-syntax.html"),
    ("pg-data-types", "https://www.postgresql.org/docs/16/datatype.html"),
    ("pg-functions", "https://www.postgresql.org/docs/16/functions.html"),
    ("pg-indexes", "https://www.postgresql.org/docs/16/indexes.html"),
    ("pg-full-text-search", "https://www.postgresql.org/docs/16/textsearch.html"),
    ("pg-json", "https://www.postgresql.org/docs/16/datatype-json.html"),
    # Performance
    ("pg-performance-tips", "https://www.postgresql.org/docs/16/performance-tips.html"),
    ("pg-explain", "https://www.postgresql.org/docs/16/using-explain.html"),
    ("pg-parallel-query", "https://www.postgresql.org/docs/16/parallel-query.html"),
    # Administration
    ("pg-backup", "https://www.postgresql.org/docs/16/backup.html"),
    ("pg-high-availability", "https://www.postgresql.org/docs/16/high-availability.html"),
    ("pg-monitoring", "https://www.postgresql.org/docs/16/monitoring.html"),
    ("pg-auth", "https://www.postgresql.org/docs/16/client-authentication.html"),
    ("pg-config", "https://www.postgresql.org/docs/16/runtime-config.html"),
    # Advanced
    ("pg-triggers", "https://www.postgresql.org/docs/16/trigger-definition.html"),
    ("pg-rules", "https://www.postgresql.org/docs/16/rules.html"),
    ("pg-extensions", "https://www.postgresql.org/docs/16/extend-extensions.html"),
    ("pg-foreign-data", "https://www.postgresql.org/docs/16/postgres-fdw.html"),
    ("pg-logical-replication", "https://www.postgresql.org/docs/16/logical-replication.html"),
    ("pg-partitioning", "https://www.postgresql.org/docs/16/ddl-partitioning.html"),
    ("pg-recursive-queries", "https://www.postgresql.org/docs/16/queries-with.html"),
    ("pg-window-functions", "https://www.postgresql.org/docs/16/tutorial-window.html"),
    ("pg-transactions", "https://www.postgresql.org/docs/16/tutorial-transactions.html"),
    ("pg-mvcc", "https://www.postgresql.org/docs/16/mvcc.html"),
    ("pg-vacuum", "https://www.postgresql.org/docs/16/routine-vacuuming.html"),
    ("pg-wal", "https://www.postgresql.org/docs/16/wal.html"),
    ("pg-plpgsql", "https://www.postgresql.org/docs/16/plpgsql.html"),
]

# EDB and community blog posts about PG + AI / RAG
BLOG_PAGES = [
    ("edb-rag-pgvector", "https://www.enterprisedb.com/blog/rag-app-postgres-and-pgvector"),
    ("pgdash-rag", "https://pgdash.io/blog/rag-with-postgresql.html"),
    (
        "pgedge-rag-part1",
        "https://www.pgedge.com/blog/building-a-rag-server-with-postgresql-part-1-loading-your-content",
    ),
]


def html_to_markdown(html: str, title: str = "") -> str:
    """Very basic HTML to markdown converter for doc pages."""
    # Remove scripts, styles, nav
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL)
    text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL)
    text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL)

    # Convert headings
    for i in range(1, 7):
        text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", rf"{'#' * i} \1", text, flags=re.DOTALL)

    # Convert paragraphs and line breaks
    text = re.sub(r"<p[^>]*>", "\n\n", text)
    text = re.sub(r"</p>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)

    # Convert lists
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"</li>", "\n", text)

    # Convert code
    text = re.sub(r"<pre[^>]*><code[^>]*>", "\n```\n", text)
    text = re.sub(r"</code></pre>", "\n```\n", text)
    text = re.sub(r"<code[^>]*>", "`", text)
    text = re.sub(r"</code>", "`", text)

    # Convert bold/italic
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)

    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#\d+;", "", text)

    # Add title
    if title:
        text = f"# {title}\n\n{text.strip()}"

    return text.strip()


def download_page(name: str, url: str, output_dir: str) -> bool:
    """Download a page and save as markdown."""
    filepath = os.path.join(output_dir, f"{name}.md")
    if os.path.exists(filepath):
        print(f"  Skip (cached): {name}")
        return True

    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        if resp.status_code != 200:
            print(f"  FAIL ({resp.status_code}): {name} — {url}")
            return False

        md = html_to_markdown(resp.text, title=name.replace("-", " ").title())

        # Skip if too short (probably an error page)
        if len(md) < 200:
            print(f"  Skip (too short): {name}")
            return False

        with open(filepath, "w") as f:
            f.write(md)

        print(f"  OK: {name} ({len(md):,} chars)")
        return True
    except Exception as e:
        print(f"  ERROR: {name} — {e}")
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Downloading PostgreSQL 16 Documentation...")
    pg_ok = 0
    for name, url in PG_DOC_PAGES:
        if download_page(name, url, OUTPUT_DIR):
            pg_ok += 1
        time.sleep(0.5)  # Be polite

    print("\nDownloading Blog Posts...")
    blog_ok = 0
    for name, url in BLOG_PAGES:
        if download_page(name, url, OUTPUT_DIR):
            blog_ok += 1
        time.sleep(0.5)

    total = pg_ok + blog_ok
    print(f"\nDone: {total} documents downloaded to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
