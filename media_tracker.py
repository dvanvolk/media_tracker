from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
import pandas as pd
import os
import threading
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

HEADERS_RADARR = {"X-Api-Key": RADARR_API_KEY}
HEADERS_SONARR = {"X-Api-Key": SONARR_API_KEY}

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend


# =============== HELPERS ==================

def load_or_create_db():
    if os.path.exists(CSV_FILE):
        print(f"Loading database from {CSV_FILE}")
        return pd.read_csv(CSV_FILE)
    print("Creating new database")
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
    try:
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

@app.route('/api/lookup', methods=['POST'])
def lookup():
    """Lookup barcode and search for matches"""
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
    
    # Search both databases
    movie_results = []
    series_results = []
    
    if suggested_title:
        if media_type == "movie":
            movie_results = search_tmdb_movie(suggested_title)
            # Also check if it exists in our database
            for result in movie_results:
                existing = df[(df['type'] == 'movie') & (df['tmdb_id'] == result['tmdbId'])]
                if not existing.empty:
                    result['already_in_library'] = True
        else:
            series_results = search_tvdb_series(suggested_title)
            # Also check if it exists in our database
            for result in series_results:
                existing = df[(df['type'] == 'series') & (df['tvdb_id'] == result['tvdbId'])]
                if not existing.empty:
                    result['already_in_library'] = True
    
    return jsonify({
        'barcode': barcode,
        'suggested_title': suggested_title,
        'suggested_type': media_type,
        'movie_results': movie_results[:10],  # Limit to 10 results
        'series_results': series_results[:10]
    })

@app.route('/api/search', methods=['POST'])
def search():
    """Manual search for movies or series"""
    data = request.json
    query = data.get('query', '').strip()
    media_type = data.get('type', 'movie')
    
    if not query:
        return jsonify({'error': 'No search query provided'}), 400
    
    if media_type == 'movie':
        results = search_tmdb_movie(query)
    else:
        results = search_tvdb_series(query)
    
    return jsonify({
        'results': results[:10],
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
            new_row = {
                "type": "movie",
                "title": selected_item["title"],
                "year": selected_item.get("year"),
                "tmdb_id": selected_item["tmdbId"],
                "tvdb_id": None,
                "season_count": None,
                "has_physical": True,
                "barcode": barcode,
                "source": "barcode"
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
            new_row = {
                "type": "series",
                "title": selected_item["title"],
                "year": selected_item.get("year"),
                "tmdb_id": None,
                "tvdb_id": selected_item["tvdbId"],
                "season_count": len(selected_item.get("seasons", [])),
                "has_physical": True,
                "barcode": barcode,
                "source": "barcode"
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


# ============ STARTUP =====================

def initialize_app():
    """Initialize the database on startup"""
    df = load_or_create_db()
    df = import_radarr(df)
    df = import_sonarr(df)
    save_db(df)
    print(f"Initialized with {len(df)} items")


if __name__ == "__main__":
    # Initialize database
    print("starting media tracker...")
    initialize_app()

    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)