const API_BASE_URL = window.location.origin;

const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const messagesEl = document.querySelector("#messages");
const clearButtonEl = document.querySelector("#clearChat");
const micButton = document.querySelector("#micButton");
const voiceStatusEl = document.querySelector(".listening-status");
const clockEl = document.querySelector("#clock");

let recognition = null;
let liveMode = false;
let isListening = false;
let isSpeaking = false;
let interactionState = "idle";
let pendingTranscript = "";
let commandCount = 0;
let systemInterval = null;
let restartTimer = null;

window.HELIX_ORB_MODE = "idle";
window.HELIX_AUDIO_LEVEL = 0;

function setOrbMode(mode) {
  window.HELIX_ORB_MODE = mode;
}

function setInteractionState(state, label) {
  interactionState = state;

  const modes = {
    idle: "idle",
    listening: "listening",
    processing: "processing",
    speaking: "speaking",
    error: "idle",
  };

  setOrbMode(modes[state] || "idle");
  document.body.dataset.helixState = state;

  if (voiceStatusEl) {
    voiceStatusEl.innerHTML = `<span></span>${label}`;
  }
}

function scheduleListening(delay = 500) {
  clearTimeout(restartTimer);

  if (!liveMode || isSpeaking || interactionState === "processing") return;

  restartTimer = setTimeout(() => {
    startListening();
  }, delay);
}

function addMessage(role, content) {
  if (!messagesEl) return;

  const article = document.createElement("article");
  article.className = `message ${role}`;

  const p = document.createElement("p");
  p.textContent = content;

  const small = document.createElement("small");
  small.textContent = role === "user" ? "Você" : "HELIX";

  article.appendChild(p);
  article.appendChild(small);

  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function normalizeText(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();
}

function commandFromNaturalSpeech(text) {
  const original = String(text || "").trim();
  const normalized = normalizeText(original);

  if (/^(helix|relix|elix|alex|hey helix|ei helix)[,\s-]+/.test(normalized)) {
    return original.replace(/^(helix|relix|elix|alex|hey helix|ei helix)[,\s-]+/i, "").trim();
  }

  if (/^(abre|abrir|abra) (o )?(obs|obsidian|obsidina|obisidian)$/.test(normalized)) {
    return "abrir obsidian";
  }

  if (/^(lista|listar|mostra|mostrar|me mostra|me lista).*(notas|obsidian)/.test(normalized)) {
    return "listar notas no obsidian";
  }

  if (/^(salva|salvar|guarda|guardar).*(resumo|conversa)/.test(normalized)) {
    return "salvar resumo no obsidian";
  }

  if (/^(anota|anotar|guarda isso|salva isso|cria uma nota|criar nota)\b/.test(normalized)) {
    const content = original.replace(/^(anota|anotar|guarda isso|salva isso|cria uma nota|criar nota)[,:]?\s*/i, "").trim();
    return `salvar no obsidian Nota de voz: ${content}`;
  }

  if (/^(busca|buscar|procura|procurar)\b/.test(normalized)) {
    const content = original.replace(/^(busca|buscar|procura|procurar)\s*/i, "").trim();
    return `buscar ${content} no obsidian`;
  }

  return original;
}

function shouldStopVoice(text) {
  const normalized = normalizeText(text);

  return /^(parar|cancelar|desligar voz|para de ouvir|modo texto|chega)$/.test(normalized);
}

function finishSpeaking() {
  isSpeaking = false;
  startSystemMonitor();

  if (liveMode) {
    setInteractionState("listening", "Modo vivo ativo. Ouvindo...");
    scheduleListening();
    return;
  }

  setInteractionState("idle", "Clique no microfone para falar");
}

function speakFallback(text) {
  if (!("speechSynthesis" in window)) {
    finishSpeaking();
    return;
  }

  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "pt-BR";
  utterance.rate = 0.94;
  utterance.pitch = 0.98;
  utterance.volume = 0.95;

  utterance.onend = finishSpeaking;
  utterance.onerror = finishSpeaking;

  speechSynthesis.speak(utterance);
}

async function speak(text) {
  if (!text) {
    finishSpeaking();
    return;
  }

  isSpeaking = true;
  stopSystemMonitor();
  setInteractionState("speaking", "Falando...");

  try {
    const response = await fetch(`${API_BASE_URL}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    const contentType = response.headers.get("content-type") || "";

    console.log("TTS status:", response.status);
    console.log("TTS content-type:", contentType);

    if (!response.ok || !contentType.includes("audio")) {
      throw new Error("TTS remoto indisponível");
    }

    const audioBlob = await response.blob();

    console.log("TTS blob size:", audioBlob.size);
    console.log("TTS blob type:", audioBlob.type);

    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);

    audio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      finishSpeaking();
    };

    audio.onerror = () => {
      URL.revokeObjectURL(audioUrl);
      speakFallback(text);
    };

    await audio.play();
  } catch (error) {
    console.warn("Usando fallback do navegador:", error);
    speakFallback(text);
  }
}

async function sendMessage(message, voiceMode = false) {
  const cleanMessage = String(message || "").trim();

  if (!cleanMessage) {
    scheduleListening();
    return;
  }

  commandCount += 1;
  updateCommandCount();

  addMessage("user", cleanMessage);

  if (inputEl) {
    inputEl.value = "";
  }

  stopSystemMonitor();
  setInteractionState("processing", "Pensando...");

  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: cleanMessage,
        voice_mode: voiceMode,
      }),
    });

    const data = await response.json();

    const helixResponse =
      data.response ||
      data.message ||
      data.reply ||
      data.error ||
      "Resposta recebida.";
    
    const helixSpeechResponse =
      data.speech_response ||
      helixResponse;

    addMessage("helix", helixResponse);

    if (data.error) {
      setInteractionState("error", "Erro na resposta");
      startSystemMonitor();
      scheduleListening(1000);
      return;
    }

    await speak(helixSpeechResponse);

  } catch (error) {
    console.error(error);
    addMessage("helix", "Erro ao conectar com o backend do Helix.");
    setInteractionState("error", "Backend offline");
    startSystemMonitor();
    scheduleListening(1200);
  }
}

async function ensureMicrophoneReady() {
  if (
    !window.isSecureContext &&
    location.hostname !== "127.0.0.1" &&
    location.hostname !== "localhost"
  ) {
    setInteractionState("error", "Microfone exige localhost ou HTTPS");
    addMessage("helix", "Abra pelo endereço local do Helix, por exemplo http://127.0.0.1:8000/app/.");
    return false;
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    setInteractionState("error", "Microfone indisponível");
    addMessage("helix", "Este navegador não liberou acesso ao microfone para esta página.");
    return false;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    return true;
  } catch (error) {
    console.warn(error);
    setInteractionState("error", "Permita o microfone");
    addMessage("helix", "Não consegui acessar o microfone. Confira a permissão do navegador.");
    return false;
  }
}

async function listenWithRecorderFallback() {
  if (isSpeaking || interactionState === "processing") return;

  setInteractionState("listening", "Gravando áudio...");

  let stream = null;

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";

    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });

    const stopped = new Promise((resolve) => {
      recorder.addEventListener("stop", resolve, { once: true });
    });

    recorder.start();

    await new Promise((resolve) => setTimeout(resolve, 5200));

    recorder.stop();
    await stopped;

    stream.getTracks().forEach((track) => track.stop());
    stream = null;

    setInteractionState("processing", "Transcrevendo...");

    const audioBlob = new Blob(chunks, { type: mimeType });
    const formData = new FormData();
    formData.append("audio", audioBlob, "helix-voice.webm");

    const response = await fetch(`${API_BASE_URL}/voice/transcribe-file`, {
      method: "POST",
      body: formData,
    });

    const data = await response.json();
    const text = String(data.text || "").trim();

    if (!text) {
      setInteractionState("error", data.error || "Não ouvi nada");
      scheduleListening(1200);
      return;
    }

    if (inputEl) inputEl.value = text;

    const command = commandFromNaturalSpeech(text);
    await sendMessage(command, true);
  } catch (error) {
    console.error(error);
    setInteractionState("error", "Falha ao gravar/transcrever");
    addMessage("helix", "Não consegui gravar ou transcrever o áudio.");
    scheduleListening(1200);
  } finally {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  }
}

function submitRecognizedSpeech() {
  const transcript = pendingTranscript.trim();
  pendingTranscript = "";

  if (!transcript) return false;

  if (shouldStopVoice(transcript)) {
    liveMode = false;
    stopListening();

    if ("speechSynthesis" in window) {
      speechSynthesis.cancel();
    }

    isSpeaking = false;
    setInteractionState("idle", "Modo vivo desativado");
    return true;
  }

  const command = commandFromNaturalSpeech(transcript);
  sendMessage(command, true);

  return true;
}

function initSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    recognition = null;
    setInteractionState("idle", "Clique no microfone para falar");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "pt-BR";
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.addEventListener("start", () => {
    if ("speechSynthesis" in window) {
      speechSynthesis.cancel();
    }

    isSpeaking = false;
    isListening = true;
    micButton?.classList.add("active");

    setInteractionState(
      "listening",
      liveMode ? "Modo vivo ativo. Ouvindo..." : "Ouvindo..."
    );
  });

  recognition.addEventListener("result", (event) => {
    let transcript = "";
    let finalResult = false;

    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      transcript += event.results[i][0].transcript;
      finalResult = event.results[i].isFinal;
    }

    transcript = transcript.trim();

    if (!transcript) return;

    pendingTranscript = transcript;

    if (inputEl) {
      inputEl.value = transcript;
    }

    setInteractionState(
      "listening",
      finalResult ? "Enviando..." : `Te ouvindo: ${transcript}`
    );

    if (finalResult) {
      stopListening();
    }
  });

  recognition.addEventListener("end", () => {
    isListening = false;
    micButton?.classList.remove("active");

    const sent = submitRecognizedSpeech();

    if (sent) return;

    if (liveMode && !isSpeaking) {
      scheduleListening(700);
      return;
    }

    if (!isSpeaking) {
      setInteractionState("idle", "Clique no microfone para falar");
    }
  });

  recognition.addEventListener("error", (event) => {
    console.warn("SpeechRecognition error:", event.error);

    isListening = false;
    micButton?.classList.remove("active");

    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      liveMode = false;
      setInteractionState("error", "Permita o microfone");
      return;
    }

    if (event.error === "aborted") return;

    setInteractionState(
      "error",
      event.error === "no-speech" ? "Não ouvi nada" : "Erro de voz"
    );

    if (liveMode) {
      scheduleListening(1000);
    }
  });
}

async function startListening() {
  if (isListening || isSpeaking || interactionState === "processing") return;

  setInteractionState("listening", "Preparando microfone...");

  const micReady = await ensureMicrophoneReady();

  if (!micReady) return;

  if (!recognition) {
    await listenWithRecorderFallback();
    return;
  }

  try {
    pendingTranscript = "";
    recognition.start();
  } catch (error) {
    console.warn("Não consegui iniciar o reconhecimento de voz:", error);

    if (liveMode) {
      await listenWithRecorderFallback();
    } else {
      setInteractionState("idle", "Clique no microfone para falar");
    }
  }
}

function stopListening() {
  if (!recognition || !isListening) return;

  try {
    recognition.stop();
  } catch (error) {
    console.warn("Erro ao parar reconhecimento:", error);
  }
}

function toggleLiveMode() {
  liveMode = !liveMode;

  if (liveMode) {
    clearTimeout(restartTimer);

    if ("speechSynthesis" in window) {
      speechSynthesis.cancel();
    }

    isSpeaking = false;
    setInteractionState("listening", "Modo vivo ativo. Ouvindo...");
    startListening();
    return;
  }

  clearTimeout(restartTimer);
  stopListening();

  if ("speechSynthesis" in window) {
    speechSynthesis.cancel();
  }

  isSpeaking = false;
  setInteractionState("idle", "Modo vivo desativado");
}

if (formEl) {
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(inputEl?.value || "", false);
  });
}

if (clearButtonEl) {
  clearButtonEl.addEventListener("click", () => {
    if (messagesEl) {
      messagesEl.innerHTML = "";
    }
  });
}

micButton?.addEventListener("click", toggleLiveMode);

function updateClock() {
  if (!clockEl) return;

  clockEl.textContent = new Date().toLocaleTimeString("pt-BR", {
    hour12: false,
  });
}

function updateCommandCount() {
  const commandCountEl = document.querySelector("#commandCount");

  if (commandCountEl) {
    commandCountEl.textContent = commandCount;
  }
}

function startSystemMonitor() {
  if (systemInterval) return;

  fetchSystemMetrics();
  systemInterval = setInterval(fetchSystemMetrics, 5000);
}

function stopSystemMonitor() {
  if (!systemInterval) return;

  clearInterval(systemInterval);
  systemInterval = null;
}

async function fetchSystemMetrics() {
  try {
    const response = await fetch(`${API_BASE_URL}/system`);

    if (!response.ok) {
      throw new Error("Erro ao buscar /system");
    }

    const data = await response.json();
    updateSystemUI(data);
  } catch (error) {
    console.error("Erro ao buscar métricas:", error);
    updateText("#systemLoad", "Offline");
  }
}

function updateSystemUI(data) {
  const cpuPercent = Number(data.cpu?.percent || 0);
  const memoryPercent = Number(data.memory?.percent || 0);
  const diskPercent = Number(data.disk?.percent || 0);

  updateText("#cpuPercent", `${cpuPercent.toFixed(0)}%`);
  updateText(
    "#ramUsage",
    `${data.memory?.used_gb ?? "--"} / ${data.memory?.total_gb ?? "--"} GB`
  );
  updateText(
    "#diskUsage",
    `${data.disk?.used_gb ?? "--"} / ${data.disk?.total_gb ?? "--"} GB`
  );

  updateText("#cpuMini", `${cpuPercent.toFixed(0)}%`);
  updateText("#memoryMini", `${memoryPercent.toFixed(0)}%`);
  updateText("#diskMini", `${diskPercent.toFixed(0)}%`);

  updateText(
    "#lastUpdate",
    new Date().toLocaleTimeString("pt-BR", { hour12: false })
  );

  updateBar("#cpuBar", cpuPercent);
  updateBar("#ramBar", memoryPercent);
  updateBar("#diskBar", diskPercent);

  if (data.uptime?.boot_time) {
    updateText("#uptime", data.uptime.boot_time);
  }

  updateProcesses(data.processes || {});
  updateSystemLoad(cpuPercent, memoryPercent);
}

function updateText(selector, value) {
  const el = document.querySelector(selector);

  if (el) {
    el.textContent = value;
  }
}

function updateBar(selector, percent) {
  const el = document.querySelector(selector);

  if (!el) return;

  const safePercent = Math.min(Math.max(percent, 0), 100);
  el.style.width = `${safePercent}%`;
}

function updateProcesses(processes) {
  const processList = document.querySelector("#processList");

  if (!processList) return;

  processList.innerHTML = "";

  Object.entries(processes).forEach(([name, running]) => {
    const div = document.createElement("div");
    div.className = "process-item";

    div.innerHTML = `
      <span>${name}</span>
      <span class="${running ? "on" : "off"}">
        ${running ? "Online" : "Offline"}
      </span>
    `;

    processList.appendChild(div);
  });
}

function updateSystemLoad(cpuPercent, memoryPercent) {
  const averageLoad = Math.round((cpuPercent + memoryPercent) / 2);
  const label =
    averageLoad >= 75 ? "High" : averageLoad >= 40 ? "Moderate" : "Low";

  updateText("#systemLoad", label);
  updateBar("#systemLoadBar", averageLoad);

  if (!isSpeaking && !liveMode && interactionState !== "processing") {
    setOrbMode(averageLoad >= 85 ? "processing" : "idle");
  }
}

function setupCollapsibleCards() {
  document.querySelectorAll(".collapsible-card").forEach((card) => {
    const button = card.querySelector(".card-toggle");

    if (!button) return;

    button.addEventListener("click", () => {
      card.classList.toggle("collapsed");
    });
  });
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopSystemMonitor();
    return;
  }

  startSystemMonitor();

  if (liveMode && !isSpeaking) {
    scheduleListening();
  }
});

initSpeechRecognition();
setInteractionState("idle", "Clique no microfone para falar");

updateClock();
setInterval(updateClock, 1000);

setupCollapsibleCards();
startSystemMonitor();