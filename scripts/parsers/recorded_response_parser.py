"""
scripts/parsers/recorded_response_parser.py

Parser for the NTA "Recorded Response" PDF format (2020-2021, 2023-2026).
Question content is embedded as images. Text layer has only metadata.

Structure per question:
  Question Number : N Question Id : XXXXX Question Type : MCQ ...
  Correct Marks : 4 Wrong Marks : 1
  Options :
  XXXXXXXXX.  [image]
  XXXXXXXXX.  [image]
  XXXXXXXXX.  [image]
  XXXXXXXXX.  [image]
"""
import re
import os
import hashlib
import pymupdf
from datetime import datetime
from typing import List, Optional, Tuple, Dict
from .base_parser import (
    BaseParser, ExtractionResult, ExtractedQuestion, ExtractedOption,
    PaperMetadata
)


class RecordedResponseParser(BaseParser):
    """Parser for 2020-2021, 2023-2026 NTA JEE Main Recorded Response format."""
    
    FORMAT_TYPE = "RECORDED_RESPONSE"
    
    def parse(self) -> ExtractionResult:
        """Parse a Recorded Response format PDF."""
        import pypdf
        
        with open(self.pdf_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        
        reader = pypdf.PdfReader(self.pdf_path, strict=False)
        total_pages = len(reader.pages)
        
        # Extract text from all pages
        page_texts = []
        full_text = ""
        for i in range(total_pages):
            pt = reader.pages[i].extract_text() or ""
            page_texts.append(pt)
            full_text += pt + "\n"
        
        # Extract metadata
        meta = self.extract_paper_metadata_from_text(page_texts[0] if page_texts else "")
        
        # Detect sections
        sections = self._detect_sections(full_text)
        
        # Parse question metadata from text layer
        questions = self._parse_question_metadata(full_text, page_texts, sections)
        
        # Extract question and option images from PDF
        if not self.skip_images:
            self._extract_images(questions, page_texts)
        
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
    
    def _detect_sections(self, full_text: str) -> List[Dict]:
        """Detect subject sections from the text layer."""
        sections = []
        
        # Look for section headers like "Mathematics Section A", "Physics Section B"
        pattern = r"((?:Mathematics|Physics|Chemistry)\s*(?:Sec(?:tion)?\s*[A-Z])?)"
        matches = list(re.finditer(pattern, full_text, re.IGNORECASE))
        
        seen = set()
        for m in matches:
            name = m.group(1).strip()
            if name.lower() not in seen:
                seen.add(name.lower())
                subject = self.classify_subject(name)
                section = self.classify_section(name)
                sections.append({
                    "name": name,
                    "subject": subject,
                    "section": section,
                    "text_pos": m.start(),
                })
        
        return sections
    
    def _parse_question_metadata(
        self, full_text: str, page_texts: List[str], sections: List[Dict]
    ) -> List[ExtractedQuestion]:
        """Parse question metadata from the text layer."""
        questions = []
        
        # Find all "Question Number : N" blocks
        pattern = (
            r"Question Number\s*:\s*(\d+)\s*"
            r"Question Id\s*:\s*(\d+)\s*"
            r"Question Type\s*:\s*(\w+)"
        )
        
        matches = list(re.finditer(pattern, full_text))
        
        # Also extract marks
        marks_pattern = r"Correct Marks\s*:\s*(\d+)\s*Wrong Marks\s*:\s*(\d+)"
        marks_matches = list(re.finditer(marks_pattern, full_text))
        
        # Build marks map by position
        marks_map = {}
        for mm in marks_matches:
            marks_map[mm.start()] = (float(mm.group(1)), float(mm.group(2)))
        
        # Extract option IDs per question
        option_pattern = r"Options\s*:\s*\n?((?:\d{5,}\.\s*\n?)+)"
        option_matches = list(re.finditer(option_pattern, full_text))
        
        # Deduplicate: same Q Number + Q ID can appear multiple times (bilingual)
        seen_questions = set()
        
        for i, m in enumerate(matches):
            q_num = int(m.group(1))
            q_id = m.group(2)
            q_type_raw = m.group(3)
            
            # Deduplicate
            dedup_key = (q_num, q_id)
            if dedup_key in seen_questions:
                continue
            seen_questions.add(dedup_key)
            
            # Normalize question type
            if q_type_raw.upper() in ("MCQ",):
                q_type = "MCQ"
            elif q_type_raw.upper() in ("SA", "NUMERIC", "NUMERICAL"):
                q_type = "NUMERICAL"
            else:
                q_type = q_type_raw.upper()
            
            # Find marks for this question
            correct_marks = None
            wrong_marks = None
            for pos in sorted(marks_map.keys()):
                if pos > m.start():
                    correct_marks, wrong_marks = marks_map[pos]
                    break
            
            # Determine subject from sections
            subject = "Unknown"
            section_name = "Section A"
            if sections:
                # Find the section this question belongs to based on text position
                for s in reversed(sections):
                    if m.start() >= s["text_pos"]:
                        subject = s["subject"]
                        section_name = s["section"]
                        break
            
            # Find source page
            source_page = self._find_page_for_question(q_num, q_id, page_texts)
            
            # Extract option NTA IDs
            option_ids = self._find_option_ids_for_question(m.start(), full_text, matches, i)
            
            # Build options
            options = []
            labels = ["A", "B", "C", "D"]
            for oi, opt_id in enumerate(option_ids[:4]):
                opt = ExtractedOption(
                    option_index=oi + 1,
                    label=labels[oi] if oi < 4 else str(oi + 1),
                    text=None,  # Text is in images
                    option_nta_id=opt_id,
                    extraction_confidence=0.0,
                )
                options.append(opt)
            
            q = ExtractedQuestion(
                question_number=q_num,
                nta_question_id=q_id,
                question_type=q_type,
                subject=subject,
                section=section_name,
                question_text=None,  # Text is in images
                options=options,
                correct_marks=correct_marks,
                wrong_marks=wrong_marks,
                source_page=source_page,
                extraction_method="RECORDED_RESPONSE_METADATA",
                extraction_confidence=0.5,  # Metadata only, no text
                needs_review=True,
                review_reason="Question text embedded as image — requires OCR or image asset",
            )
            questions.append(q)
        
        return questions
    
    def _find_option_ids_for_question(
        self, q_start: int, full_text: str, all_matches, match_idx: int
    ) -> List[str]:
        """Find the option NTA IDs associated with a question."""
        # Look for "Options :" followed by numeric IDs after the question start
        q_end = all_matches[match_idx + 1].start() if match_idx + 1 < len(all_matches) else len(full_text)
        q_block = full_text[q_start:q_end]
        
        opt_ids = re.findall(r"(\d{5,})\.\s", q_block)
        return opt_ids
    
    def _find_page_for_question(
        self, q_num: int, q_id: str, page_texts: List[str]
    ) -> Optional[int]:
        """Find which page a question appears on."""
        pattern = rf"Question Number\s*:\s*{q_num}\s+Question Id\s*:\s*{q_id}"
        for i, pt in enumerate(page_texts):
            if re.search(pattern, pt):
                return i + 1
        
        # Fallback: just find by question number
        pattern2 = rf"Question Number\s*:\s*{q_num}\b"
        for i, pt in enumerate(page_texts):
            if re.search(pattern2, pt):
                return i + 1
        
        return None
    
    def _extract_images(self, questions: List[ExtractedQuestion], page_texts: List[str]):
        """Extract question and option images from the PDF using pymupdf."""
        doc = pymupdf.open(self.pdf_path)
        
        assets_base = os.path.join(self.output_dir, "assets")
        q_dir = os.path.join(assets_base, "questions")
        opt_dir = os.path.join(assets_base, "options")
        os.makedirs(q_dir, exist_ok=True)
        os.makedirs(opt_dir, exist_ok=True)
        
        for q in questions:
            if not q.source_page or q.source_page > doc.page_count:
                continue
            
            page = doc[q.source_page - 1]
            
            # Get all images on this page
            images = page.get_images(full=True)
            
            # Extract individual question image by rendering page region
            # For now, render the full page as the question source
            pix = page.get_pixmap(dpi=200)
            img_filename = f"q_{self.basename}_q{q.question_number:03d}_page.png"
            img_path = os.path.join(q_dir, img_filename)
            pix.save(img_path)
            q.question_image_path = os.path.relpath(img_path, self.output_dir)
            
            # Extract individual question content images
            # Images associated with the question are XObjects on its page
            for idx, img_info in enumerate(images):
                xref = img_info[0]
                try:
                    base_img = doc.extract_image(xref)
                    if base_img and base_img.get("image"):
                        img_data = base_img["image"]
                        img_ext = base_img.get("ext", "png")
                        w = base_img.get("width", 0)
                        h = base_img.get("height", 0)
                        
                        # Skip tiny images (likely UI elements like bullets)
                        if w < 20 or h < 15:
                            continue
                        
                        # Large images (width > 400) are likely question text
                        if w > 400:
                            q_img_name = f"q_{self.basename}_q{q.question_number:03d}_content_{idx}.{img_ext}"
                            q_img_path = os.path.join(q_dir, q_img_name)
                            with open(q_img_path, "wb") as f:
                                f.write(img_data)
                        
                        # Medium images are likely option content
                        elif w > 20 and h > 20:
                            # Map to option if possible
                            opt_img_name = f"q_{self.basename}_q{q.question_number:03d}_img_{idx}.{img_ext}"
                            opt_img_path = os.path.join(opt_dir, opt_img_name)
                            with open(opt_img_path, "wb") as f:
                                f.write(img_data)
                
                except Exception:
                    continue
        
        doc.close()
