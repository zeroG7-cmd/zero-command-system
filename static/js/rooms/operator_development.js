// operator_development.js — the first real themed room: Operator
// Development, split into three zones (gym / study / reflection) per your
// description. Three things happen here that command_room.js didn't do:
//
// 1. Zoned floor instead of one flat plane — three colored PlaneGeometry
//    strips laid side by side, each tagged with a zone name.
// 2. Clicking yourself (the avatar) doesn't navigate anywhere - it opens
//    an in-scene panel with real stat data fetched from
//    /operator/api/summary, and the room stays visible behind it. (Note:
//    the plan going forward is for this to instead navigate to a full
//    separate profile page - that hasn't been built yet, this is still
//    the panel behavior.) The bookshelf is visible but not clickable yet -
//    that's next, once this pattern is proven with real data.
// 3. The avatar and bookshelf are chunky voxel models built by
//    voxel_builder.js instead of a placeholder capsule/cuboid - the
//    avatar from your actual zero_pixel_mini_v2.png pixel art (see
//    static/data/zero_avatar_voxel.json), the bookshelf fully procedural.

import * as THREE from '../vendor/three.module.js';
import { buildVoxelAvatar, buildVoxelBookshelf } from '../voxel_builder.js';

const canvas = document.getElementById('operator-room-canvas');
const hoverLabel = document.getElementById('operator-room-label');
const statPanel = document.getElementById('stat-panel');
const statPanelBody = document.getElementById('stat-panel-body');
const statPanelClose = document.getElementById('stat-panel-close');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);

// --- Camera --------------------------------------------------------------
const viewSize = 7;
let camera;

function buildCamera() {
  const aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
  camera = new THREE.OrthographicCamera(
    -viewSize * aspect, viewSize * aspect,
    viewSize, -viewSize,
    0.1, 100
  );
  camera.position.set(9, 10, 9);
  camera.lookAt(0, 0, 0);
}
buildCamera();

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });

function resize() {
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  renderer.setPixelRatio(window.devicePixelRatio);
  buildCamera();
}
resize();

// A ResizeObserver on the canvas itself, not just window resize: on the
// home page this room gets reparented and animated from a small grid
// tile up to filling the whole stage (see home.js's click-to-zoom), and
// that never fires a window resize event. Watching the canvas directly
// means the render buffer stays matched to its on-screen size throughout
// that animation instead of stretching a low-res image.
new ResizeObserver(resize).observe(canvas);

// --- Lighting --------------------------------------------------------------
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 0.8);
sun.position.set(5, 10, 7);
scene.add(sun);

// --- Zoned floor -----------------------------------------------------------
// Three strips side by side: gym (left) / study (center) / reflection
// (right). Colors are placeholders, not a final art direction.
const zones = [
  { name: 'Gym', color: 0x2f3a2a, x: -6 },
  { name: 'Study', color: 0x2a2f3a, x: 0 },
  { name: 'Reflection', color: 0x3a2f36, x: 6 },
];

zones.forEach((zone) => {
  const tile = new THREE.Mesh(
    new THREE.PlaneGeometry(6, 12),
    new THREE.MeshStandardMaterial({ color: zone.color })
  );
  tile.rotation.x = -Math.PI / 2;
  tile.position.set(zone.x, 0, 0);
  scene.add(tile);
});

// --- Objects ---------------------------------------------------------------
const clickable = [];

// The avatar - stands in the study zone for now (no fixed "home spot"
// decided yet). Built from your actual zero_pixel_mini_v2.png pixel art
// (see static/data/zero_avatar_voxel.json + scripts/build_avatar_voxels.py),
// extruded into voxels via the shared builder. The back half of the
// extrusion currently mirrors the front pixel data rather than using a
// real back-view reference - swap in a proper chibi back image and
// regenerate the JSON once you've drawn one; nothing else needs to change.
// Loaded async since it comes from a fetched JSON file, so it fades in a
// beat after the rest of the room rather than blocking first render.
fetch('/static/data/zero_avatar_voxel.json')
  .then((response) => response.json())
  .then((gridData) => {
    // depth was originally 4, which at this voxelSize made the figure
    // roughly 10x thinner than it is wide - basically a slab, which is
    // why it read as a flat 2D cutout under this room's static isometric
    // camera. 19 voxels deep is proportional to the 42-wide grid instead
    // (confirmed by re-rendering under this exact camera before shipping).
    const avatar = buildVoxelAvatar(gridData, { voxelSize: 0.048, depth: 19 });
    avatar.position.set(0, 0, 2.5);
    avatar.userData.label = 'Zero (click for stats)';
    avatar.userData.action = 'stats';
    scene.add(avatar);
    clickable.push(avatar);
  })
  .catch((err) => {
    console.error('Could not load the voxel avatar, falling back to a placeholder capsule:', err);
    const fallback = new THREE.Mesh(
      new THREE.CapsuleGeometry(0.6, 1.4, 4, 8),
      new THREE.MeshStandardMaterial({ color: 0xf2c14e })
    );
    fallback.position.set(0, 1.2, 2.5);
    fallback.userData.label = 'Zero (click for stats)';
    fallback.userData.action = 'stats';
    scene.add(fallback);
    clickable.push(fallback);
  });

// Bookshelf - a real procedural voxel model (frame, shelves, individual
// books) instead of a single cuboid. Not interactive yet. Will eventually
// open the Learning Hub's course/completion data the same way the avatar
// opens stats.
const bookshelf = buildVoxelBookshelf({ voxelSize: 0.1 });
bookshelf.position.set(1.8, 0, -1.5);
scene.add(bookshelf);

// Gym equipment placeholder.
const gymRack = new THREE.Mesh(
  new THREE.BoxGeometry(1.4, 1.8, 1.4),
  new THREE.MeshStandardMaterial({ color: 0x4b5d3a })
);
gymRack.position.set(-6, 0.9, 0);
scene.add(gymRack);

// Reflection-corner placeholder (a mat/cushion).
const cushion = new THREE.Mesh(
  new THREE.CylinderGeometry(0.9, 0.9, 0.3, 24),
  new THREE.MeshStandardMaterial({ color: 0x6a4b5d })
);
cushion.position.set(6, 0.15, 0);
scene.add(cushion);

// --- Raycasting: hover + click --------------------------------------------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let hovered = null;

function pointerFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

function pick(event) {
  pointerFromEvent(event);
  raycaster.setFromCamera(pointer, camera);
  // recursive: true because the voxel avatar is a Group of InstancedMeshes,
  // not a single mesh - a hit lands on one of those children, so walk back
  // up to whichever ancestor actually carries the clickable userData.
  const hits = raycaster.intersectObjects(clickable, true);
  if (!hits.length) return null;
  let obj = hits[0].object;
  while (obj && !obj.userData.action && obj.parent) obj = obj.parent;
  return obj && obj.userData.action ? obj : null;
}

canvas.addEventListener('mousemove', (event) => {
  const hit = pick(event);

  if (hit !== hovered) {
    if (hovered) hovered.scale.set(1, 1, 1);
    hovered = hit;
    if (hovered) hovered.scale.set(1.1, 1.1, 1.1);
  }

  canvas.style.cursor = hit ? 'pointer' : 'default';

  if (hit) {
    hoverLabel.textContent = hit.userData.label;
    hoverLabel.style.left = `${event.clientX + 16}px`;
    hoverLabel.style.top = `${event.clientY + 16}px`;
    hoverLabel.hidden = false;
  } else {
    hoverLabel.hidden = true;
  }
});

canvas.addEventListener('click', (event) => {
  const hit = pick(event);
  if (hit && hit.userData.action === 'stats') openStatPanel();
});

// --- Stat panel --------------------------------------------------------
function statBarRow(stat) {
  // A genuine fractional level (capability levels average up through
  // subcategory -> category -> main stat -> this row), not a display
  // artifact - plain decimal, no "Lv" label, matching the full dashboard.
  return `
    <div class="stat-row">
      <span class="stat-name">${stat.name}</span>
      <span class="stat-value">${stat.average_level.toFixed(2)}</span>
    </div>
  `;
}

async function openStatPanel() {
  statPanel.hidden = false;
  statPanelBody.textContent = 'Loading…';

  try {
    const response = await fetch('/operator/api/summary');
    const data = await response.json();

    if (data.error) {
      statPanelBody.innerHTML = `<p class="stat-error">${data.error}</p>`;
      return;
    }

    statPanelBody.innerHTML = `
      <h2>${data.operator_name} — ${data.operator_title}</h2>
      <p class="stat-sub">Level ${data.operator_level} · ${data.total_xp} XP
        (${data.xp_to_next_level} to next level)</p>
      <div class="stat-grid">
        ${data.main_stats.map(statBarRow).join('')}
      </div>
      <a class="learning-button" href="${data.skill_tree_url}">View Skill Tree</a>
    `;
  } catch (err) {
    statPanelBody.innerHTML = `<p class="stat-error">Couldn't reach the backend: ${err.message}</p>`;
  }
}

statPanelClose.addEventListener('click', () => {
  statPanel.hidden = true;
});

// --- Render loop -----------------------------------------------------------
function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();
