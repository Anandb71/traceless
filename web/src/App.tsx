import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { AttackResult, Fixture, Health, HexCell, SessionState } from "./types";
import GlobeView, { type GlobeMarker } from "./components/GlobeView";
import PhotoStage, { type PhotoMode } from "./components/PhotoStage";
import Home from "./steps/Home";
import { AttackPanel, CluesPanel, ErasePanel, ReattackPanel, ZeroPanel } from "./steps/Panels";
import SafeCard from "./steps/SafeCard";
import Bench from "./steps/Bench";
import Future from "./steps/Future";
import Readout from "./components/Readout";
import Diorama from "./components/Diorama";
import Rationale from "./components/Rationale";
import MatchView, { SnapLines } from "./steps/Match";
import { streetMatch } from "./street";
import { sound } from "./sound";

export type Step = "home" | "zero" | "attack" | "match" | "clues" | "erase" | "reattack" | "safe" | "bench" | "future";
const STEPS: Step[] = ["home", "zero", "attack", "match", "clues", "erase", "reattack", "safe", "bench", "future"];
const STEP_LABEL: Record<Step, string> = {
  home: "Send a photo",
  zero: "Your file",
  attack: "The attack",
  match: "The match",
  clues: "What gave you away",
  erase: "Protect",
  reattack: "Re-attack",
  safe: "Safe to post",
  bench: "Benchmark",
  future: "Close",
};

const FRAME_MS = 1500;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [sid, setSid] = useState<string | null>(null);
  const [st, setSt] = useState<SessionState | null>(null);
  const [step, setStep] = useState<Step>("home");
  const [frame, setFrame] = useState(-1); // collapse frame being shown
  const [precise, setPrecise] = useState(false);
  const [replay, setReplay] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [muted, setMuted] = useState(sound.muted);
  const [activeIds, setActiveIds] = useState<string[]>([]);
  const [dioramaFailed, setDioramaFailed] = useState(false);
  const frozen = useRef<number | null>(null); // ?frame=n pins the collapse (screenshots)
  const saved = useRef<string | null>(null);

  // ---- polling -----------------------------------------------------------
  useEffect(() => {
    const onHealth = (h: Health) => {
      // phones can't reach "localhost": download QRs use the LAN address
      (window as unknown as { __BASE__?: string }).__BASE__ = new URL(h.base_url).host;
      setHealth(h);
    };
    const t = setInterval(() => api.health().then(onHealth).catch(() => setHealth(null)), 2000);
    api.health().then(onHealth).catch(() => {});
    api.fixtures().then(setFixtures).catch(() => {});
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!sid || replay) return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await api.state(sid);
        if (!alive) return;
        setSt(s);
        if (s.stage === "done" && saved.current !== s.id) {
          saved.current = s.id;
          api.saveTake(s.id).catch(() => {}); // record a clean take for the PANIC key
        }
        if (s.stage !== "done" && s.stage !== "error") setTimeout(tick, 400);
      } catch {
        if (alive) setTimeout(tick, 1000);
      }
    };
    tick();
    return () => {
      alive = false;
    };
  }, [sid, replay]);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2600);
  };

  const begin = useCallback((id: string) => {
    setReplay(null);
    setSt(null);
    setFrame(-1);
    setSid(id);
    setStep("zero");
  }, []);

  const reset = useCallback(() => {
    setSid(null);
    setSt(null);
    setReplay(null);
    setFrame(-1);
    setStep("home");
  }, []);

  // ---- deep link: ?take=<name>&step=<step>&frame=<n> (README screenshots, rehearsal) ----
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    const take = q.get("take");
    if (!take) return;
    api
      .take(take)
      .then((t) => {
        setReplay(take);
        setSt(t);
        const s = q.get("step") as Step | null;
        setStep(s && STEPS.includes(s) ? s : "zero");
        if (q.get("precise") === "1") setPrecise(true);
        if (q.get("frame") != null) frozen.current = Number(q.get("frame"));
      })
      .catch(() => flash(`no take ${take}`));
  }, []);

  // ---- PANIC: play the recorded take for this step --------------------------
  const panic = useCallback(async () => {
    try {
      const takes = await api.takes();
      if (!takes.length) return flash("No recorded take yet");
      const want = st?.fixture_id && takes.includes(st.fixture_id) ? st.fixture_id : takes.includes("madrid-jamon-shopfront") ? "madrid-jamon-shopfront" : takes[0];
      const t = await api.take(want);
      setReplay(want);
      setSt(t);
      if (step === "home") setStep("zero");
      flash(`Recorded take: ${want}`);
    } catch (e) {
      flash(`Panic failed: ${e}`);
    }
  }, [st, step]);

  // ---- keyboard -------------------------------------------------------------
  // Shot 4 only exists when Attacker C made a match above its measured threshold.
  const hasMatch = !!streetMatch(st);
  const next = useCallback(() => {
    setStep((s) => {
      let i = STEPS.indexOf(s);
      if (s === "home") return s;
      if (s === "clues" && st?.already_safe) return "safe";
      i = Math.min(STEPS.length - 1, i + 1);
      if (STEPS[i] === "match" && !hasMatch) i += 1;
      return STEPS[i];
    });
  }, [st?.already_safe, hasMatch]);
  const prev = useCallback(() => {
    setStep((s) => {
      if (s === "safe" && st?.already_safe) return "clues";
      let i = Math.max(1, STEPS.indexOf(s) - 1);
      if (STEPS[i] === "match" && !hasMatch) i -= 1;
      return s === "home" ? s : STEPS[i];
    });
  }, [st?.already_safe, hasMatch]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      sound.unlock();
      if (e.key.toLowerCase() === "s" && !e.ctrlKey && !e.metaKey) {
        const m = sound.toggle();
        setMuted(m);
        flash(m ? "Sound off" : "Sound on");
        return;
      }
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") prev();
      else if (e.key.toLowerCase() === "p") panic();
      else if (e.key.toLowerCase() === "h" || e.key === "Escape") reset();
      else if (e.key.toLowerCase() === "b") setStep("bench");
      else if (e.key.toLowerCase() === "m") {
        const v = !precise;
        setPrecise(v);
        if (sid && !replay) api.privacy(sid, v).catch(() => {});
        flash(v ? "Owner OK: exact places shown" : "Privacy mode: regions only");
      } else if (e.key.toLowerCase() === "w" && e.shiftKey) {
        api.wipe().then((r) => flash(`Wiped ${r.wiped_sessions} session(s) from this laptop`));
        reset();
      }
    };
    const onClick = () => sound.unlock();
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onClick);
    };
  }, [next, prev, panic, reset, precise, sid, replay]);

  // ---- collapse animation (real frames from the ablation) ---------------------
  const frames = st?.collapse?.frames ?? [];
  useEffect(() => {
    if (step !== "attack") return;
    if (!frames.length) return;
    if (frozen.current != null) {
      setFrame(Math.min(frozen.current, frames.length - 1));
      return;
    }
    setFrame(0);
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      if (i >= frames.length) return clearInterval(t);
      setFrame(i);
    }, FRAME_MS);
    return () => clearInterval(t);
  }, [step, frames.length]);

  // ---- sound cues (synthesized; muted with S) -----------------------------------
  useEffect(() => {
    if (step === "attack" && frame >= 0) sound.ping(1 + frame * 0.04);
  }, [step, frame]);
  useEffect(() => {
    if (step === "attack" && frames.length > 1 && frozen.current == null) sound.rumble(((frames.length - 1) * FRAME_MS) / 1000);
    if (step === "match") sound.ping(0.8);
  }, [step, frames.length]);
  const hasProtected = !!st?.protected;
  useEffect(() => {
    if (step === "erase" && hasProtected) sound.shatter();
  }, [step, hasProtected]);

  // ---- derived view state -------------------------------------------------------
  const isPrecise = precise || !!st?.privacy?.precise || !!st?.truth?.public_landmark;
  const base = st?.attacks?.find((a) => a.attacker_id === "geoclip");
  const lastRound = st?.defense?.rounds?.[st.defense.rounds.length - 1];
  const after = useMemo(() => worst(lastRound?.attacks ?? []), [lastRound]);

  const shownAttack: AttackResult | undefined = (() => {
    if (step === "attack") {
      if (frames.length && frame >= 0) return frames[Math.min(frame, frames.length - 1)].attack;
      return base;
    }
    if (step === "clues" || step === "erase" || step === "match") return base;
    if (step === "reattack" || step === "safe") return after ?? base;
    return undefined;
  })();

  const cells: HexCell[] = step === "home" || step === "zero" || step === "bench" || step === "future" ? [] : shownAttack?.distribution ?? [];
  const focus =
    shownAttack?.top && step !== "home" && step !== "zero" && step !== "bench"
      ? { lat: shownAttack.top.lat, lon: shownAttack.top.lon, km2: shownAttack.credible_area_km2 }
      : null;
  const markers: GlobeMarker[] = [];
  if (isPrecise && st?.truth?.lat != null && step !== "home" && step !== "zero") {
    markers.push({ lat: st.truth.lat, lon: st.truth.lon!, kind: "truth", label: "you were here" });
  }
  if (isPrecise && shownAttack?.top && focus) {
    markers.push({ lat: shownAttack.top.lat, lon: shownAttack.top.lon, kind: "guess", label: "AI guess" });
  }

  const visible = useMemo(() => {
    const ids = new Set<string>();
    if (!st?.clues) return ids;
    if (step === "attack" && frames.length && frame >= 0) {
      frames[Math.min(frame, frames.length - 1)].restored_clue_ids.forEach((c) => ids.add(c));
      if (frame >= frames.length - 1) st.clues.forEach((c) => ids.add(c.id));
    } else if (step === "attack") {
      // before ablation is ready: show OCR/detector boxes as they are found
      st.clues.forEach((c) => ids.add(c.id));
    } else if (step === "clues" || step === "erase") {
      st.clues.forEach((c) => ids.add(c.id));
    }
    return ids;
  }, [st?.clues, step, frame, frames]);

  const photoMode: PhotoMode =
    step === "erase" && st?.protected ? "erasing" : step === "reattack" || step === "safe" ? (st?.protected ? "compare" : "original") : "original";

  // Clues step: cycle the highlight through clues in contribution order (box <-> bar).
  const ranked = useMemo(
    () => (st?.clues ?? []).filter((c) => c.contribution).sort((a, b) => a.contribution!.rank - b.contribution!.rank),
    [st?.clues],
  );
  const [hlIdx, setHlIdx] = useState(0);
  useEffect(() => {
    if (step !== "clues" || ranked.length < 2) return setHlIdx(0);
    const t = setInterval(() => setHlIdx((i) => (i + 1) % ranked.length), 2200);
    return () => clearInterval(t);
  }, [step, ranked.length]);
  const hlId = step === "clues" ? ranked[hlIdx]?.id ?? null : null;
  const highlight = step === "attack" ? activeIds : hlId;
  useEffect(() => {
    if (step !== "attack") setActiveIds([]);
  }, [step]);

  // ---- render --------------------------------------------------------------------
  if (step === "home") {
    return (
      <Shell step={step} health={health} precise={isPrecise} replay={replay} toast={toast} muted={muted}>
        <Home health={health} fixtures={fixtures} onSession={begin} />
      </Shell>
    );
  }
  if (step === "match" && st && hasMatch) {
    return (
      <Shell step={step} health={health} precise={isPrecise} replay={replay} toast={toast} muted={muted}>
        <MatchView st={st} precise={isPrecise} />
      </Shell>
    );
  }
  if (step === "future") {
    return (
      <Shell step={step} health={health} precise={isPrecise} replay={replay} toast={toast}>
        <Future />
      </Shell>
    );
  }
  if (step === "bench") {
    return (
      <Shell step={step} health={health} precise={isPrecise} replay={replay} toast={toast} muted={muted}>
        <Bench />
      </Shell>
    );
  }

  return (
    <Shell step={step} health={health} precise={isPrecise} replay={replay} toast={toast} muted={muted} stage={st?.stage} progress={st?.progress}>
      <div className="stage">
        <section className="left">
          {st?.image && step === "zero" && st.depth_url && !dioramaFailed ? (
            <Diorama
              key={st.id}
              src={st.image.url}
              depthSrc={st.depth_url}
              w={st.image.w}
              h={st.image.h}
              clues={st.clues ?? []}
              scanning
              onFail={() => setDioramaFailed(true)}
            />
          ) : st?.image ? (
            <PhotoStage
              src={st.image.url}
              protectedSrc={st.protected?.url}
              maskSrc={st.protected?.mask_url}
              w={st.image.w}
              h={st.image.h}
              clues={st.clues ?? []}
              visible={visible}
              highlight={highlight}
              mode={photoMode}
              faces={st.defense?.protected}
              showFaces={step === "erase" || step === "reattack"}
              scanning={step === "attack" && (!frames.length || frame < frames.length - 1)}
              overlay={step === "reattack" && st ? <SnapLines key={st.id} st={st} /> : null}
            />
          ) : (
            <div className="waiting">Receiving photo…</div>
          )}
          <div className="panel">
            {step === "zero" && <ZeroPanel st={st} />}
            {step === "attack" && <AttackPanel st={st} frame={frame} frames={frames.length} />}
            {step === "clues" && <CluesPanel st={st} highlight={hlId} />}
            {step === "clues" && !st?.already_safe && (
              <button className="protect-btn" onClick={() => setStep("erase")}>
                Protect my photo
              </button>
            )}
            {step === "erase" && <ErasePanel st={st} />}
            {step === "reattack" && <ReattackPanel st={st} />}
            {step === "safe" && <SafeCard st={st} />}
          </div>
        </section>
        <section className="right">
          <GlobeView
            cells={cells}
            focus={focus}
            markers={markers}
            minAltitude={isPrecise ? 0.03 : 0.35}
            tone={step === "reattack" || step === "safe" || st?.already_safe ? "safe" : "threat"}
            transitionMs={step === "attack" ? FRAME_MS - 100 : 1600}
          />
          <Readout step={step} st={st} attack={shownAttack} frame={frame} frames={frames.length} />
          {step === "attack" && <Rationale st={st} onActive={setActiveIds} />}
        </section>
      </div>
    </Shell>
  );
}

function worst(rs: AttackResult[]): AttackResult | undefined {
  const ok = rs.filter((r) => r.status === "ok" && r.distance_km != null);
  return ok.sort((a, b) => (a.distance_km ?? 0) - (b.distance_km ?? 0))[0];
}

function Shell(props: {
  step: Step;
  health: Health | null;
  precise: boolean;
  replay: string | null;
  toast: string | null;
  muted?: boolean;
  stage?: string;
  progress?: Record<string, number>;
  children: React.ReactNode;
}) {
  const { step, health } = props;
  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo" />
          TRACELESS
        </div>
        <nav className="steps">
          {STEPS.slice(1).map((s, i) => (
            <span key={s} className={`st ${s === step ? "on" : ""} ${STEPS.indexOf(s) < STEPS.indexOf(step) ? "done" : ""}`}>
              <b>{i + 1}</b>
              {STEP_LABEL[s]}
            </span>
          ))}
        </nav>
        <div className="chips">
          {props.replay && <span className="chip warn">recorded take</span>}
          {props.muted && <span className="chip dim">sound off</span>}
          <span className={`chip ${props.precise ? "warn" : ""}`}>{props.precise ? "exact places" : "privacy mode"}</span>
          <span className={`chip ${health?.cloud ? "" : "dim"}`}>{health?.cloud ? "cloud AI on" : "offline"}</span>
          <span className={`chip ${health?.ready ? "ok" : "dim"}`}>{health?.ready ? "models ready" : "warming up…"}</span>
          {props.stage && props.stage !== "done" && <span className="chip live">computing · {props.stage}</span>}
        </div>
      </header>
      <main>{props.children}</main>
      {props.toast && <div className="toast">{props.toast}</div>}
    </div>
  );
}
