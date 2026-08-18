import json
import pickle
import random
from pathlib import Path

import numpy as np
from nltk.stem import PorterStemmer
from nltk.tokenize import wordpunct_tokenize
from tensorflow.keras.models import load_model


# find folder containing this engine.py file
CHATBOT_DIR = Path(__file__).resolve().parent


# find all file paths
INTENTS_FILE = CHATBOT_DIR / "intents.json"
MODEL_FILE   = CHATBOT_DIR / "chatbot_model.keras"
WORDS_FILE   = CHATBOT_DIR / "words.pkl"
CLASSES_FILE = CHATBOT_DIR / "classes.pkl"


# minimum confidence for prediction 
MIN_CONFIDENCE = 0.45

# maximum history reserve
MAX_HISTORY_TURNS = 6


# load intents.json
with open(INTENTS_FILE, "r", encoding="utf-8") as file:
    intents_data = json.load(file)


# load the known vocabulary
with open(WORDS_FILE, "rb") as file:
    words = pickle.load(file)


# load the intent classes
with open(CLASSES_FILE, "rb") as file:
    classes = pickle.load(file)


# load the trained TensorFlow model
model = load_model(MODEL_FILE)


# creating the NLTK stemmer instance
stemmer = PorterStemmer()


# Intents that represent an active product context the user may follow up on
PRODUCT_INTENTS = {
    "product_search",
    "product_details",
    "similar_products",
    "product_comparison",
    "recommendation",
    "offers",
}

# Pronouns that signal the user is talking about the
# same item shown in the previous bot reply
CONTEXT_PRONOUNS = {
    "this", "it", "that", "these", "those", "one",
    "this one", "that one", "the first", "first one",
    "second one", "the one", "same", "similar", "them",
}

# Short words that indicate a follow-up question rather than a new topic
FOLLOW_UP_WORDS = {
    "more", "show", "another", "else", "other", "different",
    "alternatives", "yes", "yeah", "sure", "okay", "ok",
    "how much", "price", "cost", "available", "stock", "rating",
    "reviews", "details", "info", "tell", "explain",
}

# Words that specifically ask about price or availability
PRICE_WORDS  = {"price", "cost", "how much", "expensive", "cheap", "affordable", "rate"}
STOCK_WORDS  = {"available", "stock", "in stock", "availability"}

# Single-word affirmations used to confirm/continue a flow
AFFIRMATIONS = {"yes", "yeah", "sure", "okay", "ok", "alright", "go ahead", "proceed"}


def _get_last_bot_intent(history):
    """Return the intent tag from the most recent bot turn in history."""
    if not history:
        return None
    for turn in reversed(history):
        if turn.get("role") == "bot" and turn.get("intent"):
            return turn["intent"]
    return None


def _is_context_follow_up(message):
    """
    Return True when the message looks like a follow-up that refers back to
    something the bot already showed (uses a pronoun, is short and contains a
    follow-up word, or asks about price / stock).
    """
    words_set = set(message.lower().split())

    # Explicit context pronoun present
    if words_set & CONTEXT_PRONOUNS:
        return True

    # Short message (≤5 words) that contains a follow-up trigger word
    if len(words_set) <= 5 and words_set & FOLLOW_UP_WORDS:
        return True

    # Price or availability question
    if words_set & PRICE_WORDS or words_set & STOCK_WORDS:
        return True

    return False


def resolve_with_context(message, intent, confidence, history):
    if not history:
        return intent, confidence

    last_intent = _get_last_bot_intent(history)
    msg_lower   = message.lower().strip()
    msg_words   = set(msg_lower.split())

 
    if intent == "unknown" and last_intent in PRODUCT_INTENTS:
        if _is_context_follow_up(message):
            return last_intent, 0.75

    if confidence < 0.60 and last_intent in PRODUCT_INTENTS:
        if _is_context_follow_up(message):
            return last_intent, 0.70

    if msg_lower in AFFIRMATIONS:
        if last_intent == "recommendation":
            return "cart", 0.80
        if last_intent in {"checkout", "cart"}:
            return "checkout", 0.85


    if last_intent in PRODUCT_INTENTS and intent in {"unknown", "help"}:
        if msg_words & PRICE_WORDS or msg_words & STOCK_WORDS:
            return "product_details", 0.72

    if last_intent in PRODUCT_INTENTS and intent in {"unknown", "help"}:
        more_words = {"more", "another", "else", "other", "different", "alternatives"}
        if msg_words & more_words:
            return "similar_products", 0.70

    return intent, confidence


# NLP Pipeline
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
    probabilities = model.predict(bag, verbose=0)[0]
    best_position  = int(np.argmax(probabilities))
    predicted_intent = classes[best_position]
    confidence       = float(probabilities[best_position])
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
        "Try asking about products, recommendations, orders or checkout."
    )


def chatbot_reply(message, history=None):
    safe_history = []
    if history and isinstance(history, list):
        safe_history = [
            turn for turn in history
            if isinstance(turn, dict) and turn.get("role") in {"user", "bot"}
        ][-MAX_HISTORY_TURNS:]

    # Step 1 – ML model classification
    raw_intent, raw_confidence = predict_intent(message)

    # Step 2 – Context resolution layer
    intent, confidence = resolve_with_context(
        message, raw_intent, raw_confidence, safe_history
    )

    # Step 3 – Generate reply
    if intent == "unknown":
        reply = (
            "Sorry, I did not understand that. "
            "Try asking about products, recommendations, "
            "orders or checkout."
        )
    else:
        reply = get_response(intent)

    return {
        "reply":      reply,
        "intent":     intent,
        "confidence": round(confidence, 4),
    }