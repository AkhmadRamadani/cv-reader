import re
from typing import List, Dict

# ── PDF text extraction ────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file. Tries pdfminer first, then PyMuPDF."""
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(pdf_path)
        if text and text.strip():
            return text
    except ImportError:
        pass

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if text and text.strip():
            return text
    except ImportError:
        pass

    raise RuntimeError(
        "No PDF library found. Install one:\n"
        "  pip install pdfminer.six\n"
        "  pip install pymupdf"
    )


# ── Field extractors ───────────────────────────────────────────────────────────

def extract_email(text: str) -> List[str]:
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    return re.findall(pattern, text)


def extract_phone(text: str) -> List[str]:
    pattern = r"(\+?\d[\d\s\-\(\)]{7,}\d)"
    raw = re.findall(pattern, text)
    # keep only those with at least 7 digits
    return [p.strip() for p in raw if len(re.sub(r"\D", "", p)) >= 7]


def extract_name(text: str) -> str:
    """
    Heuristic: the name is usually the first non-empty, non-contact line
    that is short (≤ 6 words) and appears in the first 10 lines.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:10]:
        # skip lines that look like contact info or section headers
        if re.search(r"@|http|linkedin|github|www\.|phone|email|address", line, re.I):
            continue
        if re.search(r"\d{4,}", line):   # skip lines with long number sequences
            continue
        words = line.split()
        if 1 <= len(words) <= 6 and line[0].isupper():
            return line
    return ""


def extract_section(text: str, section_keywords: List[str]) -> str:
    """
    Find a named section in the resume and return its content until the
    next section heading (or end of document).
    """
    # Build a regex that matches any of the section headers
    kw_pattern = "|".join(re.escape(k) for k in section_keywords)
    section_re = re.compile(
        rf"(?i)(?:^|\n)({kw_pattern})\s*[:\-]?\s*\n(.*?)(?=\n[A-Z][A-Za-z\s]{{2,30}}\s*[:\-]?\s*\n|\Z)",
        re.DOTALL,
    )
    match = section_re.search(text)
    if match:
        return match.group(2).strip()
    return ""


def extract_skills(text: str) -> List[str]:
    """Extract skills section and split into individual skill tokens."""
    raw = extract_section(text, ["skills", "technical skills", "core competencies", "competencies"])
    if not raw:
        return []
    # Split on common delimiters
    items = re.split(r"[,•·|\n\t]+", raw)
    items = [i.strip(" -–*") for i in items if i.strip()]
    return [i for i in items if 1 <= len(i.split()) <= 6]


def extract_education(text: str) -> str:
    return extract_section(text, ["education", "academic background", "qualifications"])


def extract_experience(text: str) -> str:
    return extract_section(
        text,
        ["experience", "work experience", "professional experience",
         "employment history", "work history"]
    )


def extract_summary(text: str) -> str:
    return extract_section(
        text,
        ["summary", "profile", "objective", "about me", "professional summary"]
    )


def extract_linkedin(text: str) -> str:
    match = re.search(r"linkedin\.com/in/[\w\-]+", text, re.I)
    return match.group(0) if match else ""


def extract_github(text: str) -> str:
    match = re.search(r"github\.com/[\w\-]+", text, re.I)
    return match.group(0) if match else ""


# ── Main extraction pipeline ───────────────────────────────────────────────────

def extract_resume(pdf_path: str) -> Dict:
    print(f"[INFO] Reading: {pdf_path}")
    text = extract_text_from_pdf(pdf_path)

    result = {
        "name":       extract_name(text),
        "email":      extract_email(text),
        "phone":      extract_phone(text),
        "linkedin":   extract_linkedin(text),
        "github":     extract_github(text),
        "summary":    extract_summary(text),
        "skills":     extract_skills(text),
        "experience": extract_experience(text),
        "education":  extract_education(text),
    }
    return result
