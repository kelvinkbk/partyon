"""
WebSocket server module for the Audio Streamer.

Handles WebSocket connections and audio broadcasting.
"""

import asyncio
import json
import logging
from typing import Optional, Set

import websockets

from .config import ServerConfig
from .audio_capture import AudioCapture
from .connection_manager import ConnectionManager


class AudioWebSocketServer:
    """Handles WebSocket connections and audio broadcasting."""
    
    def __init__(
        self,
        config: ServerConfig,
        audio_capture: AudioCapture,
        connection_manager: ConnectionManager,
        logger: logging.Logger
    ):
        """
        Initialize the WebSocket server.
        
        Args:
            config: Server configuration.
            audio_capture: Audio capture module.
            connection_manager: Connection manager.
            logger: Logger instance.
        """
        self.config = config
        self.audio_capture = audio_capture
        self.connection_manager = connection_manager
        self.logger = logger
        self.server: Optional[websockets.WebSocketServer] = None
        self.is_running: bool = False
        self._broadcast_task: Optional[asyncio.Task] = None
        self.broadcasters: Set[str] = set()  # Track active broadcasters
        self.broadcaster_clients: Set[websockets.WebSocketServerProtocol] = set()  # Broadcaster WebSocket connections
    
    async def handler(self, websocket: websockets.WebSocketServerProtocol) -> None:
        """
        Handle individual WebSocket connection.
        
        Args:
            websocket: The WebSocket connection.
        """
        client_id = self.connection_manager.add_client(websocket)
        broadcaster_id = None
        
        try:
            async for message in websocket:
                # Handle both text (JSON) and binary (audio) messages
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        cmd_type = data.get('type')
                        
                        if cmd_type == 'start_broadcast':
                            broadcaster_id = client_id
                            self.broadcasters.add(broadcaster_id)
                            self.broadcaster_clients.add(websocket)
                            self.logger.info(f"Broadcaster {broadcaster_id} started: {data.get('name')}")
                            
                            # Notify all listeners about new broadcaster
                            await self.notify_listeners({
                                'type': 'broadcaster_update',
                                'id': broadcaster_id,
                                'name': data.get('name', 'Unknown Device'),
                                'duration': '00:00'
                            })
                        
                        elif cmd_type == 'stop_broadcast':
                            if broadcaster_id:
                                self.broadcasters.discard(broadcaster_id)
                                self.broadcaster_clients.discard(websocket)
                                self.logger.info(f"Broadcaster {broadcaster_id} stopped")
                    
                    except json.JSONDecodeError:
                        self.logger.warning(f"Invalid JSON from {client_id}")
                
                else:
                    # Binary audio data - broadcast to all non-broadcaster clients
                    await self.broadcast_audio(message, exclude_websocket=websocket)
        
        except websockets.exceptions.ConnectionClosed:
            self.logger.debug(f"Client {client_id} disconnected")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.debug(f"Client handler error for {client_id}: {e}")
        finally:
            if broadcaster_id:
                self.broadcasters.discard(broadcaster_id)
                self.broadcaster_clients.discard(websocket)
            self.connection_manager.remove_client(client_id)
    
    async def notify_listeners(self, data: dict) -> None:
        """Notify all non-broadcaster clients about broadcaster updates."""
        message = json.dumps(data)
        disconnected = set()
        
        for client in self.connection_manager.clients:
            if client not in self.broadcaster_clients:
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
        
        # Clean up disconnected clients
        for client in disconnected:
            self.connection_manager.remove_client(None)
    
    async def broadcast_audio(self, audio_data: bytes, exclude_websocket=None) -> None:
        """Broadcast audio data to all non-broadcaster listening clients."""
        disconnected = set()
        
        for client in self.connection_manager.clients:
            # Send to all listeners (non-broadcasters)
            if client not in self.broadcaster_clients and client != exclude_websocket:
                try:
                    await client.send(audio_data)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
    
    async def broadcast_loop(self) -> None:
        """Main loop for capturing and broadcasting audio."""
        self.logger.info("Starting audio broadcast loop")
        blocks_sent = 0
        silence_count = 0
        
        while self.is_running:
            data = self.audio_capture.read_block()
            
            if data:
                await self.connection_manager.broadcast(data)
                blocks_sent += 1
                silence_count = 0
                
                # Log stats on first block and then every 50 blocks
                if blocks_sent == 1:
                    self.logger.info(
                        f"Audio streaming started: block size={len(data)} bytes, "
                        f"clients={len(self.connection_manager.clients)}"
                    )
                elif blocks_sent % 50 == 0:
                    self.logger.debug(
                        f"Audio blocks sent: {blocks_sent}, "
                        f"clients: {len(self.connection_manager.clients)}"
                    )
            else:
                silence_count += 1
                if silence_count > 100:  # Log after ~2 seconds of silence
                    self.logger.warning(
                        f"No audio data received (attempt {silence_count})"
                    )
                    silence_count = 0
            
            # Let event loop breathe
            await asyncio.sleep(0)
    
    async def start(self, host: str = "0.0.0.0") -> None:
        """
        Start the WebSocket server.
        
        Args:
            host: Host address to bind to.
        """
        self.is_running = True
        
        self.server = await websockets.serve(
            self.handler,
            host,
            self.config.ws_port,
            max_size=None
        )
        
        self.logger.info(f"WebSocket server started on ws://{host}:{self.config.ws_port}")
        
        # Start broadcast loop
        self._broadcast_task = asyncio.create_task(self.broadcast_loop())
    
    async def stop(self) -> None:
        """Stop the server gracefully."""
        self.logger.info("Stopping WebSocket server")
        self.is_running = False
        
        # Cancel broadcast task
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        
        # Close all client connections
        await self.connection_manager.close_all()
        
        # Close server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        self.logger.info("WebSocket server stopped")
