"""
audit/build_database_pipeline.py
Complete, production-grade audit, extraction, classification, verification,
and relational database export pipeline for JEE Main and JEE Advanced.
"""

import json
import os
import re
import csv
from datetime import datetime
import fitz
from PIL import Image

# Directories
BASE_DIR = r"c:\Users\dell\Music\Jee Web"
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
JM_DIR = os.path.join(DB_DIR, "JEE_MAIN")
JA_DIR = os.path.join(DB_DIR, "JEE_ADVANCED")
UNIFIED_DIR = os.path.join(DB_DIR, "UNIFIED")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")
REVIEW_DIR = os.path.join(BASE_DIR, "review")
BACKUP_DIR = os.path.join(BASE_DIR, "backup_before_audit")

JM_ARCHIVE = os.path.join(BASE_DIR, "JEE_Main_PYQ_Archive")
JA_ARCHIVE = os.path.join(BASE_DIR, "JEE_Advanced_PYQ_Archive")

os.makedirs(AUDIT_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "database_import"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "questions"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "review"), exist_ok=True)
os.makedirs(os.path.join(JM_DIR, "questions"), exist_ok=True)
os.makedirs(os.path.join(JA_DIR, "questions"), exist_ok=True)

# Load Canonical Taxonomy
with open(os.path.join(UNIFIED_DIR, "database_import", "chapters_import.jsonl"), "r", encoding="utf-8") as f:
    ALL_CHAPTERS = [json.loads(line) for line in f]
with open(os.path.join(UNIFIED_DIR, "database_import", "topics_import.jsonl"), "r", encoding="utf-8") as f:
    ALL_TOPICS = [json.loads(line) for line in f]

CHAPTERS_BY_SUB = {
    "Physics": [c["chapter_name"] for c in ALL_CHAPTERS if c["subject"] == "Physics"],
    "Chemistry": [c["chapter_name"] for c in ALL_CHAPTERS if c["subject"] == "Chemistry"],
    "Mathematics": [c["chapter_name"] for c in ALL_CHAPTERS if c["subject"] == "Mathematics"]
}

TOPICS_BY_CHAP = {}
for t in ALL_TOPICS:
    cname = t["chapter_name"]
    if cname not in TOPICS_BY_CHAP:
        TOPICS_BY_CHAP[cname] = []
    TOPICS_BY_CHAP[cname].append(t["topic_name"])

# Load Marking Schemes
with open(os.path.join(UNIFIED_DIR, "database_import", "marking_schemes_import.jsonl"), "r", encoding="utf-8") as f:
    MARKING_SCHEMES = [json.loads(line) for line in f]
MS_MAP = {s["marking_scheme_id"]: s for s in MARKING_SCHEMES}

print(f"Taxonomy loaded: {len(ALL_CHAPTERS)} chapters, {len(ALL_TOPICS)} topics.")
print(f"Marking schemes loaded: {len(MARKING_SCHEMES)} schemes.")
