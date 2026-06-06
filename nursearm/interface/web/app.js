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
const sendButton = document.querySelector(".send-button");
const micButton = document.getElementById("mic-button");
const chatMessages = document.getElementById("chat-messages");
const promptChips = document.querySelectorAll("[data-prompt]");

// ── Layout persistence ────────────────────────────────────────────────────────

const STORAGE_KEY = "nursearm.ui.sizes";
const DEFAULTS = { left: 0.6, top: 0.5 };

const sizes = (() => {
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
})();

function saveSizes() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function applyLayoutSizes() {
  const rect = layout.getBoundingClientRect();
  const minLeft = 320;
  const minRight = 340;
  const gutter = 12;
  const maxLeft = Math.max(minLeft, rect.width - minRight - gutter);
  const leftPx = clamp(rect.width * sizes.left, minLeft, maxLeft);
  layout.style.setProperty("--layout-left", `${leftPx}px`);

  const cameraRect = cameraColumn.getBoundingClientRect();
  const minTop = 220;
  const minBottom = 220;
  const maxTop = Math.max(minTop, cameraRect.height - minBottom - gutter);
  const topPx = clamp(cameraRect.height * sizes.top, minTop, maxTop);
  layout.style.setProperty("--layout-top", `${topPx}px`);
}

function startResize(orientation, event) {
  event.preventDefault();
  const startX = event.clientX;
  const startY = event.clientY;
  const layoutRect = layout.getBoundingClientRect();
  const cameraRect = cameraColumn.getBoundingClientRect();
  const startLeft = sizes.left;
  const startTop = sizes.top;

  const onMove = (moveEvent) => {
    if (orientation === "vertical") {
      const minLeft = 320;
      const minRight = 340;
      const gutter = 12;
      const maxLeft = Math.max(minLeft, layoutRect.width - minRight - gutter);
      const nextLeft = clamp(startLeft * layoutRect.width + (moveEvent.clientX - startX), minLeft, maxLeft);
      sizes.left = nextLeft / layoutRect.width;
    } else {
      const minTop = 220;
      const minBottom = 220;
      const gutter = 12;
      const maxTop = Math.max(minTop, cameraRect.height - minBottom - gutter);
      const nextTop = clamp(startTop * cameraRect.height + (moveEvent.clientY - startY), minTop, maxTop);
      sizes.top = nextTop / cameraRect.height;
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
window.addEventListener("resize", applyLayoutSizes);

// ── Cameras ───────────────────────────────────────────────────────────────────
// Camera 1: RealSense top camera via /stream/palm (with palm detection overlay)
// Camera 2: HBV HD CAMERA robot-mounted via /stream/2

function startCameras() {
  cameraFrames[0].src = "/stream/palm";
  cameraFrames[1].src = "/stream/2";
}

// ── Chat ──────────────────────────────────────────────────────────────────────

let loadingBubble = null;

function setLoading(on) {
  chatInput.disabled = on;
  sendButton.disabled = on;
}

function appendMessage(role, content) {
  const node = document.createElement("article");
  node.className = `message ${role}`;
  node.setAttribute("aria-label", role === "user" ? "Your message" : "Assistant message");
  node.textContent = content;
  chatMessages.appendChild(node);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return node;
}

function showSpinner() {
  loadingBubble = document.createElement("article");
  loadingBubble.className = "message assistant loading";
  loadingBubble.textContent = "Thinking…";
  chatMessages.appendChild(loadingBubble);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideSpinner() {
  if (loadingBubble) {
    loadingBubble.remove();
    loadingBubble = null;
  }
}

async function onSubmit(event) {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  appendMessage("user", text);
  setLoading(true);
  showSpinner();

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    hideSpinner();
    appendMessage(
      "assistant",
      response.ok ? payload.reply : `Error: ${payload.detail || payload.error || "request failed"}`
    );
  } catch {
    hideSpinner();
    appendMessage("assistant", "Cannot reach the NurseArm backend.");
  } finally {
    setLoading(false);
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", onSubmit);

// ── Voice input ───────────────────────────────────────────────────────────────

let mediaRecorder = null;
let audioChunks = [];

function setMicState(s) {
  micButton.dataset.state = s;
  micButton.disabled = s === "transcribing";
  micButton.title = s === "recording" ? "Stop recording" : "Voice input";
}

micButton.addEventListener("click", async () => {
  if (micButton.dataset.state === "idle") {
    await startRecording();
  } else if (micButton.dataset.state === "recording") {
    stopRecording();
  }
});

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    appendMessage("assistant", "Microphone access denied — check browser permissions.");
    return;
  }

  audioChunks = [];
  const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";
  mediaRecorder = new MediaRecorder(stream, { mimeType });
  mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    await transcribeRecording();
  };
  mediaRecorder.start();
  setMicState("recording");
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

async function transcribeRecording() {
  setMicState("transcribing");
  setLoading(true);
  chatInput.placeholder = "Transcribing…";
  const blob = new Blob(audioChunks, { type: "audio/webm" });
  const formData = new FormData();
  formData.append("audio", blob, "recording.webm");
  let transcribedText = null;
  try {
    const response = await fetch("/transcribe", { method: "POST", body: formData });
    const payload = await response.json();
    if (response.ok && payload.text) {
      transcribedText = payload.text;
    } else if (!response.ok) {
      appendMessage("assistant", `Transcription error: ${payload.detail || "unknown"}`);
    }
  } catch {
    appendMessage("assistant", "Could not reach the transcription service.");
  } finally {
    setMicState("idle");
    setLoading(false);
    chatInput.placeholder = "Type or speak your instruction";
    if (transcribedText) {
      chatInput.value = transcribedText;
      chatInput.focus();
      chatInput.setSelectionRange(transcribedText.length, transcribedText.length);
    }
  }
}

promptChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.dataset.prompt || "";
    chatInput.focus();
  });
});

// ── Mobile tabs ───────────────────────────────────────────────────────────────

const mobileTabBtns = document.querySelectorAll(".mobile-tab-btn");

mobileTabBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    mobileTabBtns.forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-pressed", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-pressed", "true");
    document.body.classList.remove("mobile-tab-camera", "mobile-tab-status");
    if (tab !== "chat") {
      document.body.classList.add(`mobile-tab-${tab}`);
    }
  });
});

// ── Palm detection badge ──────────────────────────────────────────────────────

const palmBadge = document.getElementById("palm-badge");

async function pollPalmStatus() {
  try {
    const r = await fetch("/palm/status");
    const d = await r.json();
    if (d.detected) {
      const hand = d.handedness || "hand";
      const state = d.is_open ? "open" : "closed";
      const up = d.palm_up ? `↑ palm-up ${Math.round(d.palm_up_confidence * 100)}%` : "palm-down";
      palmBadge.textContent = `✋ ${hand}  ${state}  ${up}`;
      palmBadge.className = "palm-badge palm-badge-hand";
    } else {
      palmBadge.textContent = "no hand";
      palmBadge.className = "palm-badge palm-badge-none";
    }
  } catch {
    palmBadge.textContent = "";
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function loadRemoteUrl() {
  try {
    const r = await fetch("/health");
    const data = await r.json();
    if (data.ngrok_url) {
      const section = document.getElementById("remote-access");
      const link = document.getElementById("ngrok-link");
      const qrImg = document.getElementById("qr-image");
      link.href = data.ngrok_url;
      link.textContent = data.ngrok_url.replace("https://", "");
      qrImg.src = "/qr.svg";
      section.hidden = false;
    }
  } catch { /* server not ready yet — silent */ }
}

window.addEventListener("load", () => {
  applyLayoutSizes();
  startCameras();
  if (window.matchMedia("(min-width: 769px)").matches) {
    chatInput.focus();
  }
  loadRemoteUrl();
  pollPalmStatus();
  setInterval(pollPalmStatus, 1000);
});
