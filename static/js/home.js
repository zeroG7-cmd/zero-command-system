(() => {
    const rooms = Array.from(document.querySelectorAll('[data-room]'));
    const title = document.getElementById('inspector-title');
    const description = document.getElementById('inspector-description');
    const readout = document.getElementById('room-readout');
    const building = document.getElementById('hq-building');
    const controls = Array.from(document.querySelectorAll('.hq-control'));

    function selectRoom(room) {
        rooms.forEach((item) => item.classList.toggle('is-selected', item === room));
        const roomName = room.dataset.room || 'Headquarters Overview';
        title.textContent = roomName;
        description.textContent = room.dataset.description || '';
        readout.textContent = roomName.toUpperCase();
    }

    rooms.forEach((room) => {
        room.addEventListener('mouseenter', () => selectRoom(room));
        room.addEventListener('focus', () => selectRoom(room));

        if (room.getAttribute('aria-disabled') === 'true') {
            room.addEventListener('click', (event) => {
                event.preventDefault();
                selectRoom(room);
            });
        }
    });

    controls.forEach((control) => {
        control.addEventListener('click', () => {
            controls.forEach((item) => item.classList.toggle('is-active', item === control));
            const focusMode = control.dataset.view === 'focus';
            building.classList.toggle('is-focused', focusMode);
            if (!focusMode) {
                rooms.forEach((room) => room.classList.remove('is-selected'));
                title.textContent = 'Headquarters Overview';
                description.textContent = 'Hover over or focus a room to inspect its purpose. Active rooms open the existing Zero Command workspaces.';
                readout.textContent = 'HEADQUARTERS OVERVIEW';
            }
        });
    });
})();
