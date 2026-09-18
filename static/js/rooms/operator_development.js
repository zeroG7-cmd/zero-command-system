// operator_development.js — the first real themed room: Operator
// Development, split into three zones (gym / study / reflection) per your
// description. Two things happen here that command_room.js didn't do:
//
// 1. Zoned floor instead of one flat plane — three colored PlaneGeometry
//    strips laid side by side, each tagged with a zone name.
// 2. Clicking yourself (the avatar capsule) doesn't navigate anywhere —
//    it opens an in-scene panel with real stat data fetched from
//    /operator/api/summary, and the room stays visible behind it. That's
//    the actual pattern you asked for: popups over a persistent world,
//    not page jumps. The bookshelf is visible but not clickable yet -
//    that's next, once this pattern is proven with real data.

import * as THREE from '../vendor/three.module.js';

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
// decided yet). Capsule, not a box, so it visually reads as a figure
// rather than another piece of furniture.
const avatar = new THREE.Mesh(
  new THREE.CapsuleGeometry(0.6, 1.4, 4, 8),
  new THREE.MeshStandardMaterial({ color: 0xf2c14e })
);
avatar.position.set(0, 1.2, 2.5);
avatar.userData.label = 'Zero (click for stats)';
avatar.userData.action = 'stats';
scene.add(avatar);
clickable.push(avatar);

// Bookshelf - visible in the study zone, not interactive yet. Will
// eventually open the Learning Hub's course/completion data the same
// way the avatar opens stats.
const bookshelf = new THREE.Mesh(
  new THREE.BoxGeometry(1.6, 2.2, 0.6),
  new THREE.MeshStandardMaterial({ color: 0x8a6a3d })
);
bookshelf.position.set(1.8, 1.1, -1.5);
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
  const hits = raycaster.intersectObjects(clickable);
  return hits.length ? hits[0].object : null;
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
