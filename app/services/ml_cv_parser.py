
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from typing import Dict, List, Any
import numpy as np

class MLCVParser:
    def __init__(self):
        self.model_name = "yashpwr/resume-ner-bert-v2"
        self.tokenizer = None
        self.model = None
        self.id2label = None
        self.model_loaded = False

    def _load_model(self):
        if self.model_loaded:
            return

        try:
            print(f"Loading ML model: {self.model_name}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForTokenClassification.from_pretrained(self.model_name)
            self.id2label = self.model.config.id2label
            self.model_loaded = True
            print("ML model loaded successfully.")
        except Exception as e:
            print(f"Failed to load ML model: {e}")
            self.model_loaded = False

    def parse(self, text: str) -> Dict[str, Any]:
        self._load_model()

        if not self.tokenizer or not self.model:
            return {"error": "Model not loaded"}

        # Text cleaning/preprocessing if needed
        # The model has a max length of 512. Resumes are often longer.
        # We need to chunk the text.

        # Tokenize the entire text without truncation first to see length
        # Return python lists by default (no return_tensors="pt")
        tokens = self.tokenizer(text, add_special_tokens=False)
        input_ids = tokens["input_ids"]

        # Split into chunks of 510 tokens (leaving room for [CLS] and [SEP])
        chunk_size = 510
        chunks = [input_ids[i:i + chunk_size] for i in range(0, len(input_ids), chunk_size)]

        all_entities = []

        for chunk in chunks:
            # Add special tokens
            # Manual concatenation for robustness
            chunk_input_ids = [self.tokenizer.cls_token_id] + chunk + [self.tokenizer.sep_token_id]
            chunk_tensor = torch.tensor([chunk_input_ids])

            # Inference
            with torch.no_grad():
                outputs = self.model(chunk_tensor)
                predictions = torch.argmax(outputs.logits, dim=2)

            # Decode entities
            tokens_list = self.tokenizer.convert_ids_to_tokens(chunk_input_ids)

            current_entity = None

            for i, pred_idx in enumerate(predictions[0]):
                label = self.id2label[pred_idx.item()]
                token = tokens_list[i]

                # Skip special tokens
                if token in ["[CLS]", "[SEP]", "[PAD]"]:
                    continue

                # Handle subword tokens (start with ##)
                clean_token = token.replace("##", "") if token.startswith("##") else token

                if label.startswith("B-"):
                    if current_entity:
                        all_entities.append(current_entity)

                    current_entity = {
                        "label": label[2:],
                        "text": clean_token
                    }
                elif label.startswith("I-"):
                    if current_entity and current_entity["label"] == label[2:]:
                        # Append to current entity
                        if token.startswith("##"):
                            current_entity["text"] += clean_token
                        else:
                            current_entity["text"] += " " + clean_token
                    elif current_entity:
                        # Label mismatch or new entity implicit?
                        # Usually I- tag should follow B- tag of same type.
                        # If different, treat as new start or ignore?
                        # Let's treat as continuation if it makes sense, or start new if not.
                        # Ideally, I- tag without B- is invalid BIO, but model might produce it.
                        pass
                else: # O tag
                    if current_entity:
                        all_entities.append(current_entity)
                        current_entity = None

            if current_entity:
                all_entities.append(current_entity)

        return self._structure_data(all_entities)

    def _structure_data(self, entities: List[Dict]) -> Dict[str, Any]:
        data = {
            "name": None,
            "email": None,
            "phone": None,
            "location": None,
            "skills": [],
            "work_experience": [],
            "education": [],
            "designation": [], # Temporary list to store roles
            "companies": [],   # Temporary list to store companies
            "years_of_experience": None
        }

        for ent in entities:
            label = ent["label"]
            text = ent["text"]

            if label == "Name" and not data["name"]:
                data["name"] = text
            elif label == "Email Address":
                data["email"] = text
            elif label == "Phone":
                data["phone"] = text
            elif label == "Location":
                data["location"] = text
            elif label == "Skills":
                data["skills"].append(text)
            elif label == "Years of Experience":
                data["years_of_experience"] = text

            # Collect for later grouping
            elif label == "Designation":
                data["designation"].append(text)
            elif label == "Companies worked at":
                data["companies"].append(text)
            elif label == "Degree":
                data["education"].append({"degree": text}) # Placeholder
            elif label == "College Name":
                # Try to associate with last education entry if it lacks college
                if data["education"] and "institution" not in data["education"][-1]:
                     data["education"][-1]["institution"] = text
                else:
                     data["education"].append({"institution": text})
            elif label == "Graduation Year":
                 if data["education"] and "end_date" not in data["education"][-1]:
                     data["education"][-1]["end_date"] = text
                 else:
                     data["education"].append({"end_date": text})

        # Post-process Work Experience
        # This is a heuristic: Zip companies and designations.
        # It's imperfect but standard for flat NER outputs.
        max_len = max(len(data["companies"]), len(data["designation"]))
        for i in range(max_len):
            comp = data["companies"][i] if i < len(data["companies"]) else None
            role = data["designation"][i] if i < len(data["designation"]) else None

            if comp or role:
                data["work_experience"].append({
                    "company": comp,
                    "position": role
                })

        # Clean up temporary keys
        del data["designation"]
        del data["companies"]

        return data

# Singleton instance
ml_parser = MLCVParser()
