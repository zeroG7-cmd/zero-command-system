// home_return.js - Esc goes back to the home world from a room page.
//
// Included on the pages the home world's rooms open (Office, Operator HUD,
// Digital Lab, Flight Log). Pressing Esc navigates to "/", and the home page
// reads document.referrer to put Zero back outside the room you left.
// It stands aside when the page is using Esc itself: a modal or dialog is
// open, or you're typing in a field.
(function () {
  function busy() {
    var a = document.activeElement;
    if (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return true;
    if (document.querySelector("dialog[open], [aria-modal='true'], .modal.open, .modal.on, .modal.show")) return true;
    var m = document.getElementById("modal");   // the Office renders its modals into #modal
    return !!(m && m.innerHTML.trim());
  }
  window.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || e.defaultPrevented || e.repeat || busy()) return;
    window.location.href = "/";
  }, true);
})();
