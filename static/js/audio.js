/**
 * Audio Engine - Handles audio context, playback, and buffering.
 *
 * @module audio
 */

/**
 * Manages audio playback with Web Audio API.
 */
export class AudioEngine {
  /**
   * Create an audio engine.
   * @param {Object} options - Configuration options.
   * @param {number} options.sampleRate - Audio sample rate (default: 44100).
   * @param {number} options.channels - Number of channels (default: 2).
   * @param {Function} options.onVisualizationData - Callback for visualization data.
   */
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 44100;
    this.channels = options.channels || 2;
    this.onVisualizationData = options.onVisualizationData || (() => {});

    this.context = null;
    this.analyser = null;
    this.gainNode = null;
    this.queue = [];
    this.playTime = 0;
    this.isPaused = false;
    this.isMuted = false;
    this.volume = 1.0;
    this.maxBufferSeconds = 5;
    this.isInitialized = false;
    this._animationFrame = null;
    this.lastDataLog = null; // For debugging first data packet
  }

  /**
   * Initialize the audio context and nodes.
   * @returns {boolean} True if initialization succeeded.
   */
  initialize() {
    try {
      // Try to match server sample rate or use default
      const contextSampleRate =
        this.sampleRate === 44100 || this.sampleRate === 48000
          ? this.sampleRate
          : undefined;

      this.context = new AudioContext({
        sampleRate: contextSampleRate,
      });

      console.log(
        `Audio context initialized: SR=${this.context.sampleRate}Hz, ` +
          `Channels=${this.channels}, Configured=${this.sampleRate}Hz`,
      );

      // Create gain node for volume control
      this.gainNode = this.context.createGain();
      this.gainNode.gain.value = this.volume;
      this.gainNode.connect(this.context.destination);

      // Create analyser for visualization
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.connect(this.gainNode);

      this.isInitialized = true;
      this._startPump();

      return true;
    } catch (error) {
      console.error("Failed to initialize audio context:", error);
      return false;
    }
  }

  /**
   * Set playback volume.
   * @param {number} value - Volume from 0.0 to 1.0.
   */
  setVolume(value) {
    this.volume = Math.max(0, Math.min(1, value));
    if (this.gainNode && !this.isMuted) {
      this.gainNode.gain.value = this.volume;
    }
  }

  /**
   * Toggle mute state.
   * @param {boolean} muted - Whether to mute.
   */
  setMuted(muted) {
    this.isMuted = muted;
    if (this.gainNode) {
      this.gainNode.gain.value = muted ? 0 : this.volume;
    }
  }

  /**
   * Pause playback, continue buffering.
   */
  pause() {
    this.isPaused = true;
  }

  /**
   * Resume playback from buffer.
   */
  resume() {
    this.isPaused = false;
  }

  /**
   * Stop playback and reset state.
   */
  stop() {
    this.isPaused = false;
    this.queue = [];
    this.playTime = 0;

    if (this._animationFrame) {
      cancelAnimationFrame(this._animationFrame);
      this._animationFrame = null;
    }

    if (this.context) {
      this.context.close();
      this.context = null;
    }

    this.isInitialized = false;
  }

  /**
   * Process incoming audio data.
   * @param {ArrayBuffer} data - Raw PCM audio data.
   */
  processAudioData(data) {
    if (!this.isInitialized) {
      console.warn("Audio engine not initialized, dropping data");
      return;
    }

    const pcm = new Int16Array(data);
    const frames = pcm.length / this.channels;

    // Log first data packet and occasional statistics
    if (this.queue.length === 0 && !this.lastDataLog) {
      this.lastDataLog = Date.now();
      console.log(
        `First audio data received: ${pcm.length} samples (${frames} frames), ` +
          `${this.channels} channels, ~${((frames * 1000) / this.sampleRate).toFixed(1)}ms`,
      );
    }

    // Buffer management during pause
    if (this.isPaused) {
      const bytesPerSecond = this.sampleRate * this.channels * 2;
      const maxBufferBytes = this.maxBufferSeconds * bytesPerSecond;

      // Calculate current buffer size
      let currentSize = 0;
      for (const item of this.queue) {
        currentSize += item.byteLength;
      }

      // Discard oldest if exceeding limit
      while (
        currentSize + data.byteLength > maxBufferBytes &&
        this.queue.length > 0
      ) {
        const removed = this.queue.shift();
        currentSize -= removed.byteLength;
      }
    }

    this.queue.push(pcm);

    // Prevent massive latency buildup (e.g. tab backgrounding or network bursts)
    // 15 chunks = ~340ms max delay. If it gets higher than this, we force it to skip ahead!
    if (!this.isPaused && this.queue.length > 15) {
      console.warn(
        `Audio buffer overflow (${this.queue.length} chunks), skipping ahead`,
      );
      this.queue = [];
      this.playTime = 0; // Forces instant resync in _pump
    }
  }

  /**
   * Get frequency data for visualization.
   * @returns {Uint8Array|null} Frequency data array.
   */
  getVisualizationData() {
    if (!this.analyser) return null;

    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(data);
    return data;
  }

  /**
   * Start the audio pump loop.
   * @private
   */
  _startPump() {
    const pump = () => {
      if (!this.isInitialized) return;

      this._pump();
      this._animationFrame = requestAnimationFrame(pump);
    };
    pump();
  }

  /**
   * Schedule queued audio for playback.
   * @private
   */
  _pump() {
    if (this.isPaused || !this.context) return;

    while (this.queue.length > 0) {
      const pcm = this.queue.shift();
      const frames = pcm.length / this.channels;
      const buffer = this.context.createBuffer(
        this.channels,
        frames,
        this.sampleRate,
      );

      // Deinterleave stereo PCM
      const left = buffer.getChannelData(0);
      const right = this.channels > 1 ? buffer.getChannelData(1) : null;

      for (let i = 0, j = 0; j < frames; j++) {
        left[j] = pcm[i++] / 32768;
        if (right) {
          right[j] = pcm[i++] / 32768;
        }
      }

      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.analyser);

      if (this.playTime < this.context.currentTime) {
        this.playTime = this.context.currentTime + 0.0001;
      }

      source.start(this.playTime);
      this.playTime += buffer.duration;
    }
  }
}
