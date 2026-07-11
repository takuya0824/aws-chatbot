const SESSION_KEY = "chatbot_session_id";

function getSessionId() {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");

function appendMessage(role, text) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  appendMessage("user", text);
  input.value = "";
  input.disabled = true;

  const thinkingEl = appendMessage("assistant thinking", "...");

  try {
    const res = await fetch(window.API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: getSessionId(), message: text }),
    });
    const data = await res.json();
    thinkingEl.remove();

    if (!res.ok) {
      appendMessage("assistant", `エラー: ${data.error || res.statusText}`);
    } else {
      appendMessage("assistant", data.reply);
    }
  } catch (err) {
    thinkingEl.remove();
    appendMessage("assistant", `エラー: ${err.message}`);
  } finally {
    input.disabled = false;
    input.focus();
  }
});
