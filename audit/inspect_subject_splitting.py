import fitz, os, re

adv_dir = r"c:\Users\dell\Music\Jee Web\JEE_Advanced_PYQ_Archive"

text_years = [2014, 2017, 2018, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

for y in text_years:
    for p in ['Paper-1', 'Paper-2']:
        ppath = os.path.join(adv_dir, str(y), p, 'Question-Paper')
        files = [f for f in os.listdir(ppath) if f.endswith('.pdf') and ('English' in f or y < 2019)]
        if not files:
            continue
        f = files[0]
        doc = fitz.open(os.path.join(ppath, f))
        
        # Check TOC
        toc = doc.get_toc()
        subject_pages = {}
        if toc:
            for item in toc:
                title = item[1].upper()
                page_num = item[2]
                if 'PHY' in title:
                    subject_pages['Physics'] = page_num
                elif 'CHM' in title or 'CHEM' in title:
                    subject_pages['Chemistry'] = page_num
                elif 'MTH' in title or 'MATH' in title:
                    subject_pages['Mathematics'] = page_num
        
        # If no TOC or incomplete, scan page texts for Part headers
        if len(subject_pages) < 3:
            for i, page in enumerate(doc):
                txt = page.get_text()[:400].upper()
                if ('PART I' in txt or 'PART-I' in txt or 'PART 1' in txt or 'SECTION 1' in txt) and 'PHYSICS' in txt:
                    subject_pages['Physics'] = i + 1
                elif ('PART II' in txt or 'PART-II' in txt or 'PART 2' in txt) and 'CHEMISTRY' in txt:
                    subject_pages['Chemistry'] = i + 1
                elif ('PART III' in txt or 'PART-III' in txt or 'PART 3' in txt) and 'MATHEMATICS' in txt:
                    subject_pages['Mathematics'] = i + 1
                elif 'PHYSICS' in txt and 'Physics' not in subject_pages and len(txt) < 200:
                    subject_pages['Physics'] = i + 1
                elif 'CHEMISTRY' in txt and 'Chemistry' not in subject_pages and len(txt) < 200:
                    subject_pages['Chemistry'] = i + 1
                elif 'MATHEMATICS' in txt and 'Mathematics' not in subject_pages and len(txt) < 200:
                    subject_pages['Mathematics'] = i + 1

        print(f"{y} {p}: pages={len(doc)}, detected subjects={subject_pages}")
