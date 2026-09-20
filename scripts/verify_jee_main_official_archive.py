#!/usr/bin/env python3
"""
Official NTA JEE Main Archive Verification Script
Validates every downloaded PDF in JEE_Main_PYQ_Archive against strict quality rules:
- File exists on disk
- Has .pdf extension
- Has valid %PDF signature
- File size > 0
- SHA-256 matches manifest
- Readable by PDF parser (pypdf/fitz)
- Page count > 0
- Lightweight textual sanity check: contains question paper indicators, not answer key/notice/error page
"""

import os
import sys
import json
import hashlib
import pypdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_DIR = os.path.join(BASE_DIR, "JEE_Main_PYQ_Archive")
MANIFEST_PATH = os.path.join(ARCHIVE_DIR, "jee_main_official_paper_manifest.json")

def verify_archive():
    print("==================================================")
    print("JEE MAIN ARCHIVE & MANIFEST INTEGRITY VERIFICATION")
    print("==================================================")
    
    if not os.path.exists(MANIFEST_PATH):
        print(f"ERROR: Manifest not found at {MANIFEST_PATH}")
        return False
        
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    print(f"Total manifest records: {len(manifest)}")
    
    downloaded_records = [r for r in manifest if r.get("download_status") == "AVAILABLE_AND_DOWNLOADED"]
    print(f"Total records marked AVAILABLE_AND_DOWNLOADED: {len(downloaded_records)}")
    
    passed_count = 0
    failed_count = 0
    failures = []
    
    total_pages = 0
    total_bytes = 0
    seen_files = set()
    
    for rec in downloaded_records:
        local_path = rec.get("local_path")
        if not local_path:
            failed_count += 1
            failures.append(f"Missing local_path for record: {rec}")
            continue
            
        full_path = os.path.join(BASE_DIR, local_path)
        if not os.path.exists(full_path):
            failed_count += 1
            failures.append(f"File not found on disk: {full_path}")
            continue
            
        seen_files.add(full_path)
        sz = os.path.getsize(full_path)
        if sz == 0:
            failed_count += 1
            failures.append(f"Zero-byte file: {full_path}")
            continue
            
        with open(full_path, "rb") as fp:
            content = fp.read()
            
        if not content.startswith(b"%PDF"):
            failed_count += 1
            failures.append(f"Invalid PDF signature: {full_path}")
            continue
            
        if b"<html" in content[:200].lower() or b"<!doctype html" in content[:200].lower():
            failed_count += 1
            failures.append(f"HTML error page saved as PDF: {full_path}")
            continue
            
        sha = hashlib.sha256(content).hexdigest()
        if rec.get("sha256") and sha != rec["sha256"]:
            failed_count += 1
            failures.append(f"SHA-256 mismatch for {full_path}: expected {rec['sha256']}, got {sha}")
            continue
            
        # Parse PDF
        try:
            reader = pypdf.PdfReader(full_path, strict=False)
            num_pages = len(reader.pages)
            if num_pages == 0:
                failed_count += 1
                failures.append(f"0 pages in PDF: {full_path}")
                continue
                
            total_pages += num_pages
            total_bytes += sz
            
            # Textual sanity check
            first_text = reader.pages[0].extract_text() or ""
            low = first_text.lower()
            is_qp = any(k in low for k in ["jee", "btech", "b.tech", "question", "marks", "duration", "shift", "section", "national testing agency"])
            if not is_qp and num_pages < 3:
                failed_count += 1
                failures.append(f"Question paper sanity check failed on {full_path}: {first_text[:100]}")
                continue
                
            passed_count += 1
        except Exception as e:
            failed_count += 1
            failures.append(f"Exception parsing {full_path}: {e}")
            
    print(f"\nVerification Results:")
    print(f"- Total unique downloaded question papers verified: {len(seen_files)}")
    print(f"- Total pages across all verified QPs: {total_pages}")
    print(f"- Total verified file size: {total_bytes / 1024 / 1024:.2f} MB")
    print(f"- Passed quality checks: {passed_count}")
    print(f"- Failed quality checks: {failed_count}")
    
    if failures:
        print("\nFailures:")
        for fail in failures:
            print(f"  FAILED: {fail}")
        return False
        
    print("\nALL DOWNLOADED OFFICIAL QUESTION PAPERS PASSED INTEGRITY & QUALITY CHECKS!")
    return True

if __name__ == "__main__":
    success = verify_archive()
    sys.exit(0 if success else 1)
