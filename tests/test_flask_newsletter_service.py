import os
import sys


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard")))

from newsletter_service import NewsletterService


def test_clean_subject_strips_forward_prefixes() -> None:
    assert NewsletterService.clean_subject("Fwd: Weekly Alpha") == "Weekly Alpha"
    assert NewsletterService.clean_subject(" fw:   Weekly Alpha ") == "Weekly Alpha"
    assert NewsletterService.clean_subject("Re: Fwd: Weekly Alpha") == "Weekly Alpha"


def test_clean_subject_handles_bracket_tag_and_delimiter_variants() -> None:
    assert NewsletterService.clean_subject("[External] Fwd: Weekly Alpha") == "[External] Weekly Alpha"
    assert NewsletterService.clean_subject("Fwd：Weekly Alpha") == "Weekly Alpha"
    assert NewsletterService.clean_subject("Fwd - Weekly Alpha") == "Weekly Alpha"


def test_clean_subject_does_not_alter_regular_subjects() -> None:
    subject = "Forward Looking Market Update"
    assert NewsletterService.clean_subject(subject) == subject
