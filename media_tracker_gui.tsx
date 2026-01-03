import React, { useState, useEffect } from 'react';
import { Film, Tv, Disc, Search, AlertCircle, RefreshCw, X } from 'lucide-react';

const API_URL = 'http://localhost:5000/api';

const MediaTrackerGUI = () => {
  const [stats, setStats] = useState({
    movies: 0,
    series: 0,
    dvds: 0
  });
  
  const [genreStats, setGenreStats] = useState({
    movies: {},
    series: {},
    all: {}
  });
  
  const [barcode, setBarcode] = useState('');
  const [lastScanned, setLastScanned] = useState(null);
  const [scanDetails, setScanDetails] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  // Load stats on mount and set up auto-refresh
  useEffect(() => {
    loadStats();
    loadGenreStats();
    const interval = setInterval(() => {
      loadStats();
      loadGenreStats();
    }, 5000); // Refresh every 5 seconds
    return () => clearInterval(interval);
  }, []);

  const loadStats = async () => {
    try {
      const response = await fetch(`${API_URL}/stats`);
      if (!response.ok) throw new Error('Failed to load stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Error loading stats:', err);
    }
  };

  const loadGenreStats = async () => {
    try {
      const response = await fetch(`${API_URL}/genre-stats`);
      if (!response.ok) throw new Error('Failed to load genre stats');
      const data = await response.json();
      setGenreStats(data);
    } catch (err) {
      console.error('Error loading genre stats:', err);
    }
  };

  const handleScan = async () => {
    if (!barcode.trim()) return;

    setScanning(true);
    setError('');
    setScanDetails(null); // Clear previous scan details

    try {
      const response = await fetch(`${API_URL}/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ barcode: barcode.trim() }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.error || 'Failed to scan barcode');
        setScanDetails({
          barcode: barcode.trim(),
          error: data.error || 'Failed to scan barcode',
          steps: data.steps || [],
          timestamp: new Date().toLocaleTimeString()
        });
        setScanning(false);
        return;
      }

      // Store scan details with all steps
      setScanDetails({
        barcode: data.barcode,
        steps: data.steps || [],
        success: data.success,
        item: data.item,
        suggested_title: data.suggested_title,
        base_title: data.base_title,
        suggested_type: data.suggested_type,
        local_results: data.local_results || [],
        found_in_local: data.found_in_local,
        found_by_barcode: data.found_by_barcode,
        toggled: data.toggled,
        updated: data.updated,
        timestamp: new Date().toLocaleTimeString()
      });

      // Update stats
      await loadStats();
      
      // Show last scanned item if successful
      if (data.success && data.item) {
        setLastScanned({
          title: data.item.title,
          type: data.item.type,
          year: data.item.year,
          timestamp: new Date().toLocaleTimeString(),
          toggled: data.toggled || false,
          updated: data.updated || false
        });
      }

      setBarcode('');
      
      // Reload genre stats
      await loadGenreStats();
    } catch (err) {
      setError('Failed to connect to server. Make sure the Flask backend is running.');
      console.error('Scan error:', err);
    } finally {
      setScanning(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError('');

    try {
      const response = await fetch(`${API_URL}/sync`, {
        method: 'POST',
      });

      if (!response.ok) throw new Error('Sync failed');

      await loadStats();
      setError('');
    } catch (err) {
      setError('Failed to sync with Radarr/Sonarr');
      console.error('Sync error:', err);
    } finally {
      setSyncing(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleScan();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">Media Tracker</h1>
          <p className="text-purple-300">Track your DVD collection</p>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="mt-4 px-4 py-2 bg-purple-600/50 hover:bg-purple-600 text-white rounded-lg transition-colors duration-200 flex items-center gap-2 mx-auto"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing...' : 'Sync Libraries'}
          </button>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          {/* Movies Card */}
          <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl transform hover:scale-105 transition-transform duration-200">
            <div className="flex items-center justify-between mb-4">
              <Film className="w-12 h-12 text-blue-400" />
              <span className="text-5xl font-bold text-white">{stats.movies}</span>
            </div>
            <h3 className="text-xl font-semibold text-white">Movies</h3>
            <p className="text-purple-300 text-sm">Total in library</p>
          </div>

          {/* TV Shows Card */}
          <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl transform hover:scale-105 transition-transform duration-200">
            <div className="flex items-center justify-between mb-4">
              <Tv className="w-12 h-12 text-green-400" />
              <span className="text-5xl font-bold text-white">{stats.series}</span>
            </div>
            <h3 className="text-xl font-semibold text-white">TV Shows</h3>
            <p className="text-purple-300 text-sm">Total in library</p>
          </div>

          {/* DVDs Card */}
          <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl transform hover:scale-105 transition-transform duration-200">
            <div className="flex items-center justify-between mb-4">
              <Disc className="w-12 h-12 text-purple-400" />
              <span className="text-5xl font-bold text-white">{stats.dvds}</span>
            </div>
            <h3 className="text-xl font-semibold text-white">Physical DVDs</h3>
            <p className="text-purple-300 text-sm">Scanned copies</p>
          </div>
        </div>

        {/* Scanner Section */}
        <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20 shadow-xl mb-8">
          <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
            <Search className="w-6 h-6" />
            Scan New DVD
          </h2>
          
          <div className="space-y-4">
            <div>
              <input
                type="text"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Enter or scan barcode..."
                className="w-full px-4 py-3 bg-white/5 border border-white/20 rounded-lg text-white placeholder-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500"
                disabled={scanning}
                autoFocus
              />
            </div>
            
            <button
              onClick={handleScan}
              disabled={scanning || !barcode.trim()}
              className="w-full bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-3 px-6 rounded-lg transition-colors duration-200"
            >
              {scanning ? 'Scanning...' : 'Scan Barcode'}
            </button>
          </div>

          {error && (
            <div className="mt-4 p-4 bg-red-500/20 border border-red-500/50 rounded-lg flex items-center gap-2 text-red-200">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Scan Details */}
        {scanDetails && (
          <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20 shadow-xl mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-2xl font-bold text-white">Last Scan Details</h2>
              <button
                onClick={() => setScanDetails(null)}
                className="text-white hover:text-red-400 transition-colors"
                title="Clear scan details"
              >
                <X className="w-6 h-6" />
              </button>
            </div>
            
            <div className="space-y-4">
              {/* Barcode Info */}
              <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-lg font-semibold text-white">Barcode Scanned</h3>
                  <span className="text-purple-300 text-sm">{scanDetails.timestamp}</span>
                </div>
                <p className="text-2xl font-mono text-purple-300">{scanDetails.barcode}</p>
              </div>

              {/* Steps */}
              {scanDetails.steps && scanDetails.steps.length > 0 && (
                <div className="bg-white/5 rounded-lg p-4 border border-white/10">
                  <h3 className="text-lg font-semibold text-white mb-3">Scan Steps</h3>
                  <div className="space-y-2">
                    {scanDetails.steps.map((step, idx) => {
                      const getStatusColor = (status) => {
                        switch(status) {
                          case 'found':
                          case 'completed':
                            return 'text-green-400';
                          case 'not_found':
                            return 'text-yellow-400';
                          case 'checking':
                          case 'searching':
                            return 'text-blue-400';
                          default:
                            return 'text-purple-300';
                        }
                      };

                      const getStatusIcon = (status) => {
                        switch(status) {
                          case 'found':
                          case 'completed':
                            return '✓';
                          case 'not_found':
                            return '✗';
                          case 'checking':
                          case 'searching':
                            return '⟳';
                          default:
                            return '•';
                        }
                      };

                      return (
                        <div key={idx} className="flex items-start gap-3 p-2 bg-white/5 rounded">
                          <span className={`font-bold ${getStatusColor(step.status)}`}>
                            {getStatusIcon(step.status)}
                          </span>
                          <div className="flex-1">
                            <p className="text-white font-medium">{step.action}</p>
                            {step.details && (
                              <p className="text-purple-300 text-sm mt-1">{step.details}</p>
                            )}
                            {step.action_taken && (
                              <p className="text-green-300 text-sm mt-1 font-semibold">{step.action_taken}</p>
                            )}
                            {step.matches && step.matches.length > 0 && (
                              <div className="mt-2 space-y-1">
                                {step.matches.map((match, mIdx) => (
                                  <div key={mIdx} className="text-xs text-purple-200 bg-white/5 p-2 rounded">
                                    {match.title} ({match.year}) - {match.similarity}% match
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Lookup Results */}
              {scanDetails.suggested_title && (
                <div className="bg-blue-500/10 rounded-lg p-4 border border-blue-500/20">
                  <h3 className="text-lg font-semibold text-white mb-2">Barcode Lookup Result</h3>
                  <p className="text-white text-lg">{scanDetails.suggested_title}</p>
                  {scanDetails.base_title && scanDetails.base_title !== scanDetails.suggested_title && (
                    <p className="text-blue-300 text-sm mt-1">Extracted: {scanDetails.base_title}</p>
                  )}
                  {scanDetails.suggested_type && (
                    <p className="text-blue-300 text-sm mt-1">Type: {scanDetails.suggested_type}</p>
                  )}
                </div>
              )}

              {/* Local Search Results */}
              {scanDetails.local_results && scanDetails.local_results.length > 0 && (
                <div className="bg-green-500/10 rounded-lg p-4 border border-green-500/20">
                  <h3 className="text-lg font-semibold text-white mb-2">
                    Local Database Matches ({scanDetails.local_results.length})
                  </h3>
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {scanDetails.local_results.map((result, idx) => (
                      <div key={idx} className="bg-white/5 rounded p-3">
                        <div className="flex items-start justify-between">
                          <div>
                            <p className="text-white font-semibold">{result.title}</p>
                            <p className="text-green-300 text-sm">
                              {result.type} • {result.year} • {result.similarity?.toFixed(0) || 0}% match
                            </p>
                          </div>
                          {result.has_physical && (
                            <span className="px-2 py-1 bg-green-500/20 border border-green-500/50 text-green-300 text-xs rounded">
                              Physical
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Final Result */}
              {scanDetails.item && (
                <div className="bg-gradient-to-r from-purple-500/20 to-blue-500/20 rounded-lg p-4 border border-purple-500/30">
                  <h3 className="text-lg font-semibold text-white mb-2">
                    {scanDetails.toggled ? '✓ Toggled Physical Copy' : scanDetails.updated ? '✓ Updated Entry' : '✓ Result'}
                  </h3>
                  <p className="text-2xl font-bold text-white">{scanDetails.item.title}</p>
                  <p className="text-purple-300 text-sm mt-1">
                    {scanDetails.item.type === 'movie' ? 'Movie' : 'TV Show'} • {scanDetails.item.year}
                    {scanDetails.item.has_physical && ' • Has Physical Copy'}
                  </p>
                </div>
              )}

              {/* Not Found Message */}
              {!scanDetails.success && !scanDetails.error && (
                <div className="bg-yellow-500/10 rounded-lg p-4 border border-yellow-500/20">
                  <p className="text-yellow-300">
                    {scanDetails.message || 'Item not found in local database. Use /api/lookup for external search.'}
                  </p>
                </div>
              )}

              {/* Error Message */}
              {scanDetails.error && (
                <div className="bg-red-500/10 rounded-lg p-4 border border-red-500/20">
                  <p className="text-red-300">{scanDetails.error}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Genre Statistics */}
        <div className="bg-white/10 backdrop-blur-lg rounded-2xl p-8 border border-white/20 shadow-xl mb-8">
          <h2 className="text-2xl font-bold text-white mb-4">Collection by Genre</h2>
          
          {Object.keys(genreStats.all).length === 0 ? (
            <p className="text-purple-300 text-center py-4">No genre data available. Sync libraries to collect genre information.</p>
          ) : (
            <div className="space-y-6">
              {/* Top Genres Overall */}
              <div>
                <h3 className="text-lg font-semibold text-white mb-3">Top Genres (All)</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {Object.entries(genreStats.all)
                    .sort(([, a], [, b]) => (b as number) - (a as number))
                    .slice(0, 12)
                    .map(([genre, count]) => (
                      <div key={genre} className="bg-white/5 rounded-lg p-3 border border-white/10">
                        <p className="text-white font-semibold text-sm">{genre}</p>
                        <p className="text-purple-300 text-xl font-bold">{count}</p>
                      </div>
                    ))}
                </div>
              </div>

              {/* Movie Genres */}
              {Object.keys(genreStats.movies).length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">Movie Genres</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    {Object.entries(genreStats.movies)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .slice(0, 12)
                      .map(([genre, count]) => (
                        <div key={genre} className="bg-blue-500/10 rounded-lg p-3 border border-blue-500/20">
                          <p className="text-white font-semibold text-sm">{genre}</p>
                          <p className="text-blue-300 text-xl font-bold">{count}</p>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* TV Show Genres */}
              {Object.keys(genreStats.series).length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">TV Show Genres</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    {Object.entries(genreStats.series)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .slice(0, 12)
                      .map(([genre, count]) => (
                        <div key={genre} className="bg-green-500/10 rounded-lg p-3 border border-green-500/20">
                          <p className="text-white font-semibold text-sm">{genre}</p>
                          <p className="text-green-300 text-xl font-bold">{count}</p>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Last Scanned */}
        {lastScanned && (
          <div className="bg-gradient-to-r from-purple-500/20 to-blue-500/20 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
            <h3 className="text-lg font-semibold text-purple-300 mb-2">
              {lastScanned.toggled ? '✓ Toggled Physical Copy' : lastScanned.updated ? '✓ Updated' : '✓ Last Scanned'}
            </h3>
            <p className="text-2xl font-bold text-white mb-1">{lastScanned.title}</p>
            <p className="text-sm text-purple-300">
              {lastScanned.type === 'movie' ? 'Movie' : 'TV Show'} • {lastScanned.year} • {lastScanned.timestamp}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default MediaTrackerGUI;