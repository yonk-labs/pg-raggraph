"""Extract text from KG-RAG eval dataset PDFs into markdown files."""

import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "kg-rag-eval", "extracted")
DATASETS = {
    "sec-10q": os.path.join(
        os.path.dirname(__file__), "kg-rag-eval", "sec-10-q", "data", "v1", "docs"
    ),
    "ntsb": os.path.join(
        os.path.dirname(__file__),
        "kg-rag-eval",
        "ntsb-aviation-incident-accident-reports",
        "data",
        "v1",
        "docs",
    ),
}


def extract_pdf(pdf_path: str, output_path: str) -> bool:
    """Extract text from PDF and save as markdown."""
    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        text = "\n\n".join(text_parts)
        if len(text.strip()) < 100:
            return False

        basename = os.path.splitext(os.path.basename(pdf_path))[0]
        md = f"# {basename}\n\n{text.strip()}"

        with open(output_path, "w") as f:
            f.write(md)
        return True
    except Exception as e:
        print(f"  ERROR: {pdf_path} — {e}")
        return False


def main():
    for dataset_name, docs_dir in DATASETS.items():
        out_dir = os.path.join(OUTPUT_DIR, dataset_name)
        os.makedirs(out_dir, exist_ok=True)

        if not os.path.exists(docs_dir):
            print(f"Skip {dataset_name}: {docs_dir} not found")
            continue

        pdfs = [f for f in os.listdir(docs_dir) if f.endswith(".pdf")]
        print(f"\n{dataset_name}: {len(pdfs)} PDFs")

        ok = 0
        for pdf_name in sorted(pdfs):
            pdf_path = os.path.join(docs_dir, pdf_name)
            md_name = pdf_name.replace(".pdf", ".md")
            out_path = os.path.join(out_dir, md_name)

            if os.path.exists(out_path):
                ok += 1
                continue

            if extract_pdf(pdf_path, out_path):
                ok += 1
                print(f"  OK: {pdf_name}")
            else:
                print(f"  FAIL: {pdf_name}")

        print(f"  Extracted: {ok}/{len(pdfs)}")

    print(f"\nDone. Files in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
