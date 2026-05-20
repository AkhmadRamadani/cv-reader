from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class WorkExperience:
    start_date: str = ""
    end_date: str = ""
    position: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    responsibilities: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.responsibilities is None:
            self.responsibilities = []


@dataclass
class Education:
    start_date: str = ""
    end_date: str = ""
    degree: str = ""
    institution: str = ""
    location: str = ""
    gpa: Optional[str] = None
    details: Optional[str] = None


@dataclass
class Project:
    name: str = ""
    description: str = ""
    technologies: List[str] = field(default_factory=list)
    url: Optional[str] = None

    def __post_init__(self):
        if self.technologies is None:
            self.technologies = []


@dataclass
class Certification:
    date: str = ""
    name: str = ""
    issuer: str = ""
    credential_id: Optional[str] = None


@dataclass
class Language:
    name: str = ""
    proficiency: str = ""


@dataclass
class Organization:
    role: str = ""
    organization: str = ""
    description: str = ""
    start_date: str = ""
    end_date: str = ""


@dataclass
class Award:
    name: str = ""
    issuer: str = ""
    date: str = ""
    description: str = ""


@dataclass
class Publication:
    title: str = ""
    publisher: str = ""
    date: str = ""
    url: Optional[str] = None


@dataclass
class Reference:
    name: str = ""
    position: str = ""
    company: str = ""
    contact: str = ""


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
    skills: Dict[str, List[str]] = field(default_factory=dict)
    work_experience: List[WorkExperience] = field(default_factory=list)
    education: List[Education] = field(default_factory=list)
    projects: List[Project] = field(default_factory=list)
    certifications: List[Certification] = field(default_factory=list)
    languages: List[Language] = field(default_factory=list)
    organizations: List[Organization] = field(default_factory=list)
    awards: List[Award] = field(default_factory=list)
    publications: List[Publication] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)
    raw_text: Optional[str] = None

    def __post_init__(self):
        if self.skills is None:
            self.skills = {}
        if self.work_experience is None:
            self.work_experience = []
        if self.education is None:
            self.education = []
        if self.projects is None:
            self.projects = []
        if self.certifications is None:
            self.certifications = []
        if self.languages is None:
            self.languages = []
        if self.organizations is None:
            self.organizations = []
        if self.awards is None:
            self.awards = []
        if self.publications is None:
            self.publications = []
        if self.references is None:
            self.references = []
