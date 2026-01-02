import React, { useState, useEffect } from 'react';
import { Film, Tv, Disc, Search, AlertCircle, RefreshCw } from 'lucide-react';

const API_URL = 'http://localhost:5000/api';

const MediaTrackerGUI = () => {
  const [stats, setStats] = useState({
    movies: 0,
    series: 0,
    dvds: 0
  });
  
  const [barcode, setBarcode] = useState('');
  const [lastScanned, setLastScanned] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  // Load stats on mount and set up auto-refresh
  useEffect(() => {
    loadStats();
    const interval = setInterval(loadStats, 5000); // Refresh every 5 seconds
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

  const handleScan = async () => {
    if (!barcode.trim()) return;

    setScanning(true);
    setError('');

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
        return;
      }

      // Update stats
      await loadStats();
      
      // Show last scanned item
      setLastScanned({
        title: data.item.title,
        type: data.item.type,
        year: data.item.year,
        timestamp: new Date().toLocaleTimeString()
      });

      setBarcode('');
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

        {/* Last Scanned */}
        {lastScanned && (
          <div className="bg-gradient-to-r from-purple-500/20 to-blue-500/20 backdrop-blur-lg rounded-2xl p-6 border border-white/20 shadow-xl">
            <h3 className="text-lg font-semibold text-purple-300 mb-2">✓ Last Scanned</h3>
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