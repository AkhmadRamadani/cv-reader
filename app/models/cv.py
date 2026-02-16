from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class WorkExperience:
    start_date: str
    end_date: str
    position: str
    company: str
    location: str
    responsibilities: List[str]


@dataclass
class Education:
    start_date: str
    end_date: str
    degree: str
    institution: str
    location: str


@dataclass
class Project:
    name: str
    description: str


@dataclass
class Certification:
    date: str
    name: str
    issuer: str


@dataclass
class CVData:
    name: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None
    summary: Optional[str] = None
    technical_skills: Dict[str, List[str]] = field(default_factory=dict)
    work_experience: List[WorkExperience] = field(default_factory=list)
    education: List[Education] = field(default_factory=list)
    projects: List[Project] = field(default_factory=list)
    certifications: List[Certification] = field(default_factory=list)
    volunteering: List[str] = field(default_factory=list)

    def __post_init__(self):
        # Ensure lists/dicts are not None if passed as None explicitly
        if self.technical_skills is None:
            self.technical_skills = {}
        if self.work_experience is None:
            self.work_experience = []
        if self.education is None:
            self.education = []
        if self.projects is None:
            self.projects = []
        if self.certifications is None:
            self.certifications = []
        if self.volunteering is None:
            self.volunteering = []
