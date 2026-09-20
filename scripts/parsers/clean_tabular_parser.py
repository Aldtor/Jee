"""
scripts/parsers/clean_tabular_parser.py

Parser for the 2022 NTA JEE Main "Clean Tabular" PDF format (Session-2).
Metadata is in the text layer but question content is image-based.

Structure per question:
  Topic: Physics-Section A
  Item No: 1
  Question ID: 15477154561
  Question Type: MCQ
  Question: [image content - not extractable as text]
  A: [image content]
  B: [image content]
  C: [image content]
  D: [image content]
"""
import re
import os
import hashlib
import pymupdf
from datetime import datetime
from typing import List, Optional
from .base_parser import (
    BaseParser, ExtractionResult, ExtractedQuestion, ExtractedOption,
    PaperMetadata
)


class CleanTabularParser(BaseParser):
    """Parser for 2022 NTA JEE Main Clean Tabular format (Session-2)."""
    
    FORMAT_TYPE = "CLEAN_TABULAR"
    
    def parse(self) -> ExtractionResult:
        """Parse a 2022 Session-2 format PDF."""
        import pypdf
        
        with open(self.pdf_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        
        reader = pypdf.PdfReader(self.pdf_path, strict=False)
        total_pages = len(reader.pages)
        
        full_text = ""
        page_texts = []
        for i in range(total_pages):
            pt = reader.pages[i].extract_text() or ""
            page_texts.append(pt)
            full_text += pt + "\n"
        
        # Extract metadata
        meta = self.extract_paper_metadata_from_text(page_texts[0] if page_texts else "")
        
        # Parse questions
        questions = self._parse_questions(full_text, page_texts)
        
        # Extract question images (unless skipped)
        if not self.skip_images:
            self._extract_question_images(questions)
        
        result = ExtractionResult(
            source_path=self.pdf_path,
            source_sha256=sha256,
            format_type=self.FORMAT_TYPE,
            metadata=meta,
            questions=questions,
            total_pages=total_pages,
            extraction_timestamp=datetime.now().isoformat(),
        )
        
        return result
    
    def _parse_questions(self, full_text: str, page_texts: List[str]) -> List[ExtractedQuestion]:
        """Parse question metadata from the clean tabular format."""
        questions = []
        
        # Find all Item No occurrences with their metadata
        # Pattern: Topic: ... Item No: N ... Question ID: ... Question Type: ...
        blocks = re.split(r"(?=Topic\s*:\s*\S)", full_text)
        
        for block in blocks:
            if not block.strip():
                continue
            
            topic_m = re.search(r"Topic\s*:\s*(.+?)(?:\n|$)", block)
            item_m = re.search(r"Item No\s*:\s*(\d+)", block)
            qid_m = re.search(r"Question ID\s*:\s*(\d+)", block)
            qt_m = re.search(r"Question Type\s*:\s*(\w+)", block)
            
            if not item_m:
                continue
            
            item_no = int(item_m.group(1))
            topic_text = topic_m.group(1).strip() if topic_m else ""
            nta_id = qid_m.group(1) if qid_m else None
            q_type_raw = qt_m.group(1) if qt_m else "MCQ"
            
            # Normalize question type
            if q_type_raw.upper() in ("MCQ",):
                q_type = "MCQ"
            elif q_type_raw.upper() in ("NUMERIC", "SA", "NUMERICAL"):
                q_type = "NUMERICAL"
            else:
                q_type = q_type_raw.upper()
            
            subject = self.classify_subject(topic_text)
            section = self.classify_section(topic_text)
            
            # Source page
            source_page = self._find_page_for_item(item_no, page_texts)
            
            # Build options (MCQ only)
            options = []
            if q_type == "MCQ":
                for i, label in enumerate(["A", "B", "C", "D"]):
                    options.append(ExtractedOption(
                        option_index=i + 1,
                        label=label,
                        text=None,  # Content is image-based
                        extraction_confidence=0.0,
                    ))
            
            # Determine marks from section
            if "Section A" in topic_text or "Section-A" in topic_text:
                correct_marks = 4.0
                wrong_marks = 1.0
            elif "Section B" in topic_text or "Section-B" in topic_text:
                correct_marks = 4.0
                wrong_marks = 0.0  # No negative for numerical
            else:
                correct_marks = 4.0
                wrong_marks = 1.0 if q_type == "MCQ" else 0.0
            
            q = ExtractedQuestion(
                question_number=item_no,
                nta_question_id=nta_id,
                question_type=q_type,
                subject=subject,
                section=section,
                question_text=None,  # All content is image-based
                options=options,
                correct_marks=correct_marks,
                wrong_marks=wrong_marks,
                source_page=source_page,
                extraction_method="CLEAN_TABULAR_METADATA",
                extraction_confidence=0.5,
                needs_review=True,
                review_reason="Image-based content in CLEAN_TABULAR format",
            )
            questions.append(q)
        
        return questions
    
    def _find_page_for_item(self, item_no: int, page_texts: List[str]) -> Optional[int]:
        """Find which page an item number appears on."""
        pattern = rf"Item No\s*:\s*{item_no}\b"
        for i, pt in enumerate(page_texts):
            if re.search(pattern, pt):
                return i + 1
        return None
    
    def _extract_question_images(self, questions: List[ExtractedQuestion]):
        """Render page images for all questions."""
        doc = pymupdf.open(self.pdf_path)
        
        assets_dir = os.path.join(self.output_dir, "assets", "questions")
        os.makedirs(assets_dir, exist_ok=True)
        
        for q in questions:
            if not q.source_page or q.source_page > doc.page_count:
                continue
            
            page = doc[q.source_page - 1]
            pix = page.get_pixmap(dpi=200)
            img_filename = f"q_{self.basename}_item{q.question_number:03d}.png"
            img_path = os.path.join(assets_dir, img_filename)
            pix.save(img_path)
            q.question_image_path = os.path.relpath(img_path, self.output_dir)
        
        doc.close()
