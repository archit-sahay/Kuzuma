import os
import requests
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyOauthError
from src.utils.cache import cache, TTL_SHORT, TTL_MEDIUM
from src.utils.circuit_breaker import CircuitBreaker
from src.logger import get_logger

log = get_logger(__name__)


# Per-service circuit breakers (shared across tools using same service)
_spotify_breaker = CircuitBreaker(threshold=2, recovery_time=120, name="spotify")
_anilist_breaker = CircuitBreaker(threshold=2, recovery_time=120, name="anilist")

load_dotenv()

client_id = os.getenv('SPOTIPY_CLIENT_ID')
client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
redirect_uri = 'http://127.0.0.1:6969/auth/spotify/callback'
scope = 'user-top-read user-read-recently-played'
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
def _alert_spotify_revoked(error):
    """One-shot Discord alert when Spotify refresh token is revoked.
    Sends only when the breaker was previously closed — re-fires only after
    a successful re-auth resets the breaker, so this won't spam every hour."""
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        return
    try:
        requests.post(webhook, json={
            "content": "@everyone",
            "embeds": [{
                "title": "🎵 Spotify needs re-auth",
                "description": (
                    "Refresh token revoked. Spotify tools will return "
                    "'temporarily unavailable' until you re-auth via "
                    "`http://127.0.0.1:6969/auth/spotify/login` and SCP the "
                    "fresh `.cache-spotify.json` to the server."
                ),
                "color": 0xEF4444,  # red
                "fields": [
                    {"name": "Error", "value": str(error)[:300], "inline": False},
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=5)
        log.info("Discord alert sent: Spotify refresh token revoked")
    except Exception as e:
        log.warning(f"Spotify revoke-alert webhook failed: {e}")


def _is_invalid_grant(error) -> bool:
    """Detect the specific Spotify error that means the refresh token is dead
    and no amount of retrying will help — only manual re-auth fixes it."""
    if isinstance(error, SpotifyOauthError):
        return True  # SpotifyOauthError is only raised on hard auth failures
    msg = str(error).lower()
    return "invalid_grant" in msg or "refresh token revoked" in msg


def _get_spotify_client():
    """Returns a Spotify client or None if auth fails."""
    if _spotify_breaker.is_open:
        log.info("Spotify circuit breaker is open, skipping")
        return None
    try:
        token_info = _sp_oauth.get_cached_token()
        if not token_info:
            log.warning("No Spotify token cached")
            return None
        if _sp_oauth.is_token_expired(token_info):
            token_info = _sp_oauth.refresh_access_token(token_info["refresh_token"])
        _spotify_breaker.record_success()
        return Spotify(auth=token_info["access_token"])
    except Exception as e:
        if _is_invalid_grant(e):
            # Refresh token is permanently dead until manual re-auth.
            # Trip the breaker hard so we stop hammering Spotify, and fire
            # a one-shot Discord alert (only on the breaker's closed→open
            # transition — won't spam if we hit this path again later).
            already_open = _spotify_breaker.opened_at is not None
            _spotify_breaker.trip(recovery_seconds=3600)  # 1 hour
            if not already_open:
                log.error(f"Spotify refresh token revoked — re-auth required: {e}")
                _alert_spotify_revoked(e)
            return None
        log.error(f"Spotify auth failed: {e}")
        _spotify_breaker.record_failure()
        return None


def _spotify_unavailable():
    return {"error": "Spotify is temporarily unavailable. Try again later!"}


def _spotify_cached_fetch(cache_key: str, ttl: int, fetch):
    """Shared cache + client + error boilerplate for Spotify tools.

    `fetch(sp)` receives a live Spotify client and returns the serialized result.
    """
    cached = cache.get(cache_key)
    if cached:
        return cached
    sp = _get_spotify_client()
    if not sp:
        return _spotify_unavailable()
    try:
        result = fetch(sp)
        cache.set(cache_key, result, ttl)
        return result
    except Exception as e:
        log.error(f"{cache_key} failed: {e}")
        return _spotify_unavailable()


# ─── Tool: Top Tracks ─────────────────────────────────────────────────────────
def get_top_tracks(limit: int = 5, time_range: str = "medium_term"):
    def _fetch(sp):
        items = (sp.current_user_top_tracks(limit=limit, time_range=time_range) or {}).get("items", [])
        return [
            {"name": t["name"], "artist": t["artists"][0]["name"], "url": t["external_urls"]["spotify"]}
            for t in items
        ]
    return _spotify_cached_fetch(f"top_tracks:{limit}:{time_range}", TTL_SHORT, _fetch)


# ─── Tool: Top Artists ────────────────────────────────────────────────────────
def get_top_artists(limit: int = 5, time_range: str = "medium_term"):
    def _fetch(sp):
        items = (sp.current_user_top_artists(limit=limit, time_range=time_range) or {}).get("items", [])
        return [
            {"name": a["name"], "url": a["external_urls"]["spotify"]}
            for a in items
        ]
    return _spotify_cached_fetch(f"top_artists:{limit}:{time_range}", TTL_SHORT, _fetch)


def get_recently_played(limit: int = 20):
    def _fetch(sp):
        items = (sp.current_user_recently_played(limit=limit) or {}).get("items", [])
        return [{"track": it["track"]["name"], "played_at": it["played_at"]} for it in items]
    return _spotify_cached_fetch(f"recently_played:{limit}", TTL_SHORT, _fetch)


def get_genre_distribution(time_range: str = "medium_term", limit: int = 20):
    def _fetch(sp):
        items = (sp.current_user_top_artists(limit=limit, time_range=time_range) or {}).get("items", [])
        genres = []
        for artist in items:
            genres.extend(artist.get("genres", []))
        return [g for g, _ in Counter(genres).most_common(5)]
    return _spotify_cached_fetch(f"genre_dist:{time_range}:{limit}", TTL_MEDIUM, _fetch)


def get_anime_rating(anime_name):
    cache_key = f"anime_rating:{anime_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    # 1. Search for the anime by name
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

    search_data = _graphql_query(query=search_query, variables={"search": anime_name})

    if not search_data.get("data") or not search_data["data"]["Media"]:
        return f"Anime '{anime_name}' not found."

    anime_id = search_data["data"]["Media"]["id"]
    anime_title = search_data["data"]["Media"]["title"]["romaji"]
    log.info(f"\n\nSearch Results for '{anime_name}': [{search_data['data']}]\n\n")

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

    rating_data = _graphql_query(query=rating_query, variables=rating_variables)
    entry = rating_data.get("data", {}).get("MediaList")
    if entry is None:
        return f"You have not watched '{anime_title}'."
    else:
        score = entry["score"]
        status = entry["status"]
        result = f"You have watched '{anime_title}' (status: {status}) and rated it {score}/10."
        cache.set(cache_key, result, TTL_MEDIUM)
        return result


def get_currently_watching():
    cached = cache.get("currently_watching")
    if cached:
        return cached
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

    result = _fetch_anilist_collection(query, {"userName": "Architrash"}, "You are not currently watching any anime.")
    if isinstance(result, str):
        return result
    collection = result
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
    cache.set("currently_watching", anilist_, TTL_MEDIUM)
    return anilist_


def get_professional_experience():
    """
    Calculate professional experience from January-15-2024 to current date.
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


def get_rated_anime(limit: int = 10, score_filter: str = "top", min_score: int = None, max_score: int = None):
    """
    Returns anime based on rating criteria with flexible filtering options.

    Args:
        limit (int): Number of results to return (default: 10)
        score_filter (str): Filter type - "top", "bottom", "tens", "all", or "range"
        min_score (int): Minimum score for range filtering (optional)
        max_score (int): Maximum score for range filtering (optional)

    Returns:
        List of dictionaries with anime info, or error message

    Examples:
        get_rated_anime(5, "top")          # Top 5 highest rated
        get_rated_anime(3, "bottom")       # Bottom 3 lowest rated
        get_rated_anime(10, "tens")        # Most recent 10/10 rated
        get_rated_anime(15, "all")         # 15 most recently updated (any score)
        get_rated_anime(8, "range", 7, 9)  # 8 anime rated between 7-9
    """

    query = '''
    query ($userName: String) {
      MediaListCollection(userName: $userName, type: ANIME, sort: UPDATED_TIME_DESC) {
        lists {
          entries {
            score
            updatedAt
            media {
              id
              title {
                romaji
                english
              }
              siteUrl
              startDate {
                year
                month
                day
              }
              format
              status
              episodes
            }
          }
        }
      }
    }
    '''

    result = _fetch_anilist_collection(query, {"userName": "Architrash"})
    if isinstance(result, str):
        return result
    collection = result

    # Collect all entries with scores
    all_anime = []
    for lst in collection["lists"]:
        for entry in lst["entries"]:
            # Only include entries that have been rated (score > 0)
            if entry["score"] > 0:
                anime = entry["media"]
                all_anime.append({
                    "title": anime["title"]["romaji"],
                    "english_title": anime["title"].get("english"),
                    "url": anime["siteUrl"],
                    "score": entry["score"],
                    "updated_at": entry["updatedAt"],
                    "year": anime["startDate"]["year"] if anime["startDate"] else None,
                    "format": anime.get("format"),
                    "status": anime.get("status"),
                    "episodes": anime.get("episodes")
                })

    if not all_anime:
        return "No rated anime found."

    # Apply filtering based on score_filter parameter
    if score_filter == "tens":
        # Only 10/10 rated anime, sorted by most recent update
        filtered_anime = [anime for anime in all_anime if anime["score"] == 10]
        filtered_anime.sort(key=lambda x: x["updated_at"], reverse=True)

    elif score_filter == "top":
        # Highest rated anime first, then by most recent update
        filtered_anime = sorted(all_anime, key=lambda x: (x["score"], x["updated_at"]), reverse=True)

    elif score_filter == "bottom":
        # Lowest rated anime first, then by most recent update
        filtered_anime = sorted(all_anime, key=lambda x: (x["score"], -x["updated_at"]))

    elif score_filter == "range" and min_score is not None and max_score is not None:
        # Anime within specified score range, sorted by score then update time
        filtered_anime = [anime for anime in all_anime if min_score <= anime["score"] <= max_score]
        filtered_anime.sort(key=lambda x: (x["score"], x["updated_at"]), reverse=True)

    elif score_filter == "all":
        # All rated anime, sorted by most recent update
        filtered_anime = sorted(all_anime, key=lambda x: x["updated_at"], reverse=True)

    else:
        # Default to top-rated if invalid filter provided
        filtered_anime = sorted(all_anime, key=lambda x: (x["score"], x["updated_at"]), reverse=True)

    return filtered_anime[:limit]


def get_anime_stats():
    """
    Returns statistics about anime ratings.
    """
    query = '''
    query ($userName: String) {
      MediaListCollection(userName: $userName, type: ANIME) {
        lists {
          entries {
            score
          }
        }
      }
    }
    '''

    result = _fetch_anilist_collection(query, {"userName": "Architrash"})
    if isinstance(result, str):
        return result
    collection_ = result

    # Collect all scores
    scores = []
    for lst in collection_["lists"]:
        for entry in lst["entries"]:
            if entry["score"] > 0:  # Only count rated anime
                scores.append(entry["score"])

    if not scores:
        return "No rated anime found."

    score_counts = Counter(scores)

    return {
        "total_rated": len(scores),
        "average_score": round(sum(scores) / len(scores), 2),
        "highest_score": max(scores),
        "lowest_score": min(scores),
        "score_distribution": dict(sorted(score_counts.items())),
        "tens_count": score_counts.get(10, 0),
        "ones_count": score_counts.get(1, 0)
    }


def _fetch_anilist_collection(query: str, variables: dict, empty_msg: str = "No anime data found.") -> dict | str:
    """Run a MediaListCollection query and return the collection dict on success.

    On API error or empty result, returns a user-facing message string.
    """
    data = _graphql_query(query=query, variables=variables)
    if "errors" in data:
        return f"API Error: {data['errors']}"
    collection = data.get("data", {}).get("MediaListCollection")
    if not collection or not collection.get("lists"):
        return empty_msg
    return collection


def _graphql_query(query: str, variables: dict | None = None) -> dict:
    """Helper function to make GraphQL queries to AniList API.
    Public profile queries don't require auth — eliminates token expiry issues."""
    if _anilist_breaker.is_open:
        return {"errors": [{"message": "AniList is temporarily unavailable"}]}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        response = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10
        )
        data = response.json()
        if "errors" not in data:
            _anilist_breaker.record_success()
        return data
    except Exception as e:
        log.error(f"AniList query failed: {e}")
        _anilist_breaker.record_failure()
        return {"errors": [{"message": str(e)}]}


tool_map = {
    "get_top_tracks": get_top_tracks,
    "get_top_artists": get_top_artists,
    "get_recently_played": get_recently_played,
    "get_genre_distribution": get_genre_distribution,
    "get_anime_rating": get_anime_rating,
    "get_currently_watching": get_currently_watching,
    "get_professional_experience": get_professional_experience,
    "get_anime_stats": get_anime_stats,
    "get_rated_anime": get_rated_anime,
}
