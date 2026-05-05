"""
Audio capture module for the Audio Streamer server.

Handles device discovery and audio capture via WASAPI loopback.
"""

import logging
import time
from typing import Optional, List, Tuple
import pyaudiowpatch as pa

from .config import ServerConfig

class AudioCapture:
    """Encapsulates audio device discovery and capture logic."""
    
    def __init__(self, config: ServerConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.p_audio = pa.PyAudio()
        self.stream = None
        self.is_running: bool = False
        self.device_name: str = "Unknown"
        self.target_device_info = None
        self.consecutive_errors = 0
        self.last_reinit_attempt = 0
        self.reinit_backoff = 1  # seconds, will exponentially increase
    
    def initialize(self) -> bool:
        """Discover and initialize audio capture device."""
        try:
            wasapi_info = self.p_audio.get_host_api_info_by_type(pa.paWASAPI)
            default_speakers = self.p_audio.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            # Find loopback variant of the output device
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.p_audio.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break
                        
            self.target_device_info = default_speakers
            self.device_name = default_speakers["name"]
            self.logger.info(f"WASAPI loopback success on device: {self.device_name}")
            
            # Try to open stream with configured sample rate, fall back to other rates if needed
            sample_rates_to_try = [
                self.config.sample_rate,
                48000,
                44100,
                22050,
                int(default_speakers.get("defaultSampleRate", 44100))
            ]
            
            # Remove duplicates while preserving order
            sample_rates_to_try = list(dict.fromkeys(sample_rates_to_try))
            
            stream = None
            actual_sample_rate = None
            
            for sample_rate in sample_rates_to_try:
                try:
                    stream = self.p_audio.open(
                        format=pa.paInt16,
                        channels=self.config.channels,
                        rate=sample_rate,
                        input=True,
                        input_device_index=default_speakers["index"],
                        frames_per_buffer=self.config.block_size
                    )
                    actual_sample_rate = sample_rate
                    if sample_rate != self.config.sample_rate:
                        self.logger.warning(
                            f"Configured sample rate {self.config.sample_rate} Hz not supported. "
                            f"Using {sample_rate} Hz instead."
                        )
                    else:
                        self.logger.info(f"Using configured sample rate: {sample_rate} Hz")
                    break
                except Exception as e:
                    self.logger.debug(f"Sample rate {sample_rate} Hz failed: {e}")
                    continue
            
            if stream is None:
                self.logger.error("Could not open stream with any supported sample rate")
                return False
            
            self.stream = stream
            self.config.sample_rate = actual_sample_rate
            self.is_running = True
            self.logger.info(f"Audio stream initialized: {actual_sample_rate}Hz, {self.config.channels}ch, {self.config.block_size} frame buffer")
            return True
            
        except Exception as e:
            self.logger.error(
                "No audio source found or WASAPI failure. "
                "Ensure default speakers are enabled."
            )
            self.logger.error(f"Details: {e}")
            return False
    
    def read_block(self) -> Optional[bytes]:
        """Read a block of audio data. Handles stream recovery on closure."""
        if not self.stream or not self.is_running:
            if self.consecutive_errors == 0:
                self.logger.warning("Audio stream not available")
            return None
        
        try:
            data = self.stream.read(self.config.block_size, exception_on_overflow=False)
            # Reset error counter on successful read
            self.consecutive_errors = 0
            return data
        except Exception as e:
            error_msg = str(e)
            self.consecutive_errors += 1
            
            # Stream closed error (-9988) or other critical errors
            if "-9988" in error_msg or "closed" in error_msg.lower():
                self.logger.error(f"Audio stream closed (error #{self.consecutive_errors}): {e}")
                
                # Try to reinitialize with backoff
                current_time = time.time()
                if current_time - self.last_reinit_attempt >= self.reinit_backoff:
                    self.logger.warning(
                        f"Attempting stream recovery (backoff: {self.reinit_backoff}s)"
                    )
                    self.last_reinit_attempt = current_time
                    
                    if self.reinitialize():
                        self.logger.info("Stream recovery successful")
                        self.reinit_backoff = 1  # Reset backoff
                        self.consecutive_errors = 0
                        return None  # Don't return data on first recovery attempt
                    else:
                        # Increase backoff exponentially (max 30 seconds)
                        self.reinit_backoff = min(self.reinit_backoff * 2, 30)
                        self.logger.warning(
                            f"Stream recovery failed. Next retry in {self.reinit_backoff}s"
                        )
                return None
            else:
                # Other transient errors - just log and continue
                if self.consecutive_errors <= 3:  # Only log first 3 to avoid spam
                    self.logger.debug(f"Transient audio error: {e}")
                return None
    
    def stop(self) -> None:
        """Stop capture and release device."""
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                self.logger.warning(f"Error stopping audio stream: {e}")
            finally:
                self.stream = None
                self.is_running = False
                
        # Terminate PyAudio instance
        try:
            self.p_audio.terminate()
        except:
            pass
            
        self.logger.info("Audio capture stopped")
    
    def reinitialize(self) -> bool:
        """Attempt to reinitialize after device error."""
        self.logger.info("Attempting to reinitialize audio capture")
        self.stop()
        self.p_audio = pa.PyAudio() # Recreate PyAudio
        return self.initialize()
    
    def get_device_info(self) -> dict:
        """Get information about the current audio device."""
        return {
            "device": self.device_name,
            "sample_rate": self.config.sample_rate,
            "channels": self.config.channels,
            "is_running": self.is_running
        }
