/** Final-pass feature flags (DECISIONS D27). Override per load: ?flags=-plain,-tap,-split */
const DEFAULTS = { plain: true, tap: true, split: true };

function parse(): typeof DEFAULTS {
  const f = { ...DEFAULTS };
  const q = new URLSearchParams(location.search).get("flags");
  for (const raw of (q ?? "").split(",").filter(Boolean)) {
    const on = !raw.startsWith("-");
    const k = raw.replace(/^[-+]/, "") as keyof typeof DEFAULTS;
    if (k in f) f[k] = on;
  }
  return f;
}

/** plain: human words on stage · tap: tap-to-remove on Protect · split: diorama edge split */
export const FLAGS = parse();
