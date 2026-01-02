# media_tracker
Track Movies and TV Shows from DVD's
# Media Tracker Installation Guide

## Prerequisites

- Python 3.7+
- Node.js 14+ (for running the React interface locally, optional)
- Radarr and Sonarr installed and running
- Barcode scanner (USB or Bluetooth)

## Installation Steps

### 1. Install Python Dependencies

```bash
pip install flask flask-cors pandas requests
```

### 2. Configure API Keys

Edit the Flask backend (`media_tracker_flask.py`) and update these values:

```python
RADARR_URL = "http://192.168.1.10:7878"  # Your Radarr URL
RADARR_API_KEY = "your_radarr_api_key_here"

SONARR_URL = "http://192.168.1.10:8989"  # Your Sonarr URL
SONARR_API_KEY = "your_sonarr_api_key_here"

MOVIE_ROOT = "/movies"  # Your movie root folder path
TV_ROOT = "/tv"         # Your TV root folder path
```

**To find your API keys:**
- Radarr: Settings → General → Security → API Key
- Sonarr: Settings → General → Security → API Key

### 3. Start the Flask Backend

```bash
python media_tracker_flask.py
```

The server will start on `http://localhost:5000`

### 4. Access the Web Interface

Open your browser and go to:
```
http://localhost:5000
```

Or you can save the React component as an HTML file and open it directly.

## Usage

### Scanning DVDs

1. Focus on the barcode input field (it auto-focuses on page load)
2. Scan the barcode with your barcode scanner
3. Press Enter or click "Scan Barcode"
4. The system will:
   - Lookup the barcode in the UPC database
   - Determine if it's a movie or TV show
   - Search TMDB/TVDB for metadata
   - Add it to Radarr/Sonarr
   - Update the display with counts and last scanned item

### Syncing Libraries

Click the "Sync Libraries" button to import existing movies and TV shows from Radarr and Sonarr into your tracking database.

## Barcode Scanner Setup

Most USB barcode scanners work as keyboard input devices, so no special drivers are needed. The scanner should:

1. Scan the barcode
2. Automatically type the barcode number
3. Send an Enter key (this triggers the scan)

If your scanner doesn't send Enter automatically, just press Enter after scanning.

## File Structure

```
media_tracker/
├── media_tracker_flask.py  # Flask backend
├── media_library.csv       # Database (auto-created)
└── index.html              # React GUI (optional)
```

## Troubleshooting

### "Failed to connect to server"
- Make sure Flask is running on port 5000
- Check firewall settings
- Try accessing `http://localhost:5000/api/stats` directly

### "Barcode not found"
- The UPC database may not have that barcode
- Try searching manually in Radarr/Sonarr
- Some older DVDs may not be in the database

### "Movie/Series not found"
- The title from the barcode may not match TMDB/TVDB exactly
- You may need to add it manually in Radarr/Sonarr

### CORS Errors
- Make sure `flask-cors` is installed: `pip install flask-cors`
- The Flask app should have `CORS(app)` enabled

## Advanced Configuration

### Custom Port

To run on a different port:

```python
app.run(host='0.0.0.0', port=8080, debug=True)
```

Then update the React component's `API_URL`:

```javascript
const API_URL = 'http://localhost:8080/api';
```

### Remote Access

To access from other devices on your network:

1. Run Flask with `host='0.0.0.0'` (already set)
2. Find your computer's IP address
3. Access via `http://YOUR_IP:5000`
4. Update `API_URL` in React to use your IP

### Production Deployment

For production use:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 media_tracker_flask:app
```

## API Endpoints

- `GET /api/stats` - Get current counts
- `GET /api/media` - Get all media items
- `POST /api/scan` - Scan a barcode
- `POST /api/sync` - Sync with Radarr/Sonarr

## Support

If you encounter issues:
1. Check the Flask console for error messages
2. Check browser console (F12) for frontend errors
3. Verify Radarr/Sonarr are accessible
4. Test API endpoints directly with curl or Postman