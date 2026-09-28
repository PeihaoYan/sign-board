/**
 * Shared signature renderer.
 *
 * A submission carries its ink as vector strokes (preferred) and optionally as a
 * rendered image (older records). Drawing the strokes produces pure white lines with
 * no background of any kind, which is what the wall must show.
 *
 * This file also provides a small 5x7 bitmap font so the on-site monitor can build a
 * PNG snapshot in the browser without pulling in an external library.
 */
(function attachSignatureRenderer(global) {
  function boundsOf(strokes) {
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    strokes.forEach((stroke) => {
      stroke.forEach((point) => {
        if (point[0] < minX) minX = point[0];
        if (point[0] > maxX) maxX = point[0];
        if (point[1] < minY) minY = point[1];
        if (point[1] > maxY) maxY = point[1];
      });
    });
    if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
    return { minX, minY, maxX, maxY };
  }

  function drawStrokes(context, strokes, box, lineWidth) {
    const { minX, minY, maxX, maxY } = box.bounds;
    const inkWidth = Math.max(maxX - minX, 1) + 12;
    const inkHeight = Math.max(maxY - minY, 1) + 12;
    // `box.width/height` are in the units the ink is finally displayed in, so this transform only
    // has to map the stroke's own pixels onto the box. Any device-pixel scaling belongs to the
    // caller's transform, which is composed in below; folding it in here as well is what used to
    // shrink the ink by that factor a second time.
    const scale = Math.min(box.width / inkWidth, box.height / inkHeight);
    const offsetX = box.x + (box.width - (maxX - minX) * scale) / 2 - minX * scale;
    const offsetY = box.y + (box.height - (maxY - minY) * scale) / 2 - minY * scale;

    context.save();
    const inkTransform = { a: scale, d: scale, e: offsetX, f: offsetY };
    const outer = box.outer;
    if (outer) {
      // What the caller already had in effect, composed with the ink transform rather than
      // replaced by it: replacing it silently dropped the caller's translation, rotation and
      // scale, so a rotated signature bubble got ink from somewhere else.
      context.transform(outer.a, outer.b, outer.c, outer.d, outer.e, outer.f);
      context.transform(inkTransform.a, 0, 0, inkTransform.d, inkTransform.e, inkTransform.f);
    } else {
      // `resetTransform` and not `setTransform`: a caller may have scaled the context (a canvas
      // bitmap sized by the device pixel ratio) and handed the same scale over as the outer
      // transform. Replacing the matrix would multiply the two and draw the ink that factor too
      // large — at 3x it landed entirely off the canvas and nothing was painted at all.
      context.resetTransform();
      context.transform(inkTransform.a, 0, 0, inkTransform.d, inkTransform.e, inkTransform.f);
    }
    context.lineWidth = lineWidth.width / scale;    context.strokeStyle = lineWidth.colour || '#ffffff';
    context.lineCap = 'round';
    context.lineJoin = 'round';
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
      context.stroke();
    });
    context.restore();
  }

  /**
   * Draw the ink of one submission inside the given box, in the context's own coordinates.
   * Handles both stroke records and the legacy rendered image.
   *
   * Stroke coordinates are in pixels of the surface they were drawn on, so the ink is drawn through
   * a transform of its own — `transform` rather than `setTransform`, because a caller may have
   * already set up a translation, rotation or scale for the box (a rotated signature bubble, for
   * instance) and replacing the matrix would silently throw that away.
   *
   * `options.dpr` says how many pixels of the caller's coordinate system one box unit covers (a
   * canvas bitmap scaled by the device pixel ratio, for example; `1` when the caller works in the
   * same pixels it measured in). `options.ratio` is a legacy alias.
   *
   * `options.outerTransform` is that same scale written as a matrix, for callers whose context
   * matrix is not the one in effect at the moment of drawing — the wall's PNG export builds its
   * transform by hand. It is composed with the ink transform, not instead of it.
   */
  function drawInk(context, item, box, options) {
    const settings = options || {};
    const ratio = settings.dpr || settings.ratio || 1;
    const strokes = Array.isArray(item.strokes) ? item.strokes : [];
    const bounds = strokes.length ? boundsOf(strokes) : null;

    if (bounds) {
      drawStrokes(context, strokes, {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        bounds,
        outer: settings.outerTransform || { a: ratio, b: 0, c: 0, d: ratio, e: 0, f: 0 },
      }, {
        width: settings.lineWidth || 3.2,
        colour: settings.colour || '#ffffff',
      });
      return true;
    }

    if (item.signature_data) {
      const image = new global.Image();
      image.onload = () => {
        const imageRatio = image.naturalWidth / image.naturalHeight || 1;
        const boxRatio = box.width / box.height;
        let drawWidth = box.width;
        let drawHeight = box.height;
        if (imageRatio > boxRatio) {
          drawHeight = box.width / imageRatio;
        } else {
          drawWidth = box.height * imageRatio;
        }
        context.drawImage(
          image,
          box.x + (box.width - drawWidth) / 2,
          box.y + (box.height - drawHeight) / 2,
          drawWidth,
          drawHeight,
        );
      };
      image.src = item.signature_data;
    }
    return false;
  }

  /** Render one submission into its own canvas element. */
  function render(canvas, item, options) {
    const settings = options || {};
    const cssWidth = settings.width || 136;
    const cssHeight = settings.height || 88;
    // `resolutionRatio` lets a crowded wall trade bitmap detail for memory without
    // changing the element's on-screen size.
    const ratio = settings.resolutionRatio || Math.min(global.devicePixelRatio || 1, 2);

    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    const context = canvas.getContext('2d');
    // The context is scaled by the bitmap ratio, so the box is measured in CSS pixels; the ink is
    // given `dpr: 1` for the same reason. Passing the ratio here *and* as an outer transform is what
    // used to square it, drawing the ink `ratio` times too large and off the canvas — invisible at
    // 1x, a clipped blur at 2x, and completely empty at 3x.
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
    return drawInk(context, item, { x: 0, y: 0, width: cssWidth, height: cssHeight }, {
      dpr: 1,
      lineWidth: settings.lineWidth || 3.2,
      colour: settings.colour || '#ffffff',
    });
  }

  // ---------------------------------------------------------------------------
  // 5x7 bitmap font for the monitoring snapshot. Characters outside this table
  // (Chinese names, for example) cannot be drawn and are reported to the caller.
  // ---------------------------------------------------------------------------
  const GLYPHS = {
    '0': ['01110', '10001', '10011', '10101', '11001', '10001', '01110'],
    '1': ['00100', '01100', '00100', '00100', '00100', '00100', '01110'],
    '2': ['01110', '10001', '00001', '00010', '00100', '01000', '11111'],
    '3': ['11111', '00010', '00100', '00010', '00001', '10001', '01110'],
    '4': ['00010', '00110', '01010', '10010', '11111', '00010', '00010'],
    '5': ['11111', '10000', '11110', '00001', '00001', '10001', '01110'],
    '6': ['00110', '01000', '10000', '11110', '10001', '10001', '01110'],
    '7': ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
    '8': ['01110', '10001', '10001', '01110', '10001', '10001', '01110'],
    '9': ['01110', '10001', '10001', '01111', '00001', '00010', '01100'],
    ':': ['00000', '00100', '00100', '00000', '00100', '00100', '00000'],
    '-': ['00000', '00000', '00000', '11111', '00000', '00000', '00000'],
    '_': ['00000', '00000', '00000', '00000', '00000', '00000', '11111'],
    '/': ['00001', '00010', '00010', '00100', '01000', '01000', '10000'],
    '.': ['00000', '00000', '00000', '00000', '00000', '01100', '01100'],
    ',': ['00000', '00000', '00000', '00000', '01100', '00100', '01000'],
    ' ': ['00000', '00000', '00000', '00000', '00000', '00000', '00000'],
  };

  /**
   * Draw bitmap text. Returns the number of characters that could not be drawn,
   * so callers can decide how to represent names in other scripts.
   */
  function drawText(context, text, x, y, options) {
    const settings = options || {};
    const pixelSize = Math.max(1, Math.round((settings.size || 16) / 7));
    context.fillStyle = settings.colour || '#f7f3ea';
    let cursorX = x;
    let missing = 0;
    for (const character of String(text)) {
      const glyph = GLYPHS[character];
      if (!glyph) {
        missing += 1;
        cursorX += pixelSize * 6;
        continue;
      }
      glyph.forEach((row, rowIndex) => {
        for (let column = 0; column < row.length; column += 1) {
          if (row[column] === '1') {
            context.fillRect(cursorX + column * pixelSize, y + rowIndex * pixelSize, pixelSize, pixelSize);
          }
        }
      });
      cursorX += pixelSize * 6;
    }
    return missing;
  }

  global.renderSignatureInto = render;
  global.drawSignatureInk = drawInk;
  global.drawReportText = drawText;
})(window);
