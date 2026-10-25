import type { Fixture, Health, SessionState } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<Health>(r)),
  fixtures: () => fetch("/api/fixtures").then((r) => j<Fixture[]>(r)),
  startFixture: (id: string) =>
    fetch(`/api/sessions/fixture/${id}`, { method: "POST" }).then((r) => j<{ id: string }>(r)),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/sessions", { method: "POST", body: fd }).then((r) => j<{ id: string }>(r));
  },
  state: (id: string) => fetch(`/api/s/${id}`).then((r) => j<SessionState>(r)),
  newSlot: () => fetch("/api/slots", { method: "POST" }).then((r) => j<{ token: string; url: string; qr: string }>(r)),
  slot: (tok: string) => fetch(`/api/slots/${tok}`).then((r) => j<{ session: string | null }>(r)),
  privacy: (id: string, precise: boolean) =>
    fetch(`/api/s/${id}/privacy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ precise }),
    }).then((r) => j<{ precise: boolean }>(r)),
  saveTake: (id: string) => fetch(`/api/s/${id}/take`, { method: "POST" }).then((r) => j<{ take: string }>(r)),
  tap: (id: string, clue: string) =>
    fetch(`/api/s/${id}/tap/${clue}`, { method: "POST" }).then((r) =>
      j<{ clue_id: string; tapped: string[]; image_url: string; attack: import("./types").AttackResult; pct_pixels_changed: number; label: string }>(r),
    ),
  takes: () => fetch("/api/takes").then((r) => j<string[]>(r)),
  take: (name: string) => fetch(`/api/takes/${name}`).then((r) => j<SessionState>(r)),
  wipe: () => fetch("/api/wipe", { method: "POST" }).then((r) => j<{ wiped_sessions: number }>(r)),
  bench: () => fetch("/api/bench").then((r) => r.json()),
};
