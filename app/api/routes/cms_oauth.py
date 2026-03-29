"""
GitHub OAuth proxy for Decap CMS.
Decap CMS needs a server-side OAuth callback to exchange the GitHub code for a token.
"""
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()

GITHUB_OAUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"


@router.get("/auth/cms-oauth")
async def cms_oauth_start(request: Request):
    """Redirect to GitHub OAuth."""
    params = (
        f"client_id={settings.GITHUB_CLIENT_ID}"
        f"&scope=repo,user"
        f"&redirect_uri={settings.API_URL}/auth/cms-oauth/callback"
    )
    return RedirectResponse(f"{GITHUB_OAUTH_URL}?{params}")


@router.get("/auth/cms-oauth/callback")
async def cms_oauth_callback(code: str, request: Request):
    """Exchange code for token, return to Decap CMS."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()

    token = data.get("access_token", "")
    if not token:
        return HTMLResponse("<p>OAuth gagal. Coba lagi.</p>", status_code=400)

    # Decap CMS expects this specific postMessage format
    return HTMLResponse(f"""<!DOCTYPE html>
<html><body>
<script>
  const msg = JSON.stringify({{
    token: "{token}",
    provider: "github"
  }});
  if (window.opener) {{
    window.opener.postMessage("authorization:github:success:" + msg, "*");
  }}
  window.close();
</script>
</body></html>""")
