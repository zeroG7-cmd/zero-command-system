(() => {
  let last = localStorage.getItem("operatorReceipt");
  let timer = null;
  let stopped = false;

  function interval() {
    return document.hidden ? 60000 : 10000;
  }

  function schedule() {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(poll, interval());
  }

  async function poll() {
    try {
      const response = await fetch("/api/learning/receipts/latest", {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const receipt = await response.json();

      if (receipt.event_id && receipt.event_id !== last) {
        last = receipt.event_id;
        localStorage.setItem("operatorReceipt", last);

        const box = document.createElement("div");
        box.className = "xp-receipt-toast";
        box.innerHTML = `
          <strong>LESSON COMPLETE · +${receipt.xp || 0} XP</strong>
          <span>${receipt.unit_title || ""}</span>
          <small>${receipt.track || ""}${receipt.next_unit ? " · Next: " + receipt.next_unit : ""}</small>
        `;
        document.body.appendChild(box);
        setTimeout(() => box.remove(), 9000);

        if ("Notification" in window && Notification.permission === "granted") {
          new Notification(`Operator Zero · +${receipt.xp || 0} XP`, {
            body: receipt.unit_title || "Lesson complete",
          });
        }
      }
    } catch (_) {
      // Zero Command may be restarting. Retry on the normal schedule.
    } finally {
      schedule();
    }
  }

  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }

  document.addEventListener("visibilitychange", schedule);
  window.addEventListener("beforeunload", () => {
    stopped = true;
    clearTimeout(timer);
  });

  poll();
})();