// command_room.js — Milestone 3: the 3D "hub" room. One box per workspace,
// click a box to go there. No first-person movement, no walking — you
// confirmed the Fallout Shelter cross-section + Tamagotchi feel is about
// clickable rooms/objects, not a first-person walkable space.
//
// Three.js concepts used here, since this is new territory:
//
//   Scene    — the 3D world. Anything you want visible gets added to it.
//   Camera   — where you're looking from. This uses an OrthographicCamera,
//              not the more common PerspectiveCamera — orthographic has no
//              vanishing point, which is exactly what gives Fallout
//              Shelter's cross-section its flat, diagram-like look instead
//              of realistic depth. The camera's args are a world-space box
//              (left/right/top/bottom), not a field-of-view angle.
//   Renderer — draws Scene+Camera onto a <canvas>, once per frame.
//   Mesh     — a visible object = Geometry (its shape) + Material (its
//              surface: color, how it reacts to light).
//   Raycaster — there's no built-in "click this 3D object" event. Instead
//              you cast an invisible line from the camera through the
//              mouse position into the scene, and ask what it hit. That's
//              the whole mechanism behind click-a-box-to-navigate below.

import * as THREE from './vendor/three.module.js';

const canvas = document.getElementById('command-room-canvas');
const hoverLabel = document.getElementById('command-room-label');

// Injected by command_room.html from the Flask route — real URLs, not
// hardcoded here, so this file doesn't need to know about Flask routing.
const rooms = JSON.parse(document.getElementById('command-room-data').textContent);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111); // matches body background in style.css

// --- Camera --------------------------------------------------------------
const viewSize = 8;
let camera;

function buildCamera() {
  const aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
  camera = new THREE.OrthographicCamera(
    -viewSize * aspect, viewSize * aspect,
    viewSize, -viewSize,
    0.1, 100
  );
  // Fixed isometric-ish angle, looking down into the room. No orbit
  // controls - if the layout changes later, this is the one spot to
  // adjust.
  camera.position.set(10, 10, 10);
  camera.lookAt(0, 0, 0);
}
buildCamera();

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });

function resize() {
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  renderer.setPixelRatio(window.devicePixelRatio);
  buildCamera();
}
window.addEventListener('resize', resize);
resize();

// --- Lighting --------------------------------------------------------------
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 0.8);
sun.position.set(5, 10, 7);
scene.add(sun);

// --- Floor -------------------------------------------------------------
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(24, 24),
  new THREE.MeshStandardMaterial({ color: 0x1c2230 })
);
floor.rotation.x = -Math.PI / 2;
scene.add(floor);

// --- Room objects --------------------------------------------------------
// Placeholder boxes, one per workspace, laid out in a row. Real modeled
// furniture (the vision doc's "3D computer" for Ground Control, the
// study bookshelf for R&D) is a later pass, once this click-to-navigate
// mechanic itself is proven out.
const clickable = [];
const spacing = 4;
const startX = -((rooms.length - 1) * spacing) / 2;

rooms.forEach((room, i) => {
  const box = new THREE.Mesh(
    new THREE.BoxGeometry(2, 2, 2),
    new THREE.MeshStandardMaterial({ color: room.color })
  );
  box.position.set(startX + i * spacing, 1, 0);
  box.userData.room = room;
  scene.add(box);
  clickable.push(box);
});

// --- Raycasting: hover + click --------------------------------------------
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let hovered = null;

function pointerFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

function pickRoom(event) {
  pointerFromEvent(event);
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(clickable);
  return hits.length ? hits[0].object : null;
}

canvas.addEventListener('mousemove', (event) => {
  const hit = pickRoom(event);

  if (hit !== hovered) {
    if (hovered) hovered.scale.set(1, 1, 1);
    hovered = hit;
    if (hovered) hovered.scale.set(1.15, 1.15, 1.15);
  }

  canvas.style.cursor = hit ? 'pointer' : 'default';

  if (hit) {
    hoverLabel.textContent = hit.userData.room.label;
    hoverLabel.style.left = `${event.clientX + 16}px`;
    hoverLabel.style.top = `${event.clientY + 16}px`;
    hoverLabel.hidden = false;
  } else {
    hoverLabel.hidden = true;
  }
});

canvas.addEventListener('click', (event) => {
  const hit = pickRoom(event);
  if (hit) window.location.href = hit.userData.room.url;
});

// --- Render loop -----------------------------------------------------------
function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();
