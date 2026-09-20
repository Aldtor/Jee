"""
audit/test_processors.py
Quick test for rendering question crops from scanned PDFs and testing subject page boundaries.
"""

import fitz
import os
from PIL import Image

adv_dir = r"c:\Users\dell\Music\Jee Web\JEE_Advanced_PYQ_Archive"

# Test 2011 Paper 1
p1_2011 = os.path.join(adv_dir, "2011", "Paper-1", "Question-Paper", "JEE_Advanced_2011_Paper-1.pdf")
doc = fitz.open(p1_2011)
print(f"2011 P1: {len(doc)} pages")
# render page 0 at 150 DPI
page = doc[0]
pix = page.get_pixmap(dpi=150)
img_path = r"c:\Users\dell\Music\Jee Web\audit\sample_2011_p0.png"
pix.save(img_path)
print(f"Saved sample render to {img_path}, size: {pix.width}x{pix.height}")

# Test 2026 Paper 1 Math question 1
p1_2026 = os.path.join(adv_dir, "2026", "Paper-1", "Question-Paper", "JEE_Advanced_2026_Paper-1_English.pdf")
doc26 = fitz.open(p1_2026)
print(f"2026 P1: {len(doc26)} pages. Page 1 text snippet:")
print(doc26[0].get_text()[:200].encode('ascii', 'backslashreplace').decode('ascii'))
