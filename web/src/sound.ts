// Synthesized sound design (WebAudio, no assets): sonar ping, converge rumble, shatter.
// The AudioContext starts on the first user gesture (autoplay policy). `S` toggles mute.

const KEY = "traceless.muted";

class Sound {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  muted = localStorage.getItem(KEY) === "1";
  private listeners = new Set<(m: boolean) => void>();

  /** Call from a user gesture handler. Safe to call repeatedly. */
  unlock() {
    if (this.ctx) {
      if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
      return;
    }
    try {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.muted ? 0 : 0.6;
      this.master.connect(this.ctx.destination);
    } catch {
      this.ctx = null;
    }
  }

  toggle(): boolean {
    this.muted = !this.muted;
    localStorage.setItem(KEY, this.muted ? "1" : "0");
    if (this.master && this.ctx) this.master.gain.setTargetAtTime(this.muted ? 0 : 0.6, this.ctx.currentTime, 0.05);
    this.listeners.forEach((f) => f(this.muted));
    return this.muted;
  }

  onChange(f: (m: boolean) => void) {
    this.listeners.add(f);
    return () => this.listeners.delete(f);
  }

  private ready(): { ctx: AudioContext; out: GainNode } | null {
    if (!this.ctx || !this.master || this.muted || this.ctx.state !== "running") return null;
    return { ctx: this.ctx, out: this.master };
  }

  /** Sonar ping: sine blip with a quick pitch drop and a soft echo. */
  ping(pitch = 1) {
    const r = this.ready();
    if (!r) return;
    const { ctx, out } = r;
    const t = ctx.currentTime;
    for (const [delay, level] of [[0, 0.35], [0.22, 0.12]] as const) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(1350 * pitch, t + delay);
      o.frequency.exponentialRampToValueAtTime(880 * pitch, t + delay + 0.5);
      g.gain.setValueAtTime(0.0001, t + delay);
      g.gain.exponentialRampToValueAtTime(level, t + delay + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + delay + 0.9);
      o.connect(g).connect(out);
      o.start(t + delay);
      o.stop(t + delay + 1);
    }
  }

  /** Low rumble that swells while the globe converges. */
  rumble(seconds: number) {
    const r = this.ready();
    if (!r) return;
    const { ctx, out } = r;
    const t = ctx.currentTime;
    const dur = Math.max(1, Math.min(12, seconds));
    const o1 = ctx.createOscillator();
    const o2 = ctx.createOscillator();
    o1.type = "sawtooth";
    o2.type = "sine";
    o1.frequency.setValueAtTime(42, t);
    o1.frequency.linearRampToValueAtTime(58, t + dur);
    o2.frequency.setValueAtTime(55, t);
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(120, t);
    lp.frequency.linearRampToValueAtTime(260, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.25, t + dur * 0.8);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.8);
    o1.connect(lp);
    o2.connect(lp);
    lp.connect(g).connect(out);
    o1.start(t);
    o2.start(t);
    o1.stop(t + dur + 1);
    o2.stop(t + dur + 1);
  }

  /** Glassy shatter: filtered noise burst with a falling band-pass sweep + tinkles. */
  shatter() {
    const r = this.ready();
    if (!r) return;
    const { ctx, out } = r;
    const t = ctx.currentTime;
    const len = Math.floor(ctx.sampleRate * 1.4);
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.5);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.Q.value = 2.5;
    bp.frequency.setValueAtTime(6000, t);
    bp.frequency.exponentialRampToValueAtTime(700, t + 1.2);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.7, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.4);
    src.connect(bp).connect(g).connect(out);
    src.start(t);
    for (let k = 0; k < 7; k++) {
      const o = ctx.createOscillator();
      const og = ctx.createGain();
      const s = t + 0.05 + Math.random() * 0.7;
      o.type = "triangle";
      o.frequency.value = 2500 + Math.random() * 3500;
      og.gain.setValueAtTime(0.0001, s);
      og.gain.exponentialRampToValueAtTime(0.08, s + 0.005);
      og.gain.exponentialRampToValueAtTime(0.0001, s + 0.25);
      o.connect(og).connect(out);
      o.start(s);
      o.stop(s + 0.3);
    }
  }
}

export const sound = new Sound();
