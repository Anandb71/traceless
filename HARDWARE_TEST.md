# HARDWARE_TEST — what a human must verify (SIM mode covers the rest)

The build environment had no phone or camera. Everything below was simulated with
fixture photos; these are the checks that need real hardware before demo day.

## Phone → laptop upload
- [ ] iPhone (Safari): scan the home-screen QR → page loads → pick a photo → "Got it" →
      laptop jumps to Clue zero within ~2 s.
- [ ] Android (Chrome): same.
- [ ] **Does the browser keep GPS EXIF?** iOS Safari's photo picker often *strips*
      location from uploads (and may convert HEIC → JPEG). Record what you see on
      the Clue zero screen: GPS present / absent. If absent, the owner's private
      "where was it taken?" field on the phone page supplies the answer key.
- [ ] HEIC via cable/AirDrop to a Mac → drag onto the home screen → loads
      (pillow-heif is installed).
- [ ] A 12–48 MP photo uploads in < 5 s over a phone hotspot.

## Laptop → phone download
- [ ] Safe-to-post QR opens `/d/<token>` on the judge's phone; "Save photo"
      downloads `traceless.jpg`; long-press saves to Photos on iPhone.
- [ ] The saved file has **no EXIF/GPS** (check with any EXIF viewer app).

## Projector
- [ ] 1920×1080 mirrored: header chips, photo, globe and readout all legible from
      the back row. Distances readable (64 px numerals).
- [ ] Globe frame rate is smooth during the collapse (WebGL on the laptop GPU).

## Upgrade features (UPGRADE.md)
- [ ] Shot 1 diorama: smooth (≥ 30 fps) on the laptop GPU, no stretched "curtains" at object edges.
- [ ] Sound: pings on each collapse frame, rumble during convergence, shatter on Protect; S mutes.
- [ ] Shot 4 match lines draw in a real browser (headless screenshots only show the end state).
- [ ] Shot 5 particle dissolve plays once, then the cleaned photo stays.
- [ ] Street coverage built for the venue; a photo taken inside it gets "The match"; one taken
      elsewhere skips it.

## Network / offline
- [ ] Wi-Fi off + `TRACELESS_OFFLINE=1`: full run on 2 fixture photos.
- [ ] Phone hotspot only (no venue Wi-Fi): QR upload works.
- [ ] Firewall prompt accepted for Python on private networks.

## Timing (live budget: attack ≤ 20 s, erase ≤ 10 s, re-attack ≤ 20 s)
- [ ] Note `timings` from `/api/s/<id>` for 5 different photos (one indoor).
- [ ] PANIC (P) replays instantly on every step.

## The "Done" bar from the brief
- [ ] The full 3-minute demo runs **5 times in a row** with 5 different photos,
      including one indoor photo that takes the "already hard to place" path.
