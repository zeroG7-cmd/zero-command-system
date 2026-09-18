// home.js — headquarters overview page.
//
// Two independent behaviors live here, both replacing the old
// "Overview / Focus room" toolbar buttons that never had a script behind
// them:
//
// 1. Hovering (or keyboard-focusing) any room updates the inspector
//    panel at the bottom with that room's name/description.
// 2. Clicking a room that has real embedded interior content (right now:
//    the Operator Study canvas, marked .room-live) zooms that one room
//    to fill the stage and fades every other room out - no other rooms
//    visible, just that one, per the actual ask. There's no separate
//    toggle button, the room you click IS the control, and a small
//    "<- House" link appears on the zoomed room to back out (Escape and
//    clicking the empty stage background also back out). Rooms that are
//    plain navigation links (R&D Lab, zeroGravity Office) keep their
//    normal href behavior untouched - this only governs in-place rooms.

const stage = document.querySelector('.hq-stage');
const building = document.getElementById('hq-building');
const inspectorTitle = document.getElementById('inspector-title');
const inspectorDescription = document.getElementById('inspector-description');

const DEFAULT_INSPECTOR_TITLE = inspectorTitle ? inspectorTitle.textContent : '';
const DEFAULT_INSPECTOR_DESCRIPTION = inspectorDescription ? inspectorDescription.textContent : '';

const rooms = Array.from(document.querySelectorAll('.hq-room[data-room]'));
let focusedRoom = null;

function showInspector(room) {
  if (!inspectorTitle) return;
  inspectorTitle.textContent = room.dataset.room;
  inspectorDescription.textContent = room.dataset.description || '';
}

function resetInspector() {
  if (focusedRoom || !inspectorTitle) return; // stay on the focused room's info while zoomed in
  inspectorTitle.textContent = DEFAULT_INSPECTOR_TITLE;
  inspectorDescription.textContent = DEFAULT_INSPECTOR_DESCRIPTION;
}

rooms.forEach((room) => {
  room.addEventListener('mouseenter', () => showInspector(room));
  room.addEventListener('focus', () => showInspector(room));
  room.addEventListener('mouseleave', resetInspector);
  room.addEventListener('blur', resetInspector);

  // Concept tiles are real <a href="#"> placeholders - stop them jumping
  // the page to the top when clicked.
  if (room.classList.contains('is-concept')) {
    room.addEventListener('click', (event) => event.preventDefault());
  }
});

// --- Click-to-zoom ---------------------------------------------------------
const zoomableRooms = rooms.filter((room) => room.classList.contains('room-live'));

zoomableRooms.forEach((room) => {
  // Capture phase, ahead of anything rendered inside the room (like the
  // Three.js canvas) getting the click: while this room isn't zoomed in
  // yet, any click on it should zoom in rather than reach the scene -
  // at grid-tile size there's no real way to aim at a specific 3D object
  // anyway, so the first click always means "take me in there."
  room.addEventListener('click', (event) => {
    if (focusedRoom === room) return; // already zoomed - let the click reach the scene
    event.stopPropagation();
    focusRoom(room);
  }, { capture: true });

  room.addEventListener('keydown', (event) => {
    if (focusedRoom === room || event.target !== room) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      focusRoom(room);
    }
  });

  room.querySelector('[data-room-back]')?.addEventListener('click', (event) => {
    event.stopPropagation();
    unfocusRoom(room);
  });
});

stage?.addEventListener('click', (event) => {
  if (focusedRoom && event.target === stage) unfocusRoom(focusedRoom);
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && focusedRoom) unfocusRoom(focusedRoom);
});

function focusRoom(room) {
  const stageRect = stage.getBoundingClientRect();
  const startRect = room.getBoundingClientRect();
  const homeBox = {
    top: startRect.top - stageRect.top,
    left: startRect.left - stageRect.left,
    width: startRect.width,
    height: startRect.height,
  };

  room._homeBox = homeBox;
  room._origParent = room.parentElement;
  room._origNext = room.nextElementSibling;

  stage.appendChild(room);
  room.classList.add('is-focused-room'); // switches it to position:absolute first ...
  room.style.top = `${homeBox.top}px`;    // ... so these are read in that context, not
  room.style.left = `${homeBox.left}px`;  // the position:relative one it had in the grid
  room.style.width = `${homeBox.width}px`;
  room.style.height = `${homeBox.height}px`;

  // Force the browser to commit that starting box before the next frame
  // sets the end box - without this the two writes collapse into one and
  // it just snaps there instead of animating.
  void room.offsetWidth;

  rooms.forEach((other) => { if (other !== room) other.classList.add('is-dimmed'); });
  building.classList.add('room-focused');
  stage.classList.add('has-focused-room');
  room.querySelector('[data-room-back]')?.removeAttribute('hidden');

  requestAnimationFrame(() => {
    room.style.top = '0px';
    room.style.left = '0px';
    room.style.width = `${stageRect.width}px`;
    room.style.height = `${stageRect.height}px`;
  });

  focusedRoom = room;
  showInspector(room);
}

function unfocusRoom(room) {
  const homeBox = room._homeBox;
  if (!homeBox) return;

  room.style.top = `${homeBox.top}px`;
  room.style.left = `${homeBox.left}px`;
  room.style.width = `${homeBox.width}px`;
  room.style.height = `${homeBox.height}px`;

  rooms.forEach((other) => other.classList.remove('is-dimmed'));
  building.classList.remove('room-focused');
  stage.classList.remove('has-focused-room');
  room.querySelector('[data-room-back]')?.setAttribute('hidden', '');
  focusedRoom = null;
  resetInspector();

  function onTransitionEnd(event) {
    if (!['top', 'left', 'width', 'height'].includes(event.propertyName)) return;
    room.removeEventListener('transitionend', onTransitionEnd);
    room.classList.remove('is-focused-room');
    room.style.top = '';
    room.style.left = '';
    room.style.width = '';
    room.style.height = '';
    // Put it back exactly where it came from in the grid.
    if (room._origNext && room._origNext.isConnected) {
      room._origParent.insertBefore(room, room._origNext);
    } else if (room._origParent) {
      room._origParent.appendChild(room);
    }
  }
  room.addEventListener('transitionend', onTransitionEnd);
}
