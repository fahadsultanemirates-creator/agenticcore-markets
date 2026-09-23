"""Minimal Telegram bot for AgenticCore Markets -- a dedicated bot for this
project, deliberately separate from the agency's existing task-manager
Telegram bot (which handles unrelated client-work approvals). Talks to the
analysis service (app/main.py) over plain HTTP, so both must run on the
same host, or one reachable from the other.

Scope is intentionally minimal, matching where this project actually is
right now: no channels, no payment verification, no VIP/Apex tie-in --
just "message it a symbol, get a real signal back" for hands-on testing.
Everything else discussed (free/paid channels, content posting, tx-hash
payment verification, tying access to AC membership tiers) is a separate,
larger build for later, once the underlying pieces it depends on (a real
on-chain tier indexer in particular) exist.

Model selection: everyone gets Gemini by default; a small hardcoded
allowlist of Telegram user ids (TELEGRAM_CLAUDE_ALLOWLIST) gets Claude
instead -- the cheapest possible stand-in for "paid tier" while there's no
real subscription system yet. /start shows the caller their own Telegram
id specifically so filling in that allowlist doesn't need a separate
lookup bot.
"""

import logging

import httpx
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("markets_bot")

_TELEGRAM_MESSAGE_LIMIT = 4000  # Telegram's real limit is 4096; leave margin
_REQUEST_TIMEOUT_SECONDS = 60.0  # Claude can take ~20s; leave real headroom

_START_TEXT = (
    "AgenticCore Markets signal bot (test build).\n\n"
    "Send me a forex pair (EURUSD, GBPJPY), a commodity (XAUUSD, USOILUSD), "
    "or a crypto symbol/contract address (BTCUSD, PEPE, or a 0x... address) "
    "and I'll run the full analysis and send back a signal with reasoning.\n\n"
    "Your Telegram id is {user_id} -- for testing."
)

_SIGNAL_EMOJI = {"BUY": "\U0001f7e2", "SELL": "\U0001f534", "HOLD": "⚪"}


def normalize_symbol_input(text: str) -> str:
    """Pure: a contract address is passed through only stripped (EVM
    addresses are case-sensitive under EIP-55 checksums); anything else is
    stripped of whitespace/slashes and uppercased, so "eur/usd", " eurusd ",
    and "EURUSD" all resolve the same way."""
    stripped = text.strip()
    if stripped.lower().startswith("0x"):
        return stripped
    return stripped.replace("/", "").replace(" ", "").upper()


def pick_model_for_user(user_id: int) -> str:
    return "claude" if user_id in settings.telegram_claude_allowlist_ids else "gemini"


def format_analysis_reply(data: dict, model: str) -> str:
    """Pure: builds the Telegram reply text from the API's JSON response."""
    signal = data["signal"]
    call = signal["signal"]
    emoji = _SIGNAL_EMOJI.get(call, "")
    header = (
        f"{emoji} <b>{data['symbol']}</b> ({data['asset_type']}) -- <b>{call}</b> "
        f"({signal['confidence']:.0%} confidence)\n"
        f"<i>via {model}</i>\n"
    )
    return header + "\n" + signal["reasoning"]


def split_for_telegram(text: str, limit: int = _TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Pure: splits on paragraph breaks where possible so a long reasoning
    block doesn't get cut mid-sentence more than necessary."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else 0
    await update.message.reply_text(_START_TEXT.format(user_id=user_id))


async def handle_symbol_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or not update.effective_user:
        return

    symbol = normalize_symbol_input(update.message.text)
    if not symbol:
        return

    model = pick_model_for_user(update.effective_user.id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    url = f"{settings.markets_api_base_url}/api/v1/analysis/{symbol}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, params={"model": model})
    except httpx.TimeoutException:
        await update.message.reply_text(
            f"That took too long ({_REQUEST_TIMEOUT_SECONDS:.0f}s) and timed out -- please try again."
        )
        return
    except httpx.HTTPError as exc:
        logger.error("Analysis request failed for %s: %s", symbol, exc)
        await update.message.reply_text("Couldn't reach the analysis service right now -- please try again shortly.")
        return

    if resp.status_code == 404:
        await update.message.reply_text(
            f"Couldn't find \"{symbol}\" -- try a forex pair (EURUSD), a commodity (XAUUSD), "
            "a crypto symbol (BTCUSD), or a token's contract address (0x...)."
        )
        return
    if resp.status_code != 200:
        logger.error("Analysis request for %s returned %s: %s", symbol, resp.status_code, resp.text[:500])
        await update.message.reply_text("Something went wrong generating that signal -- please try again shortly.")
        return

    reply_text = format_analysis_reply(resp.json(), model)
    for chunk in split_for_telegram(reply_text):
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


def main() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set -- add it to .env before running the bot.")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_symbol_message))

    logger.info("Markets bot starting (polling) -- API base: %s", settings.markets_api_base_url)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
