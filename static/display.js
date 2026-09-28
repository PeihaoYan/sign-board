(() => {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  const stage = document.querySelector('#wall-stage');
  const layer = document.querySelector('#signature-layer');
  const empty = document.querySelector('#wall-empty');
  const qr = document.querySelector('#qr-image');
  const qrCopy = document.querySelector('#qr-copy');
  const status = document.querySelector('#wall-status');
  const connection = document.querySelector('#connection-status');
  const items = new Map();
  let eventConfig = null;
  let socket = null;
  let reconnectTimer = null;
  // Wall-clock cost of the last full re-layout, logged for capacity checks.
  let lastRenderMs = 0;

  const statusLabels = {
    draft: '尚未开放',
    live: '现场开放',
    paused: '暂时暂停',
    ended: '活动结束',
  };

  function setConnection(text, connected) {
    connection.textContent = text;
    connection.classList.toggle('is-live', connected);
  }

  // The placement algorithm lives in wallLayout.js, shared with the monitor page's PNG
  // export, so that the exported picture puts every signature where the wall shows it.
  const { computeWallLayout, qrBoundsFromRect } = window.wallLayout;

  // ---------------------------------------------------------------------------
  // The QR card.
  //
  // Its default width is a share of the stage (like the signature sizes), so the card keeps its
  // proportion of the background when the projector resolution changes; the per-event `qr_scale`
  // setting multiplies that, because how large a code has to be is a question of the room: from the
  // back of a hall the default card leaves a QR nobody can scan. Both numbers are written as CSS
  // variables, so the stylesheet owns the look and the page only decides the size.
  // ---------------------------------------------------------------------------
  const QR_CARD_BASE_WIDTH = 218;
  const QR_SCALE_MIN = 0.5;
  const QR_SCALE_MAX = 3;

  function qrScaleFromConfig(config) {
    const value = Number(config && config.qr_scale);
    if (!Number.isFinite(value) || value <= 0) return 1;
    return Math.min(Math.max(value, QR_SCALE_MIN), QR_SCALE_MAX);
  }

  function applyQrScale() {
    const requested = qrScaleFromConfig(eventConfig);
    // A very large card would leave the placement nowhere to put signatures. The card is roughly
    // square, so capping it at a third of the stage on either side keeps a third of the wall free
    // in the worst case (the card sits in one corner).
    const ceiling = Math.max(
      0.4,
      Math.min(stage.clientWidth / 3, stage.clientHeight / 3) / QR_CARD_BASE_WIDTH,
    );
    const scale = Math.min(requested, Math.max(ceiling, QR_SCALE_MIN));
    document.documentElement.style.setProperty('--qr-scale', scale.toFixed(3));
    return { requested, applied: scale };
  }

  // The floating QR card lives in the bottom-right corner; keep bubbles out of it
  // so that a fresh signature is never hidden behind the panel. Its bounds are cached
  // because the placement loop can run hundreds of thousands of times at 500 bubbles.
  let qrBounds = null;

  function refreshQrBounds() {
    const card = document.querySelector('.qr-card');
    const stageRect = stage.getBoundingClientRect();
    qrBounds = qrBoundsFromRect(
      card ? card.getBoundingClientRect() : null,
      stageRect,
      10,
    );
  }

  // The bubble sizes are set as CSS variables on the layer, so one write covers every bubble and
  // the stylesheet keeps control of the layout. The values come from the same `metricsFor()` the
  // placement grid uses.
  function applyBubbleMetrics(metrics) {
    layer.style.setProperty('--bubble-width', `${metrics.width}px`);
    layer.style.setProperty('--bubble-height', `${metrics.height}px`);
    layer.style.setProperty('--bubble-padding', `${metrics.padding}px`);
    layer.style.setProperty('--ink-width', `${metrics.inkWidth}px`);
    layer.style.setProperty('--ink-height', `${metrics.inkHeight}px`);
    layer.style.setProperty('--name-size', `${metrics.nameSize}px`);
  }

  function createBubble(item, index, position, resolutionRatio, metrics) {
    const bubble = document.createElement('article');
    bubble.className = 'signature-bubble';
    bubble.dataset.id = String(item.id);
    bubble.style.left = `${position.x}%`;
    bubble.style.top = `${position.y}%`;
    bubble.style.rotate = `${position.rotation.toFixed(2)}deg`;
    bubble.style.setProperty('--drift', `${position.drift.toFixed(2)}px`);
    bubble.style.animationDelay = `${position.delay.toFixed(2)}s, ${(index % 6) * 70}ms`;

    const inner = document.createElement('div');
    inner.className = 'signature-inner';
    const ink = document.createElement('canvas');
    ink.className = 'signature-ink';
    ink.setAttribute('aria-label', `${item.name || '匿名参与者'}的签名`);
    // The canvas bitmap is rendered at the size the bubble is drawn at, so the ink stays crisp
    // when the crowd forces smaller bubbles.
    window.renderSignatureInto(ink, item, {
      width: metrics.inkWidth,
      height: metrics.inkHeight,
      // The stroke width is a share of the ink, not a fixed number of pixels: a hand-written line is
    // about a twentieth of the writing's height, so shrinking the ink has to thin the pen with it or
    // the handwriting turns into a row of bars.
    lineWidth: 3.2 * metrics.scale * (metrics.inkScale || 1),
      resolutionRatio,
    });
    const name = document.createElement('div');
    name.className = 'signature-name';
    if (item.name) {
      name.textContent = item.name;
    } else {
      // A name is required, so this only covers records made before that rule; they would
      // otherwise show an empty line under their ink.
      name.textContent = '匿名参与者';
      name.classList.add('is-anonymous');
    }
    inner.append(ink, name);
    bubble.append(inner);
    return bubble;
  }

  function renderItems() {
    const started = performance.now();
    layer.replaceChildren();
    // The card's size is part of the geometry the placement avoids, so it is applied before the
    // bounds are measured.
    applyQrScale();
    refreshQrBounds();
    const list = Array.from(items.values());
    // Each signature is its own canvas. At a few hundred bubbles the total backing
    // store starts to matter, so the bitmap resolution scales down with the crowd
    // while the on-screen size stays the same.
    const resolutionRatio = list.length > 300 ? 1 : list.length > 120 ? 1.5 : 2;
    // The measured stage size and QR box are handed to the shared layout, so the monitor page
    // can reproduce these exact positions for the same list of items. What was used is recorded
    // as well: an arrangement is only reproducible with the very geometry it was computed from,
    // and measuring again later can differ by a few pixels.
    const geometry = {
      stageWidth: stage.clientWidth,
      stageHeight: stage.clientHeight,
      qr: qrBounds,
      // The crowd size decides how large each signature is drawn.
      count: list.length,
    };
    const layout = computeWallLayout(list, geometry);
    applyBubbleMetrics(layout.metrics);
    layout.bubbles.forEach(({ item, position }, index) => {
      layer.append(createBubble(item, index, position, resolutionRatio, layout.metrics));
    });
    window.wallLayout.rememberMetrics(layout.metrics, list.length);
    window.wallLayout.lastRendered = geometry;
    // The monitor's export is only the wall's arrangement if it is laid out with the same
    // geometry, and the QR card keeps changing size until its image has loaded, so the values
    // actually used are reported instead of leaving the monitor to measure its own.
    if (window.wallSync) window.wallSync.publish(geometry);
    empty.hidden = list.length > 0;
    lastRenderMs = Math.round(performance.now() - started);
    if (list.length > 20) {
      console.info(`sign-board: rendered ${list.length} signatures in ${lastRenderMs} ms`);
    }
  }

  function applyEvent(config) {
    const previousScale = qrScaleFromConfig(eventConfig);
    eventConfig = config;
    status.textContent = statusLabels[config.status] || config.status;
    status.dataset.state = config.status;
    if (config.welcome_text) qrCopy.textContent = config.welcome_text;
    // A changed QR size moves the box the placement has to keep clear, so the wall re-lays out.
    // The card's own resize observer would catch this too, but only after the stylesheet has been
    // recomputed; doing it here keeps the arrangement and the card in step.
    if (config.qr_scale !== undefined && qrScaleFromConfig(config) !== previousScale && items.size) {
      renderItems();
    }
  }

  function applySnapshot(snapshot) {
    applyEvent(snapshot.event);
    items.clear();
    snapshot.items.forEach((item) => items.set(item.id, item));
    renderItems();
  }

  function addItem(item) {
    items.delete(item.id);
    items.set(item.id, item);
    const limit = eventConfig?.display_limit || 42;
    while (items.size > limit) items.delete(items.keys().next().value);
    renderItems();
  }

  function removeItem(id) {
    items.delete(id);
    renderItems();
  }

  async function loadSnapshot() {
    const response = await fetch(`/api/events/${encodeURIComponent(slug)}/display`, { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取活动状态');
    applySnapshot(await response.json());
  }

  // The QR card is taller before the QR image inside it has loaded, and the first layout runs
  // before that: the card then shrinks, the area reserved for it changes, and the signatures
  // would keep the positions that were computed for a larger card. Watching the card means the
  // arrangement always matches the card that is actually on screen — which is also what the
  // monitor page's PNG export lays out against.
  let cardResizeTimer = null;
  const card = document.querySelector('.qr-card');
  if (card && typeof ResizeObserver === 'function') {
    const observer = new ResizeObserver(() => {
      const previous = qrBounds;
      refreshQrBounds();
      if (!previous || !qrBounds || !items.size) return;
      const moved = Math.abs(previous.left - qrBounds.left) > 0.5
        || Math.abs(previous.top - qrBounds.top) > 0.5
        || Math.abs(previous.bottom - qrBounds.bottom) > 0.5;
      if (!moved) return;
      window.clearTimeout(cardResizeTimer);
      cardResizeTimer = window.setTimeout(renderItems, 120);
    });
    observer.observe(card);
  }

  function connect() {
    if (socket && socket.readyState <= 1) return;
    setConnection('重新连接中', false);
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/events/${encodeURIComponent(slug)}/display`);
    socket.addEventListener('open', () => setConnection('实时连接', true));
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'snapshot') applySnapshot(message);
      if (message.type === 'submission') addItem(message.item);
      if (message.type === 'remove') removeItem(message.id);
      if (message.type === 'event') applyEvent(message.event);
    });
    socket.addEventListener('close', () => {
      setConnection('等待连接', false);
      window.clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connect, 3000);
    });
    socket.addEventListener('error', () => socket.close());
  }

  async function start() {
    qr.src = `/api/events/${encodeURIComponent(slug)}/qr.svg`;
    document.documentElement.style.setProperty('--wall-image', "url('/assets/assets/background.png')");
    try {
      await loadSnapshot();
      connect();
    } catch (error) {
      setConnection('暂时离线', false);
      window.setTimeout(start, 4000);
    }
  }

  let resizeTimer = null;
  function scheduleRelayout() {
    // Re-laying out hundreds of canvases is expensive, so debounce a little.
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (items.size) renderItems();
    }, 250);
  }
  window.addEventListener('resize', scheduleRelayout);
  // The signature sizes are a share of the stage, so the wall has to re-lay out when the stage
  // itself changes size — a projector switching resolution, a window being dragged, the browser
  // entering fullscreen. Watching the stage catches those even when the window event does not fire.
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(scheduleRelayout).observe(stage);
  }
  start();
})();
