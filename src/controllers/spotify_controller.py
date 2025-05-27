# controllers/spotify_auth.py
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
client_id = os.getenv('SPOTIPY_CLIENT_ID')
client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
REDIRECT_URI = "http://localhost:6969/auth/spotify/callback"
SCOPE = "user-top-read user-read-recently-played"
CACHE_PATH = ".cache-spotify.json"

# SpotifyOAuth manager (caches tokens for you)
sp_oauth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    cache_path=CACHE_PATH
)

router = APIRouter(
    prefix="/auth/spotify",
    tags=["spotify-auth"]
)


# ─── 1. Kick off OAuth ───────────────────────────────────────────────────────
@router.get("/login", summary="Start Spotify OAuth flow")
def spotify_login():
    """
    Redirects the user to Spotify's authorization page.
    """
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(auth_url)


# ─── 2. OAuth Callback ───────────────────────────────────────────────────────
@router.get("/callback", summary="Handle Spotify redirect and cache tokens")
async def spotify_callback(request: Request):
    """
    Spotify sends back ?code=... here. We exchange it for access + refresh tokens
    and store them in CACHE_PATH. After this one-time step, your app can
    refresh silently.
    """
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    if error or not code:
        raise HTTPException(400, detail="Authorization failed or was denied.")

    # Exchange code for tokens
    token_info = sp_oauth.get_access_token(code, as_dict=True)
    return JSONResponse({
        "message": "Spotify authorization successful!",
        "scopes_granted": token_info.get("scope").split(" ")
    })

