"""
scripts/parsers/jee_main_qp_parser.py

Parser for the 2022 Session-1 NTA JEE Main "JEE(Main) QP" format.
Uses Q:N, Topic Name:, ItemCode:, with question content as images.

Structure per question:
  Q:N
  Topic Name:Physics-Section A
  ItemCode:101661
  Question: [image content]
  A [image option]
  B [image option]
  C [image option]
  D [image option]
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


class JeeMainQPParser(BaseParser):
    """Parser for 2022 Session-1 NTA JEE Main QP format."""
    
    FORMAT_TYPE = "JEE_MAIN_QP"
    
    def parse(self) -> ExtractionResult:
        """Parse a JEE(Main) QP format PDF."""
        import pypdf
        
        with open(self.pdf_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        
        reader = pypdf.PdfReader(self.pdf_path, strict=False)
        total_pages = len(reader.pages)
        
        page_texts = []
        full_text = ""
        for i in range(total_pages):
            pt = reader.pages[i].extract_text() or ""
            page_texts.append(pt)
            full_text += pt + "\n"
        
        # Extract metadata from header
        meta = self._extract_qp_metadata(page_texts[0] if page_texts else "")
        
        # Parse questions
        questions = self._parse_questions(full_text, page_texts)
        
        # Extract question images
        if not self.skip_images:
            self._extract_images(questions)
        
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
    
    def _extract_qp_metadata(self, first_page: str) -> PaperMetadata:
        """Extract metadata from QP header."""
        meta = PaperMetadata()
        
        # Paper Name
        m = re.search(r"Paper\s*Name\s+(.+?)(?:\n|$)", first_page)
        if m:
            meta.paper_type = m.group(1).strip()
        
        # Test Date
        m = re.search(r"Test\s*Date\s+(.+?)(?:\n|$)", first_page)
        if m:
            meta.exam_date = m.group(1).strip()
            year_m = re.search(r"(\d{4})", m.group(1))
            if year_m:
                meta.year = int(year_m.group(1))
        
        # Slot
        m = re.search(r"Slot\s+SLOT\s*-?\s*(\d+)", first_page, re.I)
        if m:
            meta.shift = int(m.group(1))
        
        # Language
        m = re.search(r"Lang\s+(\w+)", first_page)
        if m:
            meta.language = m.group(1).strip()
        
        return meta
    
    def _parse_questions(self, full_text: str, page_texts: List[str]) -> List[ExtractedQuestion]:
        """Parse questions from QP format."""
        questions = []
        
        # Split by "Q:N" boundaries
        blocks = re.split(r"(?=Q\s*:\s*\d+)", full_text)
        
        for block in blocks:
            if not block.strip():
                continue
            
            # Extract question number
            qn_m = re.match(r"Q\s*:\s*(\d+)", block)
            if not qn_m:
                continue
            
            q_num = int(qn_m.group(1))
            
            # Extract topic
            topic_m = re.search(r"Topic\s*Name\s*:\s*(.+?)(?:\n|$)", block)
            topic_text = topic_m.group(1).strip() if topic_m else ""
            
            # Extract item code
            item_m = re.search(r"ItemCode\s*:\s*(\d+)", block)
            item_code = item_m.group(1) if item_m else None
            
            # Classify subject
            subject = self.classify_subject(topic_text)
            section = self.classify_section(topic_text)
            
            # Detect question type from section name
            if "Section B" in topic_text or "Section-B" in topic_text:
                q_type = "NUMERICAL"
            else:
                q_type = "MCQ"
            
            # Question text is in images — we cannot extract it from text layer
            # The text after "Question:" until A/B/C/D labels would be empty or minimal
            q_text = self._extract_question_text_attempt(block)
            
            # Options A-D
            options = self._extract_options_attempt(block)
            
            # Find source page
            source_page = self._find_page(q_num, page_texts)
            
            q = ExtractedQuestion(
                question_number=q_num,
                nta_question_id=item_code,
                question_type=q_type,
                subject=subject,
                section=section,
                question_text=q_text,
                options=options,
                source_page=source_page,
                extraction_method="JEE_MAIN_QP_METADATA",
                extraction_confidence=0.5 if q_text else 0.3,
                needs_review=True,
                review_reason="Image-based content in JEE_MAIN_QP format",
            )
            questions.append(q)
        
        return questions
    
    def _extract_question_text_attempt(self, block: str) -> Optional[str]:
        """Attempt to extract question text — often minimal in this format."""
        # Text between "Question:" and the first A/B/C/D label
        m = re.search(r"Question\s*:\s*\n?(.*?)(?:\n\s*[ABCD]\s*\n|\n\s*[ABCD]\s*$)", block, re.DOTALL)
        if m:
            text = m.group(1).strip()
            text = re.sub(r"\s+", " ", text)
            if text and len(text) > 3:
                return text
        return None
    
    def _extract_options_attempt(self, block: str) -> List[ExtractedOption]:
        """Attempt to extract option text — often image-based."""
        options = []
        labels = ["A", "B", "C", "D"]
        
        for i, label in enumerate(labels):
            opt = ExtractedOption(
                option_index=i + 1,
                label=label,
                text=None,  # Will be populated by image extraction
                extraction_confidence=0.0,
            )
            options.append(opt)
        
        return options
    
    def _find_page(self, q_num: int, page_texts: List[str]) -> Optional[int]:
        """Find which page a question appears on."""
        pattern = rf"Q\s*:\s*{q_num}\b"
        for i, pt in enumerate(page_texts):
            if re.search(pattern, pt):
                return i + 1
        return None
    
    def _extract_images(self, questions: List[ExtractedQuestion]):
        """Extract question images from the PDF."""
        doc = pymupdf.open(self.pdf_path)
        
        q_dir = os.path.join(self.output_dir, "assets", "questions")
        os.makedirs(q_dir, exist_ok=True)
        
        for q in questions:
            if not q.source_page or q.source_page > doc.page_count:
                continue
            
            page = doc[q.source_page - 1]
            pix = page.get_pixmap(dpi=200)
            img_filename = f"q_{self.basename}_q{q.question_number:03d}_page.png"
            img_path = os.path.join(q_dir, img_filename)
            pix.save(img_path)
            q.question_image_path = os.path.relpath(img_path, self.output_dir)
        
        doc.close()
