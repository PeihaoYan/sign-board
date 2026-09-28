(() => {
  // ---------------------------------------------------------------------------
  // Keep the wall's layout geometry reachable from the monitor page.
  //
  // The wall places signatures in percentages of its own stage and the placement rule weighs
  // candidate positions in pixels of that stage, so the exported PNG is only the wall's
  // arrangement when it is laid out with the same numbers: the stage size and the box of the
  // floating QR card (which keeps changing size until its image has loaded).
  //
  // Three carriers, in order of reliability:
  //
  //   1. the server, via /api/events/{slug}/wall-geometry — authoritative, and it survives a
  //      reload of either page or a different machine, because the display posts what it used;
  //   2. localStorage and a BroadcastChannel message, which make the same browser instant;
  //   3. nothing, in which case the export falls back to a standard 16:9 frame.
  // ---------------------------------------------------------------------------
  const CHANNEL = 'sign-board-wall';
  const STORAGE_KEY = 'sign-board-wall-geometry';
  const MIN_STAGE_WIDTH = 320;
  const MAX_STAGE_WIDTH = 7680;
  const MIN_STAGE_HEIGHT = 180;
  const MAX_STAGE_HEIGHT = 4320;
  const MAX_STAGE_PIXELS = 16777216;
  const MIN_STAGE_ASPECT = 1.25;
  const MAX_STAGE_ASPECT = 2.4;
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel(CHANNEL) : null;

  function normalise(value) {
    if (!value) return null;
    const stageWidth = Number(value.stageWidth);
    const stageHeight = Number(value.stageHeight);
    const aspect = stageWidth / stageHeight;
    if (!Number.isFinite(stageWidth) || !Number.isFinite(stageHeight)
      || stageWidth < MIN_STAGE_WIDTH || stageWidth > MAX_STAGE_WIDTH
      || stageHeight < MIN_STAGE_HEIGHT || stageHeight > MAX_STAGE_HEIGHT
      || aspect < MIN_STAGE_ASPECT || aspect > MAX_STAGE_ASPECT
      || stageWidth * stageHeight > MAX_STAGE_PIXELS) return null;
    const qr = value.qr
      ? {
        left: Number(value.qr.left),
        right: Number(value.qr.right),
        top: Number(value.qr.top),
        bottom: Number(value.qr.bottom),
      }
      : null;
    if (qr && (![qr.left, qr.right, qr.top, qr.bottom].every(Number.isFinite)
      || qr.left >= qr.right || qr.top >= qr.bottom)) return null;
    // The crowd size travels with the geometry: it decides how large each signature is drawn, so
    // the export cannot reproduce the arrangement without it. Dropping it here silently made every
    // exported picture fall back to the size for a small crowd.
    const count = Number(value.count);
    return {
      stageWidth,
      stageHeight,
      qr,
      count: Number.isFinite(count) && count >= 0 ? count : null,
    };
  }

  function readStored() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? normalise(JSON.parse(raw)) : null;
    } catch (_) {
      return null;
    }
  }

  function writeStored(geometry) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(geometry));
    } catch (_) {
      /* private mode: the broadcast and the server report still carry the geometry */
    }
  }

  let localGeometry = readStored();
  let serverGeometry = null;
  let serverChecked = false;

  if (channel) {
    channel.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.type !== 'wall-geometry') return;
      const geometry = normalise(data.geometry);
      if (geometry) localGeometry = geometry;
    });
  }

  function slug() {
    const params = new URLSearchParams(window.location.search);
    return params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  }

  /** Report the geometry the wall just laid out with. Called by display.js after every render. */
  function publish(geometry) {
    const value = normalise(geometry);
    if (!value) return;
    localGeometry = value;
    writeStored(value);
    if (channel) channel.postMessage({ type: 'wall-geometry', geometry: value });
    const body = JSON.stringify(value);
    fetch(`/api/events/${encodeURIComponent(slug())}/wall-geometry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
      credentials: 'same-origin',
      keepalive: true,
    }).catch(() => {
      /* the wall keeps working without the monitor being able to match it exactly */
    });
  }

  /** The server's copy, read once per page load; `null` when the wall never reported. */
  async function fetchServerGeometry() {
    if (serverChecked) return serverGeometry;
    serverChecked = true;
    try {
      const response = await fetch(`/api/events/${encodeURIComponent(slug())}/wall-geometry`, {
        cache: 'no-store',
      });
      if (response.ok) {
        const payload = await response.json();
        serverGeometry = normalise(payload.geometry);
        if (serverGeometry) localGeometry = serverGeometry;
      }
    } catch (_) {
      /* offline or blocked: fall back to the local copy */
    }
    return serverGeometry;
  }

  window.wallSync = {
    publish,
    /** The geometry the export should be laid out with, and where it came from. */
    async resolveGeometry() {
      const fromServer = await fetchServerGeometry();
      if (fromServer) return { geometry: fromServer, source: 'wall (server)' };
      const local = localGeometry || readStored();
      if (local) return { geometry: local, source: 'wall (this browser)' };
      return { geometry: null, source: 'none' };
    },
  };
})();
