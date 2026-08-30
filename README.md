# aiml-00-soccer-data-api

A thin, read-only FastAPI wrapper around [soccerdata](https://github.com/probberechts/soccerdata)
(Understat) and [statsbombpy](https://github.com/statsbomb/statsbombpy) (StatsBomb open data).
No database, no auth, no caching — it's a pass-through so other services in this
project can fetch soccer data over HTTP instead of importing the scraping
libraries directly.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/understat/schedule?league=&season=` | Season schedule/results (Understat, big-five leagues only) |
| GET | `/understat/player-season-stats?league=&season=` | Player season stats incl. xG/xA (Understat, big-five leagues only) |
| GET | `/statsbomb/matches?competition_id=&season_id=` | Matches for a competition/season (StatsBomb) |
| GET | `/statsbomb/matches/{match_id}/events` | Event-level data for one match (StatsBomb) |

## Run locally

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Smoke test (local)

```bash
curl "http://localhost:8000/health"

curl "http://localhost:8000/understat/schedule?league=ENG-Premier%20League&season=2023-2024"

curl "http://localhost:8000/understat/player-season-stats?league=ENG-Premier%20League&season=2023-2024"

curl "http://localhost:8000/statsbomb/matches?competition_id=43&season_id=3"

curl "http://localhost:8000/statsbomb/matches/7580/events"
```

## Run in Docker

```bash
docker build -t soccer-data-api .
docker run -p 8000:8000 soccer-data-api
```

### Smoke test (container)

Same commands as above, since the container is published on the same
`localhost:8000` port:

```bash
curl "http://localhost:8000/health"

curl "http://localhost:8000/understat/schedule?league=ENG-Premier%20League&season=2023-2024"

curl "http://localhost:8000/understat/player-season-stats?league=ENG-Premier%20League&season=2023-2024"

curl "http://localhost:8000/statsbomb/matches?competition_id=43&season_id=3"

curl "http://localhost:8000/statsbomb/matches/7580/events"
```

## Notes

- Understat and StatsBomb endpoints hit live sources (scraping/HTTP); a
  502 response means the upstream call failed, not that the request
  was malformed (that's a 422).
- Understat only covers the big-five European leagues ("ENG-Premier League",
  "ESP-La Liga", "ITA-Serie A", "GER-Bundesliga", "FRA-Ligue 1"). FBref was
  dropped because it now requires driving a headless browser past Cloudflare.
- `competition_id=43&season_id=3` is StatsBomb's freely-available
  FIFA World Cup 2018 dataset — useful for testing without credentials.
