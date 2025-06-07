from typing import List, Dict
import requests
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv
from pathlib import Path
from collections import Counter
from datetime import date


load_dotenv()

client_id = os.getenv('SPOTIPY_CLIENT_ID')
client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
redirect_uri = 'http://localhost:6969/auth/spotify/callback'
scope = 'user-top-read'
HERE = Path(__file__).resolve().parent   # .../src/utils

# 2. Climb up to your project root (two levels up: utils → src → kazuma)
PROJECT_ROOT = HERE.parent.parent        # .../kazuma

# 3. Build the cache path
CACHE_PATH = f"{PROJECT_ROOT}/.cache-spotify.json"
# print(CACHE_PATH),

_sp_oauth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=redirect_uri,
    scope=scope,
    cache_path=CACHE_PATH
)


# ─── Internal helper to get a valid Spotify client ───────────────────────────
def _get_spotify_client() -> Spotify:
    token_info = _sp_oauth.get_cached_token()
    if not token_info:
        raise RuntimeError("No Spotify token cached; run the OAuth login flow first.")
    if _sp_oauth.is_token_expired(token_info):
        token_info = _sp_oauth.refresh_access_token(token_info["refresh_token"])
    return Spotify(auth=token_info["access_token"])


# ─── Tool: Top Tracks ─────────────────────────────────────────────────────────
def get_top_tracks(limit: int = 5, time_range: str = "medium_term") -> List[Dict[str, str]]:
    """
    Returns a list of your top tracks (name, artist, url) for a given time range.
    """
    sp = _get_spotify_client()
    items = sp.current_user_top_tracks(limit=limit, time_range=time_range)["items"]
    return [
        {"name": t["name"], "artist": t["artists"][0]["name"], "url": t["external_urls"]["spotify"]}
        for t in items
    ]


# ─── Tool: Top Artists ────────────────────────────────────────────────────────
def get_top_artists(limit: int = 5, time_range: str = "medium_term") -> List[Dict[str, str]]:
    """
    Returns a list of your top artists (name, url) for a given time range.
    """
    sp = _get_spotify_client()
    items = sp.current_user_top_artists(limit=limit, time_range=time_range)["items"]
    return [
        {"name": a["name"], "url": a["external_urls"]["spotify"]}
        for a in items
    ]


def get_recently_played(limit: int = 20) -> List[Dict[str, str]]:
    """
    Returns a list of your most recently played tracks and timestamps.
    """
    sp = _get_spotify_client()
    items = sp.current_user_recently_played(limit=limit)["items"]
    return [{"track": it["track"]["name"], "played_at": it["played_at"]} for it in items]


def get_genre_distribution(time_range: str = "medium_term", limit: int = 20) -> List[str]:
    """
    Returns the top 5 genres from your top artists in the given time range.
    """
    sp = _get_spotify_client()
    items = sp.current_user_top_artists(limit=limit, time_range=time_range)["items"]
    genres = []
    for artist in items:
        genres.extend(artist.get("genres", []))
    return [g for g, _ in Counter(genres).most_common(5)]


def get_anime_rating(anime_name):

    # 1. Search for the anime by name
    access_token = os.getenv("ANILIST_API_KEY")
    search_query = '''
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        title {
          romaji
        }
      }
    }
    '''
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    search_variables = {"search": anime_name}
    search_resp = requests.post(
        "https://graphql.anilist.co",
        json={"query": search_query, "variables": search_variables},
        headers=headers
    )
    search_data = search_resp.json()
    if not search_data.get("data") or not search_data["data"]["Media"]:
        return f"Anime '{anime_name}' not found."

    anime_id = search_data["data"]["Media"]["id"]
    anime_title = search_data["data"]["Media"]["title"]["romaji"]
    print(f"\n\nSearch Results for '{anime_name}': [{search_data['data']}]\n\n")

    # 2. Fetch your list entry for this anime, specifying your username
    rating_query = '''
    query ($mediaId: Int, $userName: String) {
      MediaList(mediaId: $mediaId, type: ANIME, userName: $userName) {
        status
        score
      }
    }
    '''
    rating_variables = {"mediaId": anime_id, "userName": "Architrash"}
    rating_resp = requests.post(
        "https://graphql.anilist.co",
        json={"query": rating_query, "variables": rating_variables},
        headers=headers
    )
    rating_data = rating_resp.json()
    entry = rating_data.get("data", {}).get("MediaList")
    if entry is None:
        return f"You have not watched '{anime_title}'."
    else:
        score = entry["score"]
        status = entry["status"]
        return f"You have watched '{anime_title}' (status: {status}) and rated it {score}/10."


def get_currently_watching():
    access_token = os.environ.get("ANILIST_API_KEY")
    username = "Architrash"
    query = '''
    query ($userName: String) {
      MediaListCollection(userName: $userName, type: ANIME, status: CURRENT) {
        lists {
          entries {
            media {
              id
              title {
                romaji
                english
                native
              }
              siteUrl
            }
          }
        }
      }
    }
    '''
    variables = {"userName": username}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    response = requests.post(
        "https://graphql.anilist.co",
        json={"query": query, "variables": variables},
        headers=headers
    )
    data = response.json()
    if "errors" in data:
        return f"API Error: {data['errors']}"
    collection = data.get("data", {}).get("MediaListCollection")
    if not collection or not collection.get("lists"):
        return "You are not currently watching any anime."
    anime_list = []
    anilist_ = []
    for lst in collection["lists"]:
        for entry in lst["entries"]:
            anime = entry["media"]
            anime_list.append({
                "id": anime["id"],
                "title": anime["title"]["romaji"],
                "url": anime["siteUrl"]
            })
            anilist_.append(anime["title"]["romaji"])
    return anilist_


def get_professional_experience():
    """
    Calculate professional experience from January 15, 2024 to current date.
    Returns a dictionary with years and months of experience.
    """
    start_date = date(2024, 1, 15)
    current_date = date.today()

    # Calculate years and months manually
    years = current_date.year - start_date.year
    months = current_date.month - start_date.month

    # Adjust if current day is before start day
    if current_date.day < start_date.day:
        months -= 1

    # Adjust if months is negative
    if months < 0:
        years -= 1
        months += 12

    return {
        "years": years,
        "months": months,
        "start_date": "January 15, 2024",
        "current_date": current_date.strftime("%B %d, %Y")
    }


tool_map = {
    "get_top_tracks": get_top_tracks,
    "get_top_artists": get_top_artists,
    "get_recently_played": get_recently_played,
    "get_genre_distribution": get_genre_distribution,
    "get_anime_rating": get_anime_rating,
    "get_currently_watching": get_currently_watching,
    "get_professional_experience": get_professional_experience
}
