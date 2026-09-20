"""
scripts/parsers/base_parser.py

Abstract base class for NTA JEE Main PDF parsing.
Provides common metadata extraction and question boundary detection.
"""
import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class ExtractedOption:
    option_index: int  # 1-4
    label: str  # A, B, C, D
    text: Optional[str] = None
    image_path: Optional[str] = None
    option_nta_id: Optional[str] = None
    extraction_confidence: float = 0.0


@dataclass
class ExtractedQuestion:
    question_number: int
    nta_question_id: Optional[str] = None
    question_type: str = "MCQ"  # MCQ, SA, Numeric
    subject: Optional[str] = None
    section: Optional[str] = None
    question_text: Optional[str] = None
    question_image_path: Optional[str] = None
    options: List[ExtractedOption] = field(default_factory=list)
    correct_marks: Optional[float] = None
    wrong_marks: Optional[float] = None
    source_page: Optional[int] = None
    source_page_end: Optional[int] = None
    extraction_method: str = "UNKNOWN"
    extraction_confidence: float = 0.0
    needs_review: bool = False
    review_reason: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class PaperMetadata:
    year: int = 0
    session: str = ""
    exam_date: str = ""
    shift: int = 0
    language: str = "English"
    paper_type: str = "Paper-I (B.E./B.Tech.)"
    total_marks: Optional[int] = None
    duration_minutes: Optional[int] = None
    creation_date: Optional[str] = None
    set_name: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractionResult:
    source_path: str
    source_sha256: str
    format_type: str
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    questions: List[ExtractedQuestion] = field(default_factory=list)
    total_pages: int = 0
    extraction_timestamp: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "format_type": self.format_type,
            "metadata": self.metadata.to_dict(),
            "questions": [q.to_dict() for q in self.questions],
            "total_pages": self.total_pages,
            "extraction_timestamp": self.extraction_timestamp,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": {
                "total_questions": len(self.questions),
                "mcq": sum(1 for q in self.questions if q.question_type == "MCQ"),
                "numerical": sum(1 for q in self.questions if q.question_type in ("SA", "Numeric", "NUMERICAL")),
                "with_text": sum(1 for q in self.questions if q.question_text),
                "with_images": sum(1 for q in self.questions if q.question_image_path),
                "needs_review": sum(1 for q in self.questions if q.needs_review),
                "subjects": list(set(q.subject for q in self.questions if q.subject)),
            }
        }


class BaseParser(ABC):
    """Abstract base class for NTA JEE Main PDF parsing."""
    
    def __init__(self, pdf_path: str, output_dir: str, skip_images: bool = False):
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.basename = os.path.splitext(os.path.basename(pdf_path))[0]
        self.skip_images = skip_images
    
    @abstractmethod
    def parse(self) -> ExtractionResult:
        """Parse the PDF and return structured extraction results."""
        pass
    
    def extract_paper_metadata_from_text(self, text: str) -> PaperMetadata:
        """Extract paper metadata from the text layer."""
        meta = PaperMetadata()
        
        # Paper Name
        m = re.search(r"Question Paper Name\s*:\s*(.+?)(?:\n|$)", text)
        if m:
            name = m.group(1).strip()
            # Extract date from name like "B Tech 2nd Apr 2026 Shift 1"
            date_m = re.search(r"(\d+)\w*\s+(\w+)\s+(\d{4})", name)
            if date_m:
                meta.year = int(date_m.group(3))
            shift_m = re.search(r"Shift\s*(\d+)", name, re.I)
            if shift_m:
                meta.shift = int(shift_m.group(1))
        
        # Creation Date
        m = re.search(r"Creation Date\s*:\s*([\d-]+\s*[\d:]*)", text)
        if m:
            meta.creation_date = m.group(1).strip()
            # Extract year from creation date
            year_m = re.search(r"(\d{4})", m.group(1))
            if year_m and not meta.year:
                meta.year = int(year_m.group(1))
        
        # Duration
        m = re.search(r"Duration\s*:\s*(\d+)", text)
        if m:
            meta.duration_minutes = int(m.group(1))
        
        # Total Marks
        m = re.search(r"Total Marks\s*:\s*(\d+)", text)
        if m:
            meta.total_marks = int(m.group(1))
        
        # Set Name (2022 format)
        m = re.search(r"Set Name\s*:\s*(.+?)(?:\n|$)", text)
        if m:
            meta.set_name = m.group(1).strip()
        
        # Exam Date (2022 format)
        m = re.search(r"Exam Date\s*:\s*(.+?)(?:\n|$)", text)
        if m:
            meta.exam_date = m.group(1).strip()
        
        # Exam Shift (2022 format)
        m = re.search(r"Exam Shift\s*:\s*(\d+)", text)
        if m:
            meta.shift = int(m.group(1))
        
        # Language
        m = re.search(r"Langauge\s*:\s*(\w+)", text) or re.search(r"Language\s*:\s*(\w+)", text)
        if m:
            meta.language = m.group(1).strip()
        
        return meta
    
    def classify_subject(self, section_text: str) -> str:
        """Classify subject from section/topic text."""
        lower = section_text.lower()
        if "physics" in lower:
            return "Physics"
        elif "chemistry" in lower:
            return "Chemistry"
        elif "math" in lower:
            return "Mathematics"
        return "Unknown"
    
    def classify_section(self, section_text: str) -> str:
        """Extract section letter from section text."""
        m = re.search(r"Section\s*[-:]?\s*([A-Z])", section_text, re.I)
        if m:
            return f"Section {m.group(1).upper()}"
        return "Section A"
