from app.services.analyzer import analyze_reviews, classify_sentiment, detect_topics


def test_sentiment_labels_basic_examples():
    assert classify_sentiment("I absolutely love this excellent product")['label'] == "Positive"
    assert classify_sentiment("Terrible, broken and disappointing experience")['label'] == "Negative"
    assert classify_sentiment("The item arrived today")['label'] == "Neutral"


def test_topic_detection():
    assert "Delivery" in detect_topics("The delivery was late and tracking never updated")
    assert "Product Quality" in detect_topics("Excellent product quality and durable material")


def test_analysis_summary_counts_reviews_and_topics():
    result = analyze_reviews([
        {"review_text": "Excellent product quality"},
        {"review_text": "Terrible delivery delay"},
        {"review_text": "It arrived today"},
    ])
    assert result["total_reviews"] == 3
    assert sum(v["count"] for v in result["sentiment_distribution"].values()) == 3
    assert any(t["topic"] == "Delivery" for t in result["topics"])


def test_emotion_signals_and_priority_triage():
    from app.services.analyzer import analyze_reviews
    result = analyze_reviews([
        {"review_text": "I am extremely frustrated. This is unacceptable, refund me immediately."},
        {"review_text": "I love the delightful experience and trust this brand."},
    ])
    frustrated = result["reviews"][0]
    assert "Frustration" in frustrated["emotions"]
    assert frustrated["urgency"]["priority"] in ("High", "Critical")
    assert "Delight" in result["reviews"][1]["emotions"]
    assert result["priority_distribution"]["High"] + result["priority_distribution"]["Critical"] >= 1


def test_exact_duplicate_review_detection():
    result = analyze_reviews([
        {"review_text": "The package arrived broken and I need a refund."},
        {"review_text": "THE PACKAGE ARRIVED BROKEN, AND I NEED A REFUND!"},
        {"review_text": "Excellent quality and quick delivery."},
    ])
    assert result["duplicate_summary"]["duplicate_review_count"] == 1
    assert len(result["duplicate_summary"]["clusters"]) == 1
    assert result["reviews"][0]["duplicate_group"] == result["reviews"][1]["duplicate_group"]


def test_emerging_terms_are_repeated_and_outside_taxonomy():
    result = analyze_reviews([
        {"review_text": "The checkout spinner freezes every time and feels frustrating."},
        {"review_text": "Checkout spinner freezes again, this is annoying."},
    ])
    terms = {item["term"] for item in result["emerging_terms"]}
    assert "checkout spinner" in terms or "spinner freezes" in terms


def test_priority_score_is_bounded_and_neutral_reviews_not_overflagged():
    from app.services.analyzer import analyze_reviews
    result = analyze_reviews([
        {"review_text": "The order arrived on Tuesday."},
        {"review_text": "Unsafe damaged item. This is critical, refund immediately."},
    ])
    assert result["reviews"][0]["urgency"]["priority"] == "Low"
    assert result["reviews"][1]["urgency"]["score"] <= 5
    assert result["reviews"][1]["urgency"]["priority"] == "Critical"


def test_multilingual_sentiment_and_topics_for_supported_languages():
    from app.services.analyzer import classify_sentiment, detect_topics
    spanish = "La entrega fue terrible y el producto es malo"
    french = "La livraison était excellente et le produit est parfait"
    hindi = "उत्पाद की गुणवत्ता बहुत अच्छी है"
    assert classify_sentiment(spanish)["label"] == "Negative"
    assert "Delivery" in detect_topics(spanish)
    assert classify_sentiment(french)["label"] == "Positive"
    assert "Product Quality" in detect_topics(french)
    assert classify_sentiment(hindi)["label"] == "Positive"
    assert "Product Quality" in detect_topics(hindi)


def test_similar_review_clusters_group_reworded_feedback():
    result = analyze_reviews([
        {"review_text": "The checkout spinner freezes every time and the screen becomes stuck."},
        {"review_text": "The checkout spinner freezes again and the screen is stuck."},
        {"review_text": "I love the excellent product quality and friendly support team."},
    ])
    clusters = result["similar_review_clusters"]["clusters"]
    assert any(cluster["count"] >= 2 for cluster in clusters)
    assert result["similar_review_clusters"]["sampled_reviews"] == 3


def test_labeled_reviews_generate_evaluation_metrics():
    result = analyze_reviews([
        {"review_text": "Excellent product and wonderful quality", "expected_sentiment": "Positive"},
        {"review_text": "Terrible broken item and poor quality", "expected_sentiment": "Negative"},
        {"review_text": "The package arrived today", "expected_sentiment": "Neutral"},
    ])
    evaluation = result["model_evaluation"]
    assert evaluation["sample_size"] == 3
    assert 0 <= evaluation["accuracy"] <= 1
    assert "macro_f1" in evaluation
    assert set(evaluation["confusion_matrix"]) == {"Positive", "Neutral", "Negative"}


def test_no_labels_means_no_accuracy_claim():
    result = analyze_reviews([{"review_text": "Excellent product quality"}])
    assert result["model_evaluation"] is None
