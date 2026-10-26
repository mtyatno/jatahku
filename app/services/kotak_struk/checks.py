"""Cek silang dan arah uang untuk Dokumen Bayar. Stub: diisi di Task A5."""
from app.services.kotak_struk.readers.base import Check, ParseContext, Parsed


def common_checks(parsed: Parsed, ctx: ParseContext) -> list[Check]:
    return []


def apply_flow(parsed: Parsed, ctx: ParseContext) -> None:
    pass
