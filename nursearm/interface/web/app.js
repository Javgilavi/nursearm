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
      top:  typeof parsed.top  === "number" ? parsed.top  : DEFAULTS.top,
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
  const splitterPx = 12; // one splitter
  const available = cameraRect.height - splitterPx;
  const minSlot = 160;

  const topPx = clamp(available * sizes.top, minSlot, available - minSlot);
  layout.style.setProperty("--layout-top", `${topPx}px`);
}

function startResize(panel, event) {
  event.preventDefault();
  const startY = event.clientY;
  const startX = event.clientX;
  const layoutRect = layout.getBoundingClientRect();
  const cameraRect = cameraColumn.getBoundingClientRect();
  const startTop = sizes.top;
  const startLeft = sizes.left;

  const splitterPx = 12;
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
      const nextTop = clamp(startTop * available + (moveEvent.clientY - startY), minSlot, available - minSlot);
      sizes.top = nextTop / available;
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
    if (_robot3d) _robot3d.updateArm(pos);
  } catch { /* network error — silent */ }
}

// ── 3D Digital Twin (pure Canvas 2D — FK projection, drag to orbit) ──────────

let _robot3d = null;

function initRobot3D() {
  const canvas3d = document.getElementById("robot-3d");
  if (!canvas3d) return null;
  const ctx = canvas3d.getContext("2d");
  if (!ctx) return null;

  const L1 = 0.100, L2 = 0.100, L3 = 0.100, L4 = 0.033;
  const JSCALE = {
    shoulder_pan:  (108.9 * Math.PI / 180) / 100,
    shoulder_lift: (106.2 * Math.PI / 180) / 100,
    elbow_flex:    (108.0 * Math.PI / 180) / 100,
    wrist_flex:    (110.0 * Math.PI / 180) / 100,
  };

  let azimuth = 0.3;
  let autoRotate = true;
  let dragging = false, lastDragX = 0;
  // Neutral horizontal pose for display until first sensor reading arrives
  let currentPos = {
    shoulder_pan: 0, shoulder_lift: 0,
    elbow_flex: 0, wrist_flex: 0,
    wrist_roll: 0, gripper: 0,
  };

  canvas3d.addEventListener("pointerdown", (e) => {
    autoRotate = false;  // stop spinning on first click
    dragging = true; lastDragX = e.clientX;
    canvas3d.setPointerCapture(e.pointerId);
  });
  canvas3d.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    azimuth += (e.clientX - lastDragX) * 0.007;
    lastDragX = e.clientX;
  });
  canvas3d.addEventListener("pointerup", () => { dragging = false; });

  function fkPts(pos) {
    const q1 = (pos.shoulder_pan  || 0) * JSCALE.shoulder_pan;
    const q2 = (pos.shoulder_lift || 0) * JSCALE.shoulder_lift;
    const q3 = (pos.elbow_flex    || 0) * JSCALE.elbow_flex;
    const q4 = (pos.wrist_flex    || 0) * JSCALE.wrist_flex;
    const c1 = Math.cos(q1), s1 = Math.sin(q1);
    const c2 = Math.cos(q2), s2 = Math.sin(q2);
    const c23 = Math.cos(q2 + q3), s23 = Math.sin(q2 + q3);
    const c234 = Math.cos(q2 + q3 + q4), s234 = Math.sin(q2 + q3 + q4);
    const spread = 0.013 * (1 - Math.min(100, Math.max(0, pos.gripper || 0)) / 100) + 0.004;
    const p4x = L2 * c2 * c1 + L3 * c23 * c1 + L4 * c234 * c1;
    const p4y = L2 * c2 * s1 + L3 * c23 * s1 + L4 * c234 * s1;
    const p4z = L1 + L2 * s2 + L3 * s23 + L4 * s234;
    return {
      p0: [0, 0, 0],
      p1: [0, 0, L1],
      p2: [L2 * c2 * c1, L2 * c2 * s1, L1 + L2 * s2],
      p3: [L2 * c2 * c1 + L3 * c23 * c1, L2 * c2 * s1 + L3 * c23 * s1, L1 + L2 * s2 + L3 * s23],
      p4: [p4x, p4y, p4z],
      fL: [p4x + spread * Math.sin(q1), p4y - spread * Math.cos(q1), p4z],
      fR: [p4x - spread * Math.sin(q1), p4y + spread * Math.cos(q1), p4z],
    };
  }

  const EL = 0.22;  // elevation: gentle tilt, no extreme foreshortening
  function orbitProject(x, y, z, cx, cy, sc) {
    const cosA = Math.cos(azimuth), sinA = Math.sin(azimuth);
    const rx = x * cosA - y * sinA;
    const ry = x * sinA + y * cosA;
    const sy = z * Math.cos(EL) - ry * Math.sin(EL);
    const depth = z * Math.sin(EL) + ry * Math.cos(EL);
    const f = 0.9 / Math.max(0.3, 0.9 + depth - 0.1);
    return [cx + rx * sc * f, cy + sy * sc * f, depth];  // +sy: 180° vertical flip
  }

  (function render() {
    const dpr = window.devicePixelRatio || 1;
    const cw = canvas3d.clientWidth;
    const ch = canvas3d.clientHeight;
    if (cw === 0 || ch === 0) { requestAnimationFrame(render); return; }
    if (canvas3d.width !== cw * dpr || canvas3d.height !== ch * dpr) {
      canvas3d.width = cw * dpr;
      canvas3d.height = ch * dpr;
      ctx.scale(dpr, dpr);
    }

    ctx.clearRect(0, 0, cw, ch);

    if (autoRotate) azimuth += 0.004;
    const cx = cw * 0.46, cy = ch * 0.32;  // base at upper-third, arm hangs into lower canvas
    const sc = Math.min(cw, ch) * 2.4;
    const pt = (p) => orbitProject(p[0], p[1], p[2], cx, cy, sc);

    const { p0, p1, p2, p3, p4, fL, fR } = fkPts(currentPos);
    const pts0 = pt(p0), pts1 = pt(p1), pts2 = pt(p2),
          pts3 = pt(p3), pts4 = pt(p4), ptfL = pt(fL), ptfR = pt(fR);
    const w = Math.max(2.5, Math.min(cw, ch) * 0.028);

    const segs = [
      { a: pts1, b: pts2, color: "rgba(193,39,45,0.95)", lw: w * 1.2 },
      { a: pts2, b: pts3, color: "rgba(160,32,37,0.95)", lw: w * 1.2 },
      { a: pts3, b: pts4, color: "rgba(135,26,30,0.95)", lw: w * 0.8 },
      { a: pts4, b: ptfL, color: "rgba(46,122,98,0.95)", lw: w * 0.45 },
      { a: pts4, b: ptfR, color: "rgba(46,122,98,0.95)", lw: w * 0.45 },
    ].sort((a, b) => (b.a[2] + b.b[2]) - (a.a[2] + a.b[2]));

    segs.forEach(({ a, b, color, lw }) => {
      ctx.strokeStyle = "rgba(0,0,0,0.22)";
      ctx.lineWidth = lw + 2;
      ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(a[0] + 1.5, a[1] + 1.5); ctx.lineTo(b[0] + 1.5, b[1] + 1.5); ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = lw;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    });

    const jr = w * 0.65;
    [pts2, pts3].forEach((p) => {
      ctx.fillStyle = "rgba(0,0,0,0.22)";
      ctx.beginPath(); ctx.arc(p[0] + 1, p[1] + 1, jr, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(184,134,11,0.95)";
      ctx.beginPath(); ctx.arc(p[0], p[1], jr, 0, Math.PI * 2); ctx.fill();
    });

    requestAnimationFrame(render);
  })();

  return { updateArm: (pos) => { currentPos = { ...pos }; } };
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

["up", "down", "forward", "back", "left", "right"].forEach((dir) => {
  document.getElementById(`btn-${dir}`)?.addEventListener("click", () =>
    robotAction("move", { direction: dir, step_m: 0.02 })
  );
});

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
  _robot3d = initRobot3D();
  if (window.matchMedia("(min-width: 769px)").matches) {
    chatInput.focus();
  }
  loadRemoteUrl();
  pollPalmStatus();
  setInterval(pollPalmStatus, 1000);
  setInterval(pollRobotState, 1000 / POLL_HZ);
});
