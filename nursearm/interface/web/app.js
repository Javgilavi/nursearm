const layout = document.getElementById("layout");
const cameraColumn = document.getElementById("camera-column");
const cameraSplit = document.getElementById("camera-splitter");
const robotSplit = document.getElementById("robot-splitter");
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
const DEFAULTS = { left: 0.6, top: 0.33, mid: 0.33 };

const sizes = (() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return {
      left: typeof parsed.left === "number" ? parsed.left : DEFAULTS.left,
      top:  typeof parsed.top  === "number" ? parsed.top  : DEFAULTS.top,
      mid:  typeof parsed.mid  === "number" ? parsed.mid  : DEFAULTS.mid,
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
  const splitterPx = 12 * 2; // two splitters
  const available = cameraRect.height - splitterPx;
  const minSlot = 160;

  const topPx = clamp(available * sizes.top, minSlot, available - 2 * minSlot);
  const midPx = clamp(available * sizes.mid, minSlot, available - topPx - minSlot);

  layout.style.setProperty("--layout-top", `${topPx}px`);
  layout.style.setProperty("--layout-mid", `${midPx}px`);
}

function startResize(panel, event) {
  event.preventDefault();
  const startY = event.clientY;
  const startX = event.clientX;
  const layoutRect = layout.getBoundingClientRect();
  const cameraRect = cameraColumn.getBoundingClientRect();
  const startTop = sizes.top;
  const startMid = sizes.mid;
  const startLeft = sizes.left;

  const splitterPx = 12 * 2;
  const available = cameraRect.height - splitterPx;
  const minSlot = 160;

  const onMove = (moveEvent) => {
    if (panel === "vertical") {
      const minLeft = 320;
      const minRight = 340;
      const gutter = 12;
      const maxLeft = Math.max(minLeft, layoutRect.width - minRight - gutter);
      const nextLeft = clamp(startLeft * layoutRect.width + (moveEvent.clientX - startX), minLeft, maxLeft);
      sizes.left = nextLeft / layoutRect.width;
    } else if (panel === "cam") {
      const nextTop = clamp(startTop * available + (moveEvent.clientY - startY), minSlot, available - 2 * minSlot);
      sizes.top = nextTop / available;
    } else if (panel === "robot") {
      const topPx = sizes.top * available;
      const nextMid = clamp(startMid * available + (moveEvent.clientY - startY), minSlot, available - topPx - minSlot);
      sizes.mid = nextMid / available;
    }
    applyLayoutSizes();
    saveSizes();
  };

  const onUp = () => {
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onUp);
    document.body.classList.remove("is-resizing", "is-resizing-vertical", "is-resizing-horizontal");
  };

  const orientation = panel === "vertical" ? "vertical" : "horizontal";
  document.body.classList.add("is-resizing", `is-resizing-${orientation}`);
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onUp);
}

cameraSplit.addEventListener("pointerdown", (e) => startResize("cam", e));
robotSplit.addEventListener("pointerdown", (e) => startResize("robot", e));
layoutSplit.addEventListener("pointerdown", (e) => startResize("vertical", e));
window.addEventListener("resize", applyLayoutSizes);

// ── Cameras ───────────────────────────────────────────────────────────────────

function startCameras() {
  cameraFrames[0].src = "/stream/palm";
  cameraFrames[1].src = "/stream/2";
}

// ── Motor graph ───────────────────────────────────────────────────────────────

const MOTOR_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"];
const MOTOR_COLORS = ["#c1272d", "#2e7a62", "#b8860b", "#2a6bb8", "#8b4fa8", "#d07030"];
const HISTORY_SECS = 30;
const POLL_HZ = 10;
const MAX_POINTS = HISTORY_SECS * POLL_HZ;

const motorHistory = {};
MOTOR_NAMES.forEach((name) => { motorHistory[name] = []; });

const canvas = document.getElementById("motor-graph");
const ctx = canvas ? canvas.getContext("2d") : null;
const legendEl = document.getElementById("motor-legend");

function buildLegend() {
  if (!legendEl) return;
  legendEl.innerHTML = MOTOR_NAMES.map((name, i) =>
    `<span class="motor-legend-item">
      <span class="motor-legend-swatch" style="background:${MOTOR_COLORS[i]}"></span>
      ${name.replace("_", " ")}
    </span>`
  ).join("");
}

function drawGraph() {
  if (!canvas || !ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w === 0 || h === 0) return;

  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
  }

  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = "rgba(28,18,8,0.04)";
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(0, 0, w, h, 14);
  else ctx.rect(0, 0, w, h);
  ctx.fill();

  // Grid lines: 0, -50, +50, -100, +100 for arms; 0/50/100 for gripper
  const gridLines = [-100, -50, 0, 50, 100];
  ctx.strokeStyle = "rgba(28,18,8,0.08)";
  ctx.lineWidth = 1;
  gridLines.forEach((v) => {
    const y = ((100 - v) / 200) * h;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
    if (v === 0) {
      ctx.fillStyle = "rgba(28,18,8,0.22)";
      ctx.font = `10px ui-monospace, monospace`;
      ctx.fillText("0", 4, y - 2);
    }
  });

  const n = Math.max(...MOTOR_NAMES.map((name) => motorHistory[name].length));
  if (n < 2) return;

  MOTOR_NAMES.forEach((name, i) => {
    const hist = motorHistory[name];
    if (hist.length < 2) return;

    const color = MOTOR_COLORS[i];
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();

    hist.forEach((val, idx) => {
      // val is -100..+100 for joints, 0..100 for gripper
      const normVal = name === "gripper" ? val / 2 - 50 : val; // map gripper 0-100 → -50..+50
      const x = (idx / (MAX_POINTS - 1)) * w;
      const y = ((100 - normVal) / 200) * h;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Current value dot
    const last = hist[hist.length - 1];
    const normLast = name === "gripper" ? last / 2 - 50 : last;
    const xLast = ((hist.length - 1) / (MAX_POINTS - 1)) * w;
    const yLast = ((100 - normLast) / 200) * h;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(xLast, yLast, 3.5, 0, Math.PI * 2);
    ctx.fill();
  });
}

async function pollRobotState() {
  try {
    const r = await fetch("/robot/state");
    if (!r.ok) return;
    const data = await r.json();
    const pos = data.positions || {};
    MOTOR_NAMES.forEach((name) => {
      const val = pos[name];
      if (typeof val === "number" && isFinite(val)) {
        const hist = motorHistory[name];
        hist.push(val);
        if (hist.length > MAX_POINTS) hist.shift();
      }
    });
    drawGraph();
  } catch { /* network error — silent */ }
}

// ── Robot primitive buttons ───────────────────────────────────────────────────

async function robotAction(action, extra = {}) {
  const btn = document.getElementById(`btn-${action}`);
  if (btn) btn.disabled = true;
  try {
    await fetch("/robot/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra }),
    });
  } catch { /* silent */ } finally {
    if (btn) btn.disabled = false;
  }
}

document.getElementById("btn-home")?.addEventListener("click", () => robotAction("home"));
document.getElementById("btn-grip")?.addEventListener("click", () => robotAction("grip"));
document.getElementById("btn-release")?.addEventListener("click", () => robotAction("release"));

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
  buildLegend();
  if (window.matchMedia("(min-width: 769px)").matches) {
    chatInput.focus();
  }
  loadRemoteUrl();
  pollPalmStatus();
  setInterval(pollPalmStatus, 1000);
  setInterval(pollRobotState, 1000 / POLL_HZ);
});
