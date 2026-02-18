import re
import pdfplumber
import spacy
import redis
import hashlib
import json
from typing import Dict, List, Optional
from app.models.cv import CVData, WorkExperience, Education, Project, Certification
from app.core.config import settings
from app.utils import dataclass_to_dict

class ImprovedCVReader:
    def __init__(self):
        self.email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        self.phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}'
        self.linkedin_pattern = r'(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?'
        self.github_pattern = r'(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_-]+/?'
        self.date_pattern = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present|Current'

        # Initialize Redis
        try:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            print(f"Connected to Redis at {settings.REDIS_URL}")
        except Exception as e:
            print(f"Redis connection failed: {e}")
            self.redis = None

    def get_file_hash(self, pdf_path: str) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _reconstruct_cv_data(self, data: Dict) -> CVData:
        """Reconstruct CVData object from dictionary"""
        d = data.copy()

        # Handle list of objects
        if 'work_experience' in d and d['work_experience']:
             d['work_experience'] = [WorkExperience(**i) for i in d['work_experience']]
        if 'education' in d and d['education']:
             d['education'] = [Education(**i) for i in d['education']]
        if 'projects' in d and d['projects']:
             d['projects'] = [Project(**i) for i in d['projects']]
        if 'certifications' in d and d['certifications']:
             d['certifications'] = [Certification(**i) for i in d['certifications']]

        return CVData(**d)

    def detect_column_split(self, page) -> Optional[float]:
        """
        Detects if a page has two columns by looking for a vertical whitespace gap.
        Returns the x-coordinate of the split if found, otherwise None.
        """
        try:
            width = page.width

            # Get all characters
            chars = page.chars
            if not chars:
                return None

            # Histogram of x-coordinates (presence of text)
            # Widen the scan range to catch off-center splits
            scan_start = width * 0.1
            scan_end = width * 0.9

            # Create a bucket array for the page width
            buckets = [0] * int(width + 1)
            for char in chars:
                x0 = int(char['x0'])
                x1 = int(char['x1'])
                for x in range(x0, x1 + 1):
                    if 0 <= x < len(buckets):
                        buckets[x] = 1

            # Find longest sequence of 0s in the scan range
            current_gap = 0
            best_gap_start = 0
            best_gap_len = 0
            current_gap_start = 0

            for x in range(int(scan_start), int(scan_end)):
                if buckets[x] == 0:
                    if current_gap == 0:
                        current_gap_start = x
                    current_gap += 1
                else:
                    if current_gap > best_gap_len:
                        best_gap_len = current_gap
                        best_gap_start = current_gap_start
                    current_gap = 0

            if current_gap > best_gap_len:
                best_gap_len = current_gap
                best_gap_start = current_gap_start

            # If gap is significant (e.g., > 5 points to catch tight layouts)
            if best_gap_len > 5:
                return best_gap_start + (best_gap_len / 2)
        except Exception as e:
            print(f"Error detecting columns: {e}")

        return None

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text from PDF file with layout awareness"""
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    split_x = self.detect_column_split(page)

                    if split_x:
                        # Left column
                        left = page.crop((0, 0, split_x, page.height))
                        left_text = left.extract_text()
                        if left_text:
                            text += left_text + "\n"

                        # Right column
                        right = page.crop((split_x, 0, page.width, page.height))
                        right_text = right.extract_text()
                        if right_text:
                            text += right_text + "\n"
                    else:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
        except Exception as e:
            print(f"Error reading PDF: {e}")
        return text

    def extract_contact_info(self, text: str) -> Dict:
        """Extract all contact information"""
        lines = text.split('\n')[:15]  # Check first 15 lines
        contact = {
            'name': None,
            'title': None,
            'location': None,
            'email': None,
            'phone': None,
            'linkedin': None,
            'github': None
        }

        # Extract name (usually first non-empty line)
        for line in lines:
            line = line.strip()
            if line and len(line) < 50 and not any(char in line for char in ['@', 'http', '+']):
                if re.match(r'^[A-Z][a-zA-Z\s]+$', line):
                    contact['name'] = line
                    break

        # Extract title (often second line)
        for i, line in enumerate(lines[1:5]):
            line = line.strip()
            if line and ('developer' in line.lower() or 'engineer' in line.lower() or 'manager' in line.lower()):
                contact['title'] = line
                break

        # Extract location
        for line in lines:
            if re.search(r'\b(?:Indonesia|Malaysia|Singapore|India|USA|UK)\b', line, re.IGNORECASE):
                contact['location'] = line.strip()
                break

        # Extract email
        emails = re.findall(self.email_pattern, text)
        if emails:
            contact['email'] = emails[0]

        # Extract phone
        phones = re.findall(self.phone_pattern, text)
        if phones:
            # Filter out dates and keep only phone-like patterns
            for phone in phones:
                if len(re.sub(r'[^0-9]', '', phone)) >= 8:
                    contact['phone'] = phone
                    break

        # Extract LinkedIn
        linkedin = re.findall(self.linkedin_pattern, text, re.IGNORECASE)
        if linkedin:
            contact['linkedin'] = linkedin[0]

        # Extract GitHub
        github = re.findall(self.github_pattern, text, re.IGNORECASE)
        if github:
            contact['github'] = github[0]

        return contact

    def split_into_sections(self, text: str) -> Dict[str, str]:
        """Split CV into major sections"""
        sections = {}

        # Define section headers with regex patterns
        section_patterns = {
            'summary': r'^(?:Summary|Profile|About|Objective)\s*$',
            'technical_skills': r'^(?:Technical Skills|Skills|Competencies)\s*$',
            'experience': r'^(?:Experience|Work Experience|Employment|Professional Experience)\s*$',
            'education': r'^(?:Education|Academic Background|Qualifications)\s*$',
            'projects': r'^(?:Projects|Personal Projects|Key Projects)\s*$',
            'certifications': r'^(?:Certification|Certifications|Certificates)\s*$',
            'volunteering': r'^(?:Volunteering|Volunteer|Community)\s*$'
        }

        lines = text.split('\n')
        current_section = None
        current_content = []

        for line in lines:
            line_stripped = line.strip()

            # Check if line is a section header
            is_header = False
            for section_name, pattern in section_patterns.items():
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    # Save previous section
                    if current_section and current_content:
                        sections[current_section] = '\n'.join(current_content)

                    current_section = section_name
                    current_content = []
                    is_header = True
                    break

            if not is_header and current_section:
                if line_stripped:  # Only add non-empty lines
                    current_content.append(line)

        # Save last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content)

        return sections

    def parse_technical_skills(self, text: str) -> Dict[str, List[str]]:
        """Parse technical skills section into categories"""
        skills = {}
        lines = text.split('\n')

        # Default category for list-style skills
        if "General" not in skills:
             skills["General"] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if line contains a colon (category: items)
            if ':' in line:
                parts = line.split(':', 1)
                category = parts[0].strip()
                items_text = parts[1].strip() if len(parts) > 1 else ""

                # Split items by comma
                items = [item.strip() for item in items_text.split(',') if item.strip()]

                if items:
                    skills[category] = items
            else:
                # Treat line as skills list (comma separated or single item)
                items = [item.strip() for item in line.split(',') if item.strip()]
                if items:
                    skills["General"].extend(items)

        # Remove General if empty
        if not skills["General"]:
            del skills["General"]

        return skills

    def parse_work_experience(self, text: str) -> List[WorkExperience]:
        """Parse work experience section"""
        experiences = []
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Skip empty lines
            if not line:
                i += 1
                continue

            # Check if this line or next lines contain a date pattern
            # Pattern: Date - Date
            # We look for the date line to identify the END of the header block.

            date_line_idx = -1
            start_date, end_date = "", ""

            # Look ahead up to 3 lines to find the date line
            for offset in range(3):
                if i + offset >= len(lines): break
                check_line = lines[i + offset].strip()

                # Regex for date range: "Month Year - Month Year", "Year - Year", "Year - Present"
                date_match = re.search(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present|Current)', check_line, re.IGNORECASE)

                if date_match:
                    date_line_idx = i + offset
                    start_date = date_match.group(1)
                    end_date = date_match.group(2)
                    break

            if date_line_idx != -1:
                # Found a job block
                # Lines from i to date_line_idx-1 are likely Company and Position
                header_lines = lines[i : date_line_idx]

                company = ""
                position = ""

                # Analyze header lines
                if not header_lines:
                    # Date line itself might contain info
                    line_content = lines[date_line_idx]
                    # Remove the date part
                    line_content = re.sub(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present|Current)', '', line_content, flags=re.IGNORECASE).strip()

                    if '|' in line_content:
                        parts = line_content.split('|')
                        position = parts[0].strip()
                        company = parts[1].strip()
                    elif ' at ' in line_content:
                         parts = line_content.split(' at ')
                         position = parts[0].strip()
                         company = parts[1].strip()
                    else:
                        company = line_content

                elif len(header_lines) == 1:
                    l1 = header_lines[0].strip()
                    if '|' in l1:
                        parts = l1.split('|')
                        position = parts[0].strip()
                        company = parts[1].strip()
                    elif ' at ' in l1:
                        parts = l1.split(' at ')
                        position = parts[0].strip()
                        company = parts[1].strip()
                    else:
                        # Ambiguous. Check for position keywords.
                        if any(k in l1.lower() for k in ['developer', 'engineer', 'manager', 'lead', 'head', 'intern', 'specialist', 'consultant', 'director', 'officer', 'analyst']):
                            position = l1
                        else:
                            company = l1

                elif len(header_lines) >= 2:
                    # Use first two lines
                    l1 = header_lines[0].strip()
                    l2 = header_lines[1].strip()

                    # Distinguish using keywords
                    pos_keywords = ['developer', 'engineer', 'manager', 'lead', 'head', 'intern', 'specialist', 'consultant', 'director', 'officer', 'analyst']

                    l1_is_pos = any(k in l1.lower() for k in pos_keywords)
                    l2_is_pos = any(k in l2.lower() for k in pos_keywords)

                    if l1_is_pos and not l2_is_pos:
                        position = l1
                        company = l2
                    elif l2_is_pos and not l1_is_pos:
                        company = l1
                        position = l2
                    else:
                        # Fallback: Company then Position is standard
                        company = l1
                        position = l2

                # Extract Location from Date Line (text before date)
                date_line_text = lines[date_line_idx]
                location_text = re.sub(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present|Current)', '', date_line_text, flags=re.IGNORECASE).strip()
                location = location_text.strip(" ,·•|")

                # Responsibilities
                responsibilities = []
                j = date_line_idx + 1
                while j < len(lines):
                    line_j = lines[j].strip()
                    if not line_j:
                        j += 1
                        continue

                    # Stop if we see a date pattern in upcoming lines (start of next job)
                    is_next_job = False
                    for off in range(3):
                        if j + off < len(lines):
                            if re.search(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present|Current)', lines[j+off], re.IGNORECASE):
                                if off <= 2: # Allow up to 2 header lines before date
                                    is_next_job = True
                                    break
                    if is_next_job:
                        break

                    # Clean bullet points
                    clean_line = line_j
                    if clean_line.startswith('•') or clean_line.startswith('-'):
                        clean_line = clean_line[1:].strip()

                    if clean_line:
                        responsibilities.append(clean_line)

                    j += 1

                experiences.append(WorkExperience(
                    start_date=start_date,
                    end_date=end_date,
                    position=position,
                    company=company,
                    location=location,
                    responsibilities=responsibilities
                ))

                i = j # Move main index
            else:
                i += 1 # Continue searching

        return experiences

    def parse_education(self, text: str) -> List[Education]:
        """Parse education section"""
        education_list = []
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            start_date = ""
            end_date = ""
            degree = ""
            institution = ""
            location = ""

            # Look for degree name (first line without dates)
            if line and not re.search(r'\d{4}', line):
                degree = line

                # Next line should have institution and location
                i += 1
                if i < len(lines):
                    next_line = lines[i].strip()

                    # Look for date range pattern at the end
                    # Updated regex to support month names
                    date_match = re.search(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present)', line + ' ' + next_line, re.IGNORECASE)

                    if date_match:
                        start_date = date_match.group(1)
                        end_date = date_match.group(2)
                    else:
                        # Try to find dates in the line
                        dates = re.findall(r'\d{4}', line + ' ' + next_line)
                        if len(dates) >= 2:
                            start_date = dates[0]
                            end_date = dates[1]
                        elif len(dates) == 1:
                            start_date = dates[0]
                            end_date = "Present"
                        else:
                            start_date = ""
                            end_date = ""

                    # Parse institution and location from next_line
                    # Remove dates from the line
                    institution_location = re.sub(r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})\s*[–—-]\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}|Present)', '', next_line, flags=re.IGNORECASE).strip()

                    # Split by comma
                    parts = [p.strip() for p in institution_location.split(',')]
                    institution = parts[0] if len(parts) > 0 else ""
                    location = ', '.join(parts[1:]) if len(parts) > 1 else ""

                    # Logic to swap Degree and Institution based on keywords
                    # Expanded keywords to include more variants
                    inst_keywords = [
                        'university', 'universitas', 'institute', 'institut', 'college', 'school', 'academy',
                        'politeknik', 'politech', 'campus', 'smk', 'sma', 'high school', 'universiti'
                    ]
                    degree_keywords = [
                        'bachelor', 'master', 'diploma', 'degree', 'phd', 'doctor', 'associate',
                        'sarjana', 'magister', 'teknik', 'computer', 'science', 'informatics',
                        'information', 'mca', 'b.sc', 'm.sc', 'b.a', 'm.a', 'd4', 'd3', 'siswa',
                        'major', 'minor', 'engineering'
                    ]

                    deg_lower = degree.lower()
                    inst_lower = institution.lower()

                    has_inst_in_deg = any(k in deg_lower for k in inst_keywords)
                    has_deg_in_deg = any(k in deg_lower for k in degree_keywords)

                    has_deg_in_inst = any(k in inst_lower for k in degree_keywords)
                    has_inst_in_inst = any(k in inst_lower for k in inst_keywords)

                    # Swap if Degree var looks like Institution AND Institution var looks like Degree
                    if has_inst_in_deg and has_deg_in_inst:
                         degree, institution = institution, degree
                    # Or if Degree var looks like Institution and DOES NOT look like Degree
                    elif has_inst_in_deg and not has_deg_in_deg:
                         degree, institution = institution, degree
                    # Or if Institution var looks like Degree and DOES NOT look like Institution
                    elif has_deg_in_inst and not has_inst_in_inst:
                         degree, institution = institution, degree

                    education_list.append(Education(
                        start_date=start_date,
                        end_date=end_date,
                        degree=degree,
                        institution=institution,
                        location=location
                    ))

            i += 1

        return education_list

    def parse_projects(self, text: str) -> List[Project]:
        """Parse projects section"""
        projects = []
        lines = text.split('\n')

        current_project = None
        current_description = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if line is a project name (contains colon after project name)
            if ':' in line:
                # Save previous project
                if current_project:
                    projects.append(Project(
                        name=current_project,
                        description=' '.join(current_description).strip()
                    ))

                # Split by first colon
                parts = line.split(':', 1)
                current_project = parts[0].strip()
                # Start description with text after colon
                current_description = [parts[1].strip()] if len(parts) > 1 and parts[1].strip() else []
            elif current_project:
                # Continue description
                current_description.append(line)

        # Save last project
        if current_project:
            projects.append(Project(
                name=current_project,
                description=' '.join(current_description).strip()
            ))

        return projects

    def parse_certifications(self, text: str) -> List[Certification]:
        """Parse certifications section"""
        certifications = []
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Look for certification name and date pattern
            date_match = re.search(r'([A-Z][a-z]{2}\s+\d{4})', line)

            if date_match:
                date = date_match.group(1)
                # Certification name is before the date
                name = line[:date_match.start()].strip()

                # Check next line for issuer info
                issuer = ""
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # If next line doesn't contain a date, it's likely the issuer
                    if next_line and not re.search(r'[A-Z][a-z]{2}\s+\d{4}', next_line):
                        issuer = next_line
                        i += 1

                certifications.append(Certification(
                    date=date,
                    name=name,
                    issuer=issuer
                ))

            i += 1

        return certifications

    def parse_volunteering(self, text: str) -> List[str]:
        """Parse volunteering section"""
        activities = []
        lines = text.split('\n')

        current_activity = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if line contains a date (likely start of new activity)
            if re.search(r'[A-Z][a-z]{2}\s+\d{4}', line):
                if current_activity:
                    activities.append(current_activity)
                current_activity = line
            elif current_activity:
                # Continuation of current activity
                current_activity += ' ' + line

        # Add last activity
        if current_activity:
            activities.append(current_activity)

        return activities

    def parse_cv_logic(self, pdf_path: str) -> CVData:
        """Internal parsing logic without caching"""
        text = self.extract_text_from_pdf(pdf_path)

        if not text:
            print("Could not extract text from PDF")
            return CVData()

        # Extract contact info
        contact = self.extract_contact_info(text)

        # Split into sections
        sections = self.split_into_sections(text)

        # Create CV data object
        cv_data = CVData(
            name=contact['name'],
            title=contact['title'],
            location=contact['location'],
            email=contact['email'],
            phone=contact['phone'],
            linkedin=contact['linkedin'],
            github=contact['github'],
            summary=sections.get('summary', '').strip()
        )

        # Parse each section
        if 'technical_skills' in sections:
            cv_data.technical_skills = self.parse_technical_skills(sections['technical_skills'])

        if 'experience' in sections:
            cv_data.work_experience = self.parse_work_experience(sections['experience'])

        if 'education' in sections:
            cv_data.education = self.parse_education(sections['education'])

        if 'projects' in sections:
            cv_data.projects = self.parse_projects(sections['projects'])

        if 'certifications' in sections:
            cv_data.certifications = self.parse_certifications(sections['certifications'])

        if 'volunteering' in sections:
            cv_data.volunteering = self.parse_volunteering(sections['volunteering'])

        return cv_data

    def parse_cv(self, pdf_path: str) -> CVData:
        """Main parsing method with caching"""
        # Check cache
        file_hash = self.get_file_hash(pdf_path)
        if self.redis:
            try:
                cached_data = self.redis.get(f"cv:{file_hash}")
                if cached_data:
                    print(f"Cache hit for {file_hash}")
                    data_dict = json.loads(cached_data)
                    return self._reconstruct_cv_data(data_dict)
            except Exception as e:
                print(f"Redis get failed: {e}")

        # Parse
        cv_data = self.parse_cv_logic(pdf_path)

        # Cache
        if self.redis:
            try:
                data_dict = dataclass_to_dict(cv_data)
                self.redis.setex(f"cv:{file_hash}", 86400, json.dumps(data_dict)) # 24 hours
            except Exception as e:
                print(f"Redis set failed: {e}")

        return cv_data

# Initialize CV Reader
cv_reader = ImprovedCVReader()
