from transformers import pipeline
from app.models.cv import CVData, WorkExperience, Education, Project, Certification
from app.services.cv_parser import cv_reader
from typing import List, Dict, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MLCVParser:
    def __init__(self):
        self.nlp = None
        try:
            logger.info("Loading BERT NER model...")
            # using aggregation_strategy="simple" to merge B- and I- tags
            self.nlp = pipeline("ner", model="yashpwr/resume-ner-bert-v2", aggregation_strategy="simple")
            logger.info("BERT NER model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load BERT model: {e}")

    def parse_cv(self, pdf_path: str) -> CVData:
        # Extract text using column-aware reader
        text = cv_reader.extract_text_from_pdf(pdf_path)

        if not self.nlp:
            logger.warning("BERT model not active. Returning empty data.")
            return CVData(summary="Model failed to load.")

        # Chunk text because BERT has 512 token limit
        # A simple approximation: 1000 characters ~ 200-300 tokens
        # Overlap to avoid cutting entities
        chunks = self._chunk_text(text, chunk_size=1000, overlap=100)

        all_entities = []
        for chunk in chunks:
            try:
                entities = self.nlp(chunk)
                all_entities.extend(entities)
            except Exception as e:
                logger.error(f"Error processing chunk: {e}")

        return self._map_entities_to_cv_data(all_entities)

    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 100) -> List[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
            if start < 0: start = 0 # should not happen but safety

        return chunks

    def _map_entities_to_cv_data(self, entities: List[Dict[str, Any]]) -> CVData:
        data = CVData()

        skills = set()
        companies = []
        designations = []
        degrees = []
        colleges = []

        # We need to deduplicate entities that might appear in overlapping chunks
        # Simple deduplication by text and label
        seen = set()
        unique_entities = []
        for e in entities:
            key = (e['entity_group'], e['word'])
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        for entity in unique_entities:
            label = entity['entity_group']
            text = entity['word'].strip()

            if not text: continue

            if label == "Name" and not data.name:
                data.name = text
            elif label in ["Email Address", "Email"] and not data.email:
                data.email = text
            elif label == "Skills":
                # Split skills by comma if the model grouped them
                for skill in text.split(','):
                    skills.add(skill.strip())
            elif label == "Companies worked at":
                companies.append(text)
            elif label == "Designation":
                designations.append(text)
            elif label == "Degree":
                degrees.append(text)
            elif label == "College Name":
                colleges.append(text)
            elif label == "Location" and not data.location:
                data.location = text

        if skills:
            data.technical_skills = {"Extracted": list(skills)}

        # Attempt to pair Work Experience
        # This is a heuristic and might be inaccurate
        max_exp = max(len(companies), len(designations))
        for i in range(max_exp):
            comp = companies[i] if i < len(companies) else ""
            pos = designations[i] if i < len(designations) else ""
            if comp or pos:
                data.work_experience.append(WorkExperience(
                    company=comp,
                    position=pos,
                    start_date="",
                    end_date="",
                    location="",
                    responsibilities=[]
                ))

        # Attempt to pair Education
        max_edu = max(len(colleges), len(degrees))
        for i in range(max_edu):
            coll = colleges[i] if i < len(colleges) else ""
            deg = degrees[i] if i < len(degrees) else ""
            if coll or deg:
                data.education.append(Education(
                    institution=coll,
                    degree=deg,
                    start_date="",
                    end_date="",
                    location=""
                ))

        return data

# Initialize singleton
ml_cv_parser = MLCVParser()
