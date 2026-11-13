"""Build data/index/chunks.json from the PDFs in data/documents/.

Run this whenever you add, replace or remove a document:

    python build_index.py

Then commit the updated data/index/chunks.json. The deployed app reads only
that file. It never parses PDFs at request time.
"""
from collections import Counter

from mf_facts.index_store import INDEX_PATH, build_index, save_index


def main():
    chunks = build_index()
    save_index(chunks)
    counts = Counter((c.scheme_name, c.doc_type) for c in chunks)
    for (scheme, doc_type), n in sorted(counts.items()):
        print(f"{n:5d}  {scheme:28s} {doc_type}")
    print(f"Wrote {len(chunks)} chunks to {INDEX_PATH.relative_to(INDEX_PATH.parents[2])}")


if __name__ == "__main__":
    main()
