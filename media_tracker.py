from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
import pandas as pd
import os
import threading
import re
import queue
from dotenv import load_dotenv
from rapidfuzz import fuzz

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("Warning: pyserial not available. Serial port scanning disabled.")

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

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Serial port barcode queue
barcode_queue = queue.Queue()
serial_thread = None


# =============== HELPERS ==================

def load_or_create_db():
    if os.path.exists(CSV_FILE):
        print(f"Loading database from {CSV_FILE}")
        df = pd.read_csv(CSV_FILE)
        # Ensure genres column exists (for backward compatibility)
        if 'genres' not in df.columns:
            df['genres'] = ''
        # Fill NaN values in genres column
        df['genres'] = df['genres'].fillna('')
        return df
    print("Creating new database")
    return pd.DataFrame(columns=[
        "type", "title", "year",
        "tmdb_id", "tvdb_id",
        "season_count",
        "has_physical", "barcode",
        "source", "genres"
    ])

def save_db(df):
    df.to_csv(CSV_FILE, index=False)

# ========== IMPORT FROM RADARR ============

def import_radarr(df):
    try:
        r = requests.get(f"{RADARR_URL}/api/v3/movie", headers=HEADERS_RADARR)
        r.raise_for_status()

        rows = []
        
        for m in r.json():
            # Extract genres from Radarr response
            genres_list = m.get("genres", [])
            genres_str = ", ".join(genres_list) if genres_list else ""
            # Check if movie exists
            existing = df[(df["title"] == m["title"]) & (df["type"] == "movie")]
            
            if existing.empty:
                # Add new movie
                rows.append({
                    "type": "movie",
                    "title": m["title"],
                    "year": m["year"],
                    "tmdb_id": m["tmdbId"],
                    "tvdb_id": None,
                    "season_count": None,
                    "has_physical": False,
                    "barcode": None,
                    "source": "radarr",
                    "genres": genres_str
                })
            else:
                # Update existing movie with genres if missing
                idx = existing.index[0]
                if pd.isna(df.loc[idx, 'genres']) or df.loc[idx, 'genres'] == '':
                    df.loc[idx, 'genres'] = genres_str

        if rows:
            return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        return df
    except Exception as e:
        print(f"Error importing from Radarr: {e}")
        return df


# ========== IMPORT FROM SONARR ============

def import_sonarr(df):
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/series", headers=HEADERS_SONARR)
        r.raise_for_status()

        rows = []
        for s in r.json():
            # Extract genres from Sonarr response
            genres_list = s.get("genres", [])
            genres_str = ", ".join(genres_list) if genres_list else ""
            
            # Check if series exists
            existing = df[(df["title"] == s["title"]) & (df["type"] == "series")]
            
            if existing.empty:
                # Add new series
                rows.append({
                    "type": "series",
                    "title": s["title"],
                    "year": s["year"],
                    "tmdb_id": None,
                    "tvdb_id": s["tvdbId"],
                    "season_count": len(s["seasons"]),
                    "has_physical": False,
                    "barcode": None,
                    "source": "sonarr",
                    "genres": genres_str
                })
            else:
                # Update existing series with genres if missing
                idx = existing.index[0]
                if pd.isna(df.loc[idx, 'genres']) or df.loc[idx, 'genres'] == '':
                    df.loc[idx, 'genres'] = genres_str

        if rows:
            return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        return df
    except Exception as e:
        print(f"Error importing from Sonarr: {e}")
        return df


# ========== BARCODE LOOKUP ================

def lookup_barcode(barcode):
    try:
        r = requests.get(
            "https://api.upcitemdb.com/prod/trial/lookup",
            params={"upc": barcode}
        )
        data = r.json()

        if data.get("code") != "OK" or not data["items"]:
            return None

        return data["items"][0]["title"]
    except Exception as e:
        print(f"Error looking up barcode: {e}")
        return None


# ========== TYPE GUESSING =================

def guess_type(title):
    tv_words = ["season", "complete", "series", "tv", "dvd"]
    return "series" if any(w in title.lower() for w in tv_words) else "movie"

# ========== TITLE EXTRACTION ===============

def extract_base_title(title):
    """Extract base title from barcode lookup results, removing parenthetical info"""
    if not title:
        return ""
    
    # Remove common parenthetical patterns like "(4K Ultra HD + Blu-ray + Digital Copy)"
    # Pattern matches: (anything in parentheses)
    base_title = re.sub(r'\s*\([^)]*\)\s*', '', title)
    
    # Also remove common suffixes like " - Blu-ray", " - DVD", etc.
    base_title = re.sub(r'\s*[-–]\s*(Blu-ray|DVD|4K|Ultra HD|Digital Copy).*$', '', base_title, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    base_title = base_title.strip()
    
    return base_title

# ========== LOCAL DATABASE SEARCH ==========

def search_local_database(query, media_type=None, year=None):
    """Search local database with fuzzy matching"""
    df = load_or_create_db()
    results = []
    
    if not query:
        return results
    
    base_query = extract_base_title(query).lower()
    
    # Filter by type if specified
    if media_type:
        df_filtered = df[df['type'] == media_type]
    else:
        df_filtered = df
    
    for idx, row in df_filtered.iterrows():
        title = str(row['title']).lower() if pd.notna(row['title']) else ""
        
        # Calculate similarity
        similarity = fuzz.ratio(base_query, title)
        
        # Also check if base query is contained in title
        contains_match = base_query in title or title in base_query
        
        # Match by year if provided
        year_match = True
        if year and pd.notna(row['year']):
            year_match = abs(int(row['year']) - int(year)) <= 2  # Allow 2 year difference
        
        # Add to results if similarity is high enough or contains match
        if similarity >= 80 or (contains_match and similarity >= 60):
            if year is None or year_match:
                result = row.to_dict()
                # Convert NaN values to None for JSON serialization
                for key, value in result.items():
                    if pd.isna(value):
                        result[key] = None
                result['similarity'] = similarity
                result['match_type'] = 'local'
                results.append(result)
    
    # Sort by similarity (highest first)
    results.sort(key=lambda x: x.get('similarity', 0), reverse=True)
    
    return results[:10]  # Return top 10 matches


# ========== SEARCH TMDB ===================

def search_tmdb_movie(title):
    try:
        r = requests.get(
            f"{RADARR_URL}/api/v3/movie/lookup",
            headers=HEADERS_RADARR,
            params={"term": title}
        )
        results = r.json()
        return results if results else []
    except Exception as e:
        print(f"Error searching TMDB: {e}")
        return []

def search_tvdb_series(title):
    try:
        r = requests.get(
            f"{SONARR_URL}/api/v3/series/lookup",
            headers=HEADERS_SONARR,
            params={"term": title}
        )
        results = r.json()
        return results if results else []
    except Exception as e:
        print(f"Error searching TVDB: {e}")
        return []

# ========== ADD TO RADARR =================

def add_movie(movie):
    try:
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
        return True
    except Exception as e:
        print(f"Error adding movie to Radarr: {e}")
        return False


# ========== ADD TO SONARR =================

def add_series(series):
    try:
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
        return True
    except Exception as e:
        print(f"Error adding series to Sonarr: {e}")
        return False

# ============ WEB ROUTES ==================

@app.route('/')
def index():
    """Serve the main page"""
    return send_from_directory('.', 'index.html')

# ============ API ROUTES ==================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get current statistics"""
    df = load_or_create_db()

    stats = {
        'movies': int(df[df['type'] == 'movie'].shape[0]),
        'series': int(df[df['type'] == 'series'].shape[0]),
        'dvds': int(df[df['has_physical'] == True].shape[0])
    }

    return jsonify(stats)


@app.route('/api/media', methods=['GET'])
def get_media():
    """Get all media items"""
    df = load_or_create_db()
    return jsonify(df.to_dict('records'))

@app.route('/api/scan', methods=['POST'])
def scan():
    """Fast scan endpoint - checks barcode first, then local DB, returns immediately"""
    data = request.json
    barcode = data.get('barcode', '').strip()

    if not barcode:
        return jsonify({'error': 'No barcode provided'}), 400

    df = load_or_create_db()
    steps = []
    result_data = {
        'barcode': barcode,
        'steps': steps
    }

    # Step 1: Check if barcode already exists in database
    steps.append({'step': 1, 'action': 'Check barcode in database', 'status': 'checking'})
    barcode_matches = df[df['barcode'].astype(str) == str(barcode)]
    if not barcode_matches.empty:
        # Toggle has_physical
        idx = barcode_matches.index[0]
        old_physical = df.loc[idx, 'has_physical']
        df.loc[idx, 'has_physical'] = not df.loc[idx, 'has_physical']
        save_db(df)
        
        item = df.loc[idx].to_dict()
        steps.append({
            'step': 1, 
            'action': 'Check barcode in database', 
            'status': 'found',
            'details': f"Found existing entry: {item['title']} ({item['year']})",
            'action_taken': f"Toggled physical copy from {old_physical} to {not old_physical}"
        })
        
        result_data.update({
            'success': True,
            'item': item,
            'updated': True,
            'toggled': True,
            'found_by_barcode': True
        })
        return jsonify(result_data)

    steps.append({
        'step': 1, 
        'action': 'Check barcode in database', 
        'status': 'not_found',
        'details': 'Barcode not found in database'
    })

    # Step 2: Lookup barcode to get title
    steps.append({'step': 2, 'action': 'Lookup barcode in UPC database', 'status': 'checking'})
    title = lookup_barcode(barcode)
    if not title:
        steps.append({
            'step': 2, 
            'action': 'Lookup barcode in UPC database', 
            'status': 'not_found',
            'details': 'Barcode not found in UPC lookup database'
        })
        result_data.update({
            'success': False,
            'error': 'Barcode not found in lookup database'
        })
        return jsonify(result_data), 404

    steps.append({
        'step': 2, 
        'action': 'Lookup barcode in UPC database', 
        'status': 'found',
        'details': f"Found title: {title}"
    })

    # Step 3: Extract base title
    base_title = extract_base_title(title)
    steps.append({
        'step': 3, 
        'action': 'Extract base title', 
        'status': 'completed',
        'details': f"Extracted: '{base_title}' from '{title}'"
    })

    # Step 4: Search local database
    steps.append({'step': 4, 'action': 'Search local database', 'status': 'searching'})
    local_results = search_local_database(base_title)
    
    if local_results:
        steps.append({
            'step': 4, 
            'action': 'Search local database', 
            'status': 'found',
            'details': f"Found {len(local_results)} match(es) in local database",
            'matches': [{'title': r['title'], 'year': r.get('year'), 'similarity': r.get('similarity', 0)} for r in local_results[:5]]
        })
        
        # Found in local database - update the first match
        best_match = local_results[0]
        # Find the row in dataframe
        if 'tmdb_id' in best_match and pd.notna(best_match['tmdb_id']):
            existing = df[(df['type'] == best_match['type']) & (df['tmdb_id'] == best_match['tmdb_id'])]
        elif 'tvdb_id' in best_match and pd.notna(best_match['tvdb_id']):
            existing = df[(df['type'] == best_match['type']) & (df['tvdb_id'] == best_match['tvdb_id'])]
        else:
            existing = df[(df['type'] == best_match['type']) & (df['title'] == best_match['title'])]
        
        if not existing.empty:
            idx = existing.index[0]
            df.loc[idx, 'has_physical'] = True
            df.loc[idx, 'barcode'] = barcode
            save_db(df)
            
            item = df.loc[idx].to_dict()
            steps.append({
                'step': 5, 
                'action': 'Update database', 
                'status': 'completed',
                'details': f"Updated: {item['title']} - Set has_physical=True and added barcode"
            })
            
            result_data.update({
                'success': True,
                'item': item,
                'updated': True,
                'found_in_local': True,
                'local_results': local_results[:10]
            })
            return jsonify(result_data)
    else:
        steps.append({
            'step': 4, 
            'action': 'Search local database', 
            'status': 'not_found',
            'details': 'No matches found in local database'
        })

    # Step 5: Not found locally - return info for manual confirmation
    media_type = guess_type(title)
    steps.append({
        'step': 5, 
        'action': 'Determine media type', 
        'status': 'completed',
        'details': f"Guessed type: {media_type}"
    })
    
    result_data.update({
        'success': False,
        'suggested_title': title,
        'base_title': base_title,
        'suggested_type': media_type,
        'found_in_local': False,
        'message': 'Item not found in local database. Please use /api/lookup for external search.'
    })
    return jsonify(result_data)

@app.route('/api/lookup', methods=['POST'])
def lookup():
    """Lookup barcode and search for matches - searches local DB first, then external"""
    data = request.json
    barcode = data.get('barcode', '').strip()

    if not barcode:
        return jsonify({'error': 'No barcode provided'}), 400

    df = load_or_create_db()

    # Check if already scanned
    if barcode in df['barcode'].values:
        return jsonify({'error': 'Barcode already scanned'}), 400

    # Lookup barcode
    title = lookup_barcode(barcode)
    suggested_title = title if title else ""
    
    # Guess type
    media_type = guess_type(suggested_title) if suggested_title else "movie"
    
    # Search local database first
    local_results = []
    if suggested_title:
        base_title = extract_base_title(suggested_title)
        local_results = search_local_database(base_title, media_type)
    
    # Search external databases
    movie_results = []
    series_results = []
    
    if suggested_title:
        if media_type == "movie":
            movie_results = search_tmdb_movie(suggested_title)
            # Mark if already in library
            for result in movie_results:
                existing = df[(df['type'] == 'movie') & (df['tmdb_id'] == result['tmdbId'])]
                if not existing.empty:
                    result['already_in_library'] = True
        else:
            series_results = search_tvdb_series(suggested_title)
            # Mark if already in library
            for result in series_results:
                existing = df[(df['type'] == 'series') & (df['tvdb_id'] == result['tvdbId'])]
                if not existing.empty:
                    result['already_in_library'] = True
    
    return jsonify({
        'barcode': barcode,
        'suggested_title': suggested_title,
        'suggested_type': media_type,
        'local_results': local_results,
        'movie_results': movie_results[:10],
        'series_results': series_results[:10]
    })

@app.route('/api/search', methods=['POST'])
def search():
    """Manual search for movies or series - searches local DB first, then external"""
    data = request.json
    query = data.get('query', '').strip()
    media_type = data.get('type', 'movie')
    
    if not query:
        return jsonify({'error': 'No search query provided'}), 400
    
    # Search local database first
    local_results = search_local_database(query, media_type)
    
    # Search external databases
    if media_type == 'movie':
        external_results = search_tmdb_movie(query)
    else:
        external_results = search_tvdb_series(query)
    
    return jsonify({
        'local_results': local_results,
        'external_results': external_results[:10],
        'type': media_type
    })

@app.route('/api/confirm', methods=['POST'])
def confirm_add():
    """Confirm and add selected item to database"""
    data = request.json
    barcode = data.get('barcode', '').strip()
    media_type = data.get('type')
    selected_item = data.get('item')
    
    if not barcode or not media_type or not selected_item:
        return jsonify({'error': 'Missing required data'}), 400
    
    df = load_or_create_db()
    
    # Check if already scanned with this barcode
    if barcode in df['barcode'].values:
        return jsonify({'error': 'Barcode already scanned'}), 400
    
    if media_type == 'movie':
        # Check if movie already exists in library
        existing = df[(df['type'] == 'movie') & (df['tmdb_id'] == selected_item['tmdbId'])]
        
        if not existing.empty:
            # Update existing entry to mark as physical
            df.loc[existing.index, 'has_physical'] = True
            df.loc[existing.index, 'barcode'] = barcode
            save_db(df)
            
            return jsonify({
                'success': True,
                'item': df.loc[existing.index].iloc[0].to_dict(),
                'updated': True
            })
        else:
            # Add to Radarr
            add_movie(selected_item)
            
            # Add to database
            # Get genres from selected item if available
            genres_list = selected_item.get("genres", [])
            genres_str = ", ".join([g.get("name", g) if isinstance(g, dict) else g for g in genres_list]) if genres_list else ""
            
            new_row = {
                "type": "movie",
                "title": selected_item["title"],
                "year": selected_item.get("year"),
                "tmdb_id": selected_item["tmdbId"],
                "tvdb_id": None,
                "season_count": None,
                "has_physical": True,
                "barcode": barcode,
                "source": "barcode",
                "genres": genres_str
            }
            
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            save_db(df)
            
            return jsonify({
                'success': True,
                'item': new_row,
                'updated': False
            })
    
    else:  # series
        # Check if series already exists in library
        existing = df[(df['type'] == 'series') & (df['tvdb_id'] == selected_item['tvdbId'])]
        
        if not existing.empty:
            # Update existing entry to mark as physical
            df.loc[existing.index, 'has_physical'] = True
            df.loc[existing.index, 'barcode'] = barcode
            save_db(df)
            
            return jsonify({
                'success': True,
                'item': df.loc[existing.index].iloc[0].to_dict(),
                'updated': True
            })
        else:
            # Add to Sonarr
            add_series(selected_item)
            
            # Add to database
            # Get genres from selected item if available
            genres_list = selected_item.get("genres", [])
            genres_str = ", ".join([g.get("name", g) if isinstance(g, dict) else g for g in genres_list]) if genres_list else ""
            
            new_row = {
                "type": "series",
                "title": selected_item["title"],
                "year": selected_item.get("year"),
                "tmdb_id": None,
                "tvdb_id": selected_item["tvdbId"],
                "season_count": len(selected_item.get("seasons", [])),
                "has_physical": True,
                "barcode": barcode,
                "source": "barcode",
                "genres": genres_str
            }
            
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            save_db(df)
            
            return jsonify({
                'success': True,
                'item': new_row,
                'updated': False
            })


@app.route('/api/sync', methods=['POST'])
def sync_libraries():
    """Sync with Radarr and Sonarr"""
    df = load_or_create_db()
    df = import_radarr(df)
    df = import_sonarr(df)
    save_db(df)

    return jsonify({'success': True, 'total_items': len(df)})

@app.route('/api/genre-stats', methods=['GET'])
def get_genre_stats():
    """Get genre statistics for movies and TV shows"""
    df = load_or_create_db()
    
    # Ensure genres column exists
    if 'genres' not in df.columns:
        return jsonify({
            'movies': {},
            'series': {},
            'all': {}
        })
    
    # Initialize genre counters
    movie_genres = {}
    series_genres = {}
    all_genres = {}
    
    # Process each row
    for idx, row in df.iterrows():
        genres_str = str(row.get('genres', '')) if pd.notna(row.get('genres')) else ''
        if not genres_str:
            continue
        
        # Split genres (comma-separated)
        genres_list = [g.strip() for g in genres_str.split(',') if g.strip()]
        
        media_type = row.get('type', '')
        
        for genre in genres_list:
            # Count for all
            all_genres[genre] = all_genres.get(genre, 0) + 1
            
            # Count by type
            if media_type == 'movie':
                movie_genres[genre] = movie_genres.get(genre, 0) + 1
            elif media_type == 'series':
                series_genres[genre] = series_genres.get(genre, 0) + 1
    
    return jsonify({
        'movies': movie_genres,
        'series': series_genres,
        'all': all_genres
    })


# ========== SERIAL PORT HANDLER ============

def serial_port_reader():
    """Background thread that reads barcodes from serial port"""
    if not SERIAL_AVAILABLE or not SERIAL_PORT:
        return
    
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
        print(f"Serial port {SERIAL_PORT} opened successfully")
        
        buffer = ""
        while True:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                buffer += data
                
                # Check for complete barcode (typically ends with newline or carriage return)
                if '\n' in buffer or '\r' in buffer:
                    barcode = buffer.strip().replace('\n', '').replace('\r', '')
                    if barcode:
                        print(f"Barcode scanned from serial: {barcode}")
                        barcode_queue.put(barcode)
                    buffer = ""
            else:
                # Small delay to prevent CPU spinning
                threading.Event().wait(0.1)
                
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
    except Exception as e:
        print(f"Error in serial port reader: {e}")
    finally:
        if 'ser' in locals():
            ser.close()

def process_barcode_queue():
    """Process barcodes from the queue"""
    while True:
        try:
            barcode = barcode_queue.get(timeout=1)
            if barcode:
                # Process the barcode using the scan endpoint logic
                # This runs in a separate thread so it won't block
                with app.app_context():
                    try:
                        df = load_or_create_db()
                        
                        # Check if barcode exists
                        barcode_matches = df[df['barcode'].astype(str) == str(barcode)]
                        if not barcode_matches.empty:
                            idx = barcode_matches.index[0]
                            df.loc[idx, 'has_physical'] = not df.loc[idx, 'has_physical']
                            save_db(df)
                            print(f"Toggled physical copy for barcode: {barcode}")
                        else:
                            # Lookup and search local DB
                            title = lookup_barcode(barcode)
                            if title:
                                base_title = extract_base_title(title)
                                local_results = search_local_database(base_title)
                                if local_results:
                                    best_match = local_results[0]
                                    if 'tmdb_id' in best_match and pd.notna(best_match['tmdb_id']):
                                        existing = df[(df['type'] == best_match['type']) & (df['tmdb_id'] == best_match['tmdb_id'])]
                                    elif 'tvdb_id' in best_match and pd.notna(best_match['tvdb_id']):
                                        existing = df[(df['type'] == best_match['type']) & (df['tvdb_id'] == best_match['tvdb_id'])]
                                    else:
                                        existing = df[(df['type'] == best_match['type']) & (df['title'] == best_match['title'])]
                                    
                                    if not existing.empty:
                                        idx = existing.index[0]
                                        df.loc[idx, 'has_physical'] = True
                                        df.loc[idx, 'barcode'] = barcode
                                        save_db(df)
                                        print(f"Updated physical copy for barcode: {barcode}")
                    except Exception as e:
                        print(f"Error processing barcode {barcode}: {e}")
        except queue.Empty:
            continue

# ============ STARTUP =====================

def initialize_app():
    """Initialize the database on startup"""
    df = load_or_create_db()
    df = import_radarr(df)
    df = import_sonarr(df)
    save_db(df)
    print(f"Initialized with {len(df)} items")
    
    # Start serial port handler if configured
    global serial_thread
    if SERIAL_AVAILABLE and SERIAL_PORT:
        try:
            serial_thread = threading.Thread(target=serial_port_reader, daemon=True)
            serial_thread.start()
            print(f"Serial port reader started on {SERIAL_PORT}")
            
            # Start queue processor
            queue_thread = threading.Thread(target=process_barcode_queue, daemon=True)
            queue_thread.start()
            print("Barcode queue processor started")
        except Exception as e:
            print(f"Failed to start serial port handler: {e}")
    else:
        if not SERIAL_AVAILABLE:
            print("Serial port support not available (pyserial not installed)")
        if not SERIAL_PORT:
            print("Serial port not configured (set SERIAL_PORT environment variable)")


if __name__ == "__main__":
    # Initialize database
    print("starting media tracker...")
    initialize_app()

    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)