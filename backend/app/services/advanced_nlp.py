"""Optional multilingual and similarity analysis helpers for SentimentIQ.

The default multilingual classifier is a small, transparent lexicon baseline.
Optional sentence-transformer embeddings are only loaded from a locally supplied
model path; this module never downloads a model at runtime.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

LANGUAGE_WORDS = {
    "es": {"el", "la", "los", "las", "pero", "muy", "producto", "entrega", "precio", "servicio", "excelente", "malo", "bueno", "gracias"},
    "fr": {"le", "la", "les", "mais", "très", "produit", "livraison", "prix", "service", "excellent", "mauvais", "merci", "déçu"},
    "hi": {"hai", "ka", "ki", "ke", "bahut", "achha", "accha", "kharab", "bekar", "pasand", "dhanyavaad", "nahi", "mila"},
}

MULTILINGUAL_SENTIMENT = {
    "es": {
        "positive": {"bueno", "buena", "excelente", "increíble", "genial", "rápido", "rápida", "amable", "perfecto", "perfecta", "encanta", "feliz", "útil", "calidad"},
        "negative": {"malo", "mala", "terrible", "horrible", "lento", "lenta", "roto", "rota", "dañado", "dañada", "caro", "cara", "decepcionado", "decepcionada", "defectuoso", "pobre"},
    },
    "fr": {
        "positive": {"bon", "bonne", "excellent", "excellente", "génial", "rapide", "parfait", "parfaite", "adore", "heureux", "heureuse", "utile", "qualité", "merci"},
        "negative": {"mauvais", "mauvaise", "terrible", "horrible", "lent", "lente", "cassé", "cassée", "abîmé", "abîmée", "cher", "chère", "déçu", "déçue", "décevant", "nul"},
    },
    "hi": {
        "positive": {"अच्छा", "अच्छी", "शानदार", "बेहतरीन", "बढ़िया", "पसंद", "खुश", "तेज़", "सस्ता", "धन्यवाद", "उत्तम"},
        "negative": {"खराब", "बुरा", "बुरी", "घटिया", "टूटा", "टूटी", "देर", "महंगा", "महंगी", "निराश", "बेकार", "धीमा", "धीमी"},
    },
}

MULTILINGUAL_TOPICS = {
    "Delivery": {
        "es": ("entrega", "envío", "paquete", "reparto", "retraso", "llegó tarde"),
        "fr": ("livraison", "expédition", "colis", "retard", "livré"),
        "hi": ("डिलीवरी", "वितरण", "पार्सल", "देर से", "देर"),
    },
    "Product Quality": {
        "es": ("calidad", "producto", "roto", "defectuoso", "dañado"),
        "fr": ("qualité", "produit", "cassé", "défectueux", "abîmé"),
        "hi": ("गुणवत्ता", "उत्पाद", "खराब", "टूटा", "दोषपूर्ण"),
    },
    "Pricing": {
        "es": ("precio", "caro", "barato", "coste", "reembolso"),
        "fr": ("prix", "cher", "coût", "remboursement", "tarif"),
        "hi": ("कीमत", "महंगा", "सस्ता", "पैसे", "रिफंड"),
    },
    "Customer Support": {
        "es": ("soporte", "atención al cliente", "ayuda", "respuesta"),
        "fr": ("assistance", "service client", "aide", "réponse"),
        "hi": ("सहायता", "कस्टमर सपोर्ट", "मदद", "जवाब"),
    },
}


def detect_language(text: str) -> str:
    """Lightweight language hinting for English, Spanish, French and Hindi."""
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    tokens = set(re.findall(r"[a-záéíóúüñàâçèêëîïôùûÿœ'-]+", text.casefold()))
    scores = {lang: len(tokens.intersection(words)) for lang, words in LANGUAGE_WORDS.items()}
    lang, score = max(scores.items(), key=lambda item: item[1])
    if score >= 2:
        return lang
    if re.search(r"[áéíóúñ¿¡]", text.casefold()):
        return "es"
    if re.search(r"[àâçèêëîïôùûÿœ]", text.casefold()):
        return "fr"
    return "en"


def multilingual_sentiment(text: str, language: str) -> dict[str, float] | None:
    lexicon = MULTILINGUAL_SENTIMENT.get(language)
    if not lexicon:
        return None
    if language == "hi":
        tokens = set(re.findall(r"[\u0900-\u097F]+", text.casefold()))
    else:
        tokens = set(re.findall(r"[a-záéíóúüñàâçèêëîïôùûÿœ'-]+", text.casefold()))
    positive = len(tokens.intersection(lexicon["positive"]))
    negative = len(tokens.intersection(lexicon["negative"]))
    # Small negation adjustment for common language-specific negators.
    negators = {"es": {"no", "nunca"}, "fr": {"pas", "jamais", "non"}, "hi": {"नहीं", "मत"}}[language]
    if tokens.intersection(negators):
        positive, negative = negative, positive
    raw = positive - negative
    compound = raw / ((raw * raw + 15) ** 0.5) if raw else 0.0
    total = max(len(tokens), 1)
    return {"neg": round(negative / total, 3), "neu": round(max(total-positive-negative, 0) / total, 3), "pos": round(positive / total, 3), "compound": round(compound, 4)}


def discover_similar_review_clusters(reviews: list[dict[str, Any]], max_reviews: int = 800) -> dict[str, Any]:
    """Group similar review wording using local embeddings when configured, else TF-IDF.

    Only a bounded sample is processed to avoid quadratic work on very large uploads.
    Model paths must point to an already downloaded local SentenceTransformer model.
    """
    candidates = [r for r in reviews if len(r.get("review_text", "").strip()) >= 20]
    if len(candidates) < 2:
        return {"clusters": [], "method": "Not enough review text for similarity grouping.", "sampled_reviews": len(candidates), "threshold": None}
    sampled = candidates[:max_reviews]
    model_path = os.getenv("SENTIMENTIQ_EMBEDDING_MODEL", "").strip()
    vectors = None
    method = "TF-IDF word/phrase similarity fallback"
    threshold = 0.50
    if model_path:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(model_path, local_files_only=True)
            vectors = model.encode([r["review_text"] for r in sampled], normalize_embeddings=True, show_progress_bar=False)
            method = "Locally configured sentence-transformer embeddings"
            threshold = 0.76
        except Exception:
            vectors = None
    try:
        from sklearn.neighbors import NearestNeighbors
        from sklearn.feature_extraction.text import TfidfVectorizer
        if vectors is None:
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), analyzer="word", min_df=1, max_features=10000, sublinear_tf=True)
            vectors = vectorizer.fit_transform([r["review_text"] for r in sampled])
        neighbors = NearestNeighbors(metric="cosine", algorithm="brute", radius=1-threshold)
        neighbors.fit(vectors)
        graph = neighbors.radius_neighbors_graph(vectors, mode="connectivity")
        from scipy.sparse.csgraph import connected_components
        count, labels = connected_components(graph, directed=False)
    except Exception:
        return {"clusters": [], "method": "Similarity grouping unavailable; install scikit-learn and scipy.", "sampled_reviews": len(sampled), "threshold": threshold}

    clusters = []
    for label in set(labels):
        indexes = [i for i, value in enumerate(labels) if value == label]
        if len(indexes) < 2:
            continue
        group = [sampled[i] for i in indexes]
        words = Counter()
        for review in group:
            words.update(w for w in re.findall(r"[a-z]{4,}", review["review_text"].casefold()) if w not in {"this", "that", "with", "have", "your", "from", "very", "product", "there", "when"})
        clusters.append({
            "id": f"sim-{len(clusters)+1:03d}",
            "count": len(group),
            "review_ids": [r["review_id"] for r in group],
            "sample": group[0]["review_text"][:240],
            "common_terms": [w for w, _ in words.most_common(5)],
        })
    clusters.sort(key=lambda item: item["count"], reverse=True)
    return {"clusters": clusters[:30], "method": method, "sampled_reviews": len(sampled), "threshold": threshold}


def evaluate_labeled_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute basic classification metrics only when user-supplied labels exist."""
    labels = ("Positive", "Neutral", "Negative")
    pairs = []
    for review in reviews:
        expected = str(review.get("expected_sentiment") or "").strip().title()
        predicted = str(review.get("sentiment") or "").strip().title()
        if expected in labels and predicted in labels:
            pairs.append((expected, predicted))
    if not pairs:
        return None
    matrix = {actual: {pred: 0 for pred in labels} for actual in labels}
    for actual, predicted in pairs:
        matrix[actual][predicted] += 1
    accuracy = sum(matrix[label][label] for label in labels) / len(pairs)
    per_class = {}
    f1_values = []
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in labels if actual != label)
        fn = sum(matrix[label][pred] for pred in labels if pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": sum(matrix[label].values())}
        f1_values.append(f1)
    return {"sample_size": len(pairs), "accuracy": round(accuracy, 4), "macro_f1": round(sum(f1_values)/len(f1_values), 4), "per_class": per_class, "confusion_matrix": matrix, "note": "Metrics compare model output with user-supplied expected_sentiment labels. Use a representative held-out sample; this upload-level score is not an independent benchmark."}
