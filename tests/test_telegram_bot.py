from bot.telegram_bot import (
    format_analysis_reply,
    normalize_symbol_input,
    pick_model_for_user,
    split_for_telegram,
)


def test_normalize_symbol_input_handles_common_variants():
    assert normalize_symbol_input("eurusd") == "EURUSD"
    assert normalize_symbol_input(" EURUSD ") == "EURUSD"
    assert normalize_symbol_input("eur/usd") == "EURUSD"
    assert normalize_symbol_input("btc usd") == "BTCUSD"


def test_normalize_symbol_input_preserves_contract_address_case():
    """EVM addresses are case-sensitive under EIP-55 checksums -- uppercasing
    would break resolution, so only stripping is applied to 0x-prefixed input."""
    address = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
    assert normalize_symbol_input(f"  {address}  ") == address


def test_pick_model_for_user_respects_allowlist(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_claude_allowlist", "111,222")

    assert pick_model_for_user(111) == "claude"
    assert pick_model_for_user(999) == "gemini"


def test_format_analysis_reply_includes_symbol_signal_and_reasoning():
    data = {
        "symbol": "EURUSD",
        "asset_type": "forex",
        "signal": {"signal": "BUY", "confidence": 0.82, "reasoning": "Bullish structure at key support."},
    }

    text = format_analysis_reply(data, model="gemini")

    assert "EURUSD" in text
    assert "BUY" in text
    assert "82%" in text
    assert "via gemini" in text
    assert "Bullish structure at key support." in text


def test_split_for_telegram_returns_single_chunk_when_short():
    assert split_for_telegram("short text") == ["short text"]


def test_split_for_telegram_splits_long_text_on_paragraph_breaks():
    paragraph = "x" * 100
    long_text = "\n\n".join([paragraph] * 60)  # well over the default limit

    chunks = split_for_telegram(long_text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "".join(chunks).replace("\n\n", "") == long_text.replace("\n\n", "")
