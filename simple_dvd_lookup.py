import requests
import pandas as pd
import os
import re
import serial
import time
from dotenv import load_dotenv

# ================= CONFIG =================
load_dotenv()

RADARR_URL = os.getenv("RADARR_URL", "http://192.168.1.10:7878")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")

SONARR_URL = os.getenv("SONARR_URL", "http://192.168.1.10:8989")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")

MOVIE_ROOT = os.getenv("MOVIE_ROOT", "/movies")
TV_ROOT = os.getenv("TV_ROOT", "/tv")

CSV_FILE = "media_library.csv"
SERIAL_PORT = os.getenv("SERIAL_PORT", None)  # e.g., "COM3" on Windows, "/dev/ttyUSB0" on Linux
SERIAL_BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "115200"))

HEADERS_RADARR = {"X-Api-Key": RADARR_API_KEY}
HEADERS_SONARR = {"X-Api-Key": SONARR_API_KEY}

# =============== HELPERS ==================

def load_or_create_db():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        # Ensure proper dtypes for all columns
        df = df.astype({
            'type': 'object',
            'title': 'object',
            'year': 'object',
            'tmdb_id': 'object',
            'tvdb_id': 'object',
            'season_count': 'object',
            'has_physical': 'object',
            'barcode': 'object',
            'source': 'object'
        })
        return df
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

def lookup_barcode(barcode, max_retries=3):
    """Lookup barcode with retry logic"""
    for attempt in range(max_retries):
        try:
            r = requests.get(
                "https://api.upcitemdb.com/prod/trial/lookup",
                params={"upc": barcode},
                timeout=10
            )
            data = r.json()

            if data.get("code") == "OK" and data.get("items"):
                return data["items"][0]["title"]

            # If no items found, no point retrying
            if data.get("code") == "OK" and not data.get("items"):
                return None

        except (requests.RequestException, ValueError) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"Barcode lookup failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Barcode lookup failed after {max_retries} attempts: {e}")

    return None

# ========== TITLE CLEANING ================

def clean_title(title):
    """Remove common suffixes and formats from barcode titles"""
    # Remove parenthetical and bracketed content like (DVD), (Blu-ray), [Blu-ray], etc.
    title = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)

    # Remove 3D/2D, 4K, UHD variants
    title = re.sub(r'\s+\d[DK][/\s]*\d*[DK]*', '', title, flags=re.IGNORECASE)  # 3D/2D, 4K, 3D, etc.
    title = re.sub(r'\s+UHD', '', title, flags=re.IGNORECASE)

    # Remove common suffixes
    suffixes = [" DVD", " Blu-ray", " Digital", " Mill Creek", " Comedy", " Drama", " Action",
                " Collector s Edition", " Special Edition", " Extended Edition", " Director s Cut"]
    for suffix in suffixes:
        title = title.replace(suffix, '')

    # Remove trailing colons
    title = re.sub(r':\s*$', '', title)

    return title.strip()

# ========== TYPE GUESSING =================

def guess_type(title):
    tv_words = ["season", "complete", "series", "tv"]
    return "series" if any(w in title.lower() for w in tv_words) else "movie"

# ========== GET PROFILES ==================

def get_radarr_quality_profile():
    """Get the first available quality profile from Radarr"""
    try:
        r = requests.get(f"{RADARR_URL}/api/v3/qualityprofile", headers=HEADERS_RADARR)
        profiles = r.json()
        return profiles[0]["id"] if profiles else 1
    except:
        return 1

def get_sonarr_quality_profile():
    """Get the first available quality profile from Sonarr"""
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/qualityprofile", headers=HEADERS_SONARR)
        profiles = r.json()
        return profiles[0]["id"] if profiles else 1
    except:
        return 1

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
        "qualityProfileId": get_radarr_quality_profile(),
        "rootFolderPath": MOVIE_ROOT,
        "monitored": True,
        "addOptions": {"searchForMovie": False}
    }
    try:
        r = requests.post(f"{RADARR_URL}/api/v3/movie", json=payload, headers=HEADERS_RADARR)
        if r.status_code == 201:
            print(f"Successfully added to Radarr: {movie['title']}")
        elif r.status_code == 400:
            error_msg = r.json()
            if "MovieExistsValidator" in str(error_msg):
                print(f"Movie already exists in Radarr: {movie['title']}")
            else:
                print(f"Radarr error: {error_msg}")
        else:
            print(f"Radarr returned status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Error adding to Radarr: {e}")

# ========== ADD TO SONARR =================

def add_series(series):
    payload = {
        "tvdbId": series["tvdbId"],
        "title": series["title"],
        "year": series["year"],
        "qualityProfileId": get_sonarr_quality_profile(),
        "rootFolderPath": TV_ROOT,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": False}
    }
    try:
        r = requests.post(f"{SONARR_URL}/api/v3/series", json=payload, headers=HEADERS_SONARR)
        if r.status_code == 201:
            print(f"Successfully added to Sonarr: {series['title']}")
        elif r.status_code == 400:
            error_msg = r.json()
            if "SeriesExistsValidator" in str(error_msg):
                print(f"Series already exists in Sonarr: {series['title']}")
            else:
                print(f"Sonarr error: {error_msg}")
        else:
            print(f"Sonarr returned status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Error adding to Sonarr: {e}")

# ========== SCAN LOOP =====================

def scan_loop(df):
    print(f"Opening serial port {SERIAL_PORT} at {SERIAL_BAUDRATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print("Serial port opened. Waiting for barcode scans... (Press Ctrl+C to quit)")
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return

    try:
        while True:
            if ser.in_waiting > 0:
                barcode = ser.readline().decode('utf-8').strip()

                if not barcode:
                    continue

                print(f"\nReceived barcode: {barcode}")

                if barcode in df["barcode"].values:
                    print("Already scanned.")
                    continue

                title = lookup_barcode(barcode)
                if not title:
                    print("Barcode not found.")
                    continue

                print(f"Raw title: {title}")
                media_type = guess_type(title)
                clean_search_title = clean_title(title)
                print(f"Detected {media_type}: {clean_search_title}")

                if media_type == "movie":
                    movie = search_tmdb_movie(clean_search_title)
                    if movie:
                        # Check if movie already exists in database
                        # Convert tmdb_id to string for comparison, handling NaN values
                        existing = df[(df["type"] == "movie") & (df["tmdb_id"].astype(str).str.replace('.0', '', regex=False) == str(movie["tmdbId"]))]
                        if not existing.empty:
                            # Update existing entry with physical copy info
                            df.loc[existing.index[0], "has_physical"] = True
                            df.loc[existing.index[0], "barcode"] = barcode
                            save_db(df)
                            print(f"Updated existing movie with physical copy info.")
                        else:
                            add_movie(movie)
                            new_row = pd.DataFrame([{
                                "type": "movie",
                                "title": movie["title"],
                                "year": movie["year"],
                                "tmdb_id": movie["tmdbId"],
                                "tvdb_id": None,
                                "season_count": None,
                                "has_physical": True,
                                "barcode": barcode,
                                "source": "barcode"
                            }])
                            df = pd.concat([df, new_row], ignore_index=True)
                            save_db(df)
                            print("Added & saved.")
                    else:
                        print("Movie not found in search.")

                else:
                    series = search_tvdb_series(clean_search_title)
                    if series:
                        # Check if series already exists in database
                        # Convert tvdb_id to string for comparison, handling NaN values
                        existing = df[(df["type"] == "series") & (df["tvdb_id"].astype(str).str.replace('.0', '', regex=False) == str(series["tvdbId"]))]
                        if not existing.empty:
                            # Update existing entry with physical copy info
                            df.loc[existing.index[0], "has_physical"] = True
                            df.loc[existing.index[0], "barcode"] = barcode
                            save_db(df)
                            print(f"Updated existing series with physical copy info.")
                        else:
                            add_series(series)
                            new_row = pd.DataFrame([{
                                "type": "series",
                                "title": series["title"],
                                "year": series["year"],
                                "tmdb_id": None,
                                "tvdb_id": series["tvdbId"],
                                "season_count": len(series["seasons"]),
                                "has_physical": True,
                                "barcode": barcode,
                                "source": "barcode"
                            }])
                            df = pd.concat([df, new_row], ignore_index=True)
                            save_db(df)
                            print("Added & saved.")
                    else:
                        print("Series not found in search.")

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        ser.close()
        print("Serial port closed.")

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
