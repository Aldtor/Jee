"""
scripts/extract_all_papers.py

Master extraction pipeline that processes all 170 JEE Main PDFs.
Uses format-adaptive parsers to extract structured question data.

Usage:
    python scripts/extract_all_papers.py [--year YEAR] [--limit N] [--format FORMAT]
"""
import json
import os
import sys
import argparse
import time
from datetime import datetime
from collections import defaultdict

# Add scripts dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parsers.base_parser import ExtractionResult
from parsers.clean_tabular_parser import CleanTabularParser
from parsers.recorded_response_parser import RecordedResponseParser
from parsers.jee_main_qp_parser import JeeMainQPParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(REPO, "JEE_Main_PYQ_Archive")
INVENTORY = os.path.join(REPO, "audit", "jee_main_content_source_inventory.json")
OUTPUT_DIR = os.path.join(REPO, "JEE_QUESTION_DATABASE_FINAL")
EXTRACTION_DIR = os.path.join(OUTPUT_DIR, "extraction")


def get_parser(format_type: str, pdf_path: str, output_dir: str, skip_images: bool = False):
    """Get the appropriate parser for the PDF format."""
    if format_type == "CLEAN_TABULAR":
        return CleanTabularParser(pdf_path, output_dir, skip_images=skip_images)
    elif format_type == "JEE_MAIN_QP":
        return JeeMainQPParser(pdf_path, output_dir, skip_images=skip_images)
    elif format_type in ("RECORDED_RESPONSE", "UNKNOWN"):
        return RecordedResponseParser(pdf_path, output_dir, skip_images=skip_images)
    else:
        return RecordedResponseParser(pdf_path, output_dir, skip_images=skip_images)


def process_paper(paper: dict, output_dir: str, skip_images: bool = False) -> dict:
    """Process a single paper and return extraction results."""
    local_path = paper.get("local_path", "")
    full_path = os.path.join(REPO, local_path) if not os.path.isabs(local_path) else local_path
    
    if not os.path.exists(full_path):
        return {"error": f"File not found: {local_path}", "source_id": paper.get("source_id")}
    
    format_type = paper.get("format_type", "UNKNOWN")
    
    try:
        parser = get_parser(format_type, full_path, output_dir, skip_images=skip_images)
        result = parser.parse()
        
        # Supplement metadata from inventory
        if paper.get("year"):
            result.metadata.year = paper["year"]
        if paper.get("session"):
            result.metadata.session = paper["session"]
        if paper.get("exam_date"):
            result.metadata.exam_date = paper["exam_date"]
        if paper.get("shift"):
            result.metadata.shift = paper["shift"]
        if paper.get("language"):
            result.metadata.language = paper["language"]
        
        return result.to_dict()
    
    except Exception as e:
        return {
            "error": str(e),
            "source_id": paper.get("source_id"),
            "source_path": full_path,
        }


def main():
    parser = argparse.ArgumentParser(description="Extract all JEE Main papers")
    parser.add_argument("--year", type=int, help="Process only this year")
    parser.add_argument("--limit", type=int, help="Limit number of papers")
    parser.add_argument("--format", choices=["CLEAN_TABULAR", "RECORDED_RESPONSE"], help="Process only this format")
    parser.add_argument("--skip-images", action="store_true", help="Skip image extraction (faster)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("JEE MAIN CONTENT EXTRACTION PIPELINE")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Load source inventory
    if not os.path.exists(INVENTORY):
        print("ERROR: Source inventory not found. Run build_source_inventory.py first.")
        return 1
    
    with open(INVENTORY, "r", encoding="utf-8") as f:
        inventory = json.load(f)
    
    papers = inventory.get("papers", [])
    print(f"Total papers in inventory: {len(papers)}")
    
    # Apply filters
    if args.year:
        papers = [p for p in papers if p["year"] == args.year]
        print(f"Filtered to year {args.year}: {len(papers)} papers")
    
    if args.format:
        papers = [p for p in papers if p["format_type"] == args.format]
        print(f"Filtered to format {args.format}: {len(papers)} papers")
    
    if args.limit:
        papers = papers[:args.limit]
        print(f"Limited to {args.limit} papers")
    
    # Create output directories
    os.makedirs(EXTRACTION_DIR, exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "assets", "questions"), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, "assets", "options"), exist_ok=True)
    
    # Process papers
    results = []
    errors = []
    total_questions = 0
    total_mcq = 0
    total_numerical = 0
    total_with_text = 0
    total_needs_review = 0
    
    start_time = time.time()
    
    for i, paper in enumerate(papers):
        source_id = paper.get("source_id", f"paper_{i}")
        fmt = paper.get("format_type", "UNKNOWN")
        
        print(f"\n[{i+1}/{len(papers)}] {source_id} ({fmt})...", end=" ", flush=True)
        
        try:
            result = process_paper(paper, OUTPUT_DIR, skip_images=args.skip_images)
            
            if "error" in result and "questions" not in result:
                print(f"ERROR: {result['error'][:60]}")
                errors.append(result)
                continue
            
            # Save per-paper extraction result
            output_file = os.path.join(EXTRACTION_DIR, f"{source_id}.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            q_count = result.get("summary", {}).get("total_questions", 0)
            mcq_count = result.get("summary", {}).get("mcq", 0)
            num_count = result.get("summary", {}).get("numerical", 0)
            text_count = result.get("summary", {}).get("with_text", 0)
            review_count = result.get("summary", {}).get("needs_review", 0)
            
            total_questions += q_count
            total_mcq += mcq_count
            total_numerical += num_count
            total_with_text += text_count
            total_needs_review += review_count
            
            print(f"OK ({q_count} Qs: {mcq_count} MCQ + {num_count} NUM, {text_count} with text)")
            
            results.append({
                "source_id": source_id,
                "year": paper["year"],
                "format": fmt,
                "questions": q_count,
                "mcq": mcq_count,
                "numerical": num_count,
                "with_text": text_count,
                "needs_review": review_count,
            })
        
        except Exception as e:
            print(f"EXCEPTION: {str(e)[:60]}")
            errors.append({"source_id": source_id, "error": str(e)})
    
    elapsed = time.time() - start_time
    
    # Generate summary
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"Papers processed: {len(results)}")
    print(f"Papers failed: {len(errors)}")
    print(f"Total questions: {total_questions}")
    print(f"  MCQ: {total_mcq}")
    print(f"  Numerical: {total_numerical}")
    print(f"  With text: {total_with_text}")
    print(f"  Needs review: {total_needs_review}")
    print(f"Elapsed: {elapsed:.1f}s")
    
    # By year
    by_year = defaultdict(lambda: {"papers": 0, "questions": 0, "with_text": 0})
    for r in results:
        yd = by_year[r["year"]]
        yd["papers"] += 1
        yd["questions"] += r["questions"]
        yd["with_text"] += r["with_text"]
    
    print("\nPer year:")
    for year in sorted(by_year):
        yd = by_year[year]
        print(f"  {year}: {yd['papers']} papers, {yd['questions']} questions, {yd['with_text']} with text")
    
    # Save extraction log
    log = {
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "papers_processed": len(results),
        "papers_failed": len(errors),
        "total_questions": total_questions,
        "total_mcq": total_mcq,
        "total_numerical": total_numerical,
        "total_with_text": total_with_text,
        "total_needs_review": total_needs_review,
        "by_year": dict(by_year),
        "results": results,
        "errors": errors,
    }
    
    log_path = os.path.join(EXTRACTION_DIR, "extraction_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    print(f"\nLog: {log_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
