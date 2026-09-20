import os
import sys
import time
import hashlib
import csv
import re
import requests
import urllib3
from urllib.parse import urljoin, urlparse

urllib3.disable_warnings()

ARCHIVE_DIR = r"c:\Users\dell\Music\Jee Web\JEE_Advanced_PYQ_Archive"
QUARANTINE_DIR = os.path.join(ARCHIVE_DIR, "_quarantine")
MANIFEST_CSV = os.path.join(ARCHIVE_DIR, "jee_advanced_manifest.csv")

os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(headers)
session.verify = False

# Build complete list of official items to download
items_to_download = []

# 1. Archive items from past_qps (2007-2025)
# 2007 to 2018: 1 and 2 (Bilingual)
for y in range(2007, 2019):
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-1",
        "language": "Bilingual",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 1",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_1.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-1.pdf",
        "duplicate_status": "canonical"
    })
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-2",
        "language": "Bilingual",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 2",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_2.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-2.pdf",
        "duplicate_status": "canonical"
    })

# 2019 to 2025: English and Hindi
for y in range(2019, 2026):
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-1",
        "language": "English",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 1 (English)",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_1_English.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-1_English.pdf",
        "duplicate_status": "canonical"
    })
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-1",
        "language": "Hindi",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 1 (Hindi)",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_1_Hindi.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-1_Hindi.pdf",
        "duplicate_status": "language_equivalent_version"
    })
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-2",
        "language": "English",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 2 (English)",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_2_English.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-2_English.pdf",
        "duplicate_status": "canonical"
    })
    items_to_download.append({
        "year": str(y),
        "paper": "Paper-2",
        "language": "Hindi",
        "doc_type": "Question-Paper",
        "title": f"JEE Advanced {y} Paper 2 (Hindi)",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/{y}_2_Hindi.pdf",
        "filename": f"JEE_Advanced_{y}_Paper-2_Hindi.pdf",
        "duplicate_status": "language_equivalent_version"
    })

# 2. Current 2026: Paper 1, Paper 2, and Final Answer Keys
# Question papers
items_to_download.append({
    "year": "2026",
    "paper": "Paper-1",
    "language": "English",
    "doc_type": "Question-Paper",
    "title": "JEE Advanced 2026 Paper 1 (English)",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p1_english.pdf",
    "filename": "JEE_Advanced_2026_Paper-1_English.pdf",
    "duplicate_status": "canonical"
})
items_to_download.append({
    "year": "2026",
    "paper": "Paper-1",
    "language": "Hindi",
    "doc_type": "Question-Paper",
    "title": "JEE Advanced 2026 Paper 1 (Hindi)",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p1_hindi.pdf",
    "filename": "JEE_Advanced_2026_Paper-1_Hindi.pdf",
    "duplicate_status": "language_equivalent_version"
})
items_to_download.append({
    "year": "2026",
    "paper": "Paper-2",
    "language": "English",
    "doc_type": "Question-Paper",
    "title": "JEE Advanced 2026 Paper 2 (English)",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p2_english.pdf",
    "filename": "JEE_Advanced_2026_Paper-2_English.pdf",
    "duplicate_status": "canonical"
})
items_to_download.append({
    "year": "2026",
    "paper": "Paper-2",
    "language": "Hindi",
    "doc_type": "Question-Paper",
    "title": "JEE Advanced 2026 Paper 2 (Hindi)",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p2_hindi.pdf",
    "filename": "JEE_Advanced_2026_Paper-2_Hindi.pdf",
    "duplicate_status": "language_equivalent_version"
})

# Final Answer Keys
items_to_download.append({
    "year": "2026",
    "paper": "Paper-1",
    "language": "",
    "doc_type": "Final-Answer-Key",
    "title": "JEE Advanced 2026 Final Answer Key Paper 1",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p1_solutions_final.pdf",
    "filename": "JEE_Advanced_2026_Paper-1_Final-Answer-Key.pdf",
    "duplicate_status": "canonical"
})
items_to_download.append({
    "year": "2026",
    "paper": "Paper-2",
    "language": "",
    "doc_type": "Final-Answer-Key",
    "title": "JEE Advanced 2026 Final Answer Key Paper 2",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p2_solutions_final.pdf",
    "filename": "JEE_Advanced_2026_Paper-2_Final-Answer-Key.pdf",
    "duplicate_status": "canonical"
})

# Provisional Answer Keys
items_to_download.append({
    "year": "2026",
    "paper": "Paper-1",
    "language": "",
    "doc_type": "Provisional-Answer-Key",
    "title": "JEE Advanced 2026 Provisional Answer Key Paper 1",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p1_provisional_keys.pdf",
    "filename": "JEE_Advanced_2026_Paper-1_Provisional-Answer-Key.pdf",
    "duplicate_status": "canonical"
})
items_to_download.append({
    "year": "2026",
    "paper": "Paper-2",
    "language": "",
    "doc_type": "Provisional-Answer-Key",
    "title": "JEE Advanced 2026 Provisional Answer Key Paper 2",
    "source_page": "https://jeeadv.ac.in/",
    "url": "https://jeeadv.ac.in/documents/p2_provisional_keys.pdf",
    "filename": "JEE_Advanced_2026_Paper-2_Provisional-Answer-Key.pdf",
    "duplicate_status": "canonical"
})

# 3. AAT Papers (2016-2025)
for y in range(2016, 2026):
    items_to_download.append({
        "year": str(y),
        "paper": "AAT",
        "language": "English",
        "doc_type": "Question-Paper",
        "title": f"Architecture Aptitude Test (AAT) {y}",
        "source_page": "https://jeeadv.ac.in/archive.html",
        "url": f"https://jeeadv.ac.in/past_qps/AAT-{y}.pdf",
        "filename": f"JEE_Advanced_{y}_AAT_Question-Paper.pdf",
        "duplicate_status": "canonical"
    })

print(f"Total JEE Advanced items to download: {len(items_to_download)}")

# Download and Validation Engine
manifest_records = []
known_hashes = {}  # sha256 -> local_filepath
downloaded_count = 0
skipped_duplicate_count = 0
failed_count = 0
manual_review_count = 0

for item in items_to_download:
    url = item["url"]
    year = item["year"]
    paper = item["paper"]
    doc_type = item["doc_type"]
    filename = item["filename"]

    # Official domain validation
    domain = urlparse(url).netloc.lower()
    allowed_domains = ["jeeadv.ac.in", "jeeadv.iitb.ac.in", "jeeadv.iitd.ac.in", "jeeadv.iitk.ac.in", "jeeadv.iitm.ac.in", "jeeadv.iitr.ac.in", "jeeadv.iitkgp.ac.in", "jeeadv.iitg.ac.in"]
    if not any(domain == d or domain.endswith("." + d) for d in allowed_domains):
        print(f"[MANUAL REVIEW REQUIRED] {url}: Untrusted domain {domain}")
        manual_review_count += 1
        manifest_records.append({
            "year": year,
            "paper": paper,
            "language": item["language"],
            "document_type": doc_type,
            "title": item["title"],
            "official_source_page": item["source_page"],
            "direct_document_url": url,
            "local_path": "",
            "file_size": 0,
            "sha256": "",
            "download_status": "MANUAL_REVIEW_REQUIRED",
            "duplicate_status": "untrusted_domain"
        })
        continue

    # Determine destination subfolder:
    # 2026/Paper-1/Question-Paper/ or 2026/Paper-1/Answer-Key/
    if paper == "AAT":
        subfolder = os.path.join(ARCHIVE_DIR, "AAT")
    else:
        doc_folder = "Question-Paper" if doc_type == "Question-Paper" else "Answer-Key"
        subfolder = os.path.join(ARCHIVE_DIR, year, paper, doc_folder)

    os.makedirs(subfolder, exist_ok=True)
    target_path = os.path.join(subfolder, filename)

    print(f"Downloading [{year} {paper} {item['language']} {doc_type}]: {filename}...")

    # Avoid overwrite
    if os.path.exists(target_path):
        print(f"  [ALREADY EXISTS] {target_path}")
        with open(target_path, "rb") as fp:
            data = fp.read()
        h = hashlib.sha256(data).hexdigest()
        known_hashes[h] = target_path
        manifest_records.append({
            "year": year,
            "paper": paper,
            "language": item["language"],
            "document_type": doc_type,
            "title": item["title"],
            "official_source_page": item["source_page"],
            "direct_document_url": url,
            "local_path": os.path.relpath(target_path, ARCHIVE_DIR),
            "file_size": len(data),
            "sha256": h,
            "download_status": "already_present",
            "duplicate_status": item["duplicate_status"]
        })
        continue

    try:
        time.sleep(0.5)  # polite rate-limiting
        resp = session.get(url, timeout=30, stream=True)
        if resp.status_code != 200:
            print(f"  [HTTP {resp.status_code}] Failed for {url}")
            failed_count += 1
            manifest_records.append({
                "year": year,
                "paper": paper,
                "language": item["language"],
                "document_type": doc_type,
                "title": item["title"],
                "official_source_page": item["source_page"],
                "direct_document_url": url,
                "local_path": "",
                "file_size": 0,
                "sha256": "",
                "download_status": f"failed_http_{resp.status_code}",
                "duplicate_status": "none"
            })
            continue

        raw_data = resp.content
        file_size = len(raw_data)
        hasher = hashlib.sha256()
        hasher.update(raw_data)
        file_hash = hasher.hexdigest()

        # Validation: check PDF magic number %PDF- (allow leading whitespace per PDF spec ISO 32000-1)
        if not (raw_data.startswith(b'%PDF-') or raw_data.lstrip().startswith(b'%PDF-') or b'%PDF-' in raw_data[:1024]) or file_size < 1000:
            print(f"  [INVALID / CORRUPT] Size: {file_size} bytes. Moving to quarantine.")
            quarantine_path = os.path.join(QUARANTINE_DIR, filename)
            with open(quarantine_path, "wb") as f:
                f.write(raw_data)
            failed_count += 1
            manifest_records.append({
                "year": year,
                "paper": paper,
                "language": item["language"],
                "document_type": doc_type,
                "title": item["title"],
                "official_source_page": item["source_page"],
                "direct_document_url": url,
                "local_path": os.path.relpath(quarantine_path, ARCHIVE_DIR),
                "file_size": file_size,
                "sha256": file_hash,
                "download_status": "quarantined_invalid_pdf",
                "duplicate_status": "corrupt"
            })
            continue

        # Duplicate check by SHA-256
        dup_status = item["duplicate_status"]
        if file_hash in known_hashes:
            orig_file = known_hashes[file_hash]
            print(f"  [DUPLICATE IDENTICAL] Exact hash match with {orig_file}.")
            dup_status = "exact_duplicate"
            skipped_duplicate_count += 1
            manifest_records.append({
                "year": year,
                "paper": paper,
                "language": item["language"],
                "document_type": doc_type,
                "title": item["title"],
                "official_source_page": item["source_page"],
                "direct_document_url": url,
                "local_path": os.path.relpath(orig_file, ARCHIVE_DIR),
                "file_size": file_size,
                "sha256": file_hash,
                "download_status": "skipped_duplicate",
                "duplicate_status": dup_status
            })
            continue

        # Save valid file
        with open(target_path, "wb") as f:
            f.write(raw_data)

        known_hashes[file_hash] = target_path
        downloaded_count += 1
        print(f"  [SUCCESS] Saved as {filename} ({file_size} bytes, SHA-256: {file_hash[:8]}...)")

        manifest_records.append({
            "year": year,
            "paper": paper,
            "language": item["language"],
            "document_type": doc_type,
            "title": item["title"],
            "official_source_page": item["source_page"],
            "direct_document_url": url,
            "local_path": os.path.relpath(target_path, ARCHIVE_DIR),
            "file_size": file_size,
            "sha256": file_hash,
            "download_status": "success",
            "duplicate_status": dup_status
        })

    except Exception as e:
        print(f"  [EXCEPTION] {url}: {e}")
        failed_count += 1
        manifest_records.append({
            "year": year,
            "paper": paper,
            "language": item["language"],
            "document_type": doc_type,
            "title": item["title"],
            "official_source_page": item["source_page"],
            "direct_document_url": url,
            "local_path": "",
            "file_size": 0,
            "sha256": "",
            "download_status": "failed_exception",
            "duplicate_status": "none"
        })

# Write manifest CSV
fieldnames = [
    "year", "paper", "language", "document_type", "title",
    "official_source_page", "direct_document_url", "local_path",
    "file_size", "sha256", "download_status", "duplicate_status"
]

with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in manifest_records:
        writer.writerow(r)

print(f"\nSaved {MANIFEST_CSV}")

# Also save JSON manifest for programmatic ease
MANIFEST_JSON = os.path.join(ARCHIVE_DIR, "jee_advanced_manifest.json")
with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
    import json
    json.dump(manifest_records, f, indent=2)
print(f"Saved {MANIFEST_JSON}")

print("\n================ JEE ADVANCED SUMMARY ================")
print(f"Total items processed: {len(items_to_download)}")
print(f"Successfully downloaded: {downloaded_count}")
print(f"Skipped duplicates: {skipped_duplicate_count}")
print(f"Failed downloads: {failed_count}")
print(f"Manual review items: {manual_review_count}")
