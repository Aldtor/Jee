import os
import json
import csv
import hashlib

ARCHIVE_DIR = r"c:\Users\dell\Music\Jee Web\JEE_Main_PYQ_Archive"
MANIFEST_JSON = os.path.join(ARCHIVE_DIR, "manifest.json")
MANIFEST_CSV = os.path.join(ARCHIVE_DIR, "manifest.csv")
QUARANTINE_DIR = os.path.join(ARCHIVE_DIR, "_quarantine")

with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
    json_records = json.load(f)

with open(MANIFEST_CSV, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    csv_records = list(reader)

print(f"JSON records: {len(json_records)}")
print(f"CSV records: {len(csv_records)}")
assert len(json_records) == len(csv_records), "Record count mismatch between CSV and JSON!"

# Verification checks
verified_files = 0
hash_matches = 0
pdf_valid_count = 0
duplicates_verified = 0

years_covered = set()
sessions_covered = set()
papers_count = 0
keys_count = 0
notices_count = 0

for record in json_records:
    status = record["download_status"]
    rel_path = record["local_filename"]
    expected_hash = record["sha256_hash"]
    doc_type = record["document_type"]
    year = record["year"]
    session = record["session"]

    if year and year != "Unknown":
        years_covered.add(year)
    if session:
        sessions_covered.add(f"{year} {session}")

    if doc_type == "Question-Paper":
        papers_count += 1
    elif "Answer-Key" in doc_type:
        keys_count += 1
    else:
        notices_count += 1

    if status in ["success", "skipped_duplicate"]:
        abs_path = os.path.join(ARCHIVE_DIR, rel_path)
        assert os.path.exists(abs_path), f"File missing from disk: {abs_path}"
        verified_files += 1

        with open(abs_path, "rb") as fp:
            content = fp.read()

        assert content.startswith(b"%PDF-"), f"Not a valid PDF: {abs_path}"
        pdf_valid_count += 1

        computed_hash = hashlib.sha256(content).hexdigest()
        assert computed_hash == expected_hash, f"Hash mismatch for {abs_path}!"
        hash_matches += 1

        if status == "skipped_duplicate":
            duplicates_verified += 1

print("\n--- Verification Results ---")
print(f"Total manifest entries: {len(json_records)}")
print(f"Verified files on disk: {verified_files}")
print(f"Valid PDF headers: {pdf_valid_count}")
print(f"Exact SHA-256 hash matches: {hash_matches}")
print(f"Duplicate aliases verified: {duplicates_verified}")
print(f"Quarantine directory empty: {len(os.listdir(QUARANTINE_DIR)) == 0}")

print("\n--- Content Breakdown ---")
print(f"Years found: {sorted(list(years_covered))}")
print(f"Total Question Papers: {papers_count}")
print(f"Total Answer Keys: {keys_count}")
print(f"Total Official Notices: {notices_count}")

# Print directory tree summary
print("\n--- Local Folder Hierarchy ---")
for root, dirs, files in os.walk(ARCHIVE_DIR):
    if files:
        rel = os.path.relpath(root, ARCHIVE_DIR)
        print(f"{rel}: {len(files)} files")
