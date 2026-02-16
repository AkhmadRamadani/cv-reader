"""
Test client for CV Reader API
Demonstrates how to use the API programmatically
"""

import requests
import json
import sys
from pathlib import Path


class CVReaderClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
    
    def health_check(self):
        """Check if the API is healthy"""
        try:
            response = requests.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Health check failed: {e}")
            return None
    
    def parse_cv(self, pdf_path: str):
        """Parse a CV/Resume PDF"""
        # Check if file exists
        if not Path(pdf_path).exists():
            print(f"Error: File not found: {pdf_path}")
            return None
        
        # Check if file is PDF
        if not pdf_path.lower().endswith('.pdf'):
            print("Error: File must be a PDF")
            return None
        
        try:
            # Open and send file
            with open(pdf_path, 'rb') as f:
                files = {'file': (Path(pdf_path).name, f, 'application/pdf')}
                response = requests.post(f"{self.base_url}/parse-cv", files=files)
                response.raise_for_status()
                return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"Error parsing CV: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None
    
    def print_cv_data(self, result):
        """Pretty print CV data"""
        if not result or not result.get('success'):
            print("Failed to parse CV")
            return
        
        data = result.get('data', {})
        
        print("\n" + "="*80)
        print("CV PARSING RESULTS")
        print("="*80)
        
        # Personal Information
        print("\n📋 PERSONAL INFORMATION")
        print("-"*80)
        print(f"Name:      {data.get('name', 'N/A')}")
        print(f"Title:     {data.get('title', 'N/A')}")
        print(f"Location:  {data.get('location', 'N/A')}")
        print(f"Email:     {data.get('email', 'N/A')}")
        print(f"Phone:     {data.get('phone', 'N/A')}")
        print(f"LinkedIn:  {data.get('linkedin', 'N/A')}")
        print(f"GitHub:    {data.get('github', 'N/A')}")
        
        # Summary
        if data.get('summary'):
            print("\n📝 SUMMARY")
            print("-"*80)
            print(data['summary'])
        
        # Technical Skills
        if data.get('technical_skills'):
            print("\n💻 TECHNICAL SKILLS")
            print("-"*80)
            for category, skills in data['technical_skills'].items():
                print(f"\n{category}:")
                for skill in skills:
                    print(f"  • {skill}")
        
        # Work Experience
        if data.get('work_experience'):
            print("\n💼 WORK EXPERIENCE")
            print("-"*80)
            for i, exp in enumerate(data['work_experience'], 1):
                print(f"\n{i}. {exp['position']}")
                print(f"   {exp['company']}, {exp['location']}")
                print(f"   {exp['start_date']} - {exp['end_date']}")
                if exp.get('responsibilities'):
                    print("   Responsibilities:")
                    for resp in exp['responsibilities']:
                        print(f"     • {resp}")
        
        # Education
        if data.get('education'):
            print("\n🎓 EDUCATION")
            print("-"*80)
            for i, edu in enumerate(data['education'], 1):
                print(f"\n{i}. {edu['degree']}")
                print(f"   {edu['institution']}, {edu['location']}")
                print(f"   {edu['start_date']} - {edu['end_date']}")
        
        # Projects
        if data.get('projects'):
            print("\n📁 PROJECTS")
            print("-"*80)
            for i, proj in enumerate(data['projects'], 1):
                print(f"\n{i}. {proj['name']}")
                print(f"   {proj['description']}")
        
        # Certifications
        if data.get('certifications'):
            print("\n🏆 CERTIFICATIONS")
            print("-"*80)
            for i, cert in enumerate(data['certifications'], 1):
                print(f"\n{i}. {cert['name']}")
                print(f"   Issuer: {cert['issuer']}")
                print(f"   Date: {cert['date']}")
        
        # Volunteering
        if data.get('volunteering'):
            print("\n🤝 VOLUNTEERING")
            print("-"*80)
            for i, activity in enumerate(data['volunteering'], 1):
                print(f"{i}. {activity}")
        
        print("\n" + "="*80)


def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python test_client.py <path_to_cv.pdf>")
        print("\nExample: python test_client.py resume.pdf")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    # Create client
    client = CVReaderClient()
    
    # Check API health
    print("Checking API health...")
    health = client.health_check()
    if not health:
        print("Error: API is not responding. Make sure the server is running.")
        sys.exit(1)
    
    print(f"✓ API Status: {health.get('status')}")
    print(f"✓ Spacy Loaded: {health.get('spacy_loaded')}")
    
    # Parse CV
    print(f"\nParsing CV: {pdf_path}")
    result = client.parse_cv(pdf_path)
    
    if result:
        # Print results
        client.print_cv_data(result)
        
        # Optionally save to JSON file
        output_file = Path(pdf_path).stem + "_parsed.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Results saved to: {output_file}")
    else:
        print("Failed to parse CV")
        sys.exit(1)


if __name__ == "__main__":
    main()
