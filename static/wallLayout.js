(() => {
  // ---------------------------------------------------------------------------
  // Where the signature bubbles sit on the wall.
  //
  // This is the layout the big screen uses, in a form that does not need a live page:
  // it takes the items, the size of the stage and the box of the floating QR card, and
  // returns one position per item. It is deterministic — identical input gives identical
  // positions — which is what lets the monitor export a PNG in which every signature is
  // exactly where it is on the wall, instead of being re-shuffled.
  //
  // The live wall calls this with its own measured size, so the wall that the audience
  // sees and the exported picture are produced by one and the same code path.
  // ---------------------------------------------------------------------------
  function hash(value) {
    let result = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index);
      result = Math.imul(result, 16777619);
    }
    return result >>> 0;
  }

  function randomRatio(seed, salt) {
    return ((hash(`${seed}:${salt}`) % 100000) / 100000);
  }

  // ---------------------------------------------------------------------------
  // How big one signature is drawn.
  //
  // Two independent things decide it, and both matter:
  //
  //   1. The size of the stage. The wall places each signature in percentages of the stage, so the
  //      *positions* follow the screen automatically — but a bubble drawn at a fixed pixel size does
  //      not, and on a smaller screen the signatures ended up a larger fraction of the picture than
  //      on a bigger one (measured: 8.5% of the stage width at 1920x1080, 12.9% at 1280x720). The
  //      sizes below are therefore fractions of `REFERENCE_STAGE`, scaled by the stage the wall is
  //      actually on, so a signature keeps its proportion of the background at any resolution.
  //   2. The crowd. The wall holds as many signatures as the participants bring, so the bubbles have
  //      to shrink as the wall fills: at the scale that reads best for a handful of signatures, two
  //      hundred of them cover the venue picture and overlap each other.
  //
  // The same numbers drive three things that must not disagree:
  //
  //   * the placement grid below (a step of bubble − 8 px, so neighbours keep a small gap);
  //   * the live wall, through the CSS variables that styles.css reads;
  //   * the monitor's PNG export, which draws with these sizes as well.
  //
  // A signature that arrives later never moves the others: positions are seeded by submission id and
  // the sizes are a function of the stage and the crowd, both of which are fixed for a given layout.
  // ---------------------------------------------------------------------------
  const REFERENCE_STAGE = { width: 1920, height: 1080 };
  const BASE_WIDTH = 152;
  const BASE_HEIGHT = 118;
  const BASE_INK_WIDTH = 136;
  const BASE_INK_HEIGHT = 88;
  // How much of the bubble the handwriting itself takes.
  //
  // A bubble is the room a signature needs — the ink plus its name — and the ink used to fill almost
  // all of it (89% of the width, 75% of the height), so a wall of signatures read as a wall of solid
  // blocks of handwriting. The ink is drawn at this share of the bubble instead, and the name sits
  // directly under it. Spacing is unaffected: the envelope keeps its size, which is what the
  // placement spaces signatures by, so the same arrangement holds and only the handwriting inside it
  // gets smaller.
  const INK_SIZE_FACTOR = 0.74;
  const BASE_NAME_SIZE = 12;
  const BUBBLE_PADDING = 8;
  const BUBBLE_GAP = 8;
  // Below this the ink stops being legible; above it a handful of signatures on a huge stage would
  // look like a handful of specks.
  const STAGE_SCALE_MIN = 0.35;
  const STAGE_SCALE_MAX = 2.2;

  const SCALE_LADDER = [
    { upTo: 40, scale: 1 },
    { upTo: 90, scale: 0.8 },
    { upTo: 160, scale: 0.7 },
    { upTo: 260, scale: 0.6 },
    { upTo: 400, scale: 0.5 },
    { upTo: Infinity, scale: 0.45 },
  ];

  function bubbleScaleFor(count) {
    for (const step of SCALE_LADDER) {
      if (count <= step.upTo) return step.scale;
    }
    return SCALE_LADDER[SCALE_LADDER.length - 1].scale;
  }

  /**
   * How much bigger or smaller than the reference stage this stage is.
   *
   * The shorter side decides, because that is what a signature's height competes with: on a wall
   * twice as wide but the same height the signatures should stay the same size, since only the room
   * beside them grew.
   */
  function stageScaleFor(stageWidth, stageHeight) {
    const width = Number(stageWidth) > 0 ? Number(stageWidth) : REFERENCE_STAGE.width;
    const height = Number(stageHeight) > 0 ? Number(stageHeight) : REFERENCE_STAGE.height;
    const ratio = Math.min(
      width / REFERENCE_STAGE.width,
      height / REFERENCE_STAGE.height,
    );
    return Math.min(Math.max(ratio, STAGE_SCALE_MIN), STAGE_SCALE_MAX);
  }

  /**
   * Pixel sizes for a crowd of `count` signatures on a stage of the given size. Every caller uses
   * this one function, so the wall, its placement grid and the exported PNG cannot drift apart.
   */
  function metricsFor(count, options) {
    const settings = options || {};
    const crowdScale = bubbleScaleFor(count);
    const stageScale = stageScaleFor(settings.stageWidth, settings.stageHeight);
    // The bubble gap is a fixed share of the bubble rather than a fixed number of pixels, so the
    // spacing keeps its proportion too.
    const scale = crowdScale * stageScale;
    const round = (value) => Math.round(value);
    const width = Math.max(round(BASE_WIDTH * scale), 24);
    const height = Math.max(round(BASE_HEIGHT * scale), 18);
    return {
      scale,
      crowdScale,
      stageScale,
      width,
      height,
      padding: Math.max(2, round(BUBBLE_PADDING * scale)),
      // The ink is a fixed share of the bubble rather than nearly all of it, so a signature reads as
      // handwriting with room around it instead of as a filled block (see INK_SIZE_FACTOR).
      inkWidth: Math.max(round(BASE_INK_WIDTH * scale * INK_SIZE_FACTOR), 14),
      inkHeight: Math.max(round(BASE_INK_HEIGHT * scale * INK_SIZE_FACTOR), 10),
      inkScale: INK_SIZE_FACTOR,
      nameSize: Math.max(8, round(BASE_NAME_SIZE * scale)),
      // The grid step trails the bubble so two neighbours do not touch.
      stepWidth: Math.max(width - round(BUBBLE_GAP * scale), round(width * 0.5)),
      stepHeight: Math.max(height - round(BUBBLE_GAP * scale), round(height * 0.5)),
    };
  }

  function overlapsQrCard(bounds, x, y, halfX, halfY) {
    if (!bounds) return false;
    return x + halfX > bounds.left && x - halfX < bounds.right && y + halfY > bounds.top && y - halfY < bounds.bottom;
  }

  // Candidate positions are compared against a coarse grid instead of every placed
  // bubble: at 500 bubbles a full scan would be millions of comparisons per re-layout. The search
  // window is widened to three cells on each side, which matters once the bubbles are scaled down:
  // with one cell per step, a neighbour a little further away falls outside the scanned window and
  // is never seen, so candidates look free and the wall ends up with signatures on top of each
  // other.
  const SEARCH_CELLS = 3;

  function nearestNeighbour(x, y, grid, cellWidth, cellHeight, halfX, halfY) {
    let nearest = Number.POSITIVE_INFINITY;
    const firstColumn = Math.floor((x - halfX) / cellWidth) - SEARCH_CELLS;
    const lastColumn = Math.floor((x + halfX) / cellWidth) + SEARCH_CELLS;
    const firstRow = Math.floor((y - halfY) / cellHeight) - SEARCH_CELLS;
    const lastRow = Math.floor((y + halfY) / cellHeight) + SEARCH_CELLS;
    for (let column = firstColumn; column <= lastColumn; column += 1) {
      for (let row = firstRow; row <= lastRow; row += 1) {
        const bucket = grid.get(`${column}:${row}`);
        if (!bucket) continue;
        for (const point of bucket) {
          const dx = (x - point.x) / Math.max(halfX * 2, 1);
          const dy = (y - point.y) / Math.max(halfY * 2, 1);
          const distance = Math.sqrt(dx * dx + dy * dy);
          if (distance < nearest) nearest = distance;
        }
      }
    }
    return nearest;
  }

  // Bubbles are placed at random positions; candidates that overlap existing bubbles
  // or the QR card are skipped. Later bubbles accept a best-effort slot so that a
  // crowded wall (up to 500 signatures) still fills the screen instead of stalling.
  //
  // The bar for "far enough" has to loosen as the wall fills: at a few hundred signatures a
  // perfectly free slot often does not exist, and insisting on one made most bubbles fall back to
  // their best attempt — which is how pairs ended up almost on top of each other (a minimum centre
  // distance of 0.11 bubble widths at 200 signatures). Looking for `CROWDED_MIN_DISTANCE` instead
  // keeps neighbours readable while still spreading them out.
  const SPARSE_MIN_DISTANCE = 1;
  const CROWDED_MIN_DISTANCE = 0.72;
  const CROWDED_FROM = 60;

  function randomPosition(item, index, placed, grid, layout) {
    const stageWidth = Math.max(layout.stageWidth, 480);
    const stageHeight = Math.max(layout.stageHeight, 320);
    const halfX = ((layout.metrics.stepWidth / 2) / stageWidth) * 100;
    const halfY = ((layout.metrics.stepHeight / 2) / stageHeight) * 100;
    const cellWidth = Math.max(halfX * 2, 0.5);
    const cellHeight = Math.max(halfY * 2, 0.5);
    const minX = halfX + 1.5;
    const maxX = 100 - halfX - 1.5;
    const minY = halfY + 4;
    const maxY = 100 - halfY - 4;
    const crowded = placed.length > CROWDED_FROM;
    const wanted = crowded ? CROWDED_MIN_DISTANCE : SPARSE_MIN_DISTANCE;
    // The attempt budget is what decides whether the wall looks spread out or piled up. With a
    // small pool (12–24 candidates) most bubbles never find a slot that clears the bar and fall
    // back to their best attempt, which at 200 signatures produced stack-like clusters. Sampling
    // more candidates is cheap — the distance query only touches nine grid cells — so a crowded
    // wall gets a much larger pool.
    const attempts = placed.length > 200 ? 72 : crowded ? 96 : 60;
    let best = null;
    let bestScore = -1;

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const seed = `${item.id}:${index}:${attempt}`;
      const x = minX + randomRatio(seed, 'x') * (maxX - minX);
      const y = minY + randomRatio(seed, 'y') * (maxY - minY);
      if (overlapsQrCard(layout.qr, x, y, halfX, halfY)) continue;
      const nearest = nearestNeighbour(x, y, grid, cellWidth, cellHeight, halfX, halfY);
      if (nearest >= wanted) {
        best = { x, y };
        break;
      }
      if (nearest > bestScore) {
        bestScore = nearest;
        best = { x, y };
      }
    }

    const position = best || { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
    position.rotation = (randomRatio(`${item.id}:${index}`, 'r') - 0.5) * 9;
    position.drift = 6 + randomRatio(`${item.id}:${index}`, 'd') * 7;
    position.delay = randomRatio(`${item.id}:${index}`, 't') * -6;

    const column = Math.floor(position.x / cellWidth);
    const row = Math.floor(position.y / cellHeight);
    const key = `${column}:${row}`;
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(position);
    placed.push(position);
    return position;
  }

  // ---------------------------------------------------------------------------
  // Placing a crowded wall.
  //
  // The wall has been through three placement rules for a big crowd, and each one was measured:
  //
  //   1. Sequential random placement (the sparse rule, below) approaches the random-sequential
  //      jamming limit as the wall fills: at a few hundred signatures most candidates have no free
  //      slot, so most bubbles fall back to their least-bad attempt and the wall ends up with
  //      signatures piled on each other — at 200 signatures, 333 pairs closer than 0.6 bubble widths,
  //      the tightest pair 0.16 apart, which is one signature covering another.
  //   2. A jittered lattice fixed that: the stage was divided into cells one bubble apart in each
  //      direction, items were dealt into a shuffled order so old and new signatures mixed, and each
  //      was offset by a small random amount. Spacing became perfect — but the offset could only ever
  //      be as large as the slack between the bubble and its cell, which at 200 signatures on a
  //      1884x1044 stage is 1.7 px across and 1.6 px down, and at 500 signatures barely 1 px. Every
  //      signature therefore sat within about one pixel of its cell centre: the wall was a perfect
  //      grid with holes in it, and that is what the audience sees ("位置分布不够随机").
  //   3. What is used now is a random spread with a minimum spacing, the same idea as Poisson-disc
  //      sampling: candidates are drawn at random over the whole stage and accepted when they clear
  //      every placed signature and the card by the spacing. The even coverage that rule 2 bought is
  //      kept — every pair still clears a bubble, measured below — while positions are free to go
  //      anywhere there is room, so no row, column or repeating gap survives. This is the same
  //      statistical idea as blue-noise sampling, and it is what makes a crowd look like a crowd.
  //
  // Sparse walls keep the sequential placement: with few signatures there is room to spare, and its
  // candidate scoring spreads a handful of them more pleasingly than a spacing rule does.
  // ---------------------------------------------------------------------------
  const SCATTER_FROM = 60;
  // Candidates drawn per signature, at each spacing the placement is willing to accept. The spacing
  // ladder is walked from roomy to tight: a candidate that clears every placed signature by the
  // current radius wins immediately, so a wall with space left stays evenly spread, and only a wall
  // that has genuinely filled up falls to the next rung. The first rung has to be reachable, which
  // is why it is near the crowded spacing rather than a generous one: a radius nothing ever clears
  // would burn the whole budget on every signature and then accept the same candidate anyway.
  // Candidates drawn per signature, rung by rung down the spacing ladder. The first rung has to be
  // reachable, and the budgets are tuned so the common case — a wall with room to spare, where a
  // candidate on the roomiest rung succeeds within the first few draws — costs almost nothing, while
  // a crowded wall that has to walk the whole ladder still finishes in well under a tenth of a
  // second. The wall is laid out again whenever a signature arrives or the screen changes, so this
  // budget is paid repeatedly and is not free to grow.
  const SCATTER_TRIES = [90, 110, 70, 60];
  const SCATTER_RADII = [1.02, 0.96, 0.9, 0.84];

  function scatterLayout(items, options) {
    const { stageWidth, stageHeight, metrics, forbidden } = options;
    // Positions are looked up in a grid of cells three fifths of a bubble wide, and a candidate's
    // neighbourhood is the cell it falls in plus two on each side: that covers 1.2 bubble widths in
    // every direction, comfortably past the widest spacing the ladder asks for, so the lookup can
    // never miss a neighbour. A window that is too small does not fail loudly — it quietly reports a
    // free spot and the wall comes out crowded (measured: shrinking it to a single cell took the
    // wall's tightest pair from 0.9 bubble widths to 0.49). The frame of cells around the candidate
    // holds far fewer signatures than a one-bubble grid does, which is what keeps the search cheap.
    const cellWidth = Math.max(metrics.width * 0.6, 1);
    const cellHeight = Math.max(metrics.height * 0.6, 1);
    const CELLS_AROUND = 2;
    const grid = new Map();
    const cellOf = (x, y) => `${Math.floor(x / cellWidth)}:${Math.floor(y / cellHeight)}`;
    const addPoint = (x, y) => {
      const key = cellOf(x, y);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push({ x, y });
    };
    const nearestDistance = (x, y) => {
      let nearest = Number.POSITIVE_INFINITY;
      const centreColumn = Math.floor(x / cellWidth);
      const centreRow = Math.floor(y / cellHeight);
      for (let column = centreColumn - CELLS_AROUND; column <= centreColumn + CELLS_AROUND; column += 1) {
        for (let row = centreRow - CELLS_AROUND; row <= centreRow + CELLS_AROUND; row += 1) {
          const bucket = grid.get(`${column}:${row}`);
          if (!bucket) continue;
          for (const point of bucket) {
            const dx = (x - point.x) / metrics.width;
            const dy = (y - point.y) / metrics.height;
            const distance = Math.sqrt(dx * dx + dy * dy);
            if (distance < nearest) nearest = distance;
          }
        }
      }
      return nearest;
    };
    const marginX = metrics.width / 2 + 2;
    const marginY = metrics.height / 2 + 2;
    const spanX = stageWidth - marginX * 2;
    const spanY = stageHeight - marginY * 2;

    return items.map((item, index) => {
      const seed = `${item.id}:${index}`;
      // The roomiest candidate seen so far, kept as the answer of last resort: a wall so full that no
      // rung of the ladder is reachable still gets the signature placed, as far from its neighbours
      // as the space allows, rather than dropping it or piling it on the centre.
      let loosest = null;
      let loosestGap = -1;
      let chosen = null;
      for (let rung = 0; rung < SCATTER_RADII.length && !chosen; rung += 1) {
        const radius = SCATTER_RADII[rung];
        const budget = SCATTER_TRIES[Math.min(rung, SCATTER_TRIES.length - 1)];
        for (let attempt = 0; attempt < budget; attempt += 1) {
          const x = marginX + randomRatio(seed, `sx${attempt}`) * spanX;
          const y = marginY + randomRatio(seed, `sy${attempt}`) * spanY;
          if (forbidden && overlapsCard(x, y, forbidden.halfX, forbidden.halfY, forbidden.box)) continue;
          const gap = nearestDistance(x, y);
          if (gap > loosestGap) {
            loosestGap = gap;
            loosest = { x, y };
          }
          if (gap >= radius) {
            chosen = { x, y };
            break;
          }
        }
      }
      const position = chosen || loosest || { x: marginX + spanX / 2, y: marginY + spanY / 2 };
      addPoint(position.x, position.y);
      return {
        item,
        position: {
          x: Math.min(Math.max((position.x / stageWidth) * 100, (marginX / stageWidth) * 100), 100 - (marginX / stageWidth) * 100),
          y: Math.min(Math.max((position.y / stageHeight) * 100, (marginY / stageHeight) * 100), 100 - (marginY / stageHeight) * 100),
          rotation: (randomRatio(seed, 'r') - 0.5) * 9,
          drift: 6 + randomRatio(seed, 'd') * 7,
          delay: randomRatio(seed, 't') * -6,
        },
      };
    });
  }

  // ---------------------------------------------------------------------------
  // Keeping signatures off the QR card.
  //
  // The card is the one element on the wall that must stay readable — an enlarged card that no
  // participant can scan is worse than no card — so the placement treats the card's box as occupied
  // ground in both strategies: the crowded spread rejects any candidate that reaches into it, and the
  // sparse placement rejects candidates that overlap it. Measured with the card taking the
  // bottom-right corner of a 1884x1044 stage: 0 signatures drawn on the card at 20, 100, 200 and 500
  // signatures, where dropping the exclusion put 10 to 26 of them there.
  //
  // What does *not* work is moving the signatures afterwards. Every rule tried for that (clamping to
  // the nearest edge of the box, the closest free slot, the roomiest slot in rings, per-signature
  // slots along the card's edge) either stacked signatures on one pixel or pulled about 2% of the
  // wall into pairs closer than one bubble, because by then the free space has already been used.
  // The reservation has to happen while the signature is being placed, which is what both strategies
  // now do.
  // ---------------------------------------------------------------------------
  const CARD_DRIFT_ALLOWANCE = 12;
  // How far a pushed signature may travel, and how finely its surroundings are sampled.
  const CARD_PUSH_SEARCH = 220;
  const CARD_PUSH_STEP = 10;

  function cardBoxInPixels(qr, stageWidth, stageHeight) {
    if (!qr) return null;
    const left = (qr.left / 100) * stageWidth;
    const right = (qr.right / 100) * stageWidth;
    const top = (qr.top / 100) * stageHeight;
    const bottom = (qr.bottom / 100) * stageHeight;
    if (!(right > left) || !(bottom > top)) return null;
    return { left, right, top, bottom };
  }

  function overlapsCard(x, y, halfX, halfY, box) {
    return x + halfX > box.left && x - halfX < box.right && y + halfY > box.top && y - halfY < box.bottom;
  }

  /**
   * Nearest centre distance in bubble widths, looked up through the placement grid.
   *
   * Every signature is in the grid from the start, including the ones that will be pushed later, so
   * a moved signature can see the signature that is going to stay where its old place was. Checking
   * only against a list of the already-moved signatures — the first version of this — put several
   * signatures on the identical pixel, because the one it moved the first signature next to had not
   * been moved yet and ended up standing on top of it (measured at 500 signatures: pairs at gap 0).
   */
  function nearestPlacedDistance(x, y, grid, cellWidth, cellHeight, metrics) {
    let nearest = Number.POSITIVE_INFINITY;
    const halfX = metrics.width / 2;
    const halfY = metrics.height / 2;
    const firstColumn = Math.floor((x - halfX) / cellWidth) - SEARCH_CELLS;
    const lastColumn = Math.floor((x + halfX) / cellWidth) + SEARCH_CELLS;
    const firstRow = Math.floor((y - halfY) / cellHeight) - SEARCH_CELLS;
    const lastRow = Math.floor((y + halfY) / cellHeight) + SEARCH_CELLS;
    for (let column = firstColumn; column <= lastColumn; column += 1) {
      for (let row = firstRow; row <= lastRow; row += 1) {
        const bucket = grid.get(`${column}:${row}`);
        if (!bucket) continue;
        for (const point of bucket) {
          const dx = (x - point.x) / metrics.width;
          const dy = (y - point.y) / metrics.height;
          const distance = Math.sqrt(dx * dx + dy * dy);
          if (distance < nearest) nearest = distance;
        }
      }
    }
    return nearest;
  }

  function rebuildGrid(bubbles, stageWidth, stageHeight, cellWidth, cellHeight) {
    const grid = new Map();
    bubbles.forEach((bubble) => {
      const x = (bubble.position.x / 100) * stageWidth;
      const y = (bubble.position.y / 100) * stageHeight;
      const key = `${Math.floor(x / cellWidth)}:${Math.floor(y / cellHeight)}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push({ x, y });
    });
    return grid;
  }

  /**
   * Where a signature that landed on the card goes instead.
   *
   * The first free place around its own position, searched in rings, with three rules in order:
   * a place that leaves a full bubble of room from every other signature and a full bubble of
   * clearance from the card wins outright; failing that, the roomiest ring; failing that (a wall
   * packed solid) the first place clear of the card. Measuring the simpler rules was worth it —
   * clamping to the nearest edge of the box, taking the closest slot that merely cleared the box,
   * and aiming at a per-signature slot along the card's edge at four sizes of search all either
   * stacked signatures on one pixel or pulled 2% of the wall into pairs closer than one bubble —
   * and this is the one that keeps the wall's spacing.
   */
  function findCardExit(fromX, fromY, halfX, halfY, box, stageWidth, stageHeight, metrics, grid, cellWidth, cellHeight) {
    const marginX = Math.min(metrics.width / 2 + CARD_DRIFT_ALLOWANCE, stageWidth / 4);
    const marginY = Math.min(metrics.height / 2 + CARD_DRIFT_ALLOWANCE, stageHeight / 4);
    // Distance to the card in bubble widths, so a signature that clears it by a hair does not look
    // like one with room around it.
    const cardDistance = (pointX, pointY) => Math.max(
      (pointX - (box.left + box.right) / 2) / metrics.width - (box.right - box.left) / 2 / metrics.width,
      (pointY - (box.top + box.bottom) / 2) / metrics.height - (box.bottom - box.top) / 2 / metrics.height,
    );
    let best = null;
    const accept = (candidate) => {
      if (candidate.gap >= 1) {
        best = candidate;
        return true;
      }
      if (!best || candidate.gap > best.gap + 1e-9) best = candidate;
      return false;
    };
    for (let radius = 0; radius <= CARD_PUSH_SEARCH; radius += CARD_PUSH_STEP) {
      const samples = radius === 0 ? 1 : 12;
      for (let index = 0; index < samples; index += 1) {
        const angle = (index / samples) * Math.PI * 2;
        const x = Math.min(Math.max(fromX + Math.cos(angle) * radius, marginX), stageWidth - marginX);
        const y = Math.min(Math.max(fromY + Math.sin(angle) * radius, marginY), stageHeight - marginY);
        if (overlapsCard(x, y, halfX, halfY, box)) continue;
        const gap = Math.min(
          nearestPlacedDistance(x, y, grid, cellWidth, cellHeight, metrics),
          cardDistance(x, y),
        );
        if (accept({ x, y, gap, travel: radius })) return best;
      }
    }
    return best;
  }

  /**
   * Push every signature that landed on the QR card clear of it, in place and deterministically.
   *
   * `bubbles` is the provisional arrangement; the result keeps the order and every unaffected
   * position, so the wall and the exported picture still agree.
   */
  function keepSignaturesOffCard(bubbles, box, stageWidth, stageHeight, metrics) {
    if (!box) return bubbles;
    const halfX = metrics.width / 2 + CARD_DRIFT_ALLOWANCE;
    const halfY = metrics.height / 2 + CARD_DRIFT_ALLOWANCE;
    const cellWidth = Math.max(metrics.width, 1);
    const cellHeight = Math.max(metrics.height, 1);
    const grid = rebuildGrid(bubbles, stageWidth, stageHeight, cellWidth, cellHeight);
    // Every position lives in the grid under its own cell. A moved signature takes its own entry out
    // first: while it is still there it is its own nearest neighbour, every candidate then scores the
    // same distance to itself, and the search stops being able to tell a free slot from an occupied
    // one.
    const cellOf = (pointX, pointY) => `${Math.floor(pointX / cellWidth)}:${Math.floor(pointY / cellHeight)}`;
    const removeFromGrid = (pointX, pointY) => {
      const bucket = grid.get(cellOf(pointX, pointY));
      if (!bucket) return;
      const index = bucket.findIndex((point) => point.x === pointX && point.y === pointY);
      if (index >= 0) bucket.splice(index, 1);
    };
    const addToGrid = (pointX, pointY) => {
      const key = cellOf(pointX, pointY);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push({ x: pointX, y: pointY });
    };
    return bubbles.map((bubble) => {
      const x = (bubble.position.x / 100) * stageWidth;
      const y = (bubble.position.y / 100) * stageHeight;
      if (!overlapsCard(x, y, halfX, halfY, box)) return bubble;
      removeFromGrid(x, y);
      // A candidate that clears the card always exists: the wall caps the card at a third of the
      // stage, so at least two thirds of the wall is free of it.
      const exit = findCardExit(
        x, y, halfX, halfY, box, stageWidth, stageHeight, metrics, grid, cellWidth, cellHeight,
      );
      if (!exit) {
        // Nowhere clear of the card: put it back rather than lose it.
        addToGrid(x, y);
        return bubble;
      }
      addToGrid(exit.x, exit.y);
      return {
        item: bubble.item,
        position: {
          ...bubble.position,
          x: (exit.x / stageWidth) * 100,
          y: (exit.y / stageHeight) * 100,
        },
      };
    });
  }

  // `options.stageWidth/Height` must be the stage exactly as the wall measures it
  // (`#wall-stage` client size) and `options.qr` the card box in stage percentages, or the
  // result will be a different, though still valid, arrangement. `options.count` is the number of
  // signatures on the wall and decides how large each one is drawn; it defaults to the number of
  // items, and the monitor passes the same value so its export matches.
  function computeWallLayout(items, options) {
    const { stageWidth, stageHeight, qr, count } = options || {};
    // The stage size reaches the metrics as well, because the signature sizes are a share of the
    // stage: that is what keeps them aligned with the background when the screen changes.
    const metrics = metricsFor(typeof count === 'number' ? count : items.length, {
      stageWidth,
      stageHeight,
    });
    // The QR card is honoured by both strategies while they place: the crowded spread rejects any
    // candidate that reaches into the card, and the sparse placement rejects candidates that overlap
    // it (and, as a backstop, pushes whatever still reaches into the card clear of it, which is what
    // keeps a wall laid out before the card grew from hiding signatures behind it). Both need the
    // card's box in pixels and the bubble size, so a candidate is judged against the same rectangle
    // the wall draws the card at.
    const cardBox = cardBoxInPixels(qr, stageWidth, stageHeight);
    const halfX = metrics.width / 2 + CARD_DRIFT_ALLOWANCE;
    const halfY = metrics.height / 2 + CARD_DRIFT_ALLOWANCE;
    if (items.length >= SCATTER_FROM) {
      return {
        stageWidth,
        stageHeight,
        qr: qr || null,
        metrics,
        strategy: 'scatter',
        bubbles: scatterLayout(items, {
          stageWidth,
          stageHeight,
          metrics,
          forbidden: cardBox ? { box: cardBox, halfX, halfY } : null,
        }),
      };
    }
    const layout = { stageWidth, stageHeight, qr: qr || null, metrics };
    const placed = [];
    const grid = new Map();
    return {
      stageWidth,
      stageHeight,
      qr: layout.qr,
      metrics,
      strategy: 'sequential',
      bubbles: keepSignaturesOffCard(
        items.map((item, index) => ({
          item,
          position: randomPosition(item, index, placed, grid, layout),
        })),
        cardBox,
        stageWidth,
        stageHeight,
        metrics,
      ),
    };
  }

  // The floating QR card lives in the bottom-right corner; keeping bubbles out of it means
  // a fresh signature is never hidden behind the panel.
  function qrBoundsFromRect(cardRect, stageRect, padding) {
    if (!cardRect || !stageRect || !stageRect.width || !stageRect.height) return null;
    const clearance = padding === undefined ? 10 : padding;
    return {
      left: ((cardRect.left - stageRect.left - clearance) / stageRect.width) * 100,
      right: ((cardRect.right - stageRect.left + clearance) / stageRect.width) * 100,
      top: ((cardRect.top - stageRect.top - clearance) / stageRect.height) * 100,
      bottom: ((cardRect.bottom - stageRect.top + clearance) / stageRect.height) * 100,
    };
  }

  // ---------------------------------------------------------------------------
  // The geometry the arrangement depends on: the stage size and the QR card's box inside it.
  // Both the wall and the monitor pass the same values to `computeWallLayout`, and the display
  // publishes them (wallSync.js) so the monitor does not have to guess them.
  // ---------------------------------------------------------------------------
  function layoutDescriptor(stageElement, cardElement) {
    if (!stageElement) return null;
    const stageWidth = stageElement.clientWidth;
    const stageHeight = stageElement.clientHeight;
    if (stageWidth < 2 || stageHeight < 2) return null;
    return {
      stageWidth,
      stageHeight,
      qr: cardElement
        ? qrBoundsFromRect(cardElement.getBoundingClientRect(), stageElement.getBoundingClientRect(), 10)
        : null,
      count: lastMetrics ? lastMetrics.count : undefined,
    };
  }

  function layoutFromDescriptor(descriptor) {
    if (!descriptor || !descriptor.stageWidth || !descriptor.stageHeight) return null;
    return {
      stageWidth: descriptor.stageWidth,
      stageHeight: descriptor.stageHeight,
      qr: descriptor.qr || null,
      count: descriptor.count,
    };
  }

  // The sizes the wall is currently drawing with, published by display.js so the monitor's export
  // can draw at the same scale. Only the count travels (as `count` in the geometry): the sizes are
  // derived from it by `metricsFor`, so the two pages cannot disagree about them.
  let lastMetrics = null;

  function rememberMetrics(metrics, count) {
    lastMetrics = { metrics, count };
  }

  window.wallLayout = {
    computeWallLayout,
    qrBoundsFromRect,
    metricsFor,
    bubbleScaleFor,
    stageScaleFor,
    rememberMetrics,
    lastMetrics: () => lastMetrics,
    descriptorOf: layoutDescriptor,
    fromDescriptor: layoutFromDescriptor,
    // Exposed for the layout tests: they check the card push on its own, without a browser.
    keepSignaturesOffCard,
    cardBoxInPixels,
    cardBoxInPixels,
    CARD_DRIFT_ALLOWANCE,
    CROWDED_FROM,
    CROWDED_MIN_DISTANCE,
    SPARSE_MIN_DISTANCE,
    REFERENCE_STAGE,
    BASE_WIDTH,
    BASE_HEIGHT,
    BASE_INK_WIDTH,
    BASE_INK_HEIGHT,
    BASE_NAME_SIZE,
  };
})();
