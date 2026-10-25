import type { AttackResult, SessionState } from "../types";
import type { Step } from "../App";
import Counter from "./Counter";
import { area, km, scale } from "../format";

interface Props {
  step: Step;
  st: SessionState | null;
  attack?: AttackResult;
  frame: number;
  frames: number;
  note?: string;
}

export default function Readout({ step, st, attack, frame, frames, note }: Props) {
  if (!st || step === "zero" || !attack) return null;
  const safeTone = step === "reattack" || step === "safe" || !!st.already_safe;
  // No GPS and no owner-confirmed place: distances are measured from the AI's own
  // first guess, so lead with the search area instead (labeled, never a fake "0 m").
  const proxy = st.truth?.source === "proxy";
  const after = step === "reattack" || step === "safe";
  const areaMode = proxy && !after;
  const driver = note ? note :
    step === "attack" && frames > 0
      ? `collapse driven by ${attack.attacker_name} · frame ${Math.max(0, frame) + 1}/${frames}`
      : attack.attacker_name;
  return (
    <div className={`readout ${safeTone ? "safe" : ""}`}>
      {areaMode ? (
        <div className="ro-main">
          <span className="ro-label">Narrowed to</span>
          <Counter value={attack.credible_area_km2} format={area} />
          <span className="ro-label">search area</span>
        </div>
      ) : (
        <div className="ro-main">
          <span className="ro-label">{st.already_safe ? "Best guess" : safeTone ? (proxy ? "Guess moved" : "Best guess now") : "Placed"}</span>
          <Counter value={attack.distance_km} format={km} />
          <span className="ro-label">{proxy ? "from its first guess" : "from where you were"}</span>
        </div>
      )}
      <div className="ro-sub">
        {!areaMode && (
          <span>
            search area <Counter value={attack.credible_area_km2} format={area} />
          </span>
        )}
        <span className="scale">{scale(attack.credible_area_km2)}-level</span>
        {attack.top?.region && <span className="region">{attack.top.region}</span>}
        {proxy && <span className="muted">no GPS · no answer key given</span>}
      </div>
      <div className="ro-driver">{driver}</div>
    </div>
  );
}
