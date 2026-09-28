/**
 * Compare bubble scales for a given number of signatures on a given wall.
 *
 * The placement rule (`wallLayout.js`) is deterministic, so the arrangement for a crowd can be
 * computed here without a browser and scored: how much of the wall the bubbles cover, how many of
 * them still overlap, and how small the ink gets. That is how the scale table was chosen.
 *
 * Usage:
 *     node tests/scale_report.mjs [count] [stageWidth] [stageHeight]
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'static', 'wallLayout.js'), 'utf8');

// The module attaches itself to `window`; give it one, plus the browser globals it touches.
const sandbox = { window: {}, Math, Number, Array, Map };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const { wallLayout } = sandbox.window;

const count = Number(process.argv[2] || 200);
const stageWidth = Number(process.argv[3] || 1920);
const stageHeight = Number(process.argv[4] || 1080);

// The QR card sits in the bottom-right corner of the wall; the same box as styles.css.
const qr = {
  left: ((stageWidth - 34 - 218 - 10) / stageWidth) * 100,
  right: ((stageWidth - 34 + 10) / stageWidth) * 100,
  top: ((stageHeight - 34 - 159 - 10) / stageHeight) * 100,
  bottom: ((stageHeight - 34 + 10) / stageHeight) * 100,
};

const items = Array.from({ length: count }, (_, index) => ({ id: index + 1, name: `签名${index + 1}` }));

console.log(`wall ${stageWidth}x${stageHeight}, settled for ${count} signatures`);
console.log('count  scale  bubble   ink     step    cover    overlap  min-dist  p05   failed');
console.log('                                              (pairs<0.6)        (bubble widths)');

// The arrangement the wall would settle on for `count` signatures, with `items` filtered to that
// many: this is what a real event at that size looks like, not a smaller crowd on a big stage.
for (const sample of [12, 40, 60, 90, 120, 160, 200, 260, 320, 400, 500]) {
  const list = items.slice(0, sample);
  const layout = wallLayout.computeWallLayout(list, { stageWidth, stageHeight, qr });
  const { metrics } = layout;
  const boxes = layout.bubbles.map(({ position }) => ({
    x: (position.x / 100) * stageWidth,
    y: (position.y / 100) * stageHeight,
  }));
  // Distances in units of the bubble size: 1 means two neighbours just touch.
  const distances = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const dx = Math.abs(boxes[i].x - boxes[j].x) / metrics.width;
      const dy = Math.abs(boxes[i].y - boxes[j].y) / metrics.height;
      distances.push(Math.max(dx, dy));
    }
  }
  distances.sort((a, b) => a - b);
  const pick = (q) => distances[Math.min(distances.length - 1, Math.floor(distances.length * q))] || 0;
  const overlapping = distances.filter((value) => value < 0.6).length;
  const crowded = distances.filter((value) => value < 1).length;

  const cell = 6;
  const covered = new Set();
  for (const box of boxes) {
    for (let cx = Math.floor((box.x - metrics.width / 2) / cell); cx <= Math.floor((box.x + metrics.width / 2) / cell); cx += 1) {
      for (let cy = Math.floor((box.y - metrics.height / 2) / cell); cy <= Math.floor((box.y + metrics.height / 2) / cell); cy += 1) {
        covered.add(`${cx}:${cy}`);
      }
    }
  }
  const coverage = (covered.size * cell * cell) / (stageWidth * stageHeight);

  console.log(
    `${String(sample).padStart(5)}  ${metrics.scale.toFixed(2)}  `
    + `${`${metrics.width}x${metrics.height}`.padEnd(7)} `
    + `${`${metrics.inkWidth}x${metrics.inkHeight}`.padEnd(7)} `
    + `${`${metrics.stepWidth}x${metrics.stepHeight}`.padEnd(7)} `
    + `${(coverage * 100).toFixed(1).padStart(5)}%  `
    + `${String(overlapping).padStart(7)}  ${pick(0).toFixed(2).padStart(7)}  `
    + `${pick(0.05).toFixed(2).padStart(5)}  ${String(crowded).padStart(6)}`,
  );
}
