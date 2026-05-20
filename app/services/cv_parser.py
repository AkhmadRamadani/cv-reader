import re
import os
import pdfplumber
import redis
import hashlib
import json
from typing import Dict, List, Optional, Tuple
from app.models.cv import (
    CVData, WorkExperience, Education, Project,
    Certification, Language, Organization, Award,
    Publication, Reference
)
from app.core.config import settings
from app.core.nlp import get_nlp
from app.utils import dataclass_to_dict

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


class ImprovedCVReader:
    """
    Improved CV/Resume parser that uses NLP (spaCy) combined with
    regex patterns and heuristics for robust data extraction.
    """

    def __init__(self):
        # Contact patterns
        self.email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        self.phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}'
        self.linkedin_pattern = r'(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?'
        self.github_pattern = r'(?:https?://)?(?:www\.)?github\.com/[\w-]+/?'
        self.website_pattern = r'(?:https?://)?(?:www\.)?[\w-]+\.[\w.]+(?:/[\w.-]*)*'
        self.date_pattern = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|\d{4}'

        # Section header patterns (flexible matching)
        self.section_headers = {
            'summary': [
                r'summary', r'profile', r'about\s*me', r'objective',
                r'professional\s*summary', r'career\s*objective',
                r'personal\s*statement', r'overview'
            ],
            'experience': [
                r'experience', r'work\s*experience', r'employment',
                r'professional\s*experience', r'work\s*history',
                r'career\s*history', r'employment\s*history'
            ],
            'education': [
                r'education', r'academic', r'qualifications',
                r'academic\s*background', r'educational\s*background'
            ],
            'skills': [
                r'skills', r'technical\s*skills', r'competencies',
                r'core\s*competencies', r'expertise', r'technologies',
                r'tools\s*(?:&|and)\s*technologies', r'tech\s*stack'
            ],
            'projects': [
                r'projects', r'personal\s*projects', r'key\s*projects',
                r'notable\s*projects', r'side\s*projects'
            ],
            'certifications': [
                r'certifications?', r'certificates?', r'licenses?',
                r'professional\s*certifications?', r'credentials?'
            ],
            'languages': [
                r'languages', r'language\s*skills'
            ],
            'volunteering': [
                r'volunteer(?:ing)?', r'community',
                r'community\s*(?:service|involvement)'
            ],
            'interests': [
                r'interests', r'hobbies', r'activities'
            ],
            'references': [
                r'references', r'referees'
            ],
            'awards': [
                r'awards', r'honors', r'achievements',
                r'accomplishments'
            ],
            'publications': [
                r'publications', r'papers', r'research'
            ],
            'additional': [
                r'additional', r'additional\s*(?:information|activities)',
                r'other\s*(?:activities|information|experience)',
                r'extracurricular', r'miscellaneous'
            ]
        }

        # Job title keywords for detection
        self.title_keywords = [
            'engineer', 'developer', 'manager', 'analyst', 'designer',
            'architect', 'consultant', 'specialist', 'coordinator',
            'director', 'lead', 'senior', 'junior', 'intern',
            'administrator', 'scientist', 'researcher', 'officer',
            'executive', 'assistant', 'associate', 'head', 'chief',
            'vp', 'president', 'founder', 'co-founder', 'cto', 'ceo',
            'devops', 'qa', 'tester', 'scrum', 'product', 'project',
            'data', 'machine learning', 'ai', 'cloud', 'full stack',
            'fullstack', 'full-stack', 'frontend', 'front-end',
            'backend', 'back-end', 'mobile', 'ios', 'android', 'web'
        ]

        # Initialize Redis
        try:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.redis.ping()
            print(f"Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            print(f"Redis not available (caching disabled): {e}")
            self.redis = None

    # ─── Text Extraction ──────────────────────────────────────────────

    def extract_text(self, file_path: str) -> str:
        """Extract text from PDF or DOCX based on file extension."""
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.pdf':
            return self._extract_text_from_pdf(file_path)
        elif ext in ('.docx', '.doc'):
            return self._extract_text_from_docx(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from PDF.
        Strategy: try pdfplumber first, fall back to PyMuPDF if it fails.
        """
        # Try pdfplumber first
        text = self._extract_with_pdfplumber(pdf_path)

        # If pdfplumber failed or got no text, try PyMuPDF
        if not text.strip() and PYMUPDF_AVAILABLE:
            print("pdfplumber returned no text, trying PyMuPDF...")
            text = self._extract_with_pymupdf(pdf_path)

        if not text.strip():
            raise ValueError(
                "No text could be extracted from this PDF. "
                "The file may be scanned/image-based, corrupted, "
                "or password-protected."
            )

        return text.strip()

    def _extract_with_pdfplumber(self, pdf_path: str) -> str:
        """Extract text using pdfplumber."""
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    try:
                        page_text = page.extract_text(
                            x_tolerance=2,
                            y_tolerance=3
                        )
                        if page_text:
                            text += page_text + "\n"
                        else:
                            tables = page.extract_tables()
                            for table in tables:
                                for row in table:
                                    if row:
                                        row_text = " | ".join(
                                            cell for cell in row if cell
                                        )
                                        text += row_text + "\n"
                    except Exception as page_err:
                        print(f"pdfplumber page error: {page_err}")
                        continue
        except Exception as e:
            print(f"pdfplumber failed entirely: {e}")
        return text

    def _extract_with_pymupdf(self, pdf_path: str) -> str:
        """Extract text using PyMuPDF (fitz) as fallback."""
        text = ""
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    text += page_text + "\n"
            doc.close()
        except Exception as e:
            print(f"PyMuPDF failed: {e}")
            raise ValueError(f"Could not read PDF file: {e}")
        return text

    def _extract_text_from_docx(self, docx_path: str) -> str:
        """Extract text from DOCX file."""
        if not DOCX_AVAILABLE:
            raise ValueError(
                "python-docx is not installed. "
                "Install it with: pip install python-docx"
            )
        try:
            doc = DocxDocument(docx_path)
            lines = []
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if text:
                    lines.append(text)

            # Also extract from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(
                        cell.text.strip() for cell in row.cells
                        if cell.text.strip()
                    )
                    if row_text:
                        lines.append(row_text)

            return '\n'.join(lines)
        except Exception as e:
            raise ValueError(f"Could not read DOCX file: {e}")

    # ─── Section Splitting ─────────────────────────────────────────────

    def _is_section_header(self, line: str) -> Optional[str]:
        """
        Determine if a line is a section header.
        Returns the section name or None.
        """
        cleaned = line.strip().rstrip(':').strip()

        # Skip very long lines (unlikely to be headers)
        if len(cleaned) > 60:
            return None

        # Skip lines that look like bullet points or descriptions
        if cleaned.startswith(('•', '-', '*', '–', '►')):
            return None

        for section_name, patterns in self.section_headers.items():
            for pattern in patterns:
                if re.match(
                    rf'^{pattern}\s*:?\s*$',
                    cleaned,
                    re.IGNORECASE
                ):
                    return section_name
                # Also match ALL CAPS headers
                if re.match(
                    rf'^{pattern.upper()}\s*:?\s*$',
                    cleaned
                ):
                    return section_name

        return None

    def split_into_sections(self, text: str) -> Dict[str, str]:
        """Split CV text into sections using flexible header detection."""
        sections = {}
        lines = text.split('\n')
        current_section = 'header'  # Content before first section
        current_content = []

        for line in lines:
            section_name = self._is_section_header(line)

            if section_name:
                # Save previous section
                if current_content:
                    content = '\n'.join(current_content).strip()
                    if content:
                        sections[current_section] = content
                current_section = section_name
                current_content = []
            else:
                current_content.append(line)

        # Save last section
        if current_content:
            content = '\n'.join(current_content).strip()
            if content:
                sections[current_section] = content

        return sections

    # ─── Contact Information Extraction ────────────────────────────────

    def extract_contact_info(self, text: str, header_text: str) -> Dict:
        """
        Extract contact information using NLP + regex.
        Uses spaCy NER for name detection and regex for structured data.
        """
        contact = {
            'name': None,
            'title': None,
            'location': None,
            'email': None,
            'phone': None,
            'linkedin': None,
            'github': None,
            'website': None
        }

        # Use header section (before first real section) for contact info
        search_text = header_text if header_text else '\n'.join(
            text.split('\n')[:20]
        )

        # ── Email ──
        emails = re.findall(self.email_pattern, text)
        if emails:
            contact['email'] = emails[0]

        # ── Phone ──
        phones = re.findall(self.phone_pattern, search_text)
        for phone in phones:
            digits = re.sub(r'[^0-9]', '', phone)
            if 8 <= len(digits) <= 15:
                contact['phone'] = phone.strip()
                break

        # ── LinkedIn ──
        linkedin = re.findall(self.linkedin_pattern, text, re.IGNORECASE)
        if linkedin:
            contact['linkedin'] = linkedin[0]

        # ── GitHub ──
        github = re.findall(self.github_pattern, text, re.IGNORECASE)
        if github:
            contact['github'] = github[0]

        # ── Website (non-linkedin, non-github) ──
        urls = re.findall(
            r'https?://(?:www\.)?[\w.-]+\.[\w.]+(?:/[\w./-]*)?',
            search_text
        )
        for url in urls:
            if 'linkedin.com' not in url and 'github.com' not in url:
                contact['website'] = url
                break

        # ── Name (using spaCy NER) ──
        nlp = get_nlp()
        lines = search_text.split('\n')

        if nlp:
            # Try NER on first few lines
            for line in lines[:5]:
                line = line.strip()
                if not line or '@' in line or 'http' in line:
                    continue
                doc = nlp(line)
                for ent in doc.ents:
                    if ent.label_ == 'PERSON' and len(ent.text) > 3:
                        contact['name'] = ent.text
                        break
                if contact['name']:
                    break

        # Fallback: first non-empty line that looks like a name
        if not contact['name']:
            for line in lines[:5]:
                line = line.strip()
                if not line:
                    continue
                # Skip lines with contact info
                if any(x in line for x in ['@', 'http', '+', '(', '|']):
                    continue
                # Name heuristic: 2-4 words, mostly alphabetic
                words = line.split()
                if 2 <= len(words) <= 4 and all(
                    re.match(r"^[A-Za-z\u00C0-\u024F'.,-]+$", w)
                    for w in words
                ):
                    contact['name'] = line
                    break

        # ── Title ──
        if not contact['title']:
            for line in lines[1:8]:
                line = line.strip()
                if not line or line == contact.get('name'):
                    continue
                line_lower = line.lower()
                if any(kw in line_lower for kw in self.title_keywords):
                    # Make sure it's not too long (likely a description)
                    if len(line) < 80:
                        contact['title'] = line
                        break

        # ── Location (using spaCy GPE entities) ──
        if nlp and not contact['location']:
            for line in lines[:15]:
                line = line.strip()
                if not line:
                    continue
                doc = nlp(line)
                gpe_entities = [
                    ent.text for ent in doc.ents
                    if ent.label_ in ('GPE', 'LOC')
                ]
                if gpe_entities:
                    # If line is short and contains location, use whole line
                    if len(line) < 60:
                        contact['location'] = line
                    else:
                        contact['location'] = ', '.join(gpe_entities)
                    break

        # Fallback location: look for common patterns
        if not contact['location']:
            loc_pattern = r'(?:based\s+in|located?\s+in|address|city)\s*:?\s*(.+)'
            for line in lines[:15]:
                match = re.search(loc_pattern, line, re.IGNORECASE)
                if match:
                    contact['location'] = match.group(1).strip()
                    break

        return contact

    # ─── Skills Parsing ────────────────────────────────────────────────

    def parse_skills(self, text: str) -> Dict[str, List[str]]:
        """
        Parse skills section. Handles multiple formats:
        - Category: skill1, skill2, skill3
        - Category: skill1 | skill2 | skill3
        - • skill1 • skill2
        - Bullet lists
        """
        skills = {}
        lines = text.split('\n')
        current_category = "General"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Format: "Category: item1, item2, item3"
            if ':' in line:
                parts = line.split(':', 1)
                category = parts[0].strip().strip('•-► ')
                items_text = parts[1].strip()

                if items_text:
                    # Split by comma, pipe, or semicolon
                    items = re.split(r'[,|;]', items_text)
                    items = [
                        item.strip().strip('•-► ')
                        for item in items if item.strip()
                    ]
                    if items:
                        skills[category] = items
                        current_category = category
                else:
                    current_category = category
                    if current_category not in skills:
                        skills[current_category] = []

            # Format: bullet points under a category
            elif line.startswith(('•', '-', '*', '►', '–')):
                item = line.lstrip('•-*►– ').strip()
                if item:
                    if current_category not in skills:
                        skills[current_category] = []
                    skills[current_category].append(item)

            # Format: comma-separated on a line without category
            elif ',' in line:
                items = [i.strip() for i in line.split(',') if i.strip()]
                if items and len(items) > 1:
                    if current_category not in skills:
                        skills[current_category] = []
                    skills[current_category].extend(items)

        # Clean up empty categories
        skills = {k: v for k, v in skills.items() if v}
        return skills

    # ─── Work Experience Parsing ───────────────────────────────────────

    def _extract_date_range(self, text: str) -> Tuple[str, str]:
        """Extract start and end dates from a text string."""
        # Pattern: "Month Year - Month Year" or "Month Year – Present"
        pattern = (
            r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
            r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
            r'Nov(?:ember)?|Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|\d{4})'
            r'\s*[-–—~to]+\s*'
            r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
            r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|'
            r'Nov(?:ember)?|Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|\d{4}|'
            r'[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing)'
        )
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Try just finding two years
        years = re.findall(r'\b(20\d{2}|19\d{2})\b', text)
        if len(years) >= 2:
            return years[0], years[1]

        # Check for single year with Present
        if re.search(r'[Pp]resent|[Cc]urrent|[Nn]ow', text):
            year = re.search(r'\b(20\d{2}|19\d{2})\b', text)
            if year:
                return year.group(1), "Present"

        return "", ""

    def parse_work_experience(self, text: str) -> List[WorkExperience]:
        """
        Parse work experience section. Handles multiple formats:
        - Position | Company
        - Position at Company
        - Company — Position
        - Position\\nCompany\\nDates
        """
        experiences = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            position = ""
            company = ""
            location = ""
            start_date = ""
            end_date = ""
            responsibilities = []

            # Detect entry start by looking for date patterns nearby
            has_dates = bool(re.search(
                r'20\d{2}|19\d{2}|[Pp]resent|[Cc]urrent', line
            ))
            next_has_dates = False
            if i + 1 < len(lines):
                next_has_dates = bool(re.search(
                    r'20\d{2}|19\d{2}|[Pp]resent|[Cc]urrent',
                    lines[i + 1].strip()
                ))

            # Format: "Position | Company" or "Company | Position"
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    position = parts[0]
                    company = parts[1]
                    if len(parts) >= 3:
                        location = parts[2]

            # Format: "Position at Company" or "Position, Company"
            elif re.search(r'\s+at\s+', line, re.IGNORECASE):
                parts = re.split(r'\s+at\s+', line, flags=re.IGNORECASE)
                position = parts[0].strip()
                company = parts[1].strip() if len(parts) > 1 else ""

            # Format: "Company — Position" or "Company - Position"
            elif re.search(r'\s*[—–-]\s*', line) and not has_dates:
                parts = re.split(r'\s*[—–-]\s*', line, maxsplit=1)
                if len(parts) == 2:
                    # Heuristic: shorter part is likely the company
                    if any(kw in parts[1].lower() for kw in self.title_keywords):
                        company = parts[0].strip()
                        position = parts[1].strip()
                    else:
                        position = parts[0].strip()
                        company = parts[1].strip()

            # Format: line looks like a job title (contains title keywords)
            elif any(kw in line.lower() for kw in self.title_keywords) and len(line) < 80:
                position = line

            # If we didn't find a position/company pattern, skip
            if not position and not company:
                i += 1
                continue

            # Look at subsequent lines for dates, location, responsibilities
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()

                if not next_line:
                    i += 1
                    # Stop at double blank lines
                    if i < len(lines) and not lines[i].strip():
                        break
                    continue

                # Check if this is a new entry (has title keywords and no bullet)
                if (not next_line.startswith(('•', '-', '*', '►', '–'))
                        and not start_date
                        and not next_line.startswith((' ', '\t'))):
                    # Extract dates from this line
                    sd, ed = self._extract_date_range(next_line)
                    if sd:
                        start_date = sd
                        end_date = ed
                        # Remaining text might be location
                        remaining = re.sub(
                            r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|'
                            r'Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|'
                            r'Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
                            r'Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|'
                            r'\d{4}|[Pp]resent|[Cc]urrent|[Nn]ow|[-–—~]',
                            '', next_line
                        ).strip().strip(',').strip()
                        if remaining and not location:
                            location = remaining
                        # If no company yet, check if it's on this line
                        if not company and remaining:
                            company = remaining
                            location = ""
                        i += 1
                        continue

                    # Could be company name if we only have position
                    if not company and len(next_line) < 80:
                        company = next_line
                        i += 1
                        continue

                # Check if next line is a new experience entry
                if (self._is_section_header(next_line)
                        or ('|' in next_line and not next_line.startswith(('•', '-')))
                        or (re.search(r'\s+at\s+', next_line, re.IGNORECASE)
                            and any(kw in next_line.lower() for kw in self.title_keywords))):
                    break

                # Bullet point = responsibility
                if next_line.startswith(('•', '-', '*', '►', '–')):
                    resp = next_line.lstrip('•-*►– ').strip()
                    if resp:
                        responsibilities.append(resp)
                    i += 1
                    continue

                # Non-bullet text after dates = responsibility or description
                if start_date and next_line:
                    responsibilities.append(next_line)

                i += 1

            if position or company:
                experiences.append(WorkExperience(
                    start_date=start_date,
                    end_date=end_date,
                    position=position,
                    company=company,
                    location=location,
                    responsibilities=responsibilities
                ))

        return experiences

    # ─── Education Parsing ─────────────────────────────────────────────

    def parse_education(self, text: str) -> List[Education]:
        """
        Parse education section. Handles formats:
        - Degree\\nInstitution, Location\\nYear - Year
        - Institution | Degree | Year
        - Degree in Field, Institution (Year-Year)
        """
        education_list = []
        lines = text.split('\n')
        i = 0

        # Degree keywords for detection
        degree_keywords = [
            'bachelor', 'master', 'phd', 'ph.d', 'doctorate', 'diploma',
            'associate', 'b.s', 'b.a', 'b.sc', 'm.s', 'm.a', 'm.sc',
            'm.eng', 'b.eng', 'b.tech', 'm.tech', 'mba', 'bba',
            's.kom', 's.t', 's.si', 's1', 's2', 's3', 'sarjana',
            'magister', 'doktor', 'degree', 'certificate', 'bootcamp'
        ]

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            degree = ""
            institution = ""
            location = ""
            start_date = ""
            end_date = ""
            gpa = ""

            line_lower = line.lower()

            # Check if line contains degree keywords
            has_degree = any(kw in line_lower for kw in degree_keywords)

            # Format: "Degree | Institution | Dates"
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                for part in parts:
                    part_lower = part.lower()
                    if any(kw in part_lower for kw in degree_keywords):
                        degree = part
                    elif re.search(r'20\d{2}|19\d{2}', part):
                        sd, ed = self._extract_date_range(part)
                        start_date, end_date = sd, ed
                    elif not institution:
                        institution = part
                    else:
                        location = part

            # Line has degree keyword
            elif has_degree:
                degree = line

                # Look at next lines for institution, dates
                i += 1
                while i < len(lines) and len(education_list) < 10:
                    next_line = lines[i].strip()
                    if not next_line:
                        i += 1
                        break

                    # Check if next line is a new degree entry
                    if any(kw in next_line.lower() for kw in degree_keywords):
                        break

                    # Extract dates
                    sd, ed = self._extract_date_range(next_line)
                    if sd and not start_date:
                        start_date = sd
                        end_date = ed
                        # Remaining might be institution/location
                        remaining = re.sub(
                            r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|'
                            r'Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|'
                            r'Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
                            r'Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|'
                            r'\d{4}|[Pp]resent|[Cc]urrent|[-–—~]',
                            '', next_line
                        ).strip().strip(',').strip()
                        if remaining and not institution:
                            institution = remaining
                        i += 1
                        continue

                    # GPA
                    gpa_match = re.search(
                        r'(?:GPA|IPK|Grade)[:\s]*(\d+[.,]\d+)',
                        next_line, re.IGNORECASE
                    )
                    if gpa_match:
                        gpa = gpa_match.group(1)
                        i += 1
                        continue

                    # Institution line
                    if not institution:
                        # Split by comma for institution, location
                        parts = [p.strip() for p in next_line.split(',')]
                        institution = parts[0]
                        if len(parts) > 1:
                            location = ', '.join(parts[1:])
                        i += 1
                        continue

                    break

            # Line might be institution name (followed by degree on next line)
            elif i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if any(kw in next_line.lower() for kw in degree_keywords):
                    institution = line
                    degree = next_line
                    i += 2

                    # Look for dates
                    if i < len(lines):
                        sd, ed = self._extract_date_range(lines[i].strip())
                        if sd:
                            start_date = sd
                            end_date = ed
                            i += 1
                    continue
                else:
                    i += 1
                    continue
            else:
                i += 1
                continue

            if degree or institution:
                education_list.append(Education(
                    start_date=start_date,
                    end_date=end_date,
                    degree=degree,
                    institution=institution,
                    location=location,
                    gpa=gpa if gpa else None
                ))

            i += 1

        return education_list

    # ─── Projects Parsing ──────────────────────────────────────────────

    def parse_projects(self, text: str) -> List[Project]:
        """Parse projects section with technology extraction."""
        projects = []
        lines = text.split('\n')

        current_name = None
        current_desc_lines = []
        current_techs = []
        current_url = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for URL in line
            url_match = re.search(
                r'(https?://[\w./\-?=&]+)', line
            )

            # Detect project name: bold-like, colon-separated, or short title
            is_new_project = False

            if ':' in line and not line.startswith(('•', '-', '*')):
                parts = line.split(':', 1)
                # If left side is short (project name) and right is description
                if len(parts[0]) < 60:
                    is_new_project = True
                    name = parts[0].strip().strip('•-*► ')
                    desc_start = parts[1].strip()

            elif (line.startswith(('•', '-', '*', '►'))
                  and not current_name):
                # Bullet as project name
                is_new_project = True
                name = line.lstrip('•-*► ').strip()
                desc_start = ""

            if is_new_project:
                # Save previous project
                if current_name:
                    projects.append(Project(
                        name=current_name,
                        description=' '.join(current_desc_lines).strip(),
                        technologies=current_techs,
                        url=current_url
                    ))

                current_name = name
                current_desc_lines = [desc_start] if desc_start else []
                current_techs = []
                current_url = None

                # Extract technologies from description
                tech_match = re.search(
                    r'(?:Tech(?:nolog(?:y|ies))?|Stack|Built with|Using)'
                    r'\s*:?\s*(.+)',
                    desc_start, re.IGNORECASE
                )
                if tech_match:
                    techs = re.split(r'[,|;]', tech_match.group(1))
                    current_techs = [t.strip() for t in techs if t.strip()]

                if url_match:
                    current_url = url_match.group(1)

            elif current_name:
                # Check for tech stack line
                tech_match = re.search(
                    r'(?:Tech(?:nolog(?:y|ies))?|Stack|Built with|Using)'
                    r'\s*:?\s*(.+)',
                    line, re.IGNORECASE
                )
                if tech_match:
                    techs = re.split(r'[,|;]', tech_match.group(1))
                    current_techs.extend(
                        [t.strip() for t in techs if t.strip()]
                    )
                elif url_match:
                    current_url = url_match.group(1)
                else:
                    desc_line = line.lstrip('•-*► ').strip()
                    current_desc_lines.append(desc_line)

        # Save last project
        if current_name:
            projects.append(Project(
                name=current_name,
                description=' '.join(current_desc_lines).strip(),
                technologies=current_techs,
                url=current_url
            ))

        return projects

    # ─── Certifications Parsing ────────────────────────────────────────

    def parse_certifications(self, text: str) -> List[Certification]:
        """Parse certifications with issuer and credential ID detection."""
        certifications = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            name = ""
            date = ""
            issuer = ""
            credential_id = None

            # Extract date from line
            date_match = re.search(
                r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|'
                r'May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|'
                r'Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*\.?\s*\d{4}|'
                r'\d{1,2}/\d{4}|\d{4})',
                line
            )

            if date_match:
                date = date_match.group(1)
                # Name is the rest of the line without the date
                name = line[:date_match.start()].strip().rstrip(',-–— ')
                if not name:
                    name = line[date_match.end():].strip().lstrip(',-–— ')
            else:
                # Whole line might be the cert name
                name = line.lstrip('•-*► ').strip()

            # Look at next lines for issuer / credential ID
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    break

                # Credential ID
                cred_match = re.search(
                    r'(?:Credential|ID|License)\s*(?:ID|#|No\.?)?\s*:?\s*(.+)',
                    next_line, re.IGNORECASE
                )
                if cred_match:
                    credential_id = cred_match.group(1).strip()
                    i += 1
                    continue

                # Issuer line (short, no date, not a bullet)
                if (not re.search(r'\d{4}', next_line)
                        and not next_line.startswith(('•', '-'))
                        and len(next_line) < 80
                        and not issuer):
                    issuer = next_line.lstrip('•-*► ').strip()
                    i += 1
                    continue

                break

            if name:
                certifications.append(Certification(
                    date=date,
                    name=name,
                    issuer=issuer,
                    credential_id=credential_id
                ))

        return certifications

    # ─── Languages Parsing ─────────────────────────────────────────────

    def parse_languages(self, text: str) -> List[Language]:
        """Parse languages section."""
        languages = []
        lines = text.split('\n')

        proficiency_keywords = [
            'native', 'fluent', 'advanced', 'intermediate',
            'beginner', 'basic', 'professional', 'elementary',
            'conversational', 'proficient', 'working'
        ]

        for line in lines:
            line = line.strip().lstrip('•-*► ')
            if not line:
                continue

            name = ""
            proficiency = ""

            # Format: "Language - Proficiency" or "Language: Proficiency"
            if ':' in line or ' - ' in line or ' – ' in line:
                parts = re.split(r'[:\-–—]', line, maxsplit=1)
                name = parts[0].strip()
                if len(parts) > 1:
                    proficiency = parts[1].strip()
            # Format: "Language (Proficiency)"
            elif '(' in line:
                match = re.match(r'(.+?)\s*\((.+?)\)', line)
                if match:
                    name = match.group(1).strip()
                    proficiency = match.group(2).strip()
            else:
                # Check if line contains proficiency keyword
                for kw in proficiency_keywords:
                    if kw in line.lower():
                        # Split at the keyword
                        idx = line.lower().index(kw)
                        name = line[:idx].strip().rstrip(',-–— ')
                        proficiency = line[idx:].strip()
                        break
                if not name:
                    name = line

            if name:
                languages.append(Language(
                    name=name,
                    proficiency=proficiency
                ))

        return languages

    # ─── Organizations Parsing (volunteering, additional, etc.) ──────

    def parse_organizations(self, text: str) -> List[Organization]:
        """
        Parse organizational experience — volunteering, committees,
        speaking engagements, assessor roles, etc.
        """
        entries = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            role = ""
            organization = ""
            description = ""
            start_date = ""
            end_date = ""

            # Extract date range from line
            sd, ed = self._extract_date_range(line)
            if sd:
                start_date = sd
                end_date = ed
                # Role is the text without dates
                role = re.sub(
                    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|'
                    r'Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|'
                    r'Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
                    r'Dec(?:ember)?)\s*\.?\s*\d{4}|\d{1,2}/\d{4}|'
                    r'\d{4}|[Pp]resent|[Cc]urrent|[Nn]ow|[-–—~]',
                    '', line
                ).strip().strip(',-–— ')
            else:
                role = line.lstrip('•-*► ').strip()

            # Look at next line(s) for organization/description
            i += 1
            desc_lines = []
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    break

                # If next line has a date, it's a new entry
                next_sd, _ = self._extract_date_range(next_line)
                if next_sd and not organization:
                    break

                # First non-date line after role = organization
                if not organization and not next_line.startswith(('•', '-', '*')):
                    organization = next_line
                elif next_line.startswith(('•', '-', '*', '►', '–')):
                    desc_lines.append(next_line.lstrip('•-*►– ').strip())
                else:
                    desc_lines.append(next_line)
                i += 1

            if role:
                entries.append(Organization(
                    role=role,
                    organization=organization,
                    description=' '.join(desc_lines).strip(),
                    start_date=start_date,
                    end_date=end_date
                ))

        return entries

    # ─── Caching ───────────────────────────────────────────────────────

    def get_file_hash(self, pdf_path: str) -> str:
        """Calculate SHA256 hash of a file for caching."""
        sha256_hash = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _reconstruct_cv_data(self, data: Dict) -> CVData:
        """Reconstruct CVData from cached dictionary."""
        d = data.copy()

        if d.get('work_experience'):
            d['work_experience'] = [
                WorkExperience(**i) for i in d['work_experience']
            ]
        if d.get('education'):
            d['education'] = [Education(**i) for i in d['education']]
        if d.get('projects'):
            d['projects'] = [Project(**i) for i in d['projects']]
        if d.get('certifications'):
            d['certifications'] = [
                Certification(**i) for i in d['certifications']
            ]
        if d.get('languages'):
            d['languages'] = [Language(**i) for i in d['languages']]
        if d.get('organizations'):
            d['organizations'] = [
                Organization(**i) for i in d['organizations']
            ]
        if d.get('awards'):
            d['awards'] = [Award(**i) for i in d['awards']]
        if d.get('publications'):
            d['publications'] = [
                Publication(**i) for i in d['publications']
            ]
        if d.get('references'):
            d['references'] = [Reference(**i) for i in d['references']]

        return CVData(**d)

    # ─── Main Parse Method ─────────────────────────────────────────────

    def parse_cv_logic(self, file_path: str) -> CVData:
        """Core parsing logic — extracts all CV data from PDF or DOCX."""
        text = self.extract_text(file_path)

        if not text:
            raise ValueError("Could not extract any text from the file")

        # Split into sections
        sections = self.split_into_sections(text)

        # Extract contact info from header (text before first section)
        header_text = sections.get('header', '')
        contact = self.extract_contact_info(text, header_text)

        # Build CV data
        cv_data = CVData(
            name=contact['name'],
            title=contact['title'],
            location=contact['location'],
            email=contact['email'],
            phone=contact['phone'],
            linkedin=contact['linkedin'],
            github=contact['github'],
            website=contact['website'],
            summary=sections.get('summary', '').strip() or None,
            raw_text=text
        )

        # Parse each section
        if 'skills' in sections:
            cv_data.skills = self.parse_skills(sections['skills'])

        if 'experience' in sections:
            cv_data.work_experience = self.parse_work_experience(
                sections['experience']
            )

        if 'education' in sections:
            cv_data.education = self.parse_education(sections['education'])

        if 'projects' in sections:
            cv_data.projects = self.parse_projects(sections['projects'])

        if 'certifications' in sections:
            cv_data.certifications = self.parse_certifications(
                sections['certifications']
            )

        if 'languages' in sections:
            cv_data.languages = self.parse_languages(sections['languages'])

        if 'volunteering' in sections:
            cv_data.organizations = self.parse_organizations(
                sections['volunteering']
            )

        if 'additional' in sections:
            cv_data.organizations.extend(
                self.parse_organizations(sections['additional'])
            )

        return cv_data

    def parse_cv(self, file_path: str) -> CVData:
        """Main entry point with Redis caching."""
        file_hash = self.get_file_hash(file_path)

        # Try cache first
        if self.redis:
            try:
                cached = self.redis.get(f"cv:{file_hash}")
                if cached:
                    print(f"Cache hit for {file_hash[:12]}...")
                    data_dict = json.loads(cached)
                    return self._reconstruct_cv_data(data_dict)
            except Exception as e:
                print(f"Redis get error: {e}")

        # Parse the CV
        cv_data = self.parse_cv_logic(file_path)

        # Cache the result (24 hours)
        if self.redis:
            try:
                data_dict = dataclass_to_dict(cv_data)
                # Don't cache raw_text to save memory
                data_dict.pop('raw_text', None)
                self.redis.setex(
                    f"cv:{file_hash}", 86400, json.dumps(data_dict)
                )
            except Exception as e:
                print(f"Redis set error: {e}")

        return cv_data


# Module-level instance
cv_reader = ImprovedCVReader()
