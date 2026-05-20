import os


class Settings:
    PROJECT_NAME: str = "CV Reader API"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Spacy
    SPACY_MODEL: str = "en_core_web_sm"

    # LLM Configuration (provider-agnostic via litellm)
    # Examples:
    #   gemini/gemini-2.0-flash       (Google - needs GEMINI_API_KEY)
    #   gpt-4o-mini                   (OpenAI - needs OPENAI_API_KEY)
    #   anthropic/claude-3-haiku      (Anthropic - needs ANTHROPIC_API_KEY)
    #   groq/llama3-8b-8192           (Groq - needs GROQ_API_KEY)
    #   ollama/llama3                 (Local Ollama - free, no key needed)
    #   ollama/mistral                (Local Ollama - free, no key needed)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "")  # For Ollama: http://localhost:11434


settings = Settings()
