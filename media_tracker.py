import requests
import pandas as pd
import os
import re

# ================= CONFIG =================

RADARR_URL = "http://192.168.1.10:7878"
RADARR_API_KEY = "RADARR_API_KEY"

SONARR_URL = "http://192.168.1.10:8989"
SONARR_API_KEY = "SONARR_API_KEY"

MOVIE_ROOT = "/movies"
TV_ROOT = "/tv"

CSV_FILE = "media_library.csv"

HEADERS_RADARR = {"X-Api-Key": RADARR_API_KEY}
HEADERS_SONARR = {"X-Api-Key": SONARR_API_KEY}

# =============== HELPERS ==================

def load_or_create_db():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)
    return pd.DataFrame(columns=[
        "type", "title", "year",
        "tmdb_id", "tvdb_id",
        "season_count",
        "has_physical", "barcode",
        "source"
    ])

def save_db(df):
    df.to_csv(CSV_FILE, index=False)

# ========== IMPORT FROM RADARR ============

def import_radarr(df):
    r = requests.get(f"{RADARR_URL}/api/v3/movie", headers=HEADERS_RADARR)
    r.raise_for_status()

    rows = []
    for m in r.json():
        if not ((df["title"] == m["title"]) & (df["type"] == "movie")).any():
            rows.append({
                "type": "movie",
                "title": m["title"],
                "year": m["year"],
                "tmdb_id": m["tmdbId"],
                "tvdb_id": None,
                "season_count": None,
                "has_physical": False,
                "barcode": None,
                "source": "radarr"
            })

    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)

# ========== IMPORT FROM SONARR ============

def import_sonarr(df):
    r = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS_SONARR)
    r.raise_for_status()

    rows = []
    for s in r.json():
        if not ((df["title"] == s["title"]) & (df["type"] == "series")).any():
            rows.append({
                "type": "series",
                "title": s["title"],
                "year": s["year"],
                "tmdb_id": None,
                "tvdb_id": s["tvdbId"],
                "season_count": len(s["seasons"]),
                "has_physical": False,
                "barcode": None,
                "source": "sonarr"
            })

    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)

# ========== BARCODE LOOKUP ================

def lookup_barcode(barcode):
    r = requests.get(
        "https://api.upcitemdb.com/prod/trial/lookup",
        params={"upc": barcode}
    )
    data = r.json()

    if data.get("code") != "OK" or not data["items"]:
        return None

    return data["items"][0]["title"]

# ========== TYPE GUESSING =================

def guess_type(title):
    tv_words = ["season", "complete", "series", "tv"]
    return "series" if any(w in title.lower() for w in tv_words) else "movie"

# ========== SEARCH TMDB ===================

def search_tmdb_movie(title):
    r = requests.get(
        f"{RADARR_URL}/api/v3/movie/lookup",
        headers=HEADERS_RADARR,
        params={"term": title}
    )
    results = r.json()
    return results[0] if results else None

def search_tvdb_series(title):
    r = requests.get(
        f"{SONARR_URL}/api/v3/series/lookup",
        headers=HEADERS_SONARR,
        params={"term": title}
    )
    results = r.json()
    return results[0] if results else None

# ========== ADD TO RADARR =================

def add_movie(movie):
    payload = {
        "tmdbId": movie["tmdbId"],
        "title": movie["title"],
        "year": movie["year"],
        "qualityProfileId": 1,
        "rootFolderPath": MOVIE_ROOT,
        "monitored": True,
        "addOptions": {"searchForMovie": False}
    }
    requests.post(f"{RADARR_URL}/api/v3/movie", json=payload, headers=HEADERS_RADARR)

# ========== ADD TO SONARR =================

def add_series(series):
    payload = {
        "tvdbId": series["tvdbId"],
        "title": series["title"],
        "year": series["year"],
        "qualityProfileId": 1,
        "rootFolderPath": TV_ROOT,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": False}
    }
    requests.post(f"{SONARR_URL}/api/v3/series", json=payload, headers=HEADERS_SONARR)

# ========== SCAN LOOP =====================

def scan_loop(df):
    while True:
        barcode = input("\nScan barcode (or ENTER to quit): ").strip()
        if not barcode:
            break

        if barcode in df["barcode"].values:
            print("Already scanned.")
            continue

        title = lookup_barcode(barcode)
        if not title:
            print("Barcode not found.")
            continue

        media_type = guess_type(title)
        print(f"Detected {media_type}: {title}")

        if media_type == "movie":
            movie = search_tmdb_movie(title)
            if movie:
                add_movie(movie)
                df.loc[len(df)] = [
                    "movie", movie["title"], movie["year"],
                    movie["tmdbId"], None, None,
                    True, barcode, "barcode"
                ]

        else:
            series = search_tvdb_series(title)
            if series:
                add_series(series)
                df.loc[len(df)] = [
                    "series", series["title"], series["year"],
                    None, series["tvdbId"], len(series["seasons"]),
                    True, barcode, "barcode"
                ]

        save_db(df)
        print("Added & saved.")

# ================= MAIN ===================

def main():
    df = load_or_create_db()
    df = import_radarr(df)
    df = import_sonarr(df)
    save_db(df)

    print(f"Loaded {len(df)} items.")
    scan_loop(df)

if __name__ == "__main__":
    main()
