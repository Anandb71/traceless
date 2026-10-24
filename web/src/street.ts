import type { AttackResult, SessionState, StreetMatch } from "./types";

/** Attacker C's pre-erasure result, if any. */
export function streetAttack(st: SessionState | null | undefined): AttackResult | undefined {
  return st?.attacks?.find((a) => a.attacker_id === "street");
}

/** The best street match, only if it passed the measured inlier threshold (truth rule). */
export function streetMatch(st: SessionState | null | undefined): { attack: AttackResult; match: StreetMatch } | null {
  const a = streetAttack(st);
  const thr = st?.street_coverage?.match_threshold;
  const m = a?.street_matches?.[0];
  if (!a || a.status !== "ok" || !m || thr == null || m.inliers < thr) return null;
  return { attack: a, match: m };
}
