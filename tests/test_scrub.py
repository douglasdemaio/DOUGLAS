from __future__ import annotations

from scripts.scrub import scrub


def test_redacts_email_and_phone():
    text = "Contact: Ada <ada@example.com> or +31 6 1234 5678"
    cleaned, counts = scrub(text)
    assert "ada@example.com" not in cleaned
    assert "1234 5678" not in cleaned
    assert counts["email"] == 1
    assert counts["phone"] == 1


def test_redacts_address_lines():
    text = "Address: 12 Main Street\nNothing else here\n"
    cleaned, counts = scrub(text)
    assert "[REDACTED:address]" in cleaned
    assert "Main Street" not in cleaned
    assert counts["address"] == 1


def test_clean_text_is_unchanged():
    text = "Move 900 kg from Barcelona to Zaragoza on 2026-11-20."
    cleaned, counts = scrub(text)
    assert cleaned == text
    assert counts == {}
