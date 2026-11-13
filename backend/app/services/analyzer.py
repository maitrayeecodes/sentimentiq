"""Transparent baseline analysis for customer feedback.

VADER is a lexicon/rule-based sentiment model. Topic labels are assigned with
an explainable keyword taxonomy; they are not a trained topic model.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .advanced_nlp import (detect_language, multilingual_sentiment, discover_similar_review_clusters, evaluate_labeled_reviews, MULTILINGUAL_TOPICS)

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _SENTIMENT = SentimentIntensityAnalyzer()
    SENTIMENT_ENGINE = "VADER"
except ImportError:  # Offline/dev fallback; production installs requirements.txt.
    import math

    class _FallbackSentiment:
        positive = {"excellent", "amazing", "great", "good", "love", "loved", "perfect", "fast", "helpful", "wonderful", "outstanding", "happy", "easy", "best", "delightful"}
        negative = {"terrible", "awful", "bad", "poor", "broken", "disappointing", "slow", "late", "damaged", "rude", "frustrating", "hate", "worst", "unhelpful", "defective"}

        def polarity_scores(self, text: str) -> dict[str, float]:
            words = re.findall(r"[a-z']+", text.casefold())
            pos = sum(w in self.positive for w in words)
            neg = sum(w in self.negative for w in words)
            raw = pos - neg
            compound = raw / math.sqrt(raw * raw + 15) if raw else 0.0
            total = max(len(words), 1)
            return {"neg": round(neg / total, 3), "neu": round(max(total-pos-neg, 0) / total, 3), "pos": round(pos / total, 3), "compound": round(compound, 4)}

    _SENTIMENT = _FallbackSentiment()
    SENTIMENT_ENGINE = "Built-in offline fallback (VADER package unavailable)"

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Delivery": ("delivery", "delivered", "shipping", "shipped", "courier", "parcel", "package", "late", "delay", "tracking", "arrival"),
    "Product Quality": ("quality", "product", "material", "fabric", "durable", "broken", "defective", "damaged", "sturdy", "poorly made"),
    "Pricing": ("price", "pricing", "expensive", "cheap", "cost", "value", "discount", "refund", "overpriced", "worth"),
    "Customer Support": ("support", "service", "staff", "agent", "response", "reply", "help", "rude", "customer care", "assistance"),
    "Packaging": ("packaging", "包装", "box", "wrapped", "unboxing", "sealed", "package", "crushed"),
    "Usability": ("app", "website", "easy to use", "difficult to use", "interface", "checkout", "navigation", "login"),
}


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def classify_sentiment(text: str) -> dict[str, Any]:
    language = detect_language(text)
    scores = multilingual_sentiment(text, language)
    engine = f"{language.upper()} transparent multilingual lexicon" if scores else SENTIMENT_ENGINE
    if scores is None:
        scores = _SENTIMENT.polarity_scores(text)
    compound = scores["compound"]
    if compound >= 0.05:
        label = "Positive"
    elif compound <= -0.05:
        label = "Negative"
    else:
        label = "Neutral"
    return {
        "label": label,
        "confidence": round(abs(compound), 4),
        "compound": round(compound, 4),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "language": language,
        "engine": engine,
    }


def detect_topics(text: str) -> list[str]:
    lowered = text.casefold()
    language = detect_language(text)
    found = []
    for topic, terms in TOPIC_KEYWORDS.items():
        multilingual_terms = MULTILINGUAL_TOPICS.get(topic, {}).get(language, ())
        if any((term.casefold() in lowered) if language == "hi" else re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", lowered) for term in (*terms, *multilingual_terms)):
            found.append(topic)
    return found or ["Other"]


def topic_evidence(text: str, topic: str) -> str:
    """Return the sentence(s) that mention a topic, for explainable aspect scoring."""
    language = detect_language(text)
    terms = (*TOPIC_KEYWORDS.get(topic, ()), *MULTILINGUAL_TOPICS.get(topic, {}).get(language, ()))
    sentences = re.split(r"(?<=[.!?])\s+|[\n;]+", text)
    matched = [sentence.strip() for sentence in sentences if any(
        (term.casefold() in sentence.casefold()) if language == "hi" else re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", sentence.casefold())
        for term in terms
    )]
    return " ".join(matched)[:500] or text[:500]


ACTION_GUIDANCE = {
    "Delivery": "Review carrier performance, delivery promises and tracking communication.",
    "Product Quality": "Inspect recurring defects, supplier batches and product quality checks.",
    "Pricing": "Review price-to-value perception, fees and discount clarity.",
    "Customer Support": "Audit response times, resolution quality and support hand-offs.",
    "Packaging": "Check packaging durability, sealing and handling protection.",
    "Usability": "Identify friction in navigation, checkout and account flows.",
    "Other": "Review the underlying feedback to identify a more specific improvement area.",
}

EMOTION_LEXICON = {
    "Frustration": {"frustrated", "annoyed", "irritating", "irritated", "angry", "upset", "disappointed", "unacceptable", "ridiculous"},
    "Trust": {"trust", "reliable", "honest", "transparent", "secure", "safe", "confidence"},
    "Delight": {"love", "delightful", "wonderful", "fantastic", "amazing", "thrilled", "perfect", "excellent"},
    "Confusion": {"confusing", "unclear", "confused", "complicated", "understand", "difficult", "uncertain"},
    "Urgency": {"urgent", "immediately", "asap", "now", "emergency", "critical", "desperate"},
    "Disappointment": {"disappointed", " 기대", "expected", "regret", "waste", "letdown", "poor"},
}

URGENCY_TERMS = {
    "urgent": 3, "immediately": 3, "asap": 3, "emergency": 3, "critical": 3,
    "chargeback": 3, "fraud": 3, "unsafe": 3, "dangerous": 3,
    "cancel": 2, "cancellation": 2, "refund": 2, "broken": 2, "damaged": 2,
    "never again": 2, "unacceptable": 2, "still waiting": 2, "no response": 2,
    "late": 1, "delay": 1, "missing": 1, "wrong": 1, "problem": 1,
}

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "was", "were", "are", "is", "it", "its", "but", "not", "have", "has", "had", "from", "they", "them", "their", "you", "your", "our", "we", "i", "my", "me", "to", "of", "in", "on", "at", "a", "an", "as", "be", "been", "very", "so", "too", "just", "after", "before", "when", "what", "which", "there", "here", "can", "could", "would", "should", "will", "do", "did", "does", "no", "yes", "all", "out", "up", "down", "about", "again", "more", "less", "than", "then", "also", "only", "get", "got", "one", "product", "service", "item"
}


def detect_emotions(text: str) -> list[str]:
    words = set(re.findall(r"[a-z']+", text.casefold()))
    found = [emotion for emotion, terms in EMOTION_LEXICON.items() if words.intersection(terms)]
    return found or ["Unspecified"]


def score_urgency(text: str, sentiment: str) -> dict[str, Any]:
    lowered = text.casefold()
    matched = [term for term in URGENCY_TERMS if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", lowered)]
    raw = min(5, sum(URGENCY_TERMS[t] for t in matched))
    if sentiment == "Negative":
        raw = min(5, raw + 1)
    if raw >= 4:
        priority = "Critical"
    elif raw >= 3:
        priority = "High"
    elif raw >= 2:
        priority = "Medium"
    else:
        priority = "Low"
    return {"score": raw, "priority": priority, "signals": matched}


def _duplicate_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def discover_emerging_terms(reviews: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Find repeated, non-taxonomy unigrams/bigrams as exploratory signals, not topics."""
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    known = {term for terms in TOPIC_KEYWORDS.values() for term in terms}
    for review in reviews:
        text = review["review_text"].casefold()
        tokens = re.findall(r"[a-z][a-z'-]{2,}", text)
        filtered = [t for t in tokens if t not in STOPWORDS]
        for token in filtered:
            if token not in known:
                counts[token] += 1
                examples.setdefault(token, review["review_text"][:220])
        for left, right in zip(filtered, filtered[1:]):
            phrase = f"{left} {right}"
            if left not in known and right not in known:
                counts[phrase] += 1
                examples.setdefault(phrase, review["review_text"][:220])
    return [{"term": term, "mentions": count, "example": examples[term]}
            for term, count in counts.most_common(limit) if count >= 2]


def analyze_reviews(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    sentiment_counts: Counter[str] = Counter()
    topic_stats: dict[str, Counter[str]] = defaultdict(Counter)
    complaint_examples: dict[str, list[str]] = defaultdict(list)

    for index, row in enumerate(rows, start=1):
        text = normalize_text(row.get("review_text") or row.get("review") or row.get("text") or row.get("comment"))
        if not text:
            continue
        sentiment = classify_sentiment(text)
        topics = detect_topics(text)
        emotions = detect_emotions(text)
        urgency = score_urgency(text, sentiment["label"])
        sentiment_counts[sentiment["label"]] += 1
        aspect_sentiments = []
        for topic in topics:
            evidence = topic_evidence(text, topic)
            aspect = classify_sentiment(evidence)
            aspect_sentiments.append({
                "topic": topic, "sentiment": aspect["label"],
                "compound": aspect["compound"], "evidence": evidence,
            })
            topic_stats[topic][aspect["label"]] += 1
            if aspect["label"] == "Negative" and len(complaint_examples[topic]) < 3:
                complaint_examples[topic].append(evidence[:240])
        results.append({
            "review_id": str(row.get("review_id") or row.get("id") or f"review-{index}"),
            "review_text": text,
            "rating": row.get("rating"),
            "date": str(row.get("date") or row.get("created_at") or "") or None,
            "category": str(row.get("category") or row.get("product_category") or "Unspecified"),
            "sentiment": sentiment["label"],
            "confidence": sentiment["confidence"],
            "compound": sentiment["compound"],
            "topics": topics,
            "aspect_sentiments": aspect_sentiments,
            "emotions": emotions,
            "urgency": urgency,
            "language": sentiment.get("language", detect_language(text)),
            "sentiment_engine": sentiment.get("engine", SENTIMENT_ENGINE),
            "expected_sentiment": str(row.get("expected_sentiment") or row.get("label") or "").strip() or None,
        })

    # Exact/near-exact duplicate detection after punctuation and case normalization.
    duplicate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in results:
        key = _duplicate_key(review["review_text"])
        if len(key) >= 12:
            duplicate_groups[key].append(review)
    duplicate_clusters = []
    duplicate_total = 0
    for key, group in duplicate_groups.items():
        if len(group) > 1:
            duplicate_total += len(group) - 1
            cluster_id = f"dup-{len(duplicate_clusters)+1:03d}"
            for review in group:
                review["duplicate_group"] = cluster_id
            duplicate_clusters.append({
                "id": cluster_id, "count": len(group),
                "review_ids": [r["review_id"] for r in group],
                "sample": group[0]["review_text"][:220],
            })

    total = len(results)
    distribution = {
        label: {"count": sentiment_counts[label], "percentage": round((sentiment_counts[label] / total * 100), 2) if total else 0}
        for label in ("Positive", "Neutral", "Negative")
    }
    topics_out = []
    for topic, counts in sorted(topic_stats.items(), key=lambda item: sum(item[1].values()), reverse=True):
        mentions = sum(counts.values())
        negative = counts["Negative"]
        topics_out.append({
            "topic": topic,
            "mentions": mentions,
            "positive": counts["Positive"],
            "neutral": counts["Neutral"],
            "negative": negative,
            "negative_percentage": round(negative / mentions * 100, 2) if mentions else 0,
            "complaint_examples": complaint_examples.get(topic, []),
            "recommended_action": ACTION_GUIDANCE.get(topic, ACTION_GUIDANCE["Other"]),
        })

    complaints = [t for t in topics_out if t["negative"] > 0]
    complaints.sort(key=lambda x: (x["negative"], x["negative_percentage"]), reverse=True)
    insights = []
    if total:
        top_positive = max(topics_out, key=lambda x: x["positive"], default=None)
        top_complaint = max(topics_out, key=lambda x: x["negative"], default=None)
        if top_positive and top_positive["positive"]:
            insights.append({"type": "strength", "title": f"{top_positive['topic']} receives the most positive mentions", "evidence": f"{top_positive['positive']} positive mentions out of {top_positive['mentions']} topic mentions."})
        if top_complaint and top_complaint["negative"]:
            insights.append({"type": "attention", "title": f"Review {top_complaint['topic']} complaints", "evidence": f"{top_complaint['negative']} negative mentions ({top_complaint['negative_percentage']}% of mentions for this topic)."})
        critical = sum(1 for r in results if r["urgency"]["priority"] in ("Critical", "High"))
        if critical:
            insights.append({"type": "attention", "title": f"{critical} reviews need priority attention", "evidence": "Priority is a transparent keyword and sentiment heuristic; inspect each review before acting."})
        if duplicate_total:
            insights.append({"type": "attention", "title": f"{duplicate_total} repeated review entries detected", "evidence": "Exact normalized-text matches may indicate duplicate submissions or syndicated reviews; verify before removing."})

    priority_counts = Counter(r["urgency"]["priority"] for r in results)
    emotion_counts = Counter(e for r in results for e in r["emotions"] if e != "Unspecified")
    return {
        "total_reviews": total,
        "sentiment_distribution": distribution,
        "topics": topics_out,
        "complaints": complaints,
        "insights": insights,
        "reviews": results,
        "emotion_distribution": dict(emotion_counts),
        "priority_distribution": {p: priority_counts[p] for p in ("Critical", "High", "Medium", "Low")},
        "priority_reviews": sorted([r for r in results if r["urgency"]["priority"] in ("Critical", "High")], key=lambda r: (r["urgency"]["score"], r["sentiment"] == "Negative"), reverse=True)[:50],
        "duplicate_summary": {"duplicate_review_count": duplicate_total, "clusters": duplicate_clusters},
        "emerging_terms": discover_emerging_terms(results),
        "similar_review_clusters": discover_similar_review_clusters(results),
        "model_evaluation": evaluate_labeled_reviews(results),
        "language_distribution": dict(Counter(r["language"] for r in results)),
        "methodology": {
            "sentiment": f"{SENTIMENT_ENGINE} lexicon/rule-based scoring; labels use compound score thresholds of +/-0.05.",
            "topics": "Explainable keyword taxonomy; a review may belong to multiple topics. Topic sentiment is scored on matching sentence evidence where available, rather than blindly copying the whole-review label.",
            "aspect_sentiment": "Sentence-level keyword matching followed by the configured lexicon sentiment scorer; not a trained aspect-based sentiment model.",
            "emotions": "Transparent emotion keyword lexicons; categories are indicative signals, not validated psychological measurements.",
            "priority": "Rule-based urgency keywords plus a small negative-sentiment adjustment. Priority is triage assistance, not an automated decision or calibrated risk score.",
            "duplicates": "Exact normalized-text matching after lowercasing and removing punctuation; paraphrases and near-duplicates are not detected.",
            "emerging_terms": "Repeated unigrams and adjacent bigrams outside the fixed topic taxonomy; exploratory signals, not statistically validated emerging topics.",
            "multilingual": "Language is heuristically detected for English, Spanish, French and Hindi. Spanish/French/Hindi sentiment uses small transparent lexicons; other languages fall back to the configured baseline. It is not translation or a multilingual neural model.",
            "similarity": "Groups similar review wording using a locally configured sentence-transformer model when available; otherwise TF-IDF word/phrase similarity is used. Similarity groups are exploratory and can include false matches.",
            "evaluation": "Accuracy, macro-F1, per-class precision/recall and a confusion matrix are computed only when the uploaded file includes expected_sentiment or label values. Use held-out human-labelled data for meaningful evaluation.",
            "limitations": "This is a transparent baseline, not a domain-fine-tuned model. Sarcasm, subtle context, code-switching, dialects and nuanced multilingual context require further evaluation and model development.",
        },
    }
