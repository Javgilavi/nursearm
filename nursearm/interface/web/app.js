const layout = document.getElementById("layout");
const cameraColumn = document.getElementById("camera-column");
const cameraSplit = document.getElementById("camera-splitter");
const layoutSplit = document.getElementById("layout-splitter");
const cameraFrames = [
  document.getElementById("camera-frame-1"),
  document.getElementById("camera-frame-2"),
];
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatMessages = document.getElementById("chat-messages");
const promptChips = document.querySelectorAll("[data-prompt]");

const STORAGE_KEY = "nursearm.ui.sizes";
const DEFAULTS = {
  left: 0.6,
  top: 0.5,
};

const state = loadSizes();

function loadSizes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return {
      left: typeof parsed.left === "number" ? parsed.left : DEFAULTS.left,
      top: typeof parsed.top === "number" ? parsed.top : DEFAULTS.top,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSizes() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function refreshFrames() {
  const stamp = Date.now();
  cameraFrames.forEach((frame) => {
    frame.src = `/frame?ts=${stamp}`;
  });
}

function appendMessage(role, content) {
  const node = document.createElement("article");
  node.className = `message ${role}`;
  node.setAttribute("aria-label", role === "user" ? "Your message" : "Assistant message");
  node.textContent = content;
  chatMessages.appendChild(node);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function sendChat(text) {
  return fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .then(async (response) => {
      const payload = await response.json();
      if (!response.ok) {
        appendMessage("assistant", `Error: ${payload.error || "request failed"}`);
        return;
      }
      appendMessage("user", text);
      appendMessage("assistant", payload.reply);
      refreshFrames();
    });
}

async function onSubmit(event) {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  await sendChat(text);
}

function applyLayoutSizes() {
  const rect = layout.getBoundingClientRect();
  const minLeft = 320;
  const minRight = 340;
  const gutter = 12;
  const maxLeft = Math.max(minLeft, rect.width - minRight - gutter);
  const leftPx = clamp(rect.width * state.left, minLeft, maxLeft);
  layout.style.setProperty("--layout-left", `${leftPx}px`);

  const cameraRect = cameraColumn.getBoundingClientRect();
  const minTop = 220;
  const minBottom = 220;
  const maxTop = Math.max(minTop, cameraRect.height - minBottom - gutter);
  const topPx = clamp(cameraRect.height * state.top, minTop, maxTop);
  layout.style.setProperty("--layout-top", `${topPx}px`);
}

function startResize(orientation, event) {
  event.preventDefault();
  const startX = event.clientX;
  const startY = event.clientY;
  const layoutRect = layout.getBoundingClientRect();
  const cameraRect = cameraColumn.getBoundingClientRect();
  const startLeft = state.left;
  const startTop = state.top;

  const onMove = (moveEvent) => {
    if (orientation === "vertical") {
      const minLeft = 320;
      const minRight = 340;
      const gutter = 12;
      const maxLeft = Math.max(minLeft, layoutRect.width - minRight - gutter);
      const nextLeft = clamp(startLeft * layoutRect.width + (moveEvent.clientX - startX), minLeft, maxLeft);
      state.left = nextLeft / layoutRect.width;
    } else {
      const minTop = 220;
      const minBottom = 220;
      const gutter = 12;
      const maxTop = Math.max(minTop, cameraRect.height - minBottom - gutter);
      const nextTop = clamp(startTop * cameraRect.height + (moveEvent.clientY - startY), minTop, maxTop);
      state.top = nextTop / cameraRect.height;
    }
    applyLayoutSizes();
    saveSizes();
  };

  const onUp = () => {
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onUp);
    document.body.classList.remove("is-resizing", "is-resizing-vertical", "is-resizing-horizontal");
  };

  document.body.classList.add("is-resizing", `is-resizing-${orientation}`);
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onUp);
}

cameraSplit.addEventListener("pointerdown", (event) => startResize("horizontal", event));
layoutSplit.addEventListener("pointerdown", (event) => startResize("vertical", event));

chatForm.addEventListener("submit", onSubmit);
promptChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.dataset.prompt || "";
    chatInput.focus();
  });
});

window.addEventListener("resize", applyLayoutSizes);
window.addEventListener("load", () => {
  applyLayoutSizes();
  refreshFrames();
});

setInterval(refreshFrames, 3000);
