import os
import requests
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
CLIENT_ID = os.getenv('ANILIST_CLIENT_ID')
CLIENT_SECRET = os.getenv('ANILIST_CLIENT_SECRET')
REDIRECT_URI = "http://localhost:6969/auth/anilist/callback"

AUTH_URL = "https://anilist.co/api/v2/oauth/authorize"
TOKEN_URL = "https://anilist.co/api/v2/oauth/token"

router = APIRouter(
    prefix="/auth/anilist",
    tags=["anilist-auth"]
)


# ─── 1. Kick off OAuth ───────────────────────────────────────────────────────
@router.get("/login", summary="Start AniList OAuth flow")
def anilist_login():
    """
    Redirects the user to AniList's authorization page.
    """
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code"
        # No scope parameter needed for AniList
    }
    url = requests.Request('GET', AUTH_URL, params=params).prepare().url
    return RedirectResponse(url)


# ─── 2. OAuth Callback ───────────────────────────────────────────────────────
@router.get("/callback", summary="Handle AniList redirect and cache tokens")
async def anilist_callback(request: Request):
    """
    AniList sends back ?code=... here. Exchange it for access token.
    """
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error or not code:
        raise HTTPException(400, detail="Authorization failed or was denied.")

    # Exchange code for tokens
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    }
    headers = {"Accept": "application/json"}
    resp = requests.post(TOKEN_URL, data=data, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(400, detail=f"Token exchange failed: {resp.text}")

    token_info = resp.json()
    return JSONResponse({
        "message": "AniList authorization successful!",
        "access_token": token_info.get("access_token"),
        "token_type": token_info.get("token_type"),
        "expires_in": token_info.get("expires_in"),
        # AniList does not return refresh tokens
    })
