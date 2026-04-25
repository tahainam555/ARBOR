from __future__ import annotations

from backend.domain_classifier import DomainClassifier


def test_domain_classifier_accepts_sec_request() -> None:
    classifier = DomainClassifier()
    decision = classifier.classify("What did Apple's 10-K say about revenue growth?")

    assert decision.allowed is True
    assert decision.confidence >= 0.7


def test_domain_classifier_rejects_off_topic_request() -> None:
    classifier = DomainClassifier()
    decision = classifier.classify("Tell me a joke about the weather.")

    assert decision.allowed is False
    assert "outside" in decision.reason or "scope" in decision.reason
