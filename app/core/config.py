import os

class Settings:
    PROJECT_NAME: str = "CV Reader API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Spacy
    SPACY_MODEL: str = "en_core_web_sm"

settings = Settings()
