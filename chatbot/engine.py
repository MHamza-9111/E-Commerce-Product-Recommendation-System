import json
import pickle
import random
from pathlib import Path

import numpy as np
from nltk.stem import PorterStemmer
from nltk.tokenize import wordpunct_tokenize
from tensorflow.keras.models import load_model


# Folder containing this engine.py file
CHATBOT_DIR = Path(__file__).resolve().parent


# Complete file paths
INTENTS_FILE = CHATBOT_DIR / "intents.json"
MODEL_FILE = CHATBOT_DIR / "chatbot_model.keras"
WORDS_FILE = CHATBOT_DIR / "words.pkl"
CLASSES_FILE = CHATBOT_DIR / "classes.pkl"


# Minimum confidence required to accept a prediction
MIN_CONFIDENCE = 0.45


# Load intents.json
with open(INTENTS_FILE, "r", encoding="utf-8") as file:
    intents_data = json.load(file)


# Load the known vocabulary
with open(WORDS_FILE, "rb") as file:
    words = pickle.load(file)


# Load the intent classes
with open(CLASSES_FILE, "rb") as file:
    classes = pickle.load(file)


# Load the trained TensorFlow model
model = load_model(MODEL_FILE)


# Create the NLTK stemmer
stemmer = PorterStemmer()


def clean_text(text):
    """Convert a sentence into cleaned and stemmed words."""

    tokens = wordpunct_tokenize(text.lower())

    cleaned_tokens = []

    for token in tokens:
        if token.isalpha() and len(token) > 1:
            cleaned_tokens.append(stemmer.stem(token))

    return cleaned_tokens


def create_bag_of_words(message):
    """Convert a user message into a Bag-of-Words array."""

    message_words = clean_text(message)

    bag = np.zeros(len(words), dtype=np.float32)

    for message_word in message_words:
        if message_word in words:
            word_position = words.index(message_word)
            bag[word_position] = 1

    return np.array([bag], dtype=np.float32)


def predict_intent(message):
    """Predict the intent and confidence of a user message."""

    bag = create_bag_of_words(message)

    probabilities = model.predict(
        bag,
        verbose=0
    )[0]

    best_position = int(np.argmax(probabilities))

    predicted_intent = classes[best_position]
    confidence = float(probabilities[best_position])

    if confidence < MIN_CONFIDENCE:
        return "unknown", confidence

    return predicted_intent, confidence


def get_response(intent_tag):
    """Get a random response for a predicted intent."""

    for intent in intents_data["intents"]:
        if intent["tag"] == intent_tag:
            return random.choice(intent["responses"])

    return (
        "Sorry, I did not understand that. "
        "Try asking about products, orders or checkout."
    )


def chatbot_reply(message):
    """Create the complete chatbot result."""

    intent, confidence = predict_intent(message)

    if intent == "unknown":
        reply = (
            "Sorry, I did not understand that. "
            "Try asking about products, recommendations, "
            "orders or checkout."
        )
    else:
        reply = get_response(intent)

    return {
        "reply": reply,
        "intent": intent,
        "confidence": round(confidence, 4)
    }


# Run a terminal chatbot when this file is executed directly
if __name__ == "__main__":
    print("ApBot engine loaded successfully.")
    print("Type 'quit' to stop.")

    while True:
        user_message = input("\nYou: ").strip()

        if user_message.lower() == "quit":
            print("ApBot: Goodbye!")
            break

        if not user_message:
            print("ApBot: Please enter a message.")
            continue

        result = chatbot_reply(user_message)

        print("ApBot:", result["reply"])
        print("Intent:", result["intent"])
        print(
            "Confidence:",
            round(result["confidence"] * 100, 2),
            "%"
        )