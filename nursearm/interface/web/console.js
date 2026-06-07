const appState = {
  medication: {
    name: "Metformin",
    dosage: "500 mg",
    time: "08:00 AM",
    status: "Awaiting palm detection",
    dispensed: false,
  },
  recording: false,
  mediaRecorder: null,
  audioChunks: [],
  lastEvent: "Waiting",
};

const els = {
  chatLog: document.getElementById("chat-log"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  sendButton: document.getElementById("send-button"),
  micButton: document.getElementById("mic-button"),
  emergencyStopButton: document.getElementById("emergency-stop-button"),
  requestMedicationButton: document.getElementById("request-medication-button"),
};

const MOCK_RESPONSES = [
  {
    match: /what medication do i need today/i,
    reply: () => `Today you are scheduled to take ${appState.medication.name} ${appState.medication.dosage} at ${appState.medication.time}.`,
  },
  {
    match: /did i already take my pill/i,
    reply: () => (appState.medication.dispensed ? "Yes. Your scheduled medication was already dispensed." : "Not yet. Your next medication is still pending."),
  },
  {
    match: /give me my next medication/i,
    reply: () => "I can prepare the next medication request. Please place your palm upward in view of the camera to continue.",
  },
  {
    match: /why do i take this medication/i,
    reply: () => "This medication is part of your scheduled treatment plan. A caregiver or clinician should provide the final medical explanation for your case.",
  },
];

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function setDot(id, status) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("is-green", "is-warning", "is-red");
  if (status) el.classList.add(status);
}

function setPill(id, text, success = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("pill-success", success);
}

function addChatMessage(role, text) {
  const item = document.createElement("article");
  item.className = `chat-message ${role}`;
  const title = document.createElement("strong");
  title.textContent = role === "user" ? "Patient" : "MediPalm AI";
  const body = document.createElement("p");
  body.textContent = text;
  item.append(title, body);
  els.chatLog.append(item);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function setLastEvent(text) {
  appState.lastEvent = text;
  setText("last-event", text);
}

function updateMedicationCard() {
  setText("medication-name", appState.medication.name);
  setText("medication-dosage", appState.medication.dosage);
  setText("medication-time", appState.medication.time);
  setText("medication-detail-status", appState.medication.status);
  setText("medication-status", appState.medication.dispensed ? "Dispensed" : "Scheduled");
  setText("status-medication-text", appState.medication.dispensed ? "Medication dispensed" : "Medication selected");
  setDot("status-medication-dot", appState.medication.dispensed ? "is-green" : "is-warning");
}

function fallbackChatReply(text) {
  for (const candidate of MOCK_RESPONSES) {
    if (candidate.match.test(text)) {
      return candidate.reply();
    }
  }
  return "I can help with your medication schedule, next pill, dose status and basic medication questions.";
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} failed: ${response.status}`);
  return response.json();
}

async function refreshHealth() {
  try {
    const health = await getJson("/health");
    setText("status-camera-text", health.ok ? "Camera online" : "Camera offline");
  } catch {
    setText("status-camera-text", "Camera offline");
    setDot("status-camera-dot", "is-red");
  }
}

async function refreshState() {
  try {
    const payload = await getJson("/state");
    const cameraReady = Boolean(payload.camera_connected);
    const robotReady = Boolean(payload.robot_connected);
    setText("scene-camera", cameraReady ? "Online" : "Offline");
    setText("status-camera-text", cameraReady ? "Camera online" : "Camera offline");
    setText("status-robot-text", robotReady ? "Robot ready" : "Robot standby");
    setDot("status-camera-dot", cameraReady ? "is-green" : "is-red");
    setDot("status-robot-dot", robotReady ? "is-green" : "is-warning");
  } catch {
    setText("scene-camera", "Unavailable");
  }
}

async function refreshPalmStatus() {
  try {
    const palm = await getJson("/palm/status");
    const detected = Boolean(palm.detected);
    const open = Boolean(palm.is_open);
    const up = Boolean(palm.palm_up);
    const confidence = Number(palm.palm_up_confidence || 0);

    setText("status-palm-text", detected ? "Palm detected" : "Palm not detected");
    setDot("status-palm-dot", detected ? "is-green" : "is-warning");
    setText("palm-open", detected ? (open ? "Open hand" : "Closed / partial") : "Not detected");
    setText("palm-up", detected ? (up ? "Palm upward" : "Not upward") : "Not detected");
    setText("palm-confidence", `${Math.round(confidence * 100)}%`);

    if (detected && open && up) {
      setPill("palm-badge", "Palm ready", true);
      appState.medication.status = "Ready for dispensing";
    } else if (detected) {
      setPill("palm-badge", "Hand detected", false);
      appState.medication.status = "Waiting for upward-facing open palm";
    } else {
      setPill("palm-badge", "Monitoring", false);
      appState.medication.status = "Awaiting palm detection";
    }
    updateMedicationCard();
  } catch {
    setText("status-palm-text", "Palm not detected");
    setDot("status-palm-dot", "is-warning");
  }
}

async function refreshRobotState() {
  try {
    const payload = await getJson("/robot/state");
    const positions = payload.positions || {};
    const keys = Object.keys(positions);
    setText("robot-summary", keys.length ? "Ready" : "Unavailable");
  } catch {
    setText("robot-summary", "Unavailable");
  }
}

async function postRobotAction(action) {
  const response = await fetch("/robot/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Robot action failed: ${response.status}`);
  return data;
}

async function handleRequestMedication() {
  try {
    const palmText = document.getElementById("palm-up").textContent || "";
    const handText = document.getElementById("palm-open").textContent || "";
    if (!/Palm upward/i.test(palmText) || !/Open hand/i.test(handText)) {
      appState.medication.status = "Cannot dispense: open palm not verified";
      updateMedicationCard();
      setLastEvent("Dispense blocked by palm safety rule");
      addChatMessage("assistant", "Medication is only dispensed when an open palm facing upward is detected.");
      return;
    }

    await postRobotAction("release").catch(() => null);
    appState.medication.dispensed = true;
    appState.medication.status = "Medication dispensed successfully";
    updateMedicationCard();
    setLastEvent("Medication dispensed");
    addChatMessage("assistant", `${appState.medication.name} ${appState.medication.dosage} has been dispensed. Please take your medication carefully.`);
  } catch (error) {
    appState.medication.status = "Dispense request failed";
    updateMedicationCard();
    setLastEvent("Dispense request failed");
    addChatMessage("assistant", `I could not complete the medication request: ${error}`);
  }
}

async function handleChatSubmit(event) {
  event.preventDefault();
  const text = els.chatInput.value.trim();
  if (!text) return;
  els.chatInput.value = "";
  addChatMessage("user", text);
  els.sendButton.disabled = true;
  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Chat failed: ${response.status}`);
    addChatMessage("assistant", data.reply || fallbackChatReply(text));
  } catch {
    addChatMessage("assistant", fallbackChatReply(text));
  } finally {
    els.sendButton.disabled = false;
  }
}

async function sendAudio(blob) {
  const formData = new FormData();
  formData.append("audio", blob, "voice.webm");
  const response = await fetch("/transcribe", { method: "POST", body: formData });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Transcription failed: ${response.status}`);
  if (data.text) {
    els.chatInput.value = data.text;
  }
}

async function toggleRecording() {
  if (appState.recording && appState.mediaRecorder) {
    appState.mediaRecorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    appState.audioChunks = [];
    appState.mediaRecorder = new MediaRecorder(stream);
    appState.recording = true;
    els.micButton.textContent = "Stop";
    appState.mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) appState.audioChunks.push(event.data);
    });
    appState.mediaRecorder.addEventListener("stop", async () => {
      appState.recording = false;
      els.micButton.textContent = "Voice";
      const blob = new Blob(appState.audioChunks, { type: "audio/webm" });
      stream.getTracks().forEach((track) => track.stop());
      try {
        await sendAudio(blob);
      } catch {
        addChatMessage("assistant", "Voice transcription is unavailable right now.");
      }
    });
    appState.mediaRecorder.start();
  } catch {
    addChatMessage("assistant", "Microphone access is unavailable.");
  }
}

function bindPromptChips() {
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      els.chatInput.value = button.getAttribute("data-prompt") || "";
      els.chatInput.focus();
    });
  });
}

function bootstrap() {
  updateMedicationCard();
  addChatMessage("assistant", "Hello. I can help you check today’s medication, confirm whether you already took it and request your next pill.");
  bindPromptChips();
  els.chatForm.addEventListener("submit", handleChatSubmit);
  els.requestMedicationButton.addEventListener("click", handleRequestMedication);
  els.micButton.addEventListener("click", toggleRecording);
  els.emergencyStopButton.addEventListener("click", () => {
    setLastEvent("Emergency stop pressed");
    addChatMessage("assistant", "Emergency stop requested. Please wait for caregiver assistance.");
  });
  refreshHealth();
  refreshState();
  refreshPalmStatus();
  refreshRobotState();
  window.setInterval(() => {
    refreshHealth();
    refreshState();
    refreshPalmStatus();
    refreshRobotState();
  }, 3000);
}

window.addEventListener("load", bootstrap);
