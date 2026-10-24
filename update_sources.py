import csv
import json
from pathlib import Path

DOCS = Path("data/documents")
JSON_PATH = Path("sources.json")
CSV_PATH = Path("sources.csv")

# Verified official URLs for the eight SID/KIM documents.
BASE = "https://files.hdfcfund.com/s3fs-public"

pdf_urls = {
    "SID - HDFC Nifty 50 Index Fund dated November 21, 2025.pdf":
        f"{BASE}/SID/2025-11/SID%20-%20HDFC%20Nifty%2050%20Index%20Fund%20dated%20November%2021%2C%202025.pdf",
    "KIM - HDFC Nifty 50 Index Fund dated November 21, 2025.pdf":
        f"{BASE}/KIM/2025-11/KIM%20-%20HDFC%20Nifty%2050%20Index%20Fund%20dated%20November%2021%2C%202025.pdf",
}

# Load existing metadata and preserve its original fields.
existing_json = json.loads(JSON_PATH.read_text()) if JSON_PATH.exists() else []
existing_csv = []
if CSV_PATH.exists():
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        existing_csv = list(csv.DictReader(f))

# Generate PDF entries. Unknown URLs are deliberately left blank.
json_by_file = {item.get("file_name"): item for item in existing_json}
for path in sorted(DOCS.glob("*.pdf")):
    name = path.name
    if name not in json_by_file:
        json_by_file[name] = {
            "file_name": name,
            "source_title": name.removesuffix(".pdf"),
            "source_url": pdf_urls.get(name, ""),
            "document_date": "",
            "publisher": "HDFC Mutual Fund",
        }

# Preserve the original CSV source entries and add any missing local PDFs.
csv_by_title = {item.get("title"): item for item in existing_csv}
for path in sorted(DOCS.glob("*.pdf")):
    name = path.name
    title = name.removesuffix(".pdf")
    if title not in csv_by_title:
        csv_by_title[title] = {
            "title": title,
            "publisher": "HDFC Mutual Fund",
            "url": pdf_urls.get(name, ""),
            "topics": "Scheme information; verify document content before use",
            "document_or_check_date": "Needs verification",
        }

JSON_PATH.write_text(
    json.dumps(list(json_by_file.values()), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
    fields = ["title", "publisher", "url", "topics", "document_or_check_date"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(csv_by_title.values())

print(f"Updated {JSON_PATH}: {len(json_by_file)} PDF entries")
print(f"Updated {CSV_PATH}: {len(csv_by_title)} source entries")
print("Unknown URLs and dates were left blank or marked for verification.")
