"""
HTTP server module for the Audio Streamer.

Serves the client UI and status endpoints.
"""

import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, send_from_directory, jsonify, Response

from .config import ServerConfig
from .connection_manager import ConnectionManager


# Server start time for uptime calculation
_start_time: Optional[datetime] = None

# Get the project root directory (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def get_local_ip() -> str:
    """
    Get the local IP address of this machine.
    
    Returns:
        Local IP address string.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def create_app(
    connection_manager: ConnectionManager,
    config: ServerConfig,
    audio_device_info: Optional[dict] = None
) -> Flask:
    """
    Create Flask app with routes.
    
    Args:
        connection_manager: Connection manager instance.
        config: Server configuration.
        audio_device_info: Optional audio device information.
        
    Returns:
        Configured Flask application.
    """
    global _start_time
    _start_time = datetime.now()
    
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        """Serve the client HTML page."""
        return send_from_directory(PROJECT_ROOT, 'client.html')
    
    @app.route('/dashboard')
    def dashboard():
        """Serve the server dashboard."""
        return send_from_directory(PROJECT_ROOT, 'dashboard.html')
    
    @app.route('/mobile')
    def mobile_server():
        """Serve the mobile audio server interface."""
        return send_from_directory(PROJECT_ROOT, 'mobile-server.html')
    
    @app.route('/unified')
    def unified():
        """Serve the unified player/broadcaster interface."""
        return send_from_directory(PROJECT_ROOT, 'unified.html')
    
    @app.route('/static/js/<path:filename>')
    def serve_js(filename):
        """Serve JavaScript files."""
        return send_from_directory(PROJECT_ROOT / 'static' / 'js', filename)
    
    @app.route('/static/<path:filename>')
    def serve_static(filename):
        """Serve static files."""
        return send_from_directory(PROJECT_ROOT / 'static', filename)
    
    @app.route('/status')
    def status():
        """Return JSON with server health metrics."""
        uptime = (datetime.now() - _start_time).total_seconds() if _start_time else 0
        client_stats = connection_manager.get_stats()
        
        return jsonify({
            "status": "running",
            "uptime_seconds": int(uptime),
            "clients": {
                "connected": client_stats["connected"],
                "total_served": client_stats["total_served"]
            },
            "audio": audio_device_info or {
                "device": "Unknown",
                "sample_rate": config.sample_rate,
                "channels": config.channels
            },
            "server": {
                "http_port": config.http_port,
                "ws_port": config.ws_port
            }
        })
    
    @app.route('/api/status')
    def api_status():
        """Return server status for dashboard."""
        uptime = (datetime.now() - _start_time).total_seconds() if _start_time else 0
        client_stats = connection_manager.get_stats()
        device_info = audio_device_info or {}
        
        return jsonify({
            "status": "running",
            "uptime": int(uptime),
            "client_count": client_stats.get("connected", 0),
            "sample_rate": device_info.get('sample_rate', config.sample_rate),
            "channels": device_info.get('channels', config.channels),
            "server_info": {
                "IP Address": get_local_ip(),
                "HTTP Port": config.http_port,
                "WebSocket Port": config.ws_port,
                "Start Time": _start_time.isoformat() if _start_time else "Unknown",
                "Uptime": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s"
            },
            "clients": [f"client_{i}" for i in range(client_stats.get("connected", 0))]
        })
    
    @app.route('/api/config')
    def api_config():
        """Return configuration."""
        device_info = audio_device_info or {}
        actual_sample_rate = device_info.get('sample_rate', config.sample_rate)
        return jsonify({
            "ws_port": config.ws_port,
            "http_port": config.http_port,
            "sample_rate": actual_sample_rate,
            "channels": config.channels,
            "host": get_local_ip(),
            "timestamp": datetime.now().isoformat()
        })
    
    @app.route('/config')
    def get_config():
        """Return client-relevant configuration."""
        device_info = audio_device_info or {}
        actual_sample_rate = device_info.get('sample_rate', config.sample_rate)
        return jsonify({
            "ws_port": config.ws_port,
            "sample_rate": actual_sample_rate,
            "channels": config.channels,
            "host": get_local_ip()
        })
    
    @app.route('/api/restart-audio', methods=['POST'])
    def restart_audio():
        """Restart audio capture (placeholder)."""
        try:
            # This would require integration with the audio capture manager
            # For now, just return success
            return jsonify({"success": True, "message": "Audio restart initiated"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route('/favicon.ico')
    def favicon():
        """Return a simple favicon to avoid 404 errors."""
        # Single-pixel transparent PNG
        png_data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return Response(png_data, mimetype='image/png')
    
    return app
