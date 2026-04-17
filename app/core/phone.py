import re


def normalize_phone(phone: str) -> str:
    """Normalize phone to 62xxxxxxxxx format (digits only).

    Handles: +62xxx, 62xxx, 08xxx, 8xxx
    Returns empty string if input has fewer than 7 digits.
    """
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return ""
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif not digits.startswith("62"):
        digits = "62" + digits
    return digits


def chat_id_to_phone(chat_id: str) -> str:
    """Extract phone from WAHA chat_id (supports @c.us, @s.whatsapp.net, @lid)."""
    for suffix in ("@c.us", "@s.whatsapp.net", "@lid"):
        chat_id = chat_id.replace(suffix, "")
    return chat_id
