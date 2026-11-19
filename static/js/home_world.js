// home_world.js - Zero Command home screen (19 Nov 2026 brief).
//
// The world only draws. Brains are in Flask:
//   /home/layout          rooms, walls, colliders (static/data/home_layout.json, routes resolved by url_for)
//   /home/brief           the speech bubble (modules/home_brief.py); ?boot=1 once per app start
//   /operator/api/summary level, XP, overall for the HUD badge
// Rooms are the existing pages: entering one is a normal navigation, and
// coming back (Esc via home_return.js, or any HOME link) lands Zero outside
// the room you came from, worked out from document.referrer.
//
// Style: RETRO 3D on boot (low res, vertex snapping, fog, follow camera);
// V or the camera button switches to LOW-POLY ISO. One scene, two cameras.

import * as THREE from "three";
import { GLTFLoader } from "./vendor/addons/loaders/GLTFLoader.js";

const $ = id => document.getElementById(id);
const worldEl = $("world"), overlay = $("overlay"), fx = $("fx");
fx.classList.add("boot");

// ------------------------------------------------------------------ state
const WORLD = { pick: [], props: [] };   // scene handles shared by the build, loaders and loop
const ST = { style: "retro", bubbleMin: false, hover: null, wallet: false, brief: null, leaving: false };
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* storage off: every load counts as a boot */ } },
};

// ------------------------------------------------------------------ renderer + cameras
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;   // r186 folded PCFSoft into PCF
worldEl.prepend(renderer.domElement);
const scene = new THREE.Scene();
const isoCam = new THREE.OrthographicCamera(-10, 10, 10, -10, -100, 200);
const retroCam = new THREE.PerspectiveCamera(60, 1, .1, 200);
const SNAP = { value: new THREE.Vector2(0, 0) };     // x > 0 turns N64-style vertex snapping on
const RETRO_BG = new THREE.Color(0x2a1220), RETRO_FOG = new THREE.Fog(0x2a1220, 18, 50);
const cam = () => (ST.style === "iso" ? isoCam : retroCam);

// palette: brand black / gold / wine / bone; mint only as tech glow
const C = { black: 0x0E0B10, gold: 0xC9A24A, wine: 0x6A1F3A, wineD: 0x4a1529, bone: 0xE8D9BF, boneD: 0xd2bf9e,
  ground: 0x2b1520, groundD: 0x3c1a29, floor: 0x3a1e27, wood: 0x4a2a30, trunk: 0x5a4436, mint: 0x70FFB4, glass: 0xE8C77E, path: 0xD8BF88 };
const MATS = {};
function patchSnap(m) {
  m.onBeforeCompile = s => {
    s.uniforms.uSnap = SNAP;
    s.vertexShader = "uniform vec2 uSnap;\n" + s.vertexShader.replace("#include <project_vertex>",
      "#include <project_vertex>\n if(uSnap.x>0.){ gl_Position.xy = floor(gl_Position.xy/gl_Position.w*uSnap+.5)/uSnap*gl_Position.w; }");
  };
  return m;
}
function mat(hex, glow = false) {
  const k = hex + (glow ? "g" : "");
  return MATS[k] || (MATS[k] = patchSnap(new THREE.MeshStandardMaterial({ color: hex, flatShading: true, roughness: .92, metalness: 0,
    emissive: glow ? hex : 0x000000, emissiveIntensity: glow ? .7 : 0 })));
}
function add(geo, col, x, y, z, parent = scene, glow = false) {
  const m = new THREE.Mesh(geo, mat(col, glow)); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}
const box = (w, h, d, col, x, y, z, parent = scene, glow = false) => add(new THREE.BoxGeometry(w, h, d), col, x, y, z, parent, glow);
let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

// ------------------------------------------------------------------ boot
const [LAYOUT, summary] = await Promise.all([
  fetch("/home/layout").then(r => r.json()),
  fetch("/operator/api/summary").then(r => r.json()).catch(() => null),
]);
const ROOM = Object.fromEntries(LAYOUT.rooms.map(r => [r.id, r]));
const fromRoom = (() => {   // which room did we just come back from?
  let path = ""; try { path = new URL(document.referrer).pathname; } catch (e) { return null; }
  if (!path || path === "/" || path.startsWith("/home")) return null;
  const hit = LAYOUT.rooms.filter(r => r.route && path.startsWith(new URL(r.route, location.href).pathname))
    .sort((a, b) => b.route.length - a.route.length)[0];
  return hit ? hit.id : null;
})();
const isBoot = !store.get("zc_booted");
store.set("zc_booted", "1");


// ------------------------------------------------------------------ world build
function buildWorld() {
  box(36, .5, 36, C.black, 0, -.3, 0);
  box(33, .1, 33, C.ground, 0, -.05, 0);
  for (let i = 0; i < 70; i++) { const x = (rnd() - .5) * 31, z = (rnd() - .5) * 31; if (Math.abs(x) < 13.5 && z > -10.5 && z < 8.5) continue; box(.3, .08, .3, C.groundD, x, .04, z); }
  box(26, .1, 18, C.floor, 0, .05, -1);
  for (let x = -12; x <= 12; x += 1.5) box(.04, .005, 18, C.wood, x, .1, -1);
  for (const [x0, z0, x1, z1, h] of LAYOUT.walls) {
    const w = Math.abs(x1 - x0) || .3, d = Math.abs(z1 - z0) || .3;
    box(w, h, d, h > 2 ? C.bone : C.boneD, (x0 + x1) / 2, h / 2 + .1, (z0 + z1) / 2);
    box(w + .02, .06, d + .02, C.gold, (x0 + x1) / 2, h + .13, (z0 + z1) / 2);
  }
  // Sahelian pinnacles, toron beams and a diamond band on the tall walls (generic geometry, not Adinkra)
  for (let x = -13; x <= 13.01; x += 1.625) { box(.45, .6, .45, C.bone, x, 3.2, -10); add(new THREE.ConeGeometry(.24, .42, 4), C.bone, x, 3.7, -10); }
  for (let z = -8.375; z <= 8.01; z += 1.625) { box(.45, .6, .45, C.bone, -13, 3.2, z); add(new THREE.ConeGeometry(.24, .42, 4), C.bone, -13, 3.7, z); }
  for (let x = -12.3; x <= 12.3; x += 1.3) box(.09, .09, .8, C.wood, x, 2.5, -10);
  for (let z = -9.2; z <= 7.6; z += 1.3) box(.8, .09, .09, C.wood, -13, 2.5, z);
  { const D = [C.gold, C.wine, C.black, C.gold, C.bone]; let i = 0;
    for (let x = -12.5; x <= 12.5; x += .8) box(.3, .3, .03, D[i++ % 5], x, 2.1, -9.83).rotation.z = Math.PI / 4;
    i = 0; for (let z = -9.4; z <= 7.6; z += .8) box(.03, .3, .3, D[i++ % 5], -12.83, 2.1, z).rotation.x = Math.PI / 4; }
  for (const x of [-11, -6.5, 6.5, 11]) box(1.6, .9, .06, C.glass, x, 1.5, -9.82, scene, true);
  for (const z of [-6, 4]) box(.06, .9, 1.6, C.glass, -12.82, 1.5, z, scene, true);
  for (const [x, z0, z1] of LAYOUT.doors) { box(.3, 2.1, .3, C.bone, x, 1.15, z0); box(.3, 2.1, .3, C.bone, x, 1.15, z1); box(.34, .22, z1 - z0 + .3, C.gold, x, 2.3, (z0 + z1) / 2); }
  box(.06, .08, 2.2, C.gold, 4.5, .55, 3); box(.06, .08, 2.2, C.gold, 4.5, .95, 3);   // locked room tape
  const rug = (x, z, w, d, cols) => { const n = cols.length; for (let i = 0; i < n; i++) box(w, .02, d / n, cols[i], x, .11, z - d / 2 + (i + .5) * d / n); };
  rug(-8.75, -4.2, 4, 2.4, [C.gold, C.bone, C.wine, C.black, C.wine, C.bone, C.gold]);
  rug(0, -3.4, 4, 3, [C.wine, C.gold, C.black, C.bone, C.black, C.gold, C.wine]);
  // OFFICE
  box(3.3, .9, 1.2, C.wood, -8.75, .55, -7.2);
  box(1.4, .8, .08, C.black, -9.4, 1.45, -7.6); box(1.25, .65, .02, C.mint, -9.4, 1.45, -7.55, scene, true);
  box(1.1, .7, .08, C.black, -7.9, 1.4, -7.55); box(.95, .55, .02, C.mint, -7.9, 1.4, -7.5, scene, true);
  box(.7, .12, .7, C.black, -8.75, .6, -6.1); box(.7, .7, .1, C.black, -8.75, .95, -5.8);
  box(.5, 2, 2.4, C.wood, -12.55, 1.1, -7); for (let i = 0; i < 5; i++) box(.3, .45, .18, [C.wine, C.gold, C.bone, C.wine, C.black][i], -12.25, 1.7, -7.9 + i * .42);
  box(2.4, .45, .05, C.gold, -8.75, 2.3, -9.8, scene, true);
  // OPERATOR DEV
  box(4.6, .05, 3.6, C.wine, 9, .12, -5.2); box(4.6, .06, .16, C.gold, 9, .12, -6.95); box(4.6, .06, .16, C.gold, 9, .12, -3.45);
  box(3, 1.3, .6, C.boneD, 9, .75, -9.4);
  for (const x of [7.9, 8.6, 9.4, 10.1]) add(new THREE.CylinderGeometry(.28, .28, .08, 10), C.black, x, 1.15, -9.05).rotation.x = Math.PI / 2;
  add(new THREE.CylinderGeometry(.32, .32, 1.3, 10), C.wine, 11.8, .8, -2.2);
  // DIGITAL LAB: black floor, mint circuit lines
  box(8.2, .02, 8.7, C.black, -8.75, .11, 3.5);
  for (let x = -12.5; x <= -5; x += 1.5) box(.04, .01, 8.6, C.mint, x, .125, 3.5, scene, true);
  for (let z = -.5; z <= 7.6; z += 1.5) box(8.2, .01, .04, C.mint, -8.75, .125, z, scene, true);
  box(4, .9, 1.2, C.boneD, -8.75, .55, 6.6);
  box(1.3, .75, .08, C.black, -9.9, 1.4, 7.05); box(1.15, .6, .02, C.mint, -9.9, 1.4, 7.0, scene, true);
  box(.8, 2, .8, C.black, -12.35, 1.1, 6.8); for (let i = 0; i < 4; i++) box(.5, .05, .02, C.mint, -12.35, .55 + i * .4, 6.39, scene, true);
  // LIVING AREA
  box(4, .5, 1.1, C.wine, 0, .4, -8.2); box(4, .7, .3, C.wine, 0, .85, -8.7); box(.3, .7, 1.1, C.wine, -2.05, .55, -8.2); box(.3, .7, 1.1, C.wine, 2.05, .55, -8.2);
  box(1.8, .4, .9, C.wood, 0, .3, -6.3);
  box(3, 1.6, .08, C.black, 0, 1.9, -9.8); box(2.8, 1.4, .02, C.mint, 0, 1.9, -9.75, scene, true);
  // LOCKED ROOM
  for (const [x, z, s] of [[9, 4, 1], [10.2, 5, .8], [8.1, 6, .9], [9.3, 5.7, .6]]) box(s, s, s, C.wood, x, .1 + s / 2, z);
  // GARDEN: path, gateway arch, baobabs, flight pad
  box(2.4, .05, 3.6, C.path, 0, .03, 10);
  for (const x of [-1.5, 1.5]) { box(.45, 2.8, .45, C.wineD, x, 1.5, 8.2); box(.52, .12, .52, C.gold, x, 2.95, 8.2); }
  add(new THREE.TorusGeometry(1.5, .15, 6, 12, Math.PI), C.gold, 0, 2.95, 8.2);
  add(new THREE.OctahedronGeometry(.2, 0), C.mint, 0, 4.6, 8.2, scene, true);
  for (const [x, z] of LAYOUT.trees) {
    const s = .85 + rnd() * .35;
    add(new THREE.CylinderGeometry(.4 * s, .72 * s, 2.3 * s, 7), C.trunk, x, 1.15 * s, z);
    for (let k = 0; k < 4; k++) { const a = k * 1.57 + rnd(); add(new THREE.IcosahedronGeometry(.6 * s, 0), k % 2 ? C.wine : C.wineD, x + Math.cos(a) * .75 * s, 2.75 * s, z + Math.sin(a) * .75 * s); }
  }
  const P = LAYOUT.flight_pad, pad = new THREE.Group(); pad.position.set(P.center[0], 0, P.center[1]); scene.add(pad);
  add(new THREE.CylinderGeometry(P.radius, P.radius, .14, 12), C.black, 0, .07, 0, pad);
  add(new THREE.TorusGeometry(P.radius + .15, .09, 6, 16), C.gold, 0, .16, 0, pad).rotation.x = Math.PI / 2;
  box(.35, .04, 1.6, C.gold, -.55, .16, 0, pad); box(.35, .04, 1.6, C.gold, .55, .16, 0, pad); box(1.1, .04, .35, C.gold, 0, .16, 0, pad);
  for (let a = 0; a < 4; a++) { const an = a * Math.PI / 2, ox = Math.cos(an) * (P.radius + .7), oz = Math.sin(an) * (P.radius + .7);
    add(new THREE.CylinderGeometry(.08, .22, 1.8, 4), C.wine, ox, .9, oz, pad); add(new THREE.OctahedronGeometry(.16, 0), C.mint, ox, 1.95, oz, pad, true); }
  WORLD.droneFly = new THREE.Group(); pad.add(WORLD.droneFly);
  WORLD.bench = new THREE.Group(); WORLD.bench.position.set(...LAYOUT.lab_bench); scene.add(WORLD.bench);
  // invisible pick volumes for the enterable / locked rooms
  const zoneMat = new THREE.MeshBasicMaterial({ visible: false });
  for (const r of LAYOUT.rooms) {
    if (!r.route && !r.locked) continue;
    let m;
    if (r.zone) { const [x0, z0, x1, z1] = r.zone; m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, 2.4, z1 - z0), zoneMat); m.position.set((x0 + x1) / 2, 1.2, (z0 + z1) / 2); }
    else { m = new THREE.Mesh(new THREE.CylinderGeometry(r.circle[2], r.circle[2], 2.4, 12), zoneMat); m.position.set(r.circle[0], 1.2, r.circle[1]); }
    m.userData.room = r.id; scene.add(m); WORLD.pick.push(m);
  }
  // lights
  WORLD.hemi = new THREE.HemisphereLight(0xf3e2ea, 0x4a2a32, 1.2); scene.add(WORLD.hemi);
  const sun = new THREE.DirectionalLight(0xffe6b8, 2.3); sun.position.set(14, 22, 8); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -22, right: 22, top: 22, bottom: -22, near: 1, far: 70 });
  sun.shadow.bias = -.0005; sun.shadow.normalBias = .03; scene.add(sun); WORLD.sun = sun;
}

// ------------------------------------------------------------------ Zero (placeholder until zero_world.glb exists)
function makeZero() {
  const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
  const L = new THREE.Group(), R = new THREE.Group(), AL = new THREE.Group(), AR = new THREE.Group();
  L.position.set(-.15, .62, 0); R.position.set(.15, .62, 0); AL.position.set(-.42, 1.24, 0); AR.position.set(.42, 1.24, 0); body.add(L, R, AL, AR);
  box(.22, .62, .26, C.black, 0, -.31, 0, L); box(.22, .62, .26, C.black, 0, -.31, 0, R);
  box(.17, .56, .19, C.black, 0, -.26, 0, AL); box(.17, .56, .19, C.black, 0, -.26, 0, AR);
  box(.62, .66, .36, C.black, 0, .95, 0, body); box(.64, .08, .38, C.gold, 0, 1.07, 0, body); box(.64, .05, .38, C.gold, 0, .8, 0, body);
  box(.52, .46, .46, C.black, 0, 1.56, 0, body); box(.42, .13, .05, C.mint, 0, 1.6, .245, body, true);
  box(.05, .28, .05, C.black, .16, 1.92, 0, body); add(new THREE.SphereGeometry(.07, 6, 5), C.mint, .16, 2.08, 0, body, true);
  scene.add(root); root.userData.zero = true; WORLD.pick.push(root);
  return { root, body, L, R, AL, AR, custom: null, mixer: null, acts: {}, cur: null };
}

// ------------------------------------------------------------------ models (light Shadow MK1 copy, Zer0's Blender Zero when it exists)
function loadModels() {
  const loader = new GLTFLoader();
  if (LAYOUT.models.shadow) loader.load(LAYOUT.models.shadow, g => {
    const fit = (src, width) => {
      const m = src.clone(true); m.updateMatrixWorld(true); let bb = new THREE.Box3().setFromObject(m); const s = bb.getSize(new THREE.Vector3());
      m.scale.multiplyScalar(width / Math.max(s.x, s.z)); m.updateMatrixWorld(true); bb = new THREE.Box3().setFromObject(m); m.position.sub(bb.getCenter(new THREE.Vector3()));
      m.traverse(o => { if (o.isMesh) { o.castShadow = true; o.material = o.material.clone(); patchSnap(o.material); } });
      const w = new THREE.Group(); w.add(m); return w;
    };
    const fly = fit(g.scene, 2.2); WORLD.droneFly.add(fly);
    for (let i = 1; i <= 4; i++) { const p = fly.getObjectByName("prop_" + i); if (p) WORLD.props.push({ p, dir: i % 2 ? 1 : -1 }); }
    const bench = fit(g.scene, 1.0); bench.rotation.y = .5; WORLD.bench.add(bench);
  }, undefined, e => console.warn("Shadow model not loaded", e));
  // Zero: drop static/models/zero_world.glb in (about 2 m, feet at origin, facing Blender -Y,
  // clips Idle/Walk/Run/Wave/Jump) and it replaces the placeholder. Nothing else to change.
  if (LAYOUT.models.zero) loader.load(LAYOUT.models.zero, g => {
    const m = g.scene; let bb = new THREE.Box3().setFromObject(m); m.scale.setScalar(2 / ((bb.max.y - bb.min.y) || 1));
    bb = new THREE.Box3().setFromObject(m); const c = bb.getCenter(new THREE.Vector3()); m.position.set(-c.x, -bb.min.y, -c.z);
    m.traverse(o => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; if (o.material) patchSnap(o.material); } });
    const w = new THREE.Group(); w.add(m); zero.root.add(w); zero.custom = w; zero.body.visible = false;
    zero.mixer = g.animations.length ? new THREE.AnimationMixer(m) : null;
    for (const n of ["idle", "walk", "run", "wave", "jump"]) { const clip = g.animations.find(a => new RegExp(n, "i").test(a.name)); if (clip) zero.acts[n] = zero.mixer.clipAction(clip); }
  }, undefined, e => console.warn("Zero model not loaded, keeping placeholder", e));
}

// ------------------------------------------------------------------ collision + A* (0.4 m grid, line-of-sight smoothing)
function buildColliders() {
  const out = [], t = .15;
  for (const [x0, z0, x1, z1] of LAYOUT.walls) out.push([Math.min(x0, x1) - t, Math.min(z0, z1) - t, Math.max(x0, x1) + t, Math.max(z0, z1) + t]);
  for (const c of LAYOUT.colliders) out.push(c);
  for (const [x, z] of LAYOUT.trees) out.push([x - .7, z - .7, x + .7, z + .7]);
  return out;
}
const RAD = .38, B = LAYOUT.bounds;
function blocked(x, z) {
  if (Math.abs(x) > B - .5 || Math.abs(z) > B - .5) return true;
  for (const [a, b, c, d] of SOLIDS) if (x > a - RAD && x < c + RAD && z > b - RAD && z < d + RAD) return true;
  return false;
}
const GS = .4, GN = Math.round(2 * B / GS);
const cx = i => -B + (i + .5) * GS, ci = x => Math.max(0, Math.min(GN - 1, Math.floor((x + B) / GS)));
function buildGrid() { const g = new Uint8Array(GN * GN); for (let j = 0; j < GN; j++) for (let i = 0; i < GN; i++) g[j * GN + i] = blocked(cx(i), cx(j)) ? 1 : 0; return g; }
function los(ax, az, bx, bz) { const n = Math.ceil(Math.hypot(bx - ax, bz - az) / .15); for (let k = 1; k <= n; k++) { const t = k / n; if (blocked(ax + (bx - ax) * t, az + (bz - az) * t)) return false; } return true; }
function free(i, j) { if (!GRID[j * GN + i]) return [i, j]; for (let r = 1; r < 10; r++) for (let a = -r; a <= r; a++) for (let b = -r; b <= r; b++) { const x = i + a, y = j + b; if (x >= 0 && y >= 0 && x < GN && y < GN && !GRID[y * GN + x]) return [x, y]; } return [i, j]; }
function findPath(sx, sz, gx, gz) {
  if (los(sx, sz, gx, gz)) return [[gx, gz]];
  const [si, sj] = free(ci(sx), ci(sz)), [gi, gj] = free(ci(gx), ci(gz)), N = GN * GN;
  const g = new Float32Array(N).fill(1e9), from = new Int32Array(N).fill(-1), done = new Uint8Array(N), open = [];
  const s = sj * GN + si, goal = gj * GN + gi; g[s] = 0; open.push([0, s]);
  while (open.length) {
    let bi = 0; for (let k = 1; k < open.length; k++) if (open[k][0] < open[bi][0]) bi = k;
    const [, cur] = open.splice(bi, 1)[0];
    if (done[cur]) continue; done[cur] = 1; if (cur === goal) break;
    const x = cur % GN, y = (cur / GN) | 0;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) {
      if (!a && !b) continue; const nx = x + a, ny = y + b; if (nx < 0 || ny < 0 || nx >= GN || ny >= GN) continue; const n = ny * GN + nx;
      if (GRID[n] || done[n] || (a && b && (GRID[y * GN + nx] || GRID[ny * GN + x]))) continue;
      const ng = g[cur] + (a && b ? 1.414 : 1); if (ng < g[n]) { g[n] = ng; from[n] = cur; open.push([ng + Math.hypot(nx - gi, ny - gj), n]); }
    }
  }
  if (from[goal] < 0) return [];
  const cells = []; for (let k = goal; k !== s && k !== -1; k = from[k]) cells.push([cx(k % GN), cx((k / GN) | 0)]); cells.reverse(); if (!blocked(gx, gz)) cells.push([gx, gz]);
  const out = []; let ax = sx, az = sz, i = 0;
  while (i < cells.length) { let j = cells.length - 1; while (j > i && !los(ax, az, cells[j][0], cells[j][1])) j--; out.push(cells[j]); [ax, az] = cells[j]; i = j + 1; }
  return out;
}

// ------------------------------------------------------------------ overlays: labels, bubble, toast
function buildLabels() {
  const out = {};
  for (const r of LAYOUT.rooms) {
    if (!r.route && !r.locked) continue;   // the living area is floor, not a door
    const d = document.createElement("div"); d.className = "lbl";
    d.innerHTML = (r.locked ? "LOCKED ROOM" : esc(r.name)) + (r.route ? `<small>E TO ENTER</small>` : "");
    d.onclick = e => { e.stopPropagation(); goRoom(r.id); };
    overlay.appendChild(d); out[r.id] = d;
  }
  return out;
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function renderBubble() {
  const B = ST.brief; if (!B || !B.lines.length) { bubble.style.display = "none"; return; }
  bubble.classList.toggle("min", ST.bubbleMin);
  if (ST.bubbleMin) { bubble.innerHTML = `<div class="bh"><span>${B.lines.length === 1 ? "1 thing" : B.lines.length + " things"}</span></div>`; }
  else bubble.innerHTML = `<div class="bh"><span>${esc(B.greeting)}</span><button aria-label="Fold">–</button></div>
    <ul>${B.lines.map((l, i) => `<li class="${l.kind === "win" ? "win" : ""}"><button data-i="${i}"><span class="n">${l.kind === "win" ? "✓" : i + 1}</span><span>${esc(l.text)}</span><span class="src">${esc((ROOM[l.room] || {}).name || l.room)} › ${esc(l.hub)} · ${esc(l.source)}</span></button></li>`).join("")}</ul>
    ${B.footer ? `<div class="foot">${esc(B.footer)}</div>` : ""}`;
  bubble.querySelector(".bh").onclick = e => { e.stopPropagation(); setBubble(!ST.bubbleMin); };
  bubble.querySelectorAll("li button").forEach(b => b.onclick = e => { e.stopPropagation(); const l = B.lines[+b.dataset.i]; leaveTo(l.route); });
}
function setBubble(min) { if (ST.bubbleMin === min) return; ST.bubbleMin = min; renderBubble(); }
let toastT; function toast(m) { const t = $("toast"); t.textContent = m; t.style.display = "block"; clearTimeout(toastT); toastT = setTimeout(() => t.style.display = "none", 2800); }
const v3 = new THREE.Vector3();
function project(x, y, z) { v3.set(x, y, z).project(cam()); return { x: (v3.x + 1) / 2 * innerWidth, y: (1 - v3.y) / 2 * innerHeight, vis: v3.z > -1 && v3.z < 1 }; }
function inZone(r) { return r.zone ? Z.x >= r.zone[0] && Z.x <= r.zone[2] && Z.z >= r.zone[1] && Z.z <= r.zone[3] : Math.hypot(Z.x - r.circle[0], Z.z - r.circle[1]) < r.circle[2]; }
function nearestDoor() { let best = null, bd = 1e9; for (const r of LAYOUT.rooms) { if (!r.route) continue; const d = Math.hypot(Z.x - r.station[0], Z.z - r.station[1]); if (d < bd) { bd = d; best = r; } } return bd < 5 ? best : null; }
function placeOverlays() {
  for (const [id, el] of Object.entries(labels)) {
    const r = ROOM[id], p = project(...r.label);
    const show = Math.hypot(Z.x - r.label[0], Z.z - r.label[2]) < 5 || ST.hover === id || Z.target === id;
    el.classList.toggle("show", show && p.vis && !ST.leaving); el.style.left = p.x + "px"; el.style.top = p.y + "px";
  }
  if (bubble.style.display === "none" && !(ST.brief && ST.brief.lines.length)) return;
  const p = project(Z.x, 2.5 + Z.jumpY, Z.z), bw = bubble.offsetWidth, bh = bubble.offsetHeight, top = innerWidth < 560 ? 78 : 96;
  const x = Math.max(bw / 2 + 8, Math.min(innerWidth - bw / 2 - 8, p.x)), y = Math.max(bh + top, p.y - 6);
  bubble.style.left = x + "px"; bubble.style.top = y + "px"; bubble.style.setProperty("--tail", Math.max(14, Math.min(bw - 14, p.x - (x - bw / 2))) + "px");
  bubble.style.display = p.vis && !ST.leaving ? "block" : "none";
}

// ------------------------------------------------------------------ brief + HUD
async function loadBrief() {
  const hour = new Date().getHours();
  try {
    const B = await fetch(`/home/brief?hour=${hour}${isBoot && !fromRoom ? "&boot=1" : ""}`).then(r => r.json());
    ST.brief = B;
    const away = B.mood === "away";
    worldEl.classList.toggle("away", away); $("hud").classList.toggle("away", away);
    if (away) { WORLD.sun.color.lerp(new THREE.Color(0xffc890), .45); WORLD.hemi.intensity *= 1.1; if (!fromRoom) Z.waveT = 2.4; }
    if (B.mood === "good" && !fromRoom) Z.jumpT = .7;
    const xp = B.since_last_boot && B.since_last_boot.xp;
    if (xp) { $("xpChip").textContent = `+${xp} XP SINCE LAST BOOT`; $("xpChip").classList.add("on"); }
    ST.bubbleMin = false; renderBubble();
  } catch (e) { console.warn("Brief not loaded", e); }
}
function renderHud() {
  if (summary && !summary.error) {
    $("hLv").textContent = summary.operator_level;
    $("hLvText").textContent = `OPERATOR LV ${summary.operator_level}`;
    const ovr = typeof summary.overall === "number" ? summary.overall.toFixed(2) : summary.overall;
    $("hXp").textContent = `${Number(summary.total_xp || 0).toLocaleString("en-GB")} XP · OVR ${ovr}`;
  }
  const tick = () => { const d = new Date();
    $("hClock").innerHTML = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) + `<small>:${String(d.getSeconds()).padStart(2, "0")}</small>`;
    $("hDate").textContent = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }).replace(/,/g, "").toUpperCase(); };
  tick(); setInterval(tick, 1000);
  $("hWallet").onclick = () => { ST.wallet = !ST.wallet; $("hWallet").innerHTML = ST.wallet ? `£ <small>NOT LINKED</small>` : `£ ••••<small>TAP</small>`; };
  $("hCam").onclick = toggleStyle;
}
function locName() { for (const id of ["office", "operator", "lab", "locked", "living", "flight"]) if (ROOM[id] && inZone(ROOM[id])) return ROOM[id].name; return "GARDEN"; }

// ------------------------------------------------------------------ movement + input
const keys = new Set();
addEventListener("keydown", e => {
  if (ST.leaving || e.target.closest && e.target.closest("input,textarea,select")) return;
  const k = e.key.toLowerCase();
  if (["w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"].includes(k)) { keys.add(k); Z.path = []; Z.target = null; setBubble(true); e.preventDefault(); }
  if (k === "v" && !e.repeat) toggleStyle();
  if ((k === "e" || k === "enter") && !e.repeat) { const r = nearestDoor(); if (r) goRoom(r.id); }
});
addEventListener("keyup", e => keys.delete(e.key.toLowerCase())); addEventListener("blur", () => keys.clear());
function goRoom(id) {
  const r = ROOM[id]; if (ST.leaving || !r) return;
  if (r.locked) { toast(r.locked); return; }
  if (!r.route) return;
  Z.path = findPath(Z.x, Z.z, r.station[0], r.station[1]); Z.target = id; Z.run = false; keys.clear(); setBubble(true);
  if (!Z.path.length) leaveTo(r.route);
}
function leaveTo(route) {   // into a real page: fade, then navigate
  if (ST.leaving || !route) return; ST.leaving = true; keys.clear();
  fx.classList.remove("boot"); fx.classList.add("go");
  setTimeout(() => { location.href = route; }, 420);
}
addEventListener("pageshow", e => { if (e.persisted) { ST.leaving = false; fx.classList.remove("go"); } });   // back/forward cache
function step(dt) {
  let dx = 0, dz = 0, rem = 1e9;
  if (keys.size) {
    const f = new THREE.Vector3(); cam().getWorldDirection(f); f.y = 0; f.normalize(); const rr = new THREE.Vector3(-f.z, 0, f.x); let a = 0, b = 0;
    if (keys.has("w") || keys.has("arrowup")) a++; if (keys.has("s") || keys.has("arrowdown")) a--; if (keys.has("d") || keys.has("arrowright")) b++; if (keys.has("a") || keys.has("arrowleft")) b--;
    dx = f.x * a + rr.x * b; dz = f.z * a + rr.z * b; Z.run = false;
  } else if (Z.path.length) {
    const [tx, tz] = Z.path[0], ddx = tx - Z.x, ddz = tz - Z.z, d = Math.hypot(ddx, ddz);
    if (d < .08) { Z.path.shift(); if (!Z.path.length && Z.target) { const t = Z.target; Z.target = null; leaveTo(ROOM[t].route); } }
    else { dx = ddx / d; dz = ddz / d; rem = d; }
  }
  const len = Math.hypot(dx, dz); Z.moving = len > .01;
  if (Z.moving) {
    dx /= len; dz /= len; const sp = Math.min(rem, (Z.run ? 9 : 5) * dt), nx = Z.x + dx * sp, nz = Z.z + dz * sp;
    if (!blocked(nx, nz)) { Z.x = nx; Z.z = nz; } else if (!blocked(nx, Z.z)) Z.x = nx; else if (!blocked(Z.x, nz)) Z.z = nz; else if (Z.path.length) { Z.path = []; Z.target = null; }
    let dh = Math.atan2(dx, dz) - Z.h; dh = Math.atan2(Math.sin(dh), Math.cos(dh)); Z.h += dh * Math.min(1, dt * 12); Z.phase += dt * (Z.run ? 16 : 11);
  }
  if (Z.jumpT > 0) { Z.jumpT -= dt; Z.jumpY = Math.max(0, Math.sin((1 - Z.jumpT / .7) * Math.PI)) * .9; } else Z.jumpY = 0;
  if (Z.waveT > 0) Z.waveT -= dt;
}
function poseZero(t, dt) {
  const inside = Math.abs(Z.x) < 13 && Z.z > -10 && Z.z < 8;
  zero.root.position.set(Z.x, Z.jumpY + (inside ? .1 : 0), Z.z); zero.root.rotation.y = Z.h;
  if (zero.custom) {
    if (zero.mixer) {
      zero.mixer.update(dt);
      const A = zero.acts;
      const want = (Z.waveT > 0 && !Z.moving && A.wave) ? "wave" : (Z.jumpY > 0 && A.jump) ? "jump" : Z.moving ? ((Z.run && A.run) ? "run" : A.walk ? "walk" : null) : (A.idle ? "idle" : null);
      if (want !== zero.cur) { if (zero.cur) A[zero.cur].fadeOut(.2); if (want) A[want].reset().fadeIn(.2).play(); zero.cur = want; }
    }
    return;
  }
  const s = Z.moving ? Math.sin(Z.phase) : 0, a = Z.run ? .9 : .6;
  zero.L.rotation.x = s * a; zero.R.rotation.x = -s * a; zero.AL.rotation.x = -s * a * .8; zero.AR.rotation.x = s * a * .8;
  zero.body.position.y = Z.moving ? Math.abs(Math.cos(Z.phase)) * .07 : Math.sin(t * 2) * .02;
  zero.AR.rotation.z = (Z.waveT > 0 && !Z.moving) ? 2.6 + Math.sin(t * 10) * .35 : (Z.jumpY > 0 ? 2.4 : 0);
  zero.AL.rotation.z = Z.jumpY > 0 ? -2.4 : 0;
}
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -.1);
function aim(e) { ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ndc, cam()); }
function floorAt() { const p = new THREE.Vector3(); return ray.ray.intersectPlane(floorPlane, p) ? [p.x, p.z] : null; }
function hit(e) {
  aim(e);
  for (const h of ray.intersectObjects(WORLD.pick, true)) { let o = h.object; while (o && !o.userData.room && !o.userData.zero) o = o.parent; if (o) return o.userData.zero ? { zero: true } : { room: o.userData.room }; }
  const p = floorAt(); return p ? { point: p } : null;
}
const cv = renderer.domElement; let down = null;
cv.addEventListener("pointerdown", e => down = [e.clientX, e.clientY]);
cv.addEventListener("pointerup", e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 10 || ST.leaving) return; down = null;
  const h = hit(e); if (!h) return;
  if (h.zero) return setBubble(!ST.bubbleMin);
  if (h.room && !(inZone(ROOM[h.room]) && !ROOM[h.room].locked)) return goRoom(h.room);
  const p = h.point || floorAt(); if (!p) return;
  Z.path = findPath(Z.x, Z.z, p[0], p[1]); Z.target = null; Z.run = false; keys.clear(); setBubble(true);
});
cv.addEventListener("pointermove", e => { if (e.pointerType !== "mouse") return; const h = hit(e); ST.hover = h && h.room || null; cv.style.cursor = h && (h.room || h.zero) ? "pointer" : "crosshair"; });

// ------------------------------------------------------------------ build + start (after every helper above is defined)
buildWorld();
const zero = makeZero();
const Z = { x: LAYOUT.spawn[0], z: LAYOUT.spawn[1], h: Math.PI, moving: false, run: false, phase: 0, path: [], target: null, jumpT: 0, jumpY: 0, waveT: 0 };
if (fromRoom && ROOM[fromRoom].exit) {
  const r = ROOM[fromRoom]; Z.x = r.exit[0]; Z.z = r.exit[1]; Z.h = Math.atan2(r.exit[0] - r.station[0], r.exit[1] - r.station[1]);
}
const SOLIDS = buildColliders();
const GRID = buildGrid();
const labels = buildLabels();
const bubble = document.createElement("div"); bubble.className = "bubble"; bubble.style.display = "none"; overlay.appendChild(bubble);
renderHud();
loadModels();
loadBrief();

// ------------------------------------------------------------------ style switch, resize, loop
function resize() {
  const w = innerWidth, h = innerHeight, a = w / h;
  renderer.setPixelRatio(ST.style === "retro" ? 1 / 3 : Math.min(devicePixelRatio, 2)); renderer.setSize(w, h, false);
  const H = Math.min(28, Math.max(12.5, 10.5 / a)); Object.assign(isoCam, { left: -H * a, right: H * a, top: H, bottom: -H }); isoCam.updateProjectionMatrix();
  retroCam.aspect = a; retroCam.updateProjectionMatrix();
  SNAP.value.set(ST.style === "retro" ? Math.ceil(w / 3) / 2 : 0, Math.ceil(h / 3) / 2);
}
function applyStyle() {
  const retro = ST.style === "retro";
  worldEl.classList.toggle("retro", retro); document.body.classList.toggle("retro", retro);
  scene.fog = retro ? RETRO_FOG : null; scene.background = retro ? RETRO_BG : null;
  retroYaw = Z.h; firstCam = true;
  $("hCam").innerHTML = `CAM · ${retro ? "RETRO" : "ISO"} <small>V</small>`; resize();
}
function toggleStyle() { ST.style = ST.style === "iso" ? "retro" : "iso"; applyStyle(); }
addEventListener("resize", resize);
const camT = new THREE.Vector3(); let retroYaw = Z.h, firstCam = true;
function updateCams(dt) {
  if (ST.style === "iso") {
    const want = new THREE.Vector3(Math.max(-4, Math.min(4, Z.x * .7)), 0, Math.max(-4, Math.min(5, Z.z * .7)));
    if (innerHeight > innerWidth * 1.2) { want.x -= 1.5; want.z -= 1.5; }
    firstCam ? camT.copy(want) : camT.lerp(want, Math.min(1, dt * 2.5)); isoCam.position.copy(camT).add(new THREE.Vector3(20, 20, 20)); isoCam.lookAt(camT);
  } else {
    let dh = Z.h - retroYaw; dh = Math.atan2(Math.sin(dh), Math.cos(dh)); if (Z.moving) retroYaw += dh * Math.min(1, dt * 2.2);
    const fx_ = Math.sin(retroYaw), fz = Math.cos(retroYaw), want = new THREE.Vector3(Z.x - fx_ * 7.5, 8, Z.z - fz * 7.5);
    firstCam ? retroCam.position.copy(want) : retroCam.position.lerp(want, Math.min(1, dt * 3)); retroCam.lookAt(Z.x + fx_ * 3, 1.2, Z.z + fz * 3);
  }
  firstCam = false;
}
applyStyle();
const timer = new THREE.Timer(); let t = 0, locT = 0, first = true;
const P = LAYOUT.flight_pad;
renderer.setAnimationLoop(() => {
  timer.update(); const dt = Math.min(.05, timer.getDelta()); t += dt;
  if (!ST.leaving) step(dt);
  poseZero(t, dt);
  WORLD.droneFly.position.set(Math.cos(t * .5) * P.orbit, P.hover + Math.sin(t * 2) * .12, Math.sin(t * .5) * P.orbit);
  { const vx = -Math.sin(t * .5), vz = Math.cos(t * .5); WORLD.droneFly.rotation.set(0, Math.atan2(-vz, vx), 0); WORLD.droneFly.rotateX(-.08); }  // model +X is the nose, so it leads
  for (const { p, dir } of WORLD.props) p.rotateZ(dir * dt * 40);
  if ((locT += dt) > .25) { locT = 0; $("hLoc").textContent = locName(); }
  updateCams(dt); renderer.render(scene, cam()); placeOverlays();
  if (first) { first = false; requestAnimationFrame(() => fx.classList.remove("boot")); }
});
window.__home = { Z, ST, ROOM, goRoom, leaveTo, toggleStyle, findPath, get props() { return WORLD.props.length; }, get fromRoom() { return fromRoom; }, get isBoot() { return isBoot; } };
