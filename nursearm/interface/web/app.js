const workspace = document.querySelector(".workspace");
const layout = document.getElementById("layout");
const cameraColumn = document.getElementById("camera-column");
const cameraSplit = document.getElementById("camera-splitter");
const layoutSplit = document.getElementById("layout-splitter");
const railSplit = document.getElementById("rail-splitter");
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
const handoverButtons = document.querySelectorAll("[data-handover-color]");
const openClawStatus = document.getElementById("openclaw-status");
const openClawStatusLabel = document.getElementById("openclaw-status-label");
let remoteUrl = null;

// ── Layout persistence ────────────────────────────────────────────────────────

const STORAGE_KEY = "nursearm.ui.sizes";
const DEFAULTS = { rail: 300, left: 0.6, top: 0.5 };

const sizes = (() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return {
      rail: typeof parsed.rail === "number" ? parsed.rail : DEFAULTS.rail,
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
  if (window.matchMedia("(min-width: 1181px)").matches) {
    const workspaceRect = workspace.getBoundingClientRect();
    const minRail = 230;
    const minMain = 852;
    const splitterPx = 12;
    const maxRail = Math.max(minRail, Math.min(480, workspaceRect.width - minMain - splitterPx));
    sizes.rail = clamp(sizes.rail, minRail, maxRail);
    workspace.style.setProperty("--rail-width", `${sizes.rail}px`);
  }

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
  const workspaceRect = workspace.getBoundingClientRect();
  const cameraRect = cameraColumn.getBoundingClientRect();
  const startRail = sizes.rail;
  const startTop = sizes.top;
  const startLeft = sizes.left;

  const splitterPx = 12;
  const available = cameraRect.height - splitterPx;
  const minSlot = 160;

  const onMove = (moveEvent) => {
    if (panel === "rail") {
      const minRail = 230;
      const minMain = 852;
      const maxRail = Math.max(minRail, Math.min(480, workspaceRect.width - minMain - splitterPx));
      sizes.rail = clamp(startRail + (moveEvent.clientX - startX), minRail, maxRail);
    } else if (panel === "vertical") {
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

  const orientation = panel === "cam" ? "horizontal" : "vertical";
  document.body.classList.add("is-resizing", `is-resizing-${orientation}`);
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onUp);
}

cameraSplit.addEventListener("pointerdown", (e) => startResize("cam", e));
layoutSplit.addEventListener("pointerdown", (e) => startResize("vertical", e));
railSplit.addEventListener("pointerdown", (e) => startResize("rail", e));
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
    const cx = cw * 0.46, cy = ch * 0.22;
    const sc = Math.min(cw, 300) * 2.85;
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

function showActivity(text) {
  showSpinner();
  loadingBubble.textContent = text;
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

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 125000);
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });
    const payload = await response.json();
    hideSpinner();
    appendMessage(
      "assistant",
      response.ok ? payload.reply : `Error: ${payload.detail || payload.error || "request failed"}`
    );
  } catch (error) {
    hideSpinner();
    appendMessage(
      "assistant",
      error.name === "AbortError"
        ? "The LLM did not respond within 125 seconds."
        : "Cannot reach the NurseArm backend."
    );
  } finally {
    clearTimeout(timeout);
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

handoverButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const color = button.dataset.handoverColor;
    if (!color) return;

    appendMessage("user", `Run ACT handover for the ${color} pill.`);
    setLoading(true);
    handoverButtons.forEach((item) => { item.disabled = true; });
    showActivity(`Running ${color} pill ACT policy…`);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch("/skills/handover-pill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ color }),
        signal: controller.signal,
      });
      const payload = await response.json();
      hideSpinner();
      const note = payload.note || payload.detail || "Handover request finished.";
      appendMessage("assistant", response.ok ? note : `Error: ${note}`);
    } catch (error) {
      hideSpinner();
      appendMessage(
        "assistant",
        error.name === "AbortError"
          ? "The ACT rollout did not finish within 180 seconds."
          : "Cannot reach the NurseArm backend."
      );
    } finally {
      clearTimeout(timeout);
      setLoading(false);
      handoverButtons.forEach((item) => { item.disabled = false; });
    }
  });
});

// ── SmolVLA sort button ────────────────────────────────────────────────────────

const smolvlaBtn = document.getElementById("btn-sort-smolvla");
if (smolvlaBtn) {
  smolvlaBtn.addEventListener("click", async () => {
    appendMessage("user", "Run SmolVLA pill classification and sort.");
    setLoading(true);
    smolvlaBtn.disabled = true;
    showActivity("Running SmolVLA sort policy…");

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 300000); // 5 min — model may need to download
    try {
      const response = await fetch("/skills/sort-smolvla", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        signal: controller.signal,
      });
      const payload = await response.json();
      hideSpinner();
      const note = payload.note || payload.detail || "SmolVLA sort finished.";
      appendMessage("assistant", response.ok ? note : `Error: ${note}`);
    } catch (error) {
      hideSpinner();
      appendMessage(
        "assistant",
        error.name === "AbortError"
          ? "SmolVLA sort did not finish within 5 minutes."
          : "Cannot reach the NurseArm backend."
      );
    } finally {
      clearTimeout(timeout);
      setLoading(false);
      smolvlaBtn.disabled = false;
    }
  });
}

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
    document.body.classList.remove("mobile-tab-camera", "mobile-tab-status", "mobile-tab-schedule");
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

// ── Medication schedule ─────────────────────────────────────────────────────────

const medConn = document.getElementById("med-conn");
const medConnLabel = document.getElementById("med-conn-label");
const medAutoToggle = document.getElementById("med-autopilot-toggle");
const medList = document.getElementById("med-list");
const medEmpty = document.getElementById("med-empty");
const medAddForm = document.getElementById("med-add-form");
const medAddTime = document.getElementById("med-add-time");
const medAddTrigger = document.getElementById("med-add-trigger");
const medAddDaily = document.getElementById("med-add-daily");
const medAddBtn = document.getElementById("med-add-btn");
const medAddError = document.getElementById("med-add-error");

const medBanner = document.getElementById("med-banner");
const medBannerDot = document.getElementById("med-banner-dot");
const medBannerTitle = document.getElementById("med-banner-title");
const medBannerSub = document.getElementById("med-banner-sub");
const medBannerRun = document.getElementById("med-banner-run");
const medBannerSkip = document.getElementById("med-banner-skip");

const STATUS_CHIP = {
  scheduled: "Upcoming",
  due: "Due now",
  done: "Given",
  skipped: "Skipped",
  missed: "Missed",
};

let medAutoPilot = true;
let medConnected = false;       // writes (add/cancel) are possible
let medPending = null;          // last-known pending firing, for the banner countdown
let medServerOffset = 0;        // serverClock - clientClock, in ms
let medTriggerSig = "";         // signature of the trigger <select> options
let medBusy = false;            // suppress polling clobber during an action

function pad2(n) {
  return String(n).padStart(2, "0");
}

function renderTriggerOptions(triggers) {
  const sig = triggers.map((t) => `${t.key}:${t.label}`).join("|");
  if (sig === medTriggerSig) return;
  medTriggerSig = sig;
  const previous = medAddTrigger.value;
  medAddTrigger.innerHTML = triggers
    .map((t) => `<option value="${t.key}">${t.label}</option>`)
    .join("");
  if (triggers.some((t) => t.key === previous)) medAddTrigger.value = previous;
}

function renderConnection(connection) {
  const backend = connection?.backend;
  const ready = connection?.configured && connection?.authorized;
  medConn.classList.remove("med-conn-unknown", "med-conn-demo", "med-conn-online", "med-conn-offline");
  if (backend === "fake") {
    medConn.classList.add("med-conn-demo");
    medConnLabel.textContent = "Demo";
    medConnected = true;
  } else if (ready) {
    medConn.classList.add("med-conn-online");
    medConnLabel.textContent = "Connected";
    medConnected = true;
  } else {
    medConn.classList.add("med-conn-offline");
    medConnLabel.textContent = "Offline";
    medConnected = false;
  }
  medAddBtn.disabled = !medConnected;
  medAddTime.disabled = !medConnected;
  medAddTrigger.disabled = !medConnected;
}

function renderAutoPilot(enabled) {
  medAutoPilot = enabled;
  medAutoToggle.setAttribute("aria-checked", enabled ? "true" : "false");
}

function eventActions(ev) {
  const del = `<button type="button" class="med-mini-btn med-mini-del" data-del="${ev.id}" aria-label="Remove">×</button>`;
  if (ev.status === "due") {
    return (
      `<button type="button" class="med-mini-btn med-mini-run" data-fire="${ev.id}">Give</button>` +
      `<button type="button" class="med-mini-btn" data-skip="${ev.id}">Skip</button>`
    );
  }
  // Upcoming or missed pills can be run ahead of time ("anticipate") from the UI.
  if (ev.status === "scheduled" || ev.status === "missed") {
    return (
      `<button type="button" class="med-mini-btn" data-fire="${ev.id}" title="Run this pill now, ahead of schedule">Give now</button>` +
      del
    );
  }
  return del;
}

function renderEvents(events) {
  if (!events.length) {
    medList.innerHTML = "";
    medEmpty.hidden = false;
    return;
  }
  medEmpty.hidden = true;
  medList.innerHTML = events
    .map((ev) => {
      const chip = STATUS_CHIP[ev.status] || ev.status;
      return (
        `<li class="med-item is-${ev.status}">` +
        `<span class="med-item-dot" style="background:${ev.color_hex}"></span>` +
        `<span class="med-item-time">${ev.start_human}</span>` +
        `<span class="med-item-label">${ev.label}</span>` +
        `<span class="med-item-chip">${chip}</span>` +
        `<span class="med-item-actions">${eventActions(ev)}</span>` +
        `</li>`
      );
    })
    .join("");
}

function tickBanner() {
  if (!medPending) {
    medBanner.hidden = true;
    return;
  }
  medBanner.hidden = false;
  medBannerDot.style.background = medPending.color_hex || "var(--accent)";

  if (medPending.firing) {
    medBannerTitle.textContent = `Giving ${medPending.label}…`;
    medBannerSub.textContent = "The robot is handing over the pill.";
    medBannerRun.hidden = true;
    medBannerSkip.hidden = true;
    return;
  }

  medBannerRun.hidden = false;
  medBannerSkip.hidden = false;
  medBannerTitle.textContent = `${medPending.label} due`;

  if (medPending.fires_at) {
    const serverNow = Date.now() + medServerOffset;
    const remaining = Math.max(0, Math.ceil((Date.parse(medPending.fires_at) - serverNow) / 1000));
    medBannerSub.textContent =
      remaining > 0 ? `Giving automatically in ${remaining}s — cancel?` : "Giving now…";
  } else {
    medBannerSub.textContent = "Auto-pilot is off — give now or skip.";
  }
}

function renderSchedule(payload) {
  if (payload.server_time) {
    medServerOffset = Date.parse(payload.server_time) - Date.now();
  }
  renderConnection(payload.connection);
  renderAutoPilot(payload.auto_pilot);
  renderTriggerOptions(payload.triggers || []);
  renderEvents(payload.events || []);
  medPending = payload.pending || null;
  tickBanner();
}

async function pollSchedule() {
  if (medBusy) return;
  try {
    const r = await fetch("/calendar/schedule");
    if (!r.ok) return;
    renderSchedule(await r.json());
  } catch { /* network error — keep last-known schedule */ }
}

async function medAction(url, method = "POST") {
  medBusy = true;
  try {
    await fetch(url, { method });
  } catch { /* surfaced on next poll */ } finally {
    medBusy = false;
  }
  await pollSchedule();
}

medAutoToggle.addEventListener("click", async () => {
  const next = !medAutoPilot;
  renderAutoPilot(next);  // optimistic
  medBusy = true;
  try {
    await fetch("/calendar/auto-pilot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next }),
    });
  } catch { /* reverts on next poll */ } finally {
    medBusy = false;
  }
  await pollSchedule();
});

medList.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!target) return;
  if (target.dataset.fire) medAction(`/calendar/fire/${target.dataset.fire}`);
  else if (target.dataset.skip) medAction(`/calendar/skip/${target.dataset.skip}`);
  else if (target.dataset.del) medAction(`/calendar/events/${target.dataset.del}`, "DELETE");
});

medBannerRun.addEventListener("click", () => {
  if (medPending) medAction(`/calendar/fire/${medPending.event_id}`);
});

medBannerSkip.addEventListener("click", () => {
  if (medPending) medAction(`/calendar/skip/${medPending.event_id}`);
});

medAddForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  medAddError.hidden = true;
  const time = medAddTime.value;
  const trigger = medAddTrigger.value;
  if (!time || !trigger) return;

  const [h, m] = time.split(":").map(Number);
  const when = new Date();
  when.setHours(h, m, 0, 0);
  if (when.getTime() <= Date.now()) when.setDate(when.getDate() + 1);
  const startIso =
    `${when.getFullYear()}-${pad2(when.getMonth() + 1)}-${pad2(when.getDate())}` +
    `T${pad2(when.getHours())}:${pad2(when.getMinutes())}:00`;

  medAddBtn.disabled = true;
  medBusy = true;
  try {
    const r = await fetch("/calendar/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trigger, start_iso: startIso, daily: medAddDaily.checked }),
    });
    const payload = await r.json().catch(() => ({}));
    if (!r.ok) {
      medAddError.textContent = payload.detail || "Could not add the pill.";
      medAddError.hidden = false;
    } else {
      medAddTime.value = "";
      medAddDaily.checked = false;
    }
  } catch {
    medAddError.textContent = "Cannot reach the NurseArm backend.";
    medAddError.hidden = false;
  } finally {
    medBusy = false;
    medAddBtn.disabled = !medConnected;
  }
  await pollSchedule();
});

// ── Boot ──────────────────────────────────────────────────────────────────────

function updateOpenClawStatus(status) {
  if (!openClawStatus || !openClawStatusLabel) return;
  const active = status?.active === true;
  openClawStatus.classList.toggle("bot-status-active", active);
  openClawStatus.classList.toggle("bot-status-offline", !active);
  openClawStatusLabel.textContent = active ? "Active" : "Offline";
  openClawStatus.title = active
    ? "OpenClaw container heartbeat received"
    : "No recent heartbeat from the OpenClaw container";
}

async function pollHealth() {
  try {
    const r = await fetch("/health");
    if (!r.ok) throw new Error("health request failed");
    const data = await r.json();
    updateOpenClawStatus(data.openclaw);
    if (data.ngrok_url && data.ngrok_url !== remoteUrl) {
      const section = document.getElementById("remote-access");
      const link = document.getElementById("ngrok-link");
      const qrImg = document.getElementById("qr-image");
      remoteUrl = data.ngrok_url;
      link.href = data.ngrok_url;
      link.textContent = data.ngrok_url.replace("https://", "");
      qrImg.src = "/qr.svg";
      section.hidden = false;
    }
  } catch {
    updateOpenClawStatus(null);
  }
}

window.addEventListener("load", () => {
  applyLayoutSizes();
  startCameras();
  buildLegend();
  _robot3d = initRobot3D();
  if (window.matchMedia("(min-width: 769px)").matches) {
    chatInput.focus();
  }
  pollHealth();
  pollPalmStatus();
  pollSchedule();
  setInterval(pollHealth, 1000);
  setInterval(pollPalmStatus, 1000);
  setInterval(pollRobotState, 1000 / POLL_HZ);
  setInterval(pollSchedule, 3000);
  setInterval(tickBanner, 1000);  // smooth banner countdown between polls
});
