/** Closing shot (stage direction): where this lives in your life. A labelled concept mockup. */
export default function Future() {
  const apps = ["Messages", "Instagram", "WhatsApp", "Mail"];
  return (
    <div className="future">
      <div className="phone">
        <div className="phone-photo" />
        <div className="sheet">
          <div className="sheet-title">Share photo</div>
          <div className="sheet-row">
            {apps.map((a) => (
              <div key={a} className="share-app">
                <i />
                <span>{a}</span>
              </div>
            ))}
          </div>
          <div className="sheet-action hot">
            <b>Protect before posting</b>
            <span>TRACELESS · erase what gives your location away</span>
          </div>
          <div className="sheet-action">Copy</div>
          <div className="sheet-action">Save to Files</div>
        </div>
      </div>
      <div className="future-copy">
        <div className="kicker">Concept mockup · not a shipped feature</div>
        <h1>
          Share the moment, <em>not the address.</em>
        </h1>
        <p className="lede">One tap in the share menu, before the photo ever leaves your phone.</p>
      </div>
    </div>
  );
}
