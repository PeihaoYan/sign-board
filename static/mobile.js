(() => {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  const form = document.querySelector('#submission-form');
  const canvas = document.querySelector('#signature-canvas');
  const context = canvas.getContext('2d');
  const hint = document.querySelector('#canvas-hint');
  const clearButton = document.querySelector('#clear-signature');
  const submitButton = document.querySelector('#submit-button');
  const notice = document.querySelector('#mobile-notice');
  const success = document.querySelector('#success-panel');
  const submitAnother = document.querySelector('#submit-another');
  const title = document.querySelector('#mobile-title');
  const subtitle = document.querySelector('#mobile-subtitle');
  const orientationHint = document.querySelector('#orientation-hint');
  const landscapeButton = document.querySelector('#landscape-toggle');
  const landscapeExit = document.querySelector('#landscape-exit');
  const shell = document.querySelector('.mobile-shell');
  const firstSection = document.querySelector('.mobile-form .form-section');
  const canvasWrap = document.querySelector('.canvas-wrap');
  // The writing guide drawn over the canvas: a baseline and the prompt, turned with the ink.
  const canvasGuide = document.querySelector('.canvas-guide');
  let hasInk = false;
  let drawing = false;
  let lastPoint = null;
  let eventConfig = null;
  // Recorded ink as arrays of [x, y] bitmap-pixel points, one array per stroke.
  let strokes = [];

  function updateOrientationHint() {
    if (!orientationHint) return;
    orientationHint.textContent = document.body.classList.contains('landscape-mode')
      ? '横屏书写中：字迹按横排显示'
      : '可点「横屏书写」把画板转为横排';
  }

  // ---------------------------------------------------------------------------
  // Landscape writing mode: a tall box on a phone that stays upright.
  //
  // The participant keeps the phone in portrait. The writing area is a tall, narrow box, and only
  // the canvas *content* is turned 90°: the drawing is rotated so it reads along the phone's long
  // side, which is where a signature fits comfortably on a small screen. Nothing else about the
  // page moves — no fullscreen, no orientation lock, no viewport surgery — because every previous
  // attempt at rotating the page itself fought the browser over the viewport size.
  //
  // A point of the drawing (the "strip") is shown at (H − y, x) in the box, so a tap at box
  // position (u, v) is the strip position (v, H − u). The canvas bitmap is the strip, and its CSS
  // rotation is the only thing that turns it.
  // ---------------------------------------------------------------------------
  const LANDSCAPE_MIN_BOX_WIDTH = 200;
  const LANDSCAPE_MIN_BOX_HEIGHT = 240;
  const LANDSCAPE_MAX_BOX_HEIGHT = 720;
  const LANDSCAPE_BOX_MARGIN = 12;
  const LANDSCAPE_ASPECT = 0.62; // the strip's height ÷ its width, the shape of a signature
  let landscapeSpace = null;
  // Diagnostics for the layout test harness in tests/; only exposed when the harness asks for it
  // with ?layoutDebug=1, so the normal page carries no extra global.
  let landscapeFit = null;
  if (params.get('layoutDebug') === '1') {
    window.__signBoardLandscapeFit = () => landscapeFit;
    window.__signBoardStrokes = () => strokes.map((stroke) => stroke.length);
  }

  /**
   * Portion of the box the canvas may occupy, taken from what the rest of the form needs. The
   * canvas is taken out of the layout for one measurement so the box reports only its own chrome,
   * and it is also taken out of its landscape sizing first: otherwise the height left over from the
   * previous measurement counts as chrome and the box shrinks a little on every entry.
   */
  function measureLandscapeBox() {
    const view = window.visualViewport;
    const viewportWidth = (view ? view.width : window.innerWidth) || 320;
    const viewportHeight = (view ? view.height : window.innerHeight) || 480;
    clearLandscapeSizing();
    canvas.style.display = 'none';
    canvasWrap.offsetHeight; // force one synchronous layout before measuring
    const wrapHeight = canvasWrap.offsetHeight;
    const sectionPadding = firstSection.offsetHeight - firstSection.clientHeight;
    canvas.style.display = '';

    const header = document.querySelector('.mobile-head');
    const nameSection = document.querySelector('.mobile-form .form-section:nth-child(2)');
    const submitRow = document.querySelector('.mobile-form > .form-actions');
    const chromeHeight = [header, nameSection, submitRow]
      .reduce((total, element) => total + (element ? element.offsetHeight : 0), 0);
    const shellPadding = shell.offsetHeight - shell.clientHeight;
    const available = viewportHeight - chromeHeight - shellPadding - wrapHeight
      - sectionPadding - LANDSCAPE_BOX_MARGIN * 2;
    return {
      // The box spans the section's width, which is the screen minus the page padding. When the
      // section reports no width the box falls back to the viewport, so a bad measurement can never
      // produce an invisible box.
      width: Math.max(
        Math.min(firstSection.clientWidth || viewportWidth - 32, viewportWidth - 16),
        LANDSCAPE_MIN_BOX_WIDTH,
      ),
      height: Math.min(
        Math.max(available, LANDSCAPE_MIN_BOX_HEIGHT),
        LANDSCAPE_MAX_BOX_HEIGHT,
      ),
    };
  }

  function clearLandscapeSizing() {
    canvasWrap.style.removeProperty('width');
    canvasWrap.style.removeProperty('height');
    canvasWrap.style.removeProperty('max-width');
    canvasWrap.style.removeProperty('max-height');
    ['width', 'height', 'transform', 'transform-origin', 'position', 'top', 'left']
      .forEach((property) => {
        canvas.style.removeProperty(property);
        if (canvasGuide) canvasGuide.style.removeProperty(property);
      });
  }

  function enterLandscapeMode() {
    document.body.classList.add('landscape-mode');
    // The class changes the layout, so the measurement has to be taken after the browser has
    // applied it; measuring first reads the portrait widths and gives a box with no size.
    shell.offsetHeight;
    landscapeSpace = measureLandscapeBox();
    resizeCanvasToLandscape();
    updateOrientationHint();
  }

  function exitLandscapeMode() {
    document.body.classList.remove('landscape-mode');
    landscapeSpace = null;
    clearLandscapeSizing();
    resizeCanvas();
    updateOrientationHint();
  }

  /**
   * Give the wrapper the tall box and turn the canvas inside it. The canvas bitmap is the strip: a
   * wide, upright drawing, which is what any display scales. Only the on-screen box is tall.
   */
  function resizeCanvasToLandscape() {
    const space = landscapeSpace;
    if (!space) return;
    const boxWidth = Math.round(space.width);
    const boxHeight = Math.round(space.height);
    // The strip is as wide as the box is tall, and keeps the proportions of a signature; if it would
    // be taller than the box is wide it is fitted to the width instead.
    let stripWidth = Math.max(boxHeight, 120);
    let stripHeight = Math.round(stripWidth * LANDSCAPE_ASPECT);
    if (stripHeight > boxWidth) {
      stripHeight = boxWidth;
      stripWidth = Math.round(stripHeight / LANDSCAPE_ASPECT);
    }
    canvasWrap.style.width = `${boxWidth}px`;
    canvasWrap.style.height = `${boxHeight}px`;
    canvasWrap.style.maxWidth = 'none';
    canvasWrap.style.maxHeight = 'none';
    // The box's padding (set in the stylesheet) keeps the strip off the rounded corners; the canvas
    // and the guide sit on the padding edge.
    const boxPadding = 14;
    canvas.style.position = 'absolute';
    canvas.style.top = `${boxPadding}px`;
    canvas.style.left = `${boxPadding}px`;
    canvas.style.width = `${stripWidth}px`;
    canvas.style.height = `${stripHeight}px`;
    canvas.style.transformOrigin = '0 0';
    canvas.style.transform = `translateX(${boxWidth}px) rotate(90deg)`;
    resizeCanvasTo(stripWidth, stripHeight);
    // The guide is drawn in the same space as the ink and turned the same way, so its line and its
    // text read horizontally once the phone is turned. Sizing it to the box instead would put most
    // of it off screen after the rotation, which is how the prompt ended up cut in half at the edge.
    if (canvasGuide) {
      canvasGuide.style.position = 'absolute';
      canvasGuide.style.top = `${boxPadding}px`;
      canvasGuide.style.left = `${boxPadding}px`;
      canvasGuide.style.width = `${stripWidth}px`;
      canvasGuide.style.height = `${stripHeight}px`;
      canvasGuide.style.transformOrigin = '0 0';
      canvasGuide.style.transform = `translateX(${boxWidth}px) rotate(90deg)`;
      buildLandscapeGuide(stripWidth, stripHeight);
    }
    // Where the drawing actually is: the strip may be narrower than the box on a wide screen, and
    // the ink (and therefore the guide) is centred in it.
    landscapeFit = {
      box: `${boxWidth}x${boxHeight}`,
      strip: `${stripWidth}x${stripHeight}`,
      drawing: (() => {
        const rect = canvasWrap.getBoundingClientRect();
        return `${Math.round(rect.left)}x${Math.round(rect.top)}`;
      })(),
      rotation: 2,
    };
  }

  /**
   * Draw the landscape writing guide for a strip of the given size.
   *
   * The guide is built in the strip's coordinate space and turned with the canvas, so the participant
   * reads it along the phone's long edge — the direction they are about to write in. Everything is
   * placed as a ratio of the strip, because the strip's shape changes with the screen (a 574x268
   * viewBox on a 348x216 strip used to push the prompt off the right edge, and a fixed font size
   * made the three labels compete with each other).
   *
   * The layout is deliberately a hierarchy rather than three equal labels: the prompt is the one
   * line meant to be read first, the dashed line underneath shows where the writing goes, and the
   * two small marks say which end to start at and which way to go.
   */
  function buildLandscapeGuide(width, height) {
    if (!canvasGuide) return;
    const svgNamespace = 'http://www.w3.org/2000/svg';
    const element = (name, attributes) => {
      const node = document.createElementNS(svgNamespace, name);
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
      return node;
    };
    // Capped so the guide does not look oversized on a tablet, where the strip is much wider.
    const fontSize = Math.round(Math.min(Math.max(width * 0.055, 14), 21));
    // The writing line sits above the middle: everything that labels it stays clear of the band
    // below, which is where the signature is actually drawn.
    const baseline = Math.round(height * 0.36);
    const inset = Math.round(width * 0.06);
    const tick = Math.round(fontSize * 0.5);

    canvasGuide.setAttribute('viewBox', `0 0 ${width} ${height}`);
    canvasGuide.setAttribute('width', String(width));
    canvasGuide.setAttribute('height', String(height));
    const prompt = element('text', {
      x: Math.round(width / 2),
      y: Math.round(height * 0.19),
      'text-anchor': 'middle',
      'font-size': fontSize,
      class: 'guide-prompt',
    });
    prompt.textContent = '沿虚线从左到右书写';
    // "Start here" sits just past the end tick, above the writing band: a mark inside that band would
    // be covered by the first stroke of the signature.
    const start = element('text', {
      x: inset + Math.round(fontSize * 1.1),
      y: baseline - Math.round(fontSize * 0.45),
      'font-size': Math.round(fontSize * 0.86),
      class: 'guide-mark',
    });
    start.textContent = '起笔';
    canvasGuide.replaceChildren(
      prompt,
      element('line', {
        x1: inset,
        y1: baseline,
        x2: width - inset,
        y2: baseline,
        'stroke-dasharray': `${Math.round(fontSize * 0.85)} ${Math.round(fontSize * 0.7)}`,
      }),
      element('path', {
        d: `M${inset} ${baseline - tick} V${baseline + tick}`
          + ` M${width - inset} ${baseline - tick} V${baseline + tick}`,
      }),
      start,
    );
    // The direction mark sits below the writing line at its end: the arrow, and the two characters
    // that label it directly above the arrow, clear of the end tick by a margin of their own.
    const arrowY = baseline + Math.round(fontSize * 2);
    const arrowCentre = width - inset - Math.round(fontSize * 0.9);
    const arrowHalf = Math.round(fontSize * 1.5);
    canvasGuide.append(
      element('path', {
        d: `M${arrowCentre - arrowHalf} ${arrowY} H${arrowCentre + arrowHalf}`
          + ` M${arrowCentre + arrowHalf - Math.round(fontSize * 0.45)} ${arrowY - Math.round(fontSize * 0.26)}`
          + ` L${arrowCentre + arrowHalf} ${arrowY}`
          + ` L${arrowCentre + arrowHalf - Math.round(fontSize * 0.45)} ${arrowY + Math.round(fontSize * 0.26)}`,
        class: 'guide-arrow',
      }),
    );
    const arrowLabel = element('text', {
      x: arrowCentre,
      y: arrowY - Math.round(fontSize * 0.4),
      'text-anchor': 'middle',
      'font-size': Math.round(fontSize * 0.86),
      class: 'guide-mark',
    });
    arrowLabel.textContent = '书写方向';
    canvasGuide.append(arrowLabel);
  }

  // Sets the bitmap to the given size and keeps whatever was already drawn, rescaled.
  function resizeCanvasTo(width, height) {
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const previousWidth = canvas.width ? canvas.width / pixelRatio : width;
    const previousHeight = canvas.height ? canvas.height / pixelRatio : height;
    const previous = hasInk ? strokes.map((stroke) => stroke.map((point) => [...point])) : null;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    paintBoard();
    if (previous) {
      const scaleX = width ? previousWidth / width : 1;
      const scaleY = height ? previousHeight / height : 1;
      strokes = previous.map((stroke) => stroke.map(
        (point) => [Math.round(point[0] / scaleX), Math.round(point[1] / scaleY)],
      ));
      replayStrokes();
    }
    landscapeFit = { ...(landscapeFit || {}), bitmap: `${canvas.width}x${canvas.height}` };
  }

  function deviceToken() {
    const key = 'sign-board-device-token';
    let token = window.localStorage.getItem(key);
    if (!token) {
      token = `${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`}`;
      window.localStorage.setItem(key, token);
    }
    return token;
  }

  // The signature is sent as raw stroke points, not as an image. The display draws
  // those points as white lines, so the wall shows pure ink with no background of any
  // kind, and the request stays small (a few hundred bytes) even on constrained links.
  const STROKE_WIDTH = 4.6;
  const STROKE_COLOR = '#ffffff';

  function paintBoard() {
    context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    context.lineCap = 'round';
    context.lineJoin = 'round';
  }

  function strokeSegment(from, to) {
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.lineWidth = STROKE_WIDTH;
    context.strokeStyle = STROKE_COLOR;
    context.stroke();
  }

  // Points are recorded in bitmap pixels, which already include the device pixel ratio.
  function bitmapPoint(event) {
    const rect = canvas.getBoundingClientRect();
    const point = pointInCanvasSpace(event);
    const scaleX = rect.width ? canvas.width / rect.width : 1;
    const scaleY = rect.height ? canvas.height / rect.height : 1;
    return [Math.round(point.x * scaleX), Math.round(point.y * scaleY)];
  }

  function replayStrokes() {
    paintBoard();
    strokes.forEach((stroke) => {
      if (!stroke.length) return;
      context.beginPath();
      context.moveTo(stroke[0][0], stroke[0][1]);
      for (let index = 1; index < stroke.length; index += 1) {
        context.lineTo(stroke[index][0], stroke[index][1]);
      }
      if (stroke.length === 1) {
        context.lineTo(stroke[0][0] + 0.4, stroke[0][1] + 0.4);
      }
      context.lineWidth = STROKE_WIDTH;
      context.strokeStyle = STROKE_COLOR;
      context.stroke();
    });
  }

  // In landscape mode the canvas is turned 90° clockwise about the wrapper's top-left corner, so a
  // strip point (x, y) is shown at box position (u, v) = (H − y, x). The inverse is what maps a
  // touch back into the drawing: (x, y) = (v, H − u). The wrapper's rectangle is used rather than
  // the canvas's own, because the canvas's bounding rectangle is the box of the rotated element.
  function landscapeStripPoint(event) {
    const rect = canvasWrap.getBoundingClientRect();
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const u = event.clientX - rect.left;
    const v = event.clientY - rect.top;
    const stripWidth = canvas.width / pixelRatio;
    const stripHeight = canvas.height / pixelRatio;
    const point = {
      x: Math.min(Math.max(v, 0), stripWidth),
      y: Math.min(Math.max(stripHeight - u, 0), stripHeight),
    };
    if (window.__signBoardLandscapeFit) {
      window.__signBoardLandscapePoint = { u, v, rect: [rect.left, rect.top, rect.width, rect.height], strip: [stripWidth, stripHeight], point };
    }
    return point;
  }

  function pointInCanvasSpace(event) {
    if (document.body.classList.contains('landscape-mode')) {
      return landscapeStripPoint(event);
    }
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  // Coordinates are stored in canvas bitmap pixels, which already include the device
  // pixel ratio, so the mapped point is used as-is.
  function bitmapPoint(event) {
    const point = pointInCanvasSpace(event);
    return [Math.round(point.x), Math.round(point.y)];
  }

  function resizeCanvas() {
    if (document.body.classList.contains('landscape-mode')) {
      // The box was measured for this layout; the bitmap is the strip inside it.
      resizeCanvasToLandscape();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    resizeCanvasTo(rect.width, rect.height);
  }

  function pointFromEvent(event) {
    const point = pointInCanvasSpace(event);
    return { x: point.x, y: point.y };
  }

  function startDrawing(event) {
    event.preventDefault();
    // Capturing the pointer keeps the stroke alive when the finger leaves the canvas. It throws when
    // the pointer is not active — a synthetic event in the test harness, or a pointer the browser
    // has already dropped — and that must not cost the participant the beginning of a stroke.
    try { canvas.setPointerCapture(event.pointerId); } catch (_) { /* the stroke still draws */ }
    drawing = true;
    lastPoint = pointFromEvent(event);
    hint.classList.add('is-hidden');
    hasInk = true;
    strokes = strokes.concat([[bitmapPoint(event)]]);
  }

  function draw(event) {
    if (!drawing) return;
    event.preventDefault();
    const point = pointFromEvent(event);
    strokeSegment(lastPoint, point);
    lastPoint = point;
    const current = strokes[strokes.length - 1];
    if (current) current.push(bitmapPoint(event));
  }

  function stopDrawing(event) {
    if (!drawing) return;
    drawing = false;
    lastPoint = null;
    if (event?.pointerId !== undefined) {
      try { canvas.releasePointerCapture(event.pointerId); } catch (_) { /* pointer already released */ }
    }
  }

  function clearSignature() {
    context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    hasInk = false;
    strokes = [];
    hint.classList.remove('is-hidden');
  }

  function setNotice(message, error = true) {
    notice.textContent = message;
    notice.style.color = error ? '#a64839' : '#33776d';
  }

  async function loadEvent() {
    const response = await fetch(`/api/events/${encodeURIComponent(slug)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('活动不存在或暂时无法访问');
    eventConfig = await response.json();
    title.textContent = eventConfig.title;
    subtitle.textContent = eventConfig.subtitle || eventConfig.welcome_text;
    if (eventConfig.status !== 'live') {
      submitButton.disabled = true;
      setNotice('当前活动暂未开放提交。', true);
    }
  }

  async function submit(event) {
    event.preventDefault();
    setNotice('');
    if (!hasInk) {
      setNotice('请先写下您的签名。');
      return;
    }
    // The name is required, and the field also carries `required` so the browser blocks an empty
    // form before it gets here. This check backs up the paths that skip that validation and is
    // the same rule the server enforces.
    const name = document.querySelector('#name').value.trim();
    if (!name) {
      setNotice('请填写署名。');
      const field = document.querySelector('#name');
      field.focus();
      return;
    }
    submitButton.disabled = true;
    submitButton.textContent = '提交中…';
    try {
      const response = await fetch(`/api/events/${encodeURIComponent(slug)}/submissions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          strokes,
          device_token: deviceToken(),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = result.detail;
        throw new Error(typeof detail === 'string' ? detail : '提交失败，请稍后重试');
      }
      form.style.display = 'none';
      success.classList.add('is-visible');
    } catch (error) {
      setNotice(error.message || '提交失败，请稍后重试。');
      submitButton.disabled = false;
      submitButton.textContent = '提交到签名墙';
    }
  }

  function resetForm() {
    form.reset();
    clearSignature();
    notice.textContent = '';
    submitButton.disabled = false;
    submitButton.textContent = '提交到签名墙';
    success.classList.remove('is-visible');
    form.style.display = '';
  }

  canvas.addEventListener('pointerdown', startDrawing);
  canvas.addEventListener('pointermove', draw);
  canvas.addEventListener('pointerup', stopDrawing);
  canvas.addEventListener('pointercancel', stopDrawing);
  canvas.addEventListener('pointerleave', stopDrawing);
  clearButton.addEventListener('click', clearSignature);
  submitAnother.addEventListener('click', resetForm);
  form.addEventListener('submit', submit);
  landscapeButton.addEventListener('click', () => {
    if (document.body.classList.contains('landscape-mode')) {
      exitLandscapeMode();
    } else {
      enterLandscapeMode();
    }
  });
  landscapeExit.addEventListener('click', exitLandscapeMode);

  let resizeTimer = null;
  function handleViewportChange() {
    // The screen changed, and the recorded points are rescaled so the drawing survives.
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (document.body.classList.contains('landscape-mode')) {
      // The box was measured for the old viewport, so measure and fit again.
      landscapeSpace = measureLandscapeBox();
      resizeCanvasToLandscape();
    } else {
      resizeCanvas();
    }
      updateOrientationHint();
    }, 200);
  }
  window.addEventListener('resize', handleViewportChange);
  window.addEventListener('orientationchange', handleViewportChange);
  if (window.visualViewport) {
    // Keyboard opening and browser chrome changes move the visible area; re-fit after them.
    window.visualViewport.addEventListener('resize', handleViewportChange);
  }
  updateOrientationHint();
  resizeCanvas();
  loadEvent().catch((error) => setNotice(error.message));
})();
