import spacy

nlp = None

def load_nlp():
    global nlp
    try:
        nlp = spacy.load('en_core_web_sm')
        print("Spacy model loaded.")
    except OSError:
        print("Spacy model not found. Please install it with: python -m spacy download en_core_web_sm")
        nlp = None

def get_nlp():
    return nlp
