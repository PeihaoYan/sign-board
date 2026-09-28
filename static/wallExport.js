(() => {
  // ---------------------------------------------------------------------------
  // Export the big screen as a PNG.
  //
  // What the monitor page downloads has to be the wall the audience is looking at, not a
  // dump of the monitor's own table. The wall is a full-screen canvas: the venue picture,
  // every signature bubble drawn as ink with its small name underneath, the QR card in the
  // corner and the status chip. This module redraws exactly that.
  //
  // The positions come from wallLayout.js, the same module the wall itself lays out with,
  // so the exported picture is the current arrangement rather than a new shuffle.
  //
  // Vector strokes are drawn as ink (never a bitmap of the phone canvas), which is what the
  // wall does too: a stored signature image would bring its own background with it.
  // ---------------------------------------------------------------------------

  // Bubble sizes are not constants here: they come from `wallLayout.metricsFor(count)`, the same
  // call the wall uses, so the exported picture has the same size of signature as the screen.
  const NAME_FONT_SIZE = 12;
  const STATUS_FONT = '11px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';
  const TITLE_FONT = '700 19px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';
  const KICKER_FONT = '700 10px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';
  const COPY_FONT = '12px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

  const STATUS_LABELS = {
    draft: '尚未开放',
    live: '现场开放',
    paused: '暂时暂停',
    ended: '活动结束',
  };

  function loadImage(source) {
    return new Promise((resolve) => {
      if (!source) {
        resolve(null);
        return;
      }
      const image = new Image();
      // The QR code is an SVG and the wall image is a PNG; neither taints the canvas because
      // both are served from this origin.
      image.addEventListener('load', () => resolve(image));
      image.addEventListener('error', () => resolve(null));
      image.src = source;
    });
  }

  function roundedRect(context, x, y, width, height, radius) {
    const corner = Math.min(radius, width / 2, height / 2);
    context.beginPath();
    context.moveTo(x + corner, y);
    context.arcTo(x + width, y, x + width, y + height, corner);
    context.arcTo(x + width, y + height, x, y + height, corner);
    context.arcTo(x, y + height, x, y, corner);
    context.arcTo(x, y, x + width, y, corner);
    context.closePath();
  }

  // The arrangement depends on the wall's own geometry, because the placement is in percentages
  // of the stage and the rule weighs candidates in pixels of it. The export therefore asks
  // wallSync for the geometry the wall laid out with and only scales the picture up: taking every
  // size from the wall's logical stage keeps the arrangement identical while the file stays a
  // print-quality image. Without a reported geometry the picture is laid out on the size of this
  // window instead, which is a valid arrangement but not necessarily the one on the wall.
  const FALLBACK_EXPORT_WIDTH = 1920;
  // A signature is sized as a share of the stage, so the exported picture is only the wall's own
  // arrangement when the canvas is the wall's stage, magnified as little as possible. Raising a
  // small stage to `MIN_EXPORT_WIDTH` used to do the opposite of what it looked like it did —
  // `metricsFor` is not told about the magnification, so on a 1884 px wall the canvas was stretched
  // to a minimum of 1200/1884 while every bubble stayed at its pixel size and came out a third
  // smaller relative to the picture than on screen. `MAX_EXPORT_WIDTH` only ever shrinks a stage no
  // projector has, and it shrinks the layout with it, so the proportions still hold.
  const MIN_EXPORT_WIDTH = 640;
  const MAX_EXPORT_WIDTH = 2560;
  const STAGE_RATIO = 16 / 9;
  const MIN_LOGICAL_WIDTH = 320;
  const MAX_LOGICAL_WIDTH = 7680;
  const MIN_LOGICAL_HEIGHT = 180;
  const MAX_LOGICAL_HEIGHT = 4320;
  const MAX_LOGICAL_PIXELS = 16777216;
  const MIN_LOGICAL_ASPECT = 1.25;
  const MAX_LOGICAL_ASPECT = 2.4;

  function fallbackStage() {
    const width = Math.min(
      Math.max(window.innerWidth || 0, FALLBACK_EXPORT_WIDTH),
      MAX_EXPORT_WIDTH,
    );
    return { width, height: Math.round(width / STAGE_RATIO) };
  }

  function measureStage(geometry) {
    const candidateWidth = Number(geometry && geometry.stageWidth);
    const candidateHeight = Number(geometry && geometry.stageHeight);
    const candidateAspect = candidateWidth / candidateHeight;
    const valid = Number.isFinite(candidateWidth) && Number.isFinite(candidateHeight)
      && candidateWidth >= MIN_LOGICAL_WIDTH && candidateWidth <= MAX_LOGICAL_WIDTH
      && candidateHeight >= MIN_LOGICAL_HEIGHT && candidateHeight <= MAX_LOGICAL_HEIGHT
      && candidateAspect >= MIN_LOGICAL_ASPECT && candidateAspect <= MAX_LOGICAL_ASPECT
      && candidateWidth * candidateHeight <= MAX_LOGICAL_PIXELS;
    const logical = valid
      ? { width: candidateWidth, height: candidateHeight }
      : fallbackStage();
    const exportWidth = Math.min(
      Math.max(Math.round(logical.width), MIN_EXPORT_WIDTH),
      MAX_EXPORT_WIDTH,
    );
    const ratio = exportWidth / logical.width;
    return {
      logicalWidth: logical.width,
      logicalHeight: logical.height,
      width: exportWidth,
      height: Math.round(logical.height * ratio),
      ratio,
    };
  }

  // Kept for callers that want the card's box (the monitor page reports it and the placement uses
  // it to keep signatures out of that corner), even though the export does not draw the card.
  function qrCardBox(geometry, stageWidth, stageHeight) {
    const qr = geometry && geometry.qr;
    if (!qr || !geometry.stageWidth) return null;
    const scaleX = stageWidth / geometry.stageWidth;
    const scaleY = stageHeight / geometry.stageHeight;
    const clearance = 10;
    const left = (qr.left + clearance) * geometry.stageWidth / 100;
    const right = (qr.right - clearance) * geometry.stageWidth / 100;
    const top = (qr.top + clearance) * geometry.stageHeight / 100;
    const bottom = (qr.bottom - clearance) * geometry.stageHeight / 100;
    return {
      x: left * scaleX,
      y: top * scaleY,
      width: Math.max((right - left) * scaleX, 60),
      height: Math.max((bottom - top) * scaleY, 60),
      radius: 16,
      scale: (scaleX + scaleY) / 2,
    };
  }
  function eventSlug() {
    const params = new URLSearchParams(window.location.search);
    return params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  }

  function drawBubble(context, item, position, stage, metrics, options) {
    const drawInk = !(options && options.skipInk);
    const scale = stage.ratio;
    const centerX = (position.x / 100) * stage.logicalWidth * scale;
    const centerY = (position.y / 100) * stage.logicalHeight * scale;
    context.save();
    context.translate(centerX, centerY);
    context.rotate((position.rotation * Math.PI) / 180);
    // From here on the sizes are the wall's own pixel sizes, so the picture is the wall
    // magnified rather than a wall laid out differently.
    context.scale(scale, scale);

    const inkOffsetX = -metrics.inkWidth / 2;
    const inkOffsetY = -metrics.height / 2 + metrics.padding;
    if (drawInk) {
      context.save();
      context.translate(inkOffsetX, inkOffsetY);
      // The stroke coordinates are device pixels, so `drawSignatureInk` draws them through a
      // device-pixel transform. Three values have to agree for the ink to land in this bubble: the
      // device-pixel scale (`dpr`), the transform that is in effect here (a canvas transform is not
      // inherited by that function), and 1/scale inside the box so that composing the two leaves
      // the ink at the wall's own size instead of the export's magnified one.
      window.drawSignatureInk(
        context,
        item,
        { x: 0, y: 0, width: metrics.inkWidth, height: metrics.inkHeight },
        {
          dpr: scale,
          // The same share of the ink the wall uses, so the exported picture has the same weight of
          // pen as the screen it is a picture of.
          lineWidth: 3.2 * (metrics.inkScale || 1),
          colour: '#ffffff',
          outerTransform: {
            a: scale,
            b: 0,
            c: 0,
            d: scale,
            e: inkOffsetX * scale,
            f: inkOffsetY * scale,
          },
        },
      );
      context.restore();
    }

    const label = item.name || '匿名参与者';
    context.font = `600 ${metrics.nameSize}px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif`;
    context.fillStyle = '#ffffff';
    context.globalAlpha = item.name ? 0.92 : 0.7;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    const labelY = -metrics.height / 2 + metrics.padding + metrics.inkHeight
      + Math.max(4, NAME_FONT_SIZE * metrics.scale * 0.8);
    context.shadowColor = 'rgba(8, 18, 30, 0.85)';
    context.shadowBlur = 3;
    context.fillText(label, 0, labelY, metrics.width - metrics.padding * 2);
    context.restore();
  }

  function drawStatusChip(context, config) {
    if (!config) return;
    const label = STATUS_LABELS[config.status] || config.status || '';
    if (!label) return;
    context.save();
    context.font = STATUS_FONT;
    const textWidth = context.measureText(label).width;
    const chipWidth = textWidth + 24;
    const chipHeight = 24;
    context.fillStyle = 'rgba(12, 22, 34, 0.72)';
    roundedRect(context, 16, 16, chipWidth, chipHeight, chipHeight / 2);
    context.fill();
    context.strokeStyle = 'rgba(230, 184, 92, 0.45)';
    context.lineWidth = 1;
    context.stroke();
    context.fillStyle = '#f0d9a4';
    context.textAlign = 'left';
    context.textBaseline = 'middle';
    context.fillText(label, 28, 16 + chipHeight / 2);
    context.restore();
  }

  // Returns the layout and the canvas, so the caller can both download it and describe it.
  //
  // `options.skipInk` draws the picture without the stroke of one submission, keeping it in the
  // layout so nothing else moves. The test suite subtracts the two pictures to measure exactly
  // where that signature's ink was painted, which no colour threshold on top of the venue image can
  // do reliably.
  async function renderWallPng(options) {
    const settings = options || {};
    const slug = settings.slug || eventSlug();
    const skipInk = settings.skipInk === undefined ? null : String(settings.skipInk);
    const response = await fetch(`/api/events/${encodeURIComponent(slug)}/display`, { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取大屏数据');
    const snapshot = await response.json();
    const items = snapshot.items || [];
    if (!items.length) throw new Error('大屏当前没有签名可下载。');

    const resolved = window.wallSync
      ? await window.wallSync.resolveGeometry()
      : { geometry: null, source: 'none' };
    const stage = measureStage(resolved.geometry);
    const canvas = document.createElement('canvas');
    canvas.width = stage.width;
    canvas.height = stage.height;
    const context = canvas.getContext('2d');
    const scale = stage.ratio;
    context.setTransform(scale, 0, 0, scale, 0, 0);

    // Only the venue picture is fetched: the QR card is not part of the picture.
    const background = await loadImage('/assets/assets/background.png');

    // Everything below is drawn in the wall's own pixel sizes, on a canvas magnified by
    // `stage.ratio`, so the picture and the wall agree on where every element is.
    const logicalWidth = stage.logicalWidth;
    const logicalHeight = stage.logicalHeight;
    context.fillStyle = '#12283c';
    context.fillRect(0, 0, logicalWidth, logicalHeight);
    if (background) {
      // The wall shows the venue picture with `background-size: cover`, centred.
      const cover = Math.max(logicalWidth / background.width, logicalHeight / background.height);
      const drawWidth = background.width * cover;
      const drawHeight = background.height * cover;
      context.drawImage(
        background,
        (logicalWidth - drawWidth) / 2,
        (logicalHeight - drawHeight) / 2,
        drawWidth,
        drawHeight,
      );
    }

    const geometry = resolved.geometry
      ? {
        stageWidth: resolved.geometry.stageWidth,
        stageHeight: resolved.geometry.stageHeight,
        qr: resolved.geometry.qr,
        count: resolved.geometry.count,
      }
      : { stageWidth: logicalWidth, stageHeight: logicalHeight, qr: null };
    const layout = window.wallLayout.computeWallLayout(items, geometry);

    context.textAlign = 'center';
    context.textBaseline = 'middle';
    layout.bubbles.forEach(({ item, position }) => {
      // Only the requested signature skips its ink; the option means "leave this stroke out".
      const skipThisInk = skipInk !== null && String(item.id) === skipInk;
      drawBubble(context, item, position, stage, layout.metrics, { skipInk: skipThisInk });
    });

    // The QR card is deliberately not drawn: the picture is the wall of signatures, and a QR code
    // in a deck or a photo would be an invitation nobody can accept. Its box still travels in the
    // geometry, because the placement keeps signatures out of that corner — the arrangement has to
    // stay the one on screen.
    drawStatusChip(context, snapshot.event);

    lastBubbles = layout.bubbles.map(({ item, position }) => ({
      id: item.id,
      name: item.name,
      x: position.x,
      y: position.y,
      rotation: position.rotation,
    }));

    return {
      canvas,
      ratio: stage.ratio,
      stage,
      geometry,
      geometrySource: resolved.source,
      event: snapshot.event,
      items,
      bubbles: lastBubbles,
    };
  }

  function buildWallPngFileName() {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '');
    return `sign-board-wall-${stamp}.png`;
  }

  // The test driver in tests/check_wall_export.py reads the arrangement this produced, to
  // confirm it is the arrangement the wall itself is showing.
  window.__wallExportBubbles = () => lastBubbles;
  let lastBubbles = null;

  window.wallExport = {
    renderWallPng,
    buildWallPngFileName,
    measureStage,
    qrCardBox,
  };
})();
