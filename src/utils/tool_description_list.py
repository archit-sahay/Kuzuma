tools = [
    {
        "type": "function",
        "function": {
            "name": "get_top_tracks",
            "description": (
                "Returns a list of your top Spotify tracks for a given time range. "
                "Each track is a dictionary with 'name', 'artist', and 'url'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of top tracks to return (default 5)"
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range: short_term, medium_term, or long_term (default medium_term)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_artists",
            "description": (
                "Returns a list of your top Spotify artists for a given time range. "
                "Each artist is a dictionary with 'name' and 'url'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of top artists to return (default 5)"
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range: short_term, medium_term, or long_term (default medium_term)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recently_played",
            "description": (
                "Returns a list of your most recently played Spotify tracks and their timestamps. "
                "Each item is a dictionary with 'track' and 'played_at'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of tracks to return (default 20)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_genre_distribution",
            "description": (
                "Returns the top 5 genres from your top Spotify artists in the given time range. "
                "Returns a list of genre strings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time_range": {
                        "type": "string",
                        "description": "Time range: short_term, medium_term, or long_term (default medium_term)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of top artists to analyze (default 20)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_anime_rating",
            "description": (
                "Returns your AniList rating and status for a given anime by name, or tells you if you haven't watched it. "
                "Returns a string with your rating and status, or a message if not watched."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "anime_name": {
                        "type": "string",
                        "description": "Name of the anime to search and check rating for"
                    }
                },
                "required": ["anime_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_currently_watching",
            "description": (
                "Returns a list of anime you are currently watching on AniList. "
                "Each anime is a dictionary with 'id', 'title', and 'url'. "
                "Use this information to answer the user's question in natural language."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_professional_experience",
            "description": (
                "Returns Archit's professional experience duration from January 15, 2024 to current date. "
                "Returns a dictionary with 'years', 'months', 'start_date', and 'current_date'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_rated_anime",
            "description": (
                "Retrieves anime from Archit's AniList based on rating criteria. Can get top-rated, bottom-rated, perfect 10s, or anime within specific score ranges. "
                "Each anime is a dictionary with 'title', 'english_title', 'url', 'score', 'updated_at', and 'year'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of anime to return (default 10)"
                    },
                    "score_filter": {
                        "type": "string",
                        "description": "Filter type: top, bottom, tens, all, or range (default top)"
                    },
                    "min_score": {
                        "type": "integer",
                        "description": "Minimum score for range filtering (1-10, only used with 'range' filter)"
                    },
                    "max_score": {
                        "type": "integer",
                        "description": "Maximum score for range filtering (1-10, only used with 'range' filter)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_anime_stats",
            "description": (
                "Returns comprehensive statistics about Archit's anime rating patterns including total rated anime, average score, score distribution, and counts of perfect 10s and lowest ratings. "
                "Returns a dictionary with statistics about viewing habits and rating tendencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]
