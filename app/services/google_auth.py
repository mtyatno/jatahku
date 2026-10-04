"""Verifikasi ID token dari Google Identity Services (tombol "Masuk dengan Google")."""
import httpx

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


async def verify_google_credential(credential: str, client_id: str, http: httpx.AsyncClient | None = None) -> dict | None:
    """Kembalikan {sub, email, name} bila token sah untuk client_id kita, selain itu None."""
    if not credential or not client_id:
        return None
    own_client = http is None
    http = http or httpx.AsyncClient(timeout=10)
    try:
        res = await http.get(TOKENINFO_URL, params={"id_token": credential})
    except httpx.HTTPError:
        return None
    finally:
        if own_client:
            await http.aclose()

    if res.status_code != 200:
        return None
    claims = res.json()
    # tokeninfo sudah menolak token kedaluwarsa / tanda tangan salah; sisanya kita cek sendiri.
    if claims.get("aud") != client_id or claims.get("iss") not in GOOGLE_ISSUERS:
        return None
    if str(claims.get("email_verified")).lower() != "true" or not claims.get("email") or not claims.get("sub"):
        return None
    return {
        "sub": claims["sub"],
        "email": claims["email"].strip().lower(),
        "name": (claims.get("name") or claims["email"].split("@")[0]).strip()[:100],
    }
