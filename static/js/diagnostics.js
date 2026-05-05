/**
 * Diagnostic helper for debugging audio issues
 */

export class AudioDiagnostics {
  /**
   * Check audio context and browser capabilities
   */
  static checkAudioSupport() {
    const errors = [];
    const warnings = [];

    // Check AudioContext support
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) {
      errors.push("AudioContext not supported in this browser");
      return { errors, warnings, supported: false };
    }

    // Try to create context
    try {
      const ctx = new AudioContext();
      const info = {
        state: ctx.state,
        sampleRate: ctx.sampleRate,
        outputChannels: ctx.destination.maxChannelCount,
        resume: typeof ctx.resume === "function",
      };

      console.log("AudioContext Info:", info);

      // Check if context needs resuming
      if (ctx.state === "suspended") {
        warnings.push("AudioContext is suspended - user interaction required");
      }

      // Check for unusual sample rates
      if (ctx.sampleRate < 44100 || ctx.sampleRate > 96000) {
        warnings.push(`Unusual sample rate: ${ctx.sampleRate}Hz`);
      }

      ctx.close();
      return { errors, warnings, supported: true, sampleRate: ctx.sampleRate };
    } catch (e) {
      errors.push(`Failed to create AudioContext: ${e.message}`);
      return { errors, warnings, supported: false };
    }
  }

  /**
   * Log connection and data diagnostics
   */
  static logStreamInfo(config, connectionStatus, bufferedFrames) {
    const log = {
      timestamp: new Date().toISOString(),
      config: {
        sample_rate: config.sample_rate,
        channels: config.channels,
        host: config.host,
        ws_port: config.ws_port,
      },
      connection: connectionStatus,
      buffer: bufferedFrames,
      audio: this.checkAudioSupport(),
    };

    console.log("=== AUDIO STREAM DIAGNOSTICS ===");
    console.table(log);

    return log;
  }
}
