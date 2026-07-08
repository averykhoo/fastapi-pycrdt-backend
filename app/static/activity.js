// Active-time telemetry: batches interaction/visibility events to the server
// so it can derive how long a user was *actively* working vs. merely present.

const HEARTBEAT_MS = 2000;      // proves the page is open and visible
const INPUT_THROTTLE_MS = 500;  // at most one "input" tick per interval
const FLUSH_MS = 1000;

export function startActivityTracking({ docId, user }) {
  let queue = [];
  let lastInput = 0;

  const push = (type) => queue.push({ type, ts: Date.now() });

  const flush = () => {
    if (!queue.length) return;
    const body = JSON.stringify({ doc_id: docId, user, events: queue });
    queue = [];
    fetch("/api/activity", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  };

  for (const evt of ["keydown", "pointerdown", "pointermove", "wheel"]) {
    window.addEventListener(evt, () => {
      const now = Date.now();
      if (now - lastInput >= INPUT_THROTTLE_MS) {
        lastInput = now;
        push("input");
      }
    }, { passive: true, capture: true });
  }

  document.addEventListener("visibilitychange", () =>
    push(document.visibilityState === "hidden" ? "hidden" : "visible"));
  window.addEventListener("focus", () => push("focus"));
  window.addEventListener("blur", () => push("blur"));

  window.addEventListener("pagehide", () => {
    push("unload");
    const body = JSON.stringify({ doc_id: docId, user, events: queue });
    queue = [];
    navigator.sendBeacon("/api/activity", new Blob([body], { type: "application/json" }));
  });

  setInterval(() => {
    if (document.visibilityState === "visible") push("heartbeat");
  }, HEARTBEAT_MS);
  setInterval(flush, FLUSH_MS);

  push("visible");
  return { track: push, flush };
}
