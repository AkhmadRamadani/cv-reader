# CV Reader FastAPI Application

A FastAPI application that extracts structured information from CV/Resume PDFs using advanced text parsing and NLP techniques. This application is production-ready with Redis caching and rate limiting.

## Features

- 📄 Extract personal information (name, email, phone, LinkedIn, GitHub)
- 💼 Parse work experience with dates, positions, and responsibilities
- 🎓 Extract education history
- 💻 Categorize technical skills
- 📁 Parse projects and descriptions
- 🏆 Extract certifications
- 🤝 Parse volunteering activities
- 🚀 Fast and efficient API
- 📊 RESTful JSON responses
- ⚡ Redis caching for performance
- 🛡️ Rate limiting for API protection

## Project Structure

The project has been refactored for better maintainability:

```
.
├── app
│   ├── api          # API endpoints
│   ├── core         # Configuration, NLP, Rate Limiting
│   ├── models       # Data models
│   ├── services     # Business logic (CV Parsing)
│   └── main.py      # Application entry point
├── templates        # LaTeX templates
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Download Spacy Model

```bash
python -m spacy download en_core_web_sm
```

## Running the Application

### Development Mode

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode (Docker)

To run the application with Redis caching and Gunicorn:

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

## API Documentation

Once the server is running, you can access:
- Interactive API docs (Swagger UI): `http://localhost:8000/docs`
- Alternative API docs (ReDoc): `http://localhost:8000/redoc`

## Features Detail

### Redis Caching
The application uses Redis to cache parsed CV results for 24 hours. The cache key is generated from the SHA256 hash of the PDF file content.

### Rate Limiting
The API is rate-limited to 5 requests per minute per IP address to prevent abuse.

## LaTeX CV Template

A clean and professional LaTeX CV template is included in `templates/cv_template.tex`.

### How to use with Overleaf

1.  Go to [Overleaf](https://www.overleaf.com/).
2.  Create a **New Project** -> **Blank Project**.
3.  Name your project (e.g., "My CV").
4.  In the project editor, replace the content of `main.tex` with the content of `templates/cv_template.tex`.
5.  Click **Recompile**.
6.  Edit the content with your own information.
7.  Download the PDF.

## API Endpoints

### 1. Root Endpoint
```
GET /
```
Returns API information and available endpoints.

### 2. Health Check
```
GET /health
```
Check if the API is running and if spacy model is loaded.

### 3. Parse CV
```
POST /parse-cv
```
Upload and parse a CV/Resume PDF file.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Body: PDF file (form field name: `file`)

**Example using curl:**
```bash
curl -X POST "http://localhost:8000/parse-cv" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/your/resume.pdf"
```

## License

MIT
