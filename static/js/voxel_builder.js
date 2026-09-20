// voxel_builder.js — shared helpers for turning pixel-art data and simple
// procedural descriptions into chunky voxel THREE.Group objects, in the
// same visual language across the avatar and room furniture.
//
// Two builders live here:
//   buildVoxelAvatar(gridData, opts)   - from a pixel-art grid (front real,
//                                         back mirrored until a real back
//                                         reference exists)
//   buildVoxelBookshelf(opts)          - fully procedural, no source image
//
// Both use THREE.InstancedMesh grouped by color so a few thousand small
// cubes cost one draw call per color instead of one per cube.

import * as THREE from './vendor/three.module.js';

function instanceGroup(byColor, voxelSize, positionFn) {
  const group = new THREE.Group();
  const dummy = new THREE.Object3D();
  const geo = new THREE.BoxGeometry(voxelSize * 0.97, voxelSize * 0.97, voxelSize * 0.97);
  for (const [hex, cells] of Object.entries(byColor)) {
    const mat = new THREE.MeshStandardMaterial({ color: '#' + hex, roughness: 0.78, metalness: 0.04 });
    const inst = new THREE.InstancedMesh(geo, mat, cells.length);
    inst.castShadow = true;
    inst.receiveShadow = true;
    let i = 0;
    for (const cell of cells) {
      positionFn(dummy, cell);
      dummy.updateMatrix();
      inst.setMatrixAt(i++, dummy.matrix);
    }
    group.add(inst);
  }
  return group;
}

/**
 * gridData: { w, h, front: [[hex|null,...],...], back: [[hex|null,...],...] }
 * as produced by scripts/build_avatar_voxels.py (see that file for how the
 * back layer is currently a mirrored stand-in, not a real back reference).
 */
export function buildVoxelAvatar(gridData, opts = {}) {
  const voxelSize = opts.voxelSize ?? 0.075;
  const depth = opts.depth ?? 4;
  const { w: COLS, h: ROWS, front, back } = gridData;
  const halfDepth = Math.floor(depth / 2);

  const byColor = {};
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const frontHex = front[r][c];
      const backHex = back[r][c];
      for (let d = 0; d < depth; d++) {
        // Front half of the extrusion uses the real front pixel data,
        // back half uses the mirrored stand-in - see module doc comment.
        const hex = d < halfDepth ? frontHex : (backHex ?? frontHex);
        if (!hex) continue;
        (byColor[hex] ??= []).push([r, c, d]);
      }
    }
  }

  const group = instanceGroup(byColor, voxelSize, (dummy, [r, c, d]) => {
    dummy.position.set(
      (c - COLS / 2 + 0.5) * voxelSize,
      (ROWS - r - 0.5) * voxelSize,
      (d - depth / 2 + 0.5) * voxelSize
    );
  });
  group.userData.footHeight = 0; // model's own origin is at its base already (y=0 = floor)
  group.userData.heightWorld = ROWS * voxelSize;
  return group;
}

/**
 * Fully procedural voxel bookshelf - frame, shelves, and individual books
 * of varying width/height/color/depth so it doesn't read as one slab.
 * No source image; this is authored directly the same way you'd block out
 * a Minecraft build.
 */
export function buildVoxelBookshelf(opts = {}) {
  const voxelSize = opts.voxelSize ?? 0.06;
  const seed = opts.seed ?? 1;

  const W_VOX = 11, H_VOX = 22, D_VOX = 5;
  const WOOD_DARK = '4a2f1c', WOOD_MID = '6a4526', WOOD_TRIM = '3a2413';
  const BOOK_COLORS = ['b23a3a', '3a5fb2', '3a8a52', 'd4a23c', '7a4bb2', '2f2f38', 'c9c9d1', 'b25a2f'];

  const model = Array.from({ length: H_VOX }, () =>
    Array.from({ length: W_VOX }, () => Array(D_VOX).fill(null))
  );
  function set(x, y, z, color) {
    if (x < 0 || x >= W_VOX || y < 0 || y >= H_VOX || z < 0 || z >= D_VOX) return;
    model[y][x][z] = color;
  }
  function fillBox(x0, x1, y0, y1, z0, z1, color) {
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) for (let z = z0; z <= z1; z++) set(x, y, z, color);
  }

  fillBox(0, 0, 0, H_VOX - 1, 0, D_VOX - 1, WOOD_MID);
  fillBox(W_VOX - 1, W_VOX - 1, 0, H_VOX - 1, 0, D_VOX - 1, WOOD_MID);
  fillBox(1, W_VOX - 2, 0, H_VOX - 1, 0, 0, WOOD_DARK);
  fillBox(0, W_VOX - 1, H_VOX - 1, H_VOX - 1, 0, D_VOX - 1, WOOD_TRIM);
  fillBox(0, W_VOX - 1, 0, 0, 0, D_VOX - 1, WOOD_TRIM);

  const shelfYs = [5, 10, 15];
  shelfYs.forEach(y => fillBox(1, W_VOX - 2, y, y, 0, D_VOX - 1, WOOD_TRIM));

  let colorSeed = seed;
  function rnd() { colorSeed = (colorSeed * 1103515245 + 12345) & 0x7fffffff; return colorSeed / 0x7fffffff; }

  const rowBands = [[1, 4], [6, 9], [11, 14], [16, 20]];
  rowBands.forEach(([yFloor, yTop]) => {
    let x = 1;
    while (x < W_VOX - 1) {
      const bookW = rnd() < 0.75 ? 1 : 2;
      if (x + bookW - 1 > W_VOX - 2) break;
      if (rnd() < 0.08) { x += 1; continue; }
      const heightVar = Math.floor(rnd() * 3);
      const bookTop = yTop - heightVar;
      const color = BOOK_COLORS[Math.floor(rnd() * BOOK_COLORS.length)];
      const depth = rnd() < 0.2 ? 2 : 3;
      fillBox(x, x + bookW - 1, yFloor, bookTop, 1, depth, color);
      x += bookW;
    }
  });
  fillBox(2, 4, H_VOX, H_VOX, 1, 3, '3a8a52');
  fillBox(5, 5, H_VOX, H_VOX + 1, 1, 3, 'd4a23c');

  const byColor = {};
  for (let y = 0; y < model.length; y++) {
    for (let x = 0; x < W_VOX; x++) {
      for (let z = 0; z < D_VOX; z++) {
        const c = model[y][x][z];
        if (!c) continue;
        (byColor[c] ??= []).push([x, y, z]);
      }
    }
  }

  const group = instanceGroup(byColor, voxelSize, (dummy, [x, y, z]) => {
    dummy.position.set((x - W_VOX / 2 + 0.5) * voxelSize, y * voxelSize + voxelSize / 2, (z - D_VOX / 2 + 0.5) * voxelSize);
  });
  group.userData.heightWorld = H_VOX * voxelSize;
  group.userData.widthWorld = W_VOX * voxelSize;
  return group;
}
