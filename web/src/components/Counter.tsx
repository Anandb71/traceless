import { useEffect, useRef, useState } from "react";

interface Props {
  value: number | null | undefined;
  format: (v: number) => string;
  /** interpolate in log space (distances, areas span orders of magnitude) */
  log?: boolean;
  ms?: number;
}

/** Animates between REAL values only — never invents intermediate data on its own. */
export default function Counter({ value, format, log = true, ms = 1100 }: Props) {
  const [shown, setShown] = useState<number | null>(value ?? null);
  const from = useRef<number | null>(value ?? null);
  useEffect(() => {
    if (value == null) {
      setShown(null);
      from.current = null;
      return;
    }
    const a = from.current ?? value;
    const b = value;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const v = log && a > 0 && b > 0 ? Math.exp(Math.log(a) + (Math.log(b) - Math.log(a)) * e) : a + (b - a) * e;
      setShown(v);
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      from.current = b;
    };
  }, [value, ms, log]);
  return <span className="num">{shown == null ? "—" : format(shown)}</span>;
}
