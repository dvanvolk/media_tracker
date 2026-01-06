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

# TMDB API key for potential future use (currently using Radarr's TMDB integration)
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

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
    """Lookup barcode with retry logic and rate limiting protection"""
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
            
            # Handle rate limiting or other errors
            if data.get("code") != "OK":
                error_msg = data.get("message", "Unknown error")
                # If rate limited, wait longer before retrying
                if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s for rate limits
                        print(f"Rate limited (attempt {attempt + 1}/{max_retries}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"Rate limited after {max_retries} attempts. UPCItemDB may have daily limits.")
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

def extract_year(title):
    """Extract year from title if present in brackets or parentheses"""
    # Look for 4-digit years in brackets [2001] or parentheses (2011)
    year_match = re.search(r'[\[\(](\d{4})[\]\)]', title)
    if year_match:
        try:
            return int(year_match.group(1))
        except ValueError:
            pass
    return None

def clean_title(title):
    """Remove common suffixes, formats, and studio names from barcode titles"""
    # Common studio/distributor names to remove (at the start of title)
    studio_patterns = [
        r'^20th\s+Century\s+Fox\s+Home\s+Entertainment\s+',
        r'^20th\s+Century\s+Studios\s+',
        r'^Universal\s+Studios\s*[-–]\s*',
        r'^Universal\s+Home\s+Entertainment\s+',
        r'^Mill\s+Creek\s*[-–]\s*',
        r'^Mill\s+Creek\s+Entertainment\s+',
        r'^Dreamworks\s+Animated\s+',
        r'^Dreamworks\s+',
        r'^WGBH\s+',
        r'^Warner\s+Bros\s*\.?\s*',
        r'^Sony\s+Pictures\s+',
        r'^Paramount\s+',
        r'^Disney\s+',
        r'^Lionsgate\s+',
        r'^Anchor\s+Bay\s+',
        r'^Criterion\s+Collection\s+',
        r'^Shout\s+Factory\s+',
    ]
    
    for pattern in studio_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    
    # Remove parenthetical and bracketed content like (DVD), (Blu-ray), [Blu-ray], etc.
    # But preserve year information first (we extract it separately)
    title = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)

    # Remove 3D/2D, 4K, UHD variants
    title = re.sub(r'\s+\d[DK][/\s]*\d*[DK]*', '', title, flags=re.IGNORECASE)  # 3D/2D, 4K, 3D, etc.
    title = re.sub(r'\s+UHD', '', title, flags=re.IGNORECASE)

    # Remove common suffixes
    suffixes = [
        " DVD", " Blu-ray", " Digital", " Mill Creek", " Comedy", " Drama", " Action",
        " Collector s Edition", " Special Edition", " Extended Edition", " Director s Cut",
        " Widescreen", " Full Screen", " Standard Definition", " Kids & Family",
        " Walmart Exclusive", " Masterpiece", " DIGITAL VIDEO DISC"
    ]
    for suffix in suffixes:
        title = title.replace(suffix, '')

    # Remove trailing colons, dashes, and extra whitespace
    title = re.sub(r'[:–-]\s*$', '', title)
    title = re.sub(r'\s+', ' ', title)  # Collapse multiple spaces

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

def search_tmdb_movie(title, preferred_year=None):
    """Search for movie using Radarr's TMDB lookup, trying multiple title variations.
    Returns the best match, preferring results that match preferred_year if provided.
    Uses fuzzy matching to find the best title match when no year is specified."""
    from difflib import SequenceMatcher

    all_results = []

    # Try the full cleaned title first
    search_terms = [title]

    # If title is long, try just the first few words (often the actual movie title)
    words = title.split()
    if len(words) > 3:
        search_terms.append(' '.join(words[:3]))
        search_terms.append(' '.join(words[:2]))

    # Try removing common words that might interfere
    common_words = ['the', 'a', 'an', 'and', 'or', 'but']
    filtered_words = [w for w in words if w.lower() not in common_words]
    if len(filtered_words) < len(words) and len(filtered_words) > 0:
        search_terms.append(' '.join(filtered_words))

    # Collect all results from all search terms
    for search_term in search_terms:
        try:
            r = requests.get(
                f"{RADARR_URL}/api/v3/movie/lookup",
                headers=HEADERS_RADARR,
                params={"term": search_term},
                timeout=10
            )
            r.raise_for_status()
            results = r.json()
            if results:
                seen_ids = {m.get("tmdbId") for m in all_results}
                for movie in results:
                    if movie.get("tmdbId") not in seen_ids:
                        all_results.append(movie)
                        seen_ids.add(movie.get("tmdbId"))
        except (requests.RequestException, ValueError, KeyError):
            continue

    if not all_results:
        return None

    # Debug: Show all found results
    if len(all_results) > 1:
        print(f"Found {len(all_results)} movie matches:")
        for i, m in enumerate(all_results[:5], 1):
            print(f"  {i}. {m.get('title', 'Unknown')} ({m.get('year', 'unknown year')})")

    # If we have a preferred year, prioritize exact matches
    if preferred_year:
        exact_matches = [m for m in all_results if m.get("year") == preferred_year]
        if exact_matches:
            exact_matches.sort(key=lambda x: (
                x.get("popularity", 0),
                x.get("ratings", {}).get("value", 0) if isinstance(x.get("ratings"), dict) else 0
            ), reverse=True)
            return exact_matches[0]

        close_matches = [m for m in all_results if abs(m.get("year", 0) - preferred_year) <= 2]
        if close_matches:
            close_matches.sort(key=lambda x: abs(x.get("year", 0) - preferred_year))
            return close_matches[0]

    # Calculate similarity for each result
    def calculate_similarity(movie_title, search_title):
        movie_lower = movie_title.lower().strip()
        search_lower = search_title.lower().strip()

        if movie_lower == search_lower:
            return 1.0

        return SequenceMatcher(None, movie_lower, search_lower).ratio()

    # NEW: Check for perfect title matches first
    perfect_matches = []
    for movie in all_results:
        movie_title = movie.get("title", "")
        similarity = calculate_similarity(movie_title, title)
        if similarity == 1.0:
            perfect_matches.append(movie)

    # If we have perfect title match(es), choose the most popular one
    if perfect_matches:
        print(f"Found {len(perfect_matches)} perfect title match(es)")
        perfect_matches.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        selected = perfect_matches[0]
        print(f"Selected perfect match: {selected.get('title')} ({selected.get('year')})")
        return selected

    # Otherwise, use fuzzy matching with combined score
    scored_results = []
    for movie in all_results:
        movie_title = movie.get("title", "")
        similarity = calculate_similarity(movie_title, title)

        max_popularity = max((m.get("popularity", 0) for m in all_results), default=1)
        normalized_popularity = movie.get("popularity", 0) / max_popularity if max_popularity > 0 else 0

        # Weight: 80% similarity, 20% popularity
        combined_score = (similarity * 0.8) + (normalized_popularity * 0.2)

        scored_results.append({
            "movie": movie,
            "similarity": similarity,
            "popularity": movie.get("popularity", 0),
            "combined_score": combined_score
        })

    scored_results.sort(key=lambda x: x["combined_score"], reverse=True)

    if len(scored_results) > 1:
        print(f"\nTop matches by similarity:")
        for i, result in enumerate(scored_results[:3], 1):
            movie = result["movie"]
            print(f"  {i}. {movie.get('title')} ({movie.get('year')}) - "
                  f"Similarity: {result['similarity']:.2f}, Score: {result['combined_score']:.2f}")

    selected = scored_results[0]["movie"]
    print(f"Selected: {selected.get('title')} ({selected.get('year')})")

    return selected
    # If no preferred year, use fuzzy matching to find best title match
    # Calculate similarity ratio for each result
    def calculate_similarity(movie_title, search_title):
        """Calculate similarity between movie title and search title"""
        # Normalize both titles for comparison
        movie_lower = movie_title.lower().strip()
        search_lower = search_title.lower().strip()

        # Direct match gets highest score
        if movie_lower == search_lower:
            return 1.0

        # Use SequenceMatcher for fuzzy matching
        return SequenceMatcher(None, movie_lower, search_lower).ratio()

    # Score each movie by title similarity and popularity
    scored_results = []
    for movie in all_results:
        movie_title = movie.get("title", "")
        similarity = calculate_similarity(movie_title, title)

        # Combine similarity score with popularity (normalized)
        # Similarity is weighted heavily (80%), popularity is 20%
        max_popularity = max((m.get("popularity", 0) for m in all_results), default=1)
        normalized_popularity = movie.get("popularity", 0) / max_popularity if max_popularity > 0 else 0

        combined_score = (similarity * 0.8) + (normalized_popularity * 0.2)

        scored_results.append({
            "movie": movie,
            "similarity": similarity,
            "popularity": movie.get("popularity", 0),
            "combined_score": combined_score
        })

    # Sort by combined score (descending)
    scored_results.sort(key=lambda x: x["combined_score"], reverse=True)

    # Show top matches for debugging
    if len(scored_results) > 1:
        print(f"\nTop matches by similarity:")
        for i, result in enumerate(scored_results[:3], 1):
            movie = result["movie"]
            print(f"  {i}. {movie.get('title')} ({movie.get('year')}) - "
                  f"Similarity: {result['similarity']:.2f}, Score: {result['combined_score']:.2f}")

    selected = scored_results[0]["movie"]
    print(f"Selected: {selected.get('title')} ({selected.get('year')})")

    return selected

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

# ========== BATCH MODE ====================

def batch_scan_and_review(df):
    """Batch mode: collect barcodes, lookup titles, then review before adding"""
    print(f"Opening serial port {SERIAL_PORT} at {SERIAL_BAUDRATE} baud...")
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print("Serial port opened.")
        print("\n=== BATCH MODE ===")
        print("Scan barcodes. Press Ctrl+C when done scanning to review results.")
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return

    barcodes = []

    try:
        # Phase 1: Collect barcodes
        while True:
            if ser.in_waiting > 0:
                barcode = ser.readline().decode('utf-8').strip()
                if not barcode:
                    continue

                if barcode in [b[0] for b in barcodes]:
                    print(f"Barcode {barcode} already in batch, skipping.")
                    continue

                if barcode in df["barcode"].values:
                    print(f"Barcode {barcode} already in database, skipping.")
                    continue

                barcodes.append((barcode, None, None))  # (barcode, raw_title, cleaned_title)
                print(f"[{len(barcodes)}] Added: {barcode}")

    except KeyboardInterrupt:
        print(f"\n\nCollected {len(barcodes)} barcodes. Starting lookup...\n")
    finally:
        ser.close()
        print("Serial port closed.")

    if not barcodes:
        print("No barcodes collected.")
        return

    # Phase 2: Lookup titles (conserve API calls)
    print("\n=== LOOKING UP TITLES ===")
    results = []
    for i, (barcode, _, _) in enumerate(barcodes, 1):
        print(f"[{i}/{len(barcodes)}] Looking up {barcode}...", end=" ")
        raw_title = lookup_barcode(barcode)

        if not raw_title:
            print("NOT FOUND")
            results.append((barcode, None, None, None, None, None))
            time.sleep(0.5)  # Rate limit protection
            continue

        print(f"✓")
        media_type = guess_type(raw_title)
        extracted_year = extract_year(raw_title)
        cleaned_title = clean_title(raw_title)

        results.append((barcode, raw_title, cleaned_title, media_type, extracted_year, None))
        time.sleep(0.3)  # Rate limit protection between lookups

    # Phase 3: Search TMDB/TVDB for matches
    print("\n=== SEARCHING FOR MATCHES ===")
    final_results = []
    for i, (barcode, raw_title, cleaned_title, media_type, extracted_year, _) in enumerate(results, 1):
        if not cleaned_title:
            final_results.append((barcode, raw_title, cleaned_title, media_type, extracted_year, None))
            continue

        print(f"\n[{i}/{len(results)}] Searching: {cleaned_title}")

        if media_type == "movie":
            match = search_tmdb_movie(cleaned_title, preferred_year=extracted_year)
        else:
            match = search_tvdb_series(cleaned_title)

        final_results.append((barcode, raw_title, cleaned_title, media_type, extracted_year, match))

    # Phase 4: Review and approve
    print("\n\n" + "="*60)
    print("=== REVIEW RESULTS ===")
    print("="*60)

    for i, (barcode, raw_title, cleaned_title, media_type, extracted_year, match) in enumerate(final_results, 1):
        print(f"\n[{i}/{len(final_results)}]")
        print(f"  Barcode: {barcode}")
        print(f"  Raw title: {raw_title or 'NOT FOUND'}")

        if not match:
            print(f"  Status: ❌ No match found")
            continue

        print(f"  Cleaned: {cleaned_title}")
        print(f"  Type: {media_type}")
        if extracted_year:
            print(f"  Year from barcode: {extracted_year}")

        if media_type == "movie":
            print(f"  Match: {match.get('title')} ({match.get('year')})")
            print(f"  TMDB ID: {match.get('tmdbId')}")
        else:
            print(f"  Match: {match.get('title')} ({match.get('year')})")
            print(f"  TVDB ID: {match.get('tvdbId')}")
            print(f"  Seasons: {len(match.get('seasons', []))}")

        # Check if already exists
        if media_type == "movie":
            existing = df[(df["type"] == "movie") & (df["tmdb_id"].astype(str).str.replace('.0', '', regex=False) == str(match["tmdbId"]))]
        else:
            existing = df[(df["type"] == "series") & (df["tvdb_id"].astype(str).str.replace('.0', '', regex=False) == str(match["tvdbId"]))]

        if not existing.empty:
            print(f"  ⚠️  Already in database")
            response = input("  Update with physical copy info? (y/n/q to quit): ").strip().lower()
        else:
            response = input("  Add this to Radarr/Sonarr? (y/n/q to quit): ").strip().lower()

        if response == 'q':
            print("\nReview cancelled.")
            break
        elif response == 'y':
            if not existing.empty:
                # Update existing
                df.loc[existing.index[0], "has_physical"] = True
                df.loc[existing.index[0], "barcode"] = barcode
                save_db(df)
                print("  ✓ Updated with physical copy info")
            else:
                # Add new
                if media_type == "movie":
                    add_movie(match)
                    new_row = pd.DataFrame([{
                        "type": "movie",
                        "title": match["title"],
                        "year": match["year"],
                        "tmdb_id": match["tmdbId"],
                        "tvdb_id": None,
                        "season_count": None,
                        "has_physical": True,
                        "barcode": barcode,
                        "source": "barcode_batch"
                    }])
                else:
                    add_series(match)
                    new_row = pd.DataFrame([{
                        "type": "series",
                        "title": match["title"],
                        "year": match["year"],
                        "tmdb_id": None,
                        "tvdb_id": match["tvdbId"],
                        "season_count": len(match["seasons"]),
                        "has_physical": True,
                        "barcode": barcode,
                        "source": "barcode_batch"
                    }])

                df = pd.concat([df, new_row], ignore_index=True)
                save_db(df)
                print("  ✓ Added and saved")
        else:
            print("  ⏭️  Skipped")

    print("\n✓ Batch review complete!")
    return df

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
                    print("Barcode not found. This may be due to:")
                    print("  - Barcode not in UPCItemDB database")
                    print("  - Rate limiting (free tier has daily limits)")
                    print("  - Network issues")
                    print("  - Try again later or manually add this item")
                    # Add a small delay to avoid hammering the API
                    time.sleep(0.5)
                    continue
                
                # Small delay between successful lookups to avoid rate limiting
                time.sleep(0.2)

                print(f"Raw title: {title}")
                media_type = guess_type(title)
                # Extract year before cleaning (since clean_title removes brackets)
                extracted_year = extract_year(title)
                clean_search_title = clean_title(title)
                print(f"Detected {media_type}: {clean_search_title}")
                if extracted_year:
                    print(f"Extracted year from barcode: {extracted_year}")

                if media_type == "movie":
                    movie = search_tmdb_movie(clean_search_title, preferred_year=extracted_year)
                    if movie:
                        year_info = f" ({movie.get('year', 'unknown year')})"
                        if extracted_year and movie.get('year') != extracted_year:
                            print(f"Warning: Found movie from {movie.get('year')}, but barcode suggests {extracted_year}")
                        print(f"Selected: {movie.get('title', 'Unknown')}{year_info}")
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
    import sys

    df = load_or_create_db()
    df = import_radarr(df)
    df = import_sonarr(df)
    save_db(df)

    print(f"Loaded {len(df)} items.")

    # Check for batch mode flag
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        print("\nStarting BATCH MODE...")
        batch_scan_and_review(df)
    else:
        print("\nStarting LIVE MODE (use --batch flag for batch mode)...")
        scan_loop(df)

if __name__ == "__main__":
    main()
