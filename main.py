"""Thin, read-only pass-through API over soccerdata and statsbombpy.

This service has no database and no auth. Every endpoint calls the
underlying scraping/API library (through a short-lived in-memory cache),
converts the result to JSON-serializable records, and returns it. It
exists so other services in this project can fetch soccer data over HTTP
instead of importing the scraping libraries themselves.
"""

import logging
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

import pandas as pd
import soccerdata as sd
from fastapi import FastAPI, HTTPException
from statsbombpy import sb

logger = logging.getLogger("soccer_data_api")

app = FastAPI(title="Soccer Data API")

CACHE_TTL_SECONDS = 300  # Upstream data changes rarely; 5 minutes is plenty.


def _ttl_hash(seconds: int = CACHE_TTL_SECONDS) -> int:
    """Compute a bucket value that changes once per `seconds`.

    Passing this as an extra argument to an `lru_cache`-decorated function
    gives that function a TTL: the bucket value (and therefore the cache
    key) only changes once the window rolls over, so calls within the same
    window are served from cache and calls in a later window re-fetch.

    Args:
        seconds (int): Length of the cache window in seconds.

    Returns:
        int: The current cache-bucket identifier.
    """
    return int(time.time() // seconds)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame to a list of JSON-serializable records.

    Args:
        df (pd.DataFrame): DataFrame returned by an underlying data library.

    Returns:
        list[dict[str, Any]]: One dict per row, suitable for a JSON response.
    """
    return df.reset_index().to_dict(orient="records")


def _fetch_or_502(label: str, fetch: "Callable[[], pd.DataFrame]") -> pd.DataFrame:
    """Run a cached fetch call, turning library failures into an HTTP error.

    Args:
        label (str): Short description of the call, used in log/error text.
        fetch (Callable[[], pd.DataFrame]): Zero-arg callable that performs
            the (possibly cached) upstream lookup.

    Returns:
        pd.DataFrame: The DataFrame returned by `fetch`.

    Raises:
        HTTPException: 422 if the library rejected the arguments as
            malformed/unknown (e.g. an unrecognized league or stat type);
            502 if the underlying scrape/API call failed for any other
            reason (network error, upstream layout change, etc).
    """
    try:
        return fetch()
    except (ValueError, KeyError) as exc:
        logger.warning("%s rejected its arguments: %s", label, exc)
        raise HTTPException(
            status_code=422, detail=f"{label} received invalid arguments: {exc}"
        ) from exc
    except Exception as exc:
        logger.exception("%s failed", label)
        raise HTTPException(status_code=502, detail=f"{label} failed: {exc}") from exc


@lru_cache(maxsize=128)
def _cached_understat_schedule(league: str, season: str, _ttl: int) -> pd.DataFrame:
    """Fetch the Understat season schedule for a league/season, cached by TTL.

    Understat replaces FBref here because FBref now requires driving a real
    browser (to clear Cloudflare), which is too heavy/flaky for this service.
    Understat is a plain HTTP source but only covers the big-five European
    leagues.

    Args:
        league (str): League identifier as expected by soccerdata (one of the
            big-five leagues, e.g. "ENG-Premier League").
        season (str): Season identifier as expected by soccerdata.
        _ttl (int): Cache-bucket value from `_ttl_hash()`; not otherwise
            used, it just forces a fresh call once the window rolls over.

    Returns:
        pd.DataFrame: Raw schedule data from Understat.
    """
    return sd.Understat(league, season).read_schedule()


@lru_cache(maxsize=128)
def _cached_understat_player_season_stats(
    league: str, season: str, _ttl: int
) -> pd.DataFrame:
    """Fetch Understat player season stats for a league/season, cached by TTL.

    Args:
        league (str): League identifier as expected by soccerdata (one of the
            big-five leagues, e.g. "ENG-Premier League").
        season (str): Season identifier as expected by soccerdata.
        _ttl (int): Cache-bucket value from `_ttl_hash()`.

    Returns:
        pd.DataFrame: Raw player season stats from Understat (goals, xG,
            assists, xA, shots, key passes, xGChain, xGBuildup, etc.).
    """
    return sd.Understat(league, season).read_player_season_stats()


@lru_cache(maxsize=128)
def _cached_statsbomb_matches(
    competition_id: int, season_id: int, _ttl: int
) -> pd.DataFrame:
    """Fetch StatsBomb matches for a competition/season, cached by TTL.

    Args:
        competition_id (int): StatsBomb competition ID.
        season_id (int): StatsBomb season ID.
        _ttl (int): Cache-bucket value from `_ttl_hash()`.

    Returns:
        pd.DataFrame: Raw match data from StatsBomb.
    """
    df = sb.matches(competition_id=competition_id, season_id=season_id)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast(pd.DataFrame, df)


@lru_cache(maxsize=256)
def _cached_statsbomb_events(match_id: int, _ttl: int) -> pd.DataFrame:
    """Fetch StatsBomb event data for one match, cached by TTL.

    Match data is immutable once published, so this cache never needs to
    expire in practice, but it still shares the standard TTL for simplicity.

    Args:
        match_id (int): StatsBomb match ID.
        _ttl (int): Cache-bucket value from `_ttl_hash()`.

    Returns:
        pd.DataFrame: Raw event data from StatsBomb.
    """
    df = sb.events(match_id=match_id)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast(pd.DataFrame, df)


@app.get("/health")
def health() -> dict[str, str]:
    """Report basic service liveness.

    Returns:
        dict[str, str]: A constant `{"status": "ok"}` payload.
    """
    return {"status": "ok"}


@app.get("/understat/schedule")
def understat_schedule(league: str, season: str) -> list[dict[str, Any]]:
    """Fetch the season schedule/results for a league from Understat.

    Args:
        league (str): League identifier as expected by soccerdata. Understat
            only covers the big-five European leagues: "ENG-Premier League",
            "ESP-La Liga", "ITA-Serie A", "GER-Bundesliga", "FRA-Ligue 1".
        season (str): Season identifier as expected by soccerdata (e.g.
            "2023-2024" or "2324").

    Returns:
        list[dict[str, Any]]: One record per scheduled/played match.

    Raises:
        HTTPException: 422 for an unrecognized league/season, 502 if the
            Understat fetch otherwise fails.
    """
    df = _fetch_or_502(
        "Understat schedule lookup",
        lambda: _cached_understat_schedule(league, season, _ttl_hash()),
    )
    return _records(df)


@app.get("/understat/player-season-stats")
def understat_player_season_stats(league: str, season: str) -> list[dict[str, Any]]:
    """Fetch player season stats (goals, xG, assists, xA, etc.) from Understat.

    Args:
        league (str): League identifier as expected by soccerdata. Understat
            only covers the big-five European leagues: "ENG-Premier League",
            "ESP-La Liga", "ITA-Serie A", "GER-Bundesliga", "FRA-Ligue 1".
        season (str): Season identifier as expected by soccerdata (e.g.
            "2023-2024" or "2324").

    Returns:
        list[dict[str, Any]]: One record per player.

    Raises:
        HTTPException: 422 for an unrecognized league/season, 502 if the
            Understat fetch otherwise fails.
    """
    df = _fetch_or_502(
        "Understat player season stats lookup",
        lambda: _cached_understat_player_season_stats(league, season, _ttl_hash()),
    )
    return _records(df)


@app.get("/statsbomb/matches")
def statsbomb_matches(competition_id: int, season_id: int) -> list[dict[str, Any]]:
    """Fetch matches for a StatsBomb competition/season.

    Args:
        competition_id (int): StatsBomb competition ID.
        season_id (int): StatsBomb season ID.

    Returns:
        list[dict[str, Any]]: One record per match.

    Raises:
        HTTPException: 422 for an unrecognized competition/season pairing,
            502 if the StatsBomb API call otherwise fails.
    """
    df = _fetch_or_502(
        "StatsBomb matches lookup",
        lambda: _cached_statsbomb_matches(competition_id, season_id, _ttl_hash()),
    )
    return _records(df)


@app.get("/statsbomb/matches/{match_id}/events")
def statsbomb_match_events(match_id: int) -> list[dict[str, Any]]:
    """Fetch event-level data (shots, xG, passes) for one StatsBomb match.

    Args:
        match_id (int): StatsBomb match ID.

    Returns:
        list[dict[str, Any]]: One record per event in the match.

    Raises:
        HTTPException: 422 for an unrecognized match ID, 502 if the
            StatsBomb API call otherwise fails.
    """
    df = _fetch_or_502(
        "StatsBomb events lookup",
        lambda: _cached_statsbomb_events(match_id, _ttl_hash()),
    )
    return _records(df)
