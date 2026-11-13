# SentimentIQ analysis methodology (Iteration 6)

## 1. Whole-review sentiment

Each non-empty review is scored with VADER when the `vaderSentiment` package is installed. The compound score is labelled Positive at `>= 0.05`, Negative at `<= -0.05`, and Neutral between those thresholds. The absolute compound score is a lexicon score magnitude, not a calibrated probability or confidence interval. An offline fallback is used only when VADER is unavailable; the API's methodology response identifies the active engine.

## 2. Topic detection

SentimentIQ uses an explainable keyword taxonomy for Delivery, Product Quality, Pricing, Customer Support, Packaging and Usability. Reviews can match multiple topics. A review with no taxonomy match is assigned to Other. This is not unsupervised topic modelling and it can miss paraphrases or new themes.

## 3. Topic-level sentiment evidence

For each topic detected in a review, the analyzer finds sentence(s) containing one or more keywords for that topic. It scores the matching text separately and stores the sentence evidence, topic label and compound score. This allows mixed feedback to show different sentiment by topic. If no matching sentence can be isolated, the full review is used as a fallback evidence span.

This is a transparent sentence-matching heuristic, not a trained aspect-based sentiment model. Keyword ambiguity, negation, sarcasm, multilingual reviews and context across sentences can produce errors. Human review is recommended before taking consequential action.

## 4. Recommended next steps

Topic recommendations are static operational prompts associated with the detected theme. They are not generated from a causal diagnosis and should be treated as investigation suggestions, not proof of root cause.

## 5. Upload limits and parsing

- CSV: UTF-8 or UTF-8 with BOM; first row is the header.
- Excel: `.xlsx` only; first worksheet and first row are used.
- Maximum compressed upload size: 10 MB.
- Excel expanded archive processing cap: 100 MB.
- Maximum processed review rows: 20,000.
- Required review text column: `review_text`, `review`, `text`, `comment` or `feedback`.
- Optional columns: `review_id`/`id`, `rating`/`stars`, `date`/`created_at`, `category`/`product_category`.

## 6. Emotion cues (Iteration 5)

Emotion labels are generated from transparent keyword lexicons for Frustration, Trust, Delight, Confusion, Urgency and Disappointment. A review can receive multiple cues; reviews without a matching term are labelled Unspecified. These are language cues, not psychological assessments, validated emotion classification or a claim about the writer's internal state.

## 7. Priority triage (Iteration 5)

A bounded 0–5 urgency score combines matched urgency phrases with a one-point adjustment for negative overall sentiment. Score bands map to Low, Medium, High and Critical. The response includes the matched phrases so users can inspect why a review was flagged. This is a simple heuristic, not a calibrated risk score, SLA prediction or automated escalation decision. Always inspect the source review.

## 8. Duplicate review detection (Iteration 5)

The analyzer lowercases review text and removes punctuation/spacing differences, then groups exact normalized matches. It reports duplicate groups and review IDs but does not delete data. Paraphrases and semantic near-duplicates are not detected; repeated wording can also be legitimate, so verify before removing any record.

## 9. Emerging term discovery (Iteration 5)

The analyzer counts repeated unigrams and adjacent bigrams that are not already in the fixed topic keyword list, returning a small ranked list and example snippet. This is exploratory vocabulary discovery, not statistically validated trend detection, unsupervised topic modelling or proof that a topic is newly emerging. Validate terms with review context and time-based data before making decisions.

## 10. Multilingual baseline (Iteration 6)

SentimentIQ now heuristically identifies English, Spanish, French and Hindi text. Spanish, French and Hindi use small transparent sentiment lexicons; English uses the configured VADER scorer or the offline fallback. Topic detection has corresponding keyword additions for Delivery, Product Quality, Pricing and Customer Support. This is not machine translation, broad language coverage or a multilingual neural classifier. Code-switching, dialects, transliteration and nuanced grammar can be misclassified. Language and sentiment outputs should be reviewed, especially for mixed-language feedback.

## 11. Similar-review discovery (Iteration 6)

Similar review clusters use a local SentenceTransformer model only when `SENTIMENTIQ_EMBEDDING_MODEL` points to an already downloaded local model directory. No model is downloaded at runtime. If no usable local model is configured, the system falls back to TF-IDF word/phrase similarity. To bound compute, at most the first 800 non-trivial review texts are considered. Similarity groups can contain false positives or miss paraphrases; they are exploratory review-navigation aids, not validated topics or duplicate-removal decisions.

## 12. Labelled evaluation (Iteration 6)

An optional `expected_sentiment` column (also accepted: `label` or `ground_truth_sentiment`) can contain Positive, Neutral or Negative. When present, SentimentIQ compares predictions with these user-provided labels and reports sample size, accuracy, macro-F1, per-class precision/recall/F1 and a confusion matrix. These are meaningful only if labels are human-reviewed and the sample is representative. For unbiased model evaluation, use a held-out dataset that was not used to tune rules or thresholds. Metrics computed on the same uploaded sample are descriptive, not an independent benchmark.
