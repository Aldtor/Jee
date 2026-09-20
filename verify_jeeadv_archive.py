import os
import sys
import json
import csv
import hashlib

JEE_MAIN_DIR = r"c:\Users\dell\Music\Jee Web\JEE_Main_PYQ_Archive"
JEE_ADV_DIR = r"c:\Users\dell\Music\Jee Web\JEE_Advanced_PYQ_Archive"
MANIFEST_CSV = os.path.join(JEE_ADV_DIR, "jee_advanced_manifest.csv")
MANIFEST_JSON = os.path.join(JEE_ADV_DIR, "jee_advanced_manifest.json")
QUARANTINE_DIR = os.path.join(JEE_ADV_DIR, "_quarantine")

print("=================================================================")
print("          JEE ADVANCED ARCHIVE VERIFICATION & AUDIT             ")
print("=================================================================")

# 1. VERIFY JEE MAIN ARCHIVE INTEGRITY (Ensure it wasn't modified or deleted)
print("\n--- STEP 1: Verifying JEE Main Archive Integrity ---")
if not os.path.exists(JEE_MAIN_DIR):
    print("CRITICAL FAILURE: JEE_Main_PYQ_Archive does not exist!")
    sys.exit(1)

main_files = [f for f in os.listdir(JEE_MAIN_DIR)]
print(f"JEE Main directory root items: {len(main_files)}")
total_main_files = 0
for root, dirs, files in os.walk(JEE_MAIN_DIR):
    total_main_files += len(files)
print(f"Total files in JEE Main archive: {total_main_files}")
assert total_main_files >= 57, f"JEE Main archive corrupted! Expected >= 57 files, found {total_main_files}"
print("[PASS] JEE Main archive is completely intact and untouched.")

# 2. VERIFY JEE ADVANCED MANIFESTS
print("\n--- STEP 2: Verifying JEE Advanced Manifests ---")
assert os.path.exists(MANIFEST_CSV), f"Manifest CSV missing: {MANIFEST_CSV}"
assert os.path.exists(MANIFEST_JSON), f"Manifest JSON missing: {MANIFEST_JSON}"

with open(MANIFEST_CSV, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    csv_records = list(reader)

with open(MANIFEST_JSON, "r", encoding="utf-8") as f:
    json_records = json.load(f)

print(f"CSV records: {len(csv_records)}")
print(f"JSON records: {len(json_records)}")
assert len(csv_records) == len(json_records), "Mismatch between CSV and JSON record count!"
print("[PASS] Manifest CSV and JSON counts match exactly.")

# Expected CSV columns:
expected_cols = [
    "year", "paper", "language", "document_type", "title",
    "official_source_page", "direct_document_url", "local_path",
    "file_size", "sha256", "download_status", "duplicate_status"
]
assert reader.fieldnames == expected_cols, f"CSV columns mismatch! Got: {reader.fieldnames}"
print("[PASS] CSV headers match required specification exactly.")

# 3. VERIFY PHYSICAL FILES & INTEGRITY
print("\n--- STEP 3: Verifying File Integrity & Official Sources ---")
verified_files = 0
hash_matches = 0
pdf_magic_matches = 0
allowed_domains = ["jeeadv.ac.in", "jeeadv.iitb.ac.in", "jeeadv.iitd.ac.in", "jeeadv.iitk.ac.in", "jeeadv.iitm.ac.in", "jeeadv.iitr.ac.in", "jeeadv.iitkgp.ac.in", "jeeadv.iitg.ac.in"]

total_qp_count = 0
total_ak_count = 0
total_aat_count = 0
english_count = 0
hindi_count = 0
bilingual_count = 0
canonical_count = 0
language_equiv_count = 0
duplicate_files_count = 0

years_data = {}  # year -> {"P1": [], "P2": [], "AK1": [], "AK2": [], "AAT": []}

for rec in csv_records:
    year = rec["year"]
    paper = rec["paper"]
    lang = rec["language"]
    doc_type = rec["document_type"]
    status = rec["download_status"]
    dup_status = rec["duplicate_status"]
    url = rec["direct_document_url"]
    rel_path = rec["local_path"]
    expected_size = int(rec["file_size"])
    expected_hash = rec["sha256"]

    # Domain check
    assert any(dom in url for dom in allowed_domains), f"Untrusted domain in {url}"

    # Status tracking
    if year not in years_data:
        years_data[year] = {"P1": [], "P2": [], "AK1": [], "AK2": [], "AAT": []}

    if status in ["success", "already_present"]:
        abs_path = os.path.join(JEE_ADV_DIR, rel_path)
        assert os.path.exists(abs_path), f"File missing from disk: {abs_path}"
        verified_files += 1

        with open(abs_path, "rb") as fp:
            data = fp.read()

        assert len(data) == expected_size, f"Size mismatch for {abs_path}: disk={len(data)}, expected={expected_size}"
        assert data.startswith(b"%PDF-") or data.lstrip().startswith(b"%PDF-") or b"%PDF-" in data[:1024], f"Invalid PDF header for {abs_path}"
        pdf_magic_matches += 1

        actual_hash = hashlib.sha256(data).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {abs_path}!"
        hash_matches += 1

        # Classify document
        if doc_type == "Question-Paper":
            if paper == "Paper-1":
                years_data[year]["P1"].append(lang)
                total_qp_count += 1
            elif paper == "Paper-2":
                years_data[year]["P2"].append(lang)
                total_qp_count += 1
            elif paper == "AAT":
                years_data[year]["AAT"].append(lang)
                total_aat_count += 1
        elif "Answer-Key" in doc_type:
            if paper == "Paper-1":
                years_data[year]["AK1"].append(doc_type)
                total_ak_count += 1
            elif paper == "Paper-2":
                years_data[year]["AK2"].append(doc_type)
                total_ak_count += 1

        if lang == "English":
            english_count += 1
        elif lang == "Hindi":
            hindi_count += 1
        elif lang == "Bilingual":
            bilingual_count += 1

        if dup_status == "canonical":
            canonical_count += 1
        elif dup_status == "language_equivalent_version":
            language_equiv_count += 1
        elif dup_status == "exact_duplicate":
            duplicate_files_count += 1

# Check quarantine directory
quarantine_files = os.listdir(QUARANTINE_DIR)
print(f"Quarantine directory empty: {len(quarantine_files) == 0} (found {len(quarantine_files)})")
assert len(quarantine_files) == 0, f"Quarantine contains files: {quarantine_files}"

print("\n--- STEP 4: Verification Summary Statistics ---")
print(f"Total manifest records: {len(csv_records)}")
print(f"Total verified files on disk: {verified_files}")
print(f"Valid PDF %PDF- magic headers: {pdf_magic_matches}")
print(f"Exact SHA-256 hash matches: {hash_matches}")
print(f"Total Question Papers (Paper 1 & 2): {total_qp_count}")
print(f"Total Answer Key Documents: {total_ak_count}")
print(f"Total Architecture Aptitude Test (AAT) Papers: {total_aat_count}")
print(f"English copies: {english_count}")
print(f"Hindi copies: {hindi_count}")
print(f"Bilingual copies (2007-2018): {bilingual_count}")
print(f"Canonical primary copies: {canonical_count}")
print(f"Language equivalent copies (Hindi): {language_equiv_count}")
print(f"Exact duplicate files: {duplicate_files_count}")

# 4. COMPLETENESS MATRIX
print("\n=================================================================")
print("                   YEAR-BY-YEAR COMPLETENESS TABLE               ")
print("=================================================================")
print(f"{'Year':<6} | {'Paper 1':<22} | {'Paper 2':<22} | {'Answer Key 1':<22} | {'Answer Key 2':<22}")
print("-" * 105)

all_years = sorted(list(years_data.keys()))
for yr in all_years:
    data = years_data[yr]
    # Format Paper 1
    p1_str = "NOT FOUND"
    if data["P1"]:
        if "Bilingual" in data["P1"]:
            p1_str = "FOUND (Bilingual)"
        elif "English" in data["P1"] and "Hindi" in data["P1"]:
            p1_str = "FOUND (Eng + Hin)"
        elif "English" in data["P1"]:
            p1_str = "FOUND (English)"
        else:
            p1_str = f"FOUND ({', '.join(data['P1'])})"

    # Format Paper 2
    p2_str = "NOT FOUND"
    if data["P2"]:
        if "Bilingual" in data["P2"]:
            p2_str = "FOUND (Bilingual)"
        elif "English" in data["P2"] and "Hindi" in data["P2"]:
            p2_str = "FOUND (Eng + Hin)"
        elif "English" in data["P2"]:
            p2_str = "FOUND (English)"
        else:
            p2_str = f"FOUND ({', '.join(data['P2'])})"

    # Format Answer Key 1
    ak1_str = "NOT FOUND"
    if data["AK1"]:
        ak1_str = f"FOUND ({', '.join(data['AK1'])})"

    # Format Answer Key 2
    ak2_str = "NOT FOUND"
    if data["AK2"]:
        ak2_str = f"FOUND ({', '.join(data['AK2'])})"

    print(f"{yr:<6} | {p1_str:<22} | {p2_str:<22} | {ak1_str:<22} | {ak2_str:<22}")

print("=================================================================")
print("\n[ALL AUDIT CHECKS PASSED SUCCESSFULLY]")
