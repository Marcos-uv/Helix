const API_BASE_URL = "http://127.0.0.1:8000";

const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const sendButtonEl = document.querySelector("#sendButton");
const messagesEl = document.querySelector("#messages");
const statusEl = document.querySelector("#status");

function addMessage(role, text, isError = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${isError ? " error" : ""}`;

  const label = document.createElement("strong");
  label.textContent = role === "user" ? "VOCÊ" : "HELIX";

  const paragraph = document.createElement("p");
  paragraph.textContent = text;

  article.append(label, paragraph);
  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage() {
  const message = inputEl.value.trim();

  if (!message) return;

  addMessage("user", message);
  inputEl.value = "";
  sendButtonEl.disabled = true;
  statusEl.textContent = "Pensando...";

  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
        user_name: "marcos",
      }),
    });

    const data = await response.json();

    if (!response.ok || data.error) {
      addMessage(
        "assistant",
        data.response || data.error || "Erro ao processar.",
        true
      );
      return;
    }

    addMessage("assistant", data.response || "Resposta vazia.");
  } catch (error) {
    console.error(error);
    addMessage("assistant", "Erro ao conectar com o backend.", true);
  } finally {
    sendButtonEl.disabled = false;
    statusEl.textContent = "Online";
    inputEl.focus();
  }
}

formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});