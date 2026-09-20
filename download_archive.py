import os
import sys
import time
import hashlib
import json
import csv
import re
import requests
import urllib3

urllib3.disable_warnings()

ARCHIVE_DIR = r"c:\Users\dell\Music\Jee Web\JEE_Main_PYQ_Archive"
QUARANTINE_DIR = os.path.join(ARCHIVE_DIR, "_quarantine")
MANIFEST_CSV = os.path.join(ARCHIVE_DIR, "manifest.csv")
MANIFEST_JSON = os.path.join(ARCHIVE_DIR, "manifest.json")

os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(headers)
session.verify = False

# Read classified docs
with open(r"C:\Users\dell\.gemini\antigravity-ide\brain\00c035f5-b98b-4ec7-abe2-773a9e7fd2a5\scratch\classified_docs.json", "r", encoding="utf-8") as f:
    classified_items = json.load(f)

# Also load all archive items to ensure we don't miss any keys or question papers
with open(r"C:\Users\dell\.gemini\antigravity-ide\brain\00c035f5-b98b-4ec7-abe2-773a9e7fd2a5\scratch\nta_archive_jee.json", "r", encoding="utf-8") as f:
    nta_archive = json.load(f)

# Combine and deduplicate candidates by URL
candidates_by_url = {}

for item in classified_items:
    url = item["url"]
    candidates_by_url[url] = item

for item in nta_archive:
    url = item["url"]
    if url not in candidates_by_url:
        candidates_by_url[url] = {
            "title": item["title"],
            "url": url,
            "source_page": "https://nta.ac.in/NoticeBoardArchive",
            "is_paper": item["is_paper"],
            "is_key": item["is_key"]
        }

print(f"Total candidate documents to process: {len(candidates_by_url)}")

def parse_metadata(item):
    title = item.get("title", "")
    url = item.get("url", "")
    low = (title + " " + url).lower()

    # Allowed official domains check
    # jeemain.nta.nic.in, nta.ac.in, official subdomains of nta.ac.in, cdnbbsr.s3waas.gov.in (official CDN for jeemain.nta.nic.in)
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    allowed_domains = ["jeemain.nta.nic.in", "nta.ac.in", "cdnbbsr.s3waas.gov.in", "examinationservices.nic.in"]
    if not any(domain == d or domain.endswith("." + d) for d in allowed_domains):
        return None, "Untrusted domain: " + domain

    # Determine Year
    year_match = re.findall(r'20[12]\d', title + " " + url)
    valid_years = [int(y) for y in year_match if 2018 <= int(y) <= 2026]
    year = str(max(valid_years)) if valid_years else "Unknown-Year"

    # Determine Session
    session_str = "Session-General"
    if "session - 4" in low or "session 4" in low or "session-4" in low or "session  4" in low:
        session_str = "Session-4"
    elif "session - 3" in low or "session 3" in low or "session-3" in low or "session  3" in low:
        session_str = "Session-3"
    elif "session - 2" in low or "session 2" in low or "session-2" in low or "session  2" in low or "session-ii" in low or "session ii" in low:
        session_str = "Session-2"
    elif "session - 1" in low or "session 1" in low or "session-1" in low or "session  1" in low or "session-i" in low or "session i" in low:
        session_str = "Session-1"
    elif "april" in low or "apr" in low:
        session_str = "Session-2" if int(year) >= 2022 else "Session-April"
    elif "march" in low or "mar" in low:
        session_str = "Session-2" if int(year) == 2021 else "Session-March"
    elif "february" in low or "feb" in low:
        session_str = "Session-1" if int(year) == 2021 else "Session-Feb"
    elif "january" in low or "jan" in low:
        session_str = "Session-1" if int(year) >= 2022 else "Session-Jan"

    # Determine Paper
    paper_str = "Paper-1"
    if "paper 2" in low or "paper-2" in low or "paper-ii" in low or "paper ii" in low or "b.arch" in low or "b.plan" in low:
        paper_str = "Paper-2"

    # Determine Document Type
    doc_type = "Notice"
    if "question paper" in low or ("b tech" in low and any(s in low for s in ["apr", "shift"])):
        doc_type = "Question-Paper"
    elif any(k in low for k in ["final answer key", "final provisional answer key", "provisional final key", "final key", "final-answer-key"]):
        doc_type = "Final-Answer-Key"
    elif "answer key" in low or "answer keys" in low:
        if any(w in low for w in ["provisional", "challenge", "display"]):
            doc_type = "Provisional-Answer-Key-Notice"
        else:
            doc_type = "Answer-Key"

    # Extract Shift & Exam Date
    shift = "Shift-General"
    shift_m = re.search(r'shift\s*[-–]?\s*([12])', low)
    if shift_m:
        shift = f"Shift-{shift_m.group(1)}"

    exam_date = ""
    date_m = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s*(apr|jan|feb|mar|jul|aug|sep|oct)\w*\s*(20\d\d)?', low)
    if date_m:
        day = date_m.group(1).zfill(2)
        month_str = date_m.group(2)[:3]
        months = {"jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06","jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"}
        m_num = months.get(month_str, "04")
        y_str = date_m.group(3) or year
        exam_date = f"{y_str}-{m_num}-{day}"

    # Target folder:
    # JEE_Main_PYQ_Archive/<Year>/<Session>/Question-Papers or Answer-Keys or Notices
    subfolder = "Answer-Keys"
    if doc_type == "Question-Paper":
        subfolder = "Question-Papers"
    elif "Notice" in doc_type:
        subfolder = "Notices"

    target_dir = os.path.join(ARCHIVE_DIR, year, session_str, subfolder)

    # Standardized filename
    # e.g.: JEE_Main_2026_Session-2_2026-04-02_Shift-1_Question-Paper.pdf
    # e.g.: JEE_Main_2026_Session-2_Paper-1_Final-Answer-Key.pdf
    date_part = f"_{exam_date}" if exam_date else ""
    shift_part = f"_{shift}" if shift != "Shift-General" else ""
    paper_part = f"_{paper_str}" if "Final-Answer-Key" in doc_type or "Answer-Key" in doc_type else ""

    filename = f"JEE_Main_{year}_{session_str}{date_part}{shift_part}{paper_part}_{doc_type}.pdf"
    filename = re.sub(r'__+', '_', filename)

    metadata = {
        "year": year,
        "session": session_str,
        "paper": paper_str,
        "exam_date": exam_date,
        "shift": shift if shift != "Shift-General" else "",
        "document_type": doc_type,
        "title": title,
        "official_source_page_url": item.get("source_page", ""),
        "direct_document_url": url,
        "target_dir": target_dir,
        "local_filename": filename
    }

    return metadata, None

# Process candidate files
manifest_records = []
known_hashes = {}  # sha256 -> local_filepath
downloaded_count = 0
skipped_duplicate_count = 0
failed_count = 0
manual_review_count = 0

for url, item in candidates_by_url.items():
    meta, err = parse_metadata(item)
    if err:
        print(f"[MANUAL REVIEW] {url}: {err}")
        manual_review_count += 1
        manifest_records.append({
            "year": "Unknown",
            "session": "",
            "exam_date": "",
            "shift": "",
            "paper": "",
            "document_type": "Unknown",
            "title": item.get("title", ""),
            "official_source_page_url": item.get("source_page", ""),
            "direct_document_url": url,
            "local_filename": "",
            "download_status": "manual_review",
            "http_status": "",
            "file_size_bytes": 0,
            "sha256_hash": "",
            "date_downloaded": "",
            "notes": err
        })
        continue

    # Create destination directory
    os.makedirs(meta["target_dir"], exist_ok=True)
    target_path = os.path.join(meta["target_dir"], meta["local_filename"])

    # If file exists already on disk, check if it's already recorded
    if os.path.exists(target_path):
        # We don't overwrite existing files
        # Check if identical or append index
        base, ext = os.path.splitext(meta["local_filename"])
        idx = 2
        while os.path.exists(os.path.join(meta["target_dir"], f"{base}_{idx}{ext}")):
            idx += 1
        target_path = os.path.join(meta["target_dir"], f"{base}_{idx}{ext}")
        meta["local_filename"] = f"{base}_{idx}{ext}"

    print(f"Downloading [{meta['year']} {meta['session']} {meta['document_type']}]: {meta['title'][:60]}...")
    try:
        time.sleep(0.6)  # polite rate limiting
        resp = session.get(url, timeout=30, stream=True)
        http_status = resp.status_code
        if resp.status_code != 200:
            print(f"  [HTTP {resp.status_code}] Failed for {url}")
            failed_count += 1
            manifest_records.append({
                **meta,
                "download_status": f"failed_http_{resp.status_code}",
                "http_status": resp.status_code,
                "file_size_bytes": 0,
                "sha256_hash": "",
                "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
                "notes": f"HTTP {resp.status_code}"
            })
            continue

        raw_data = resp.content
        file_size = len(raw_data)
        hasher = hashlib.sha256()
        hasher.update(raw_data)
        file_hash = hasher.hexdigest()

        # Validation: check PDF magic number %PDF-
        if not raw_data.startswith(b'%PDF-') or file_size < 1000:
            print(f"  [INVALID / CORRUPT] Size: {file_size} bytes. Moving to quarantine.")
            quarantine_path = os.path.join(QUARANTINE_DIR, meta["local_filename"])
            with open(quarantine_path, "wb") as f:
                f.write(raw_data)
            failed_count += 1
            manifest_records.append({
                **meta,
                "download_status": "quarantined_invalid_pdf",
                "http_status": http_status,
                "file_size_bytes": file_size,
                "sha256_hash": file_hash,
                "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
                "notes": f"Quarantined: not a valid PDF or file too small ({file_size} bytes)"
            })
            continue

        # Duplicate check by SHA-256
        if file_hash in known_hashes:
            orig_file = known_hashes[file_hash]
            print(f"  [DUPLICATE] Identical to {orig_file}. Recording duplicate in manifest.")
            skipped_duplicate_count += 1
            manifest_records.append({
                **meta,
                "local_filename": os.path.relpath(orig_file, ARCHIVE_DIR),
                "download_status": "skipped_duplicate",
                "http_status": http_status,
                "file_size_bytes": file_size,
                "sha256_hash": file_hash,
                "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
                "notes": f"Duplicate of {os.path.basename(orig_file)}"
            })
            continue

        # Save valid file
        with open(target_path, "wb") as f:
            f.write(raw_data)

        known_hashes[file_hash] = target_path
        downloaded_count += 1
        print(f"  [SUCCESS] Saved as {meta['local_filename']} ({file_size} bytes, SHA-256: {file_hash[:8]}...)")

        manifest_records.append({
            **meta,
            "local_filename": os.path.relpath(target_path, ARCHIVE_DIR),
            "download_status": "success",
            "http_status": http_status,
            "file_size_bytes": file_size,
            "sha256_hash": file_hash,
            "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": "Verified authentic PDF"
        })

    except Exception as e:
        print(f"  [EXCEPTION] {url}: {e}")
        failed_count += 1
        manifest_records.append({
            **meta,
            "download_status": "failed_exception",
            "http_status": "",
            "file_size_bytes": 0,
            "sha256_hash": "",
            "date_downloaded": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": str(e)
        })

# Clean target_dir from manifest records before writing
clean_manifest = []
for r in manifest_records:
    item = dict(r)
    if "target_dir" in item:
        del item["target_dir"]
    clean_manifest.append(item)

# Write manifest.json
with open(MANIFEST_JSON, "w", encoding="utf-8") as f:
    json.dump(clean_manifest, f, indent=2)
print(f"\nSaved {MANIFEST_JSON}")

# Write manifest.csv
fieldnames = [
    "year", "session", "paper", "exam_date", "shift", "document_type",
    "title", "official_source_page_url", "direct_document_url",
    "local_filename", "download_status", "http_status",
    "file_size_bytes", "sha256_hash", "date_downloaded", "notes"
]

with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in clean_manifest:
        writer.writerow(row)
print(f"Saved {MANIFEST_CSV}")

print("\n================ ARCHIVE SUMMARY ================")
print(f"Total processed: {len(candidates_by_url)}")
print(f"Successfully downloaded: {downloaded_count}")
print(f"Skipped duplicates: {skipped_duplicate_count}")
print(f"Failed downloads: {failed_count}")
print(f"Manual review items: {manual_review_count}")
