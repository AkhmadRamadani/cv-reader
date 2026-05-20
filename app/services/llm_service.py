"""
Provider-agnostic LLM service using litellm.

Supports any provider by changing LLM_MODEL env var:
  - gemini/gemini-2.0-flash  (Google)
  - gpt-4o-mini              (OpenAI)
  - anthropic/claude-3-haiku (Anthropic)
  - groq/llama3-8b-8192      (Groq)
  - ollama/llama3            (Local, free)
"""

import json
import hashlib
import litellm
import redis
from typing import Optional
from app.core.config import settings

# Suppress litellm debug logs
litellm.suppress_debug_info = True

CV_EXTRACTION_PROMPT = """You are a CV/Resume data extraction expert. Extract structured information from the following CV text and return it as a valid JSON object.

Rules:
- Extract ALL information present in the CV regardless of profession or industry
- If a field is not found, use null
- For arrays, use empty array [] if no items found
- Return ONLY valid JSON, no markdown, no explanation
- Dates should be kept in their original format
- Responsibilities/duties should be individual items in an array
- Skills can be from any field: technical, soft skills, languages, tools, methodologies, etc.
- Work experience includes any type of employment: corporate, freelance, teaching, medical, legal, creative, etc.

Return this exact JSON structure:
{
  "name": "Full name",
  "title": "Professional title/headline",
  "location": "Address or location",
  "email": "email@example.com",
  "phone": "phone number",
  "linkedin": "linkedin URL",
  "github": "github or portfolio URL",
  "website": "personal/professional website URL",
  "summary": "Professional summary, objective, or profile text",
  "skills": {
    "Category Name": ["skill1", "skill2"]
  },
  "work_experience": [
    {
      "position": "Job Title/Role",
      "company": "Company/Organization Name",
      "location": "City, Country",
      "start_date": "Start date",
      "end_date": "End date or Present",
      "description": "Brief role description if any",
      "responsibilities": ["responsibility/achievement 1", "responsibility/achievement 2"]
    }
  ],
  "education": [
    {
      "degree": "Degree/Qualification name",
      "institution": "University/School/Institution name",
      "location": "City, Country",
      "start_date": "Start date",
      "end_date": "End date",
      "gpa": "GPA/Grade if mentioned",
      "details": "Relevant coursework, thesis, honors, etc."
    }
  ],
  "projects": [
    {
      "name": "Project name",
      "description": "Project description",
      "technologies": ["tool/method/tech used"],
      "url": "project URL if any"
    }
  ],
  "certifications": [
    {
      "name": "Certification/License name",
      "issuer": "Issuing organization",
      "date": "Date obtained",
      "credential_id": "ID/Number if mentioned"
    }
  ],
  "languages": [
    {
      "name": "Language",
      "proficiency": "Level"
    }
  ],
  "organizations": [
    {
      "role": "Role/Position",
      "organization": "Organization name",
      "description": "Description of involvement",
      "start_date": "Start date",
      "end_date": "End date"
    }
  ],
  "awards": [
    {
      "name": "Award/Achievement name",
      "issuer": "Issuing body",
      "date": "Date",
      "description": "Description if any"
    }
  ],
  "publications": [
    {
      "title": "Publication title",
      "publisher": "Journal/Conference/Publisher",
      "date": "Date",
      "url": "URL if any"
    }
  ],
  "references": [
    {
      "name": "Reference name",
      "position": "Their position",
      "company": "Their company",
      "contact": "Phone or email"
    }
  ]
}

CV Text:
"""


class LLMService:
    """Provider-agnostic LLM service for CV extraction."""

    def __init__(self):
        self.model = settings.LLM_MODEL
        self.api_base = settings.LLM_API_BASE or None

        # Initialize Redis for caching
        try:
            self.redis = redis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
            self.redis.ping()
            print("LLM Service: Redis cache connected")
        except Exception as e:
            print(f"LLM Service: Redis not available (no caching): {e}")
            self.redis = None

    def _get_text_hash(self, text: str) -> str:
        """Hash the input text for cache key."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def extract_cv_structured(self, raw_text: str) -> dict:
        """
        Send raw CV text to LLM and get structured JSON back.
        Uses Redis cache — same file = instant response on repeat calls.
        """
        # Check cache first
        text_hash = self._get_text_hash(raw_text)
        cache_key = f"llm_cv:{self.model}:{text_hash}"

        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    print(f"LLM cache hit for {text_hash[:12]}...")
                    return json.loads(cached)
            except Exception as e:
                print(f"Redis cache get error: {e}")

        # No cache hit — call LLM
        prompt = CV_EXTRACTION_PROMPT + raw_text

        kwargs = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        # For Ollama or custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base

        try:
            response = litellm.completion(**kwargs)
            content = response.choices[0].message.content

            # Clean response — strip markdown code fences if present
            content = content.strip()
            if content.startswith("```"):
                # Remove ```json and trailing ```
                lines = content.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = '\n'.join(lines)

            # Try to parse JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Attempt to repair truncated JSON
                repaired = self._repair_json(content)
                if repaired is not None:
                    result = repaired
                else:
                    raise ValueError(
                        f"LLM returned invalid JSON that could not be repaired. "
                        f"Raw response: {content[:200]}"
                    )

            # Cache the result (24 hours)
            if self.redis:
                try:
                    self.redis.setex(cache_key, 86400, json.dumps(result))
                    print(f"LLM result cached for {text_hash[:12]}...")
                except Exception as e:
                    print(f"Redis cache set error: {e}")

            return result

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"LLM request failed: {e}")

    def _repair_json(self, content: str) -> Optional[dict]:
        """
        Attempt to repair truncated or malformed JSON.
        Handles common cases: missing closing braces/brackets,
        unterminated strings.
        """
        # Remove trailing incomplete values (unterminated strings)
        # Find the last complete key-value pair
        content = content.rstrip()

        # Try progressively trimming from the end
        # and closing open structures
        for trim in range(0, min(200, len(content)), 1):
            attempt = content[:len(content) - trim] if trim > 0 else content

            # Count open/close braces and brackets
            open_braces = attempt.count('{') - attempt.count('}')
            open_brackets = attempt.count('[') - attempt.count(']')

            # Check if we're inside an unterminated string
            # Simple heuristic: if odd number of unescaped quotes
            in_string = attempt.count('"') % 2 != 0

            if in_string:
                # Close the string
                attempt += '"'

            # Remove trailing comma if present
            attempt = attempt.rstrip()
            if attempt.endswith(','):
                attempt = attempt[:-1]

            # Close open brackets and braces
            attempt += ']' * open_brackets
            attempt += '}' * open_braces

            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue

        return None

    def get_model_info(self) -> dict:
        """Return current LLM configuration."""
        return {
            "model": self.model,
            "api_base": self.api_base or "default",
            "provider": self.model.split("/")[0] if "/" in self.model else "openai"
        }


# Module-level instance
llm_service = LLMService()
