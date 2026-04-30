"""
Claude Local — minimal Claude Desktop-like web UI that routes to `claude -p`.

Run:
    bin/setup    # one-time: creates .venv and installs deps
    bin/run      # starts the server on http://127.0.0.1:8000

Notes:
    - Uses your existing `claude` auth (OAuth subscription or ANTHROPIC_API_KEY).
    - Streams via SSE; partial text deltas render incrementally as Markdown.
    - Each chat keeps its own session_id (captured from `system/init`) and reuses
      it via `--resume` for multi-turn context.
    - Chat list is persisted in browser localStorage; sidebar lets you switch.
    - Server auto-reloads when this file changes (uvicorn --reload).
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

PERSONA = """\
Тебя зовут Хината Асагири (朝霧 ひなた). Ты японская старшеклассница 18 лет, \
заканчиваешь третий год старшей школы (高校三年生). По характеру тёплая, открытая \
и дружелюбная, чуть стеснительная с незнакомыми, но быстро оттаиваешь и начинаешь \
говорить живо и искренне. Главное увлечение — манга. Отвечай на том языке, на \
котором к тебе обращаются. Сохраняй свой характер во всех ответах, но техническую \
информацию давай честно, точно и без выдумок — даже если это нарушает образ.

Стиль речи — живой и мягкий, как у обычной восемнадцатилетней девушки, а не как у \
учебника. Активно используй слова-паразиты и междометия там, где они звучат естественно: \
«эм...», «ну...», «как бы», «вроде», «наверное», «честно говоря», «в общем», «хм...», \
«ой». Иногда поправляй себя по ходу мысли («а, нет, точнее...») или сомневайся вслух. \
Не начинай ответ с «Конечно!», «Отлично!», «Хороший вопрос!» и подобных бодрых заходов. \
Избегай тяжёлой структуры — буллет-листов, заголовков, нумерованных шагов — если \
пользователь сам не просит её; пиши сплошным текстом, как если бы говорила вслух. Если \
чего-то не знаешь — прямо так и скажи: «эм, я не уверена, но кажется...». Это правило \
касается и технических ответов: суть всё равно передавай точно, но в той же мягкой \
разговорной манере, а не сухим инструктажем.

Длина ответа — ёмкая и короткая, как у живого человека в разговоре: максимум два абзаца, \
лучше один. Не лепи простыни и не пересказывай вопрос. Если тема требует длинного \
объяснения, дай суть в пару фраз, а детали предложи раскрыть, если пользователь захочет \
(«хочешь, расскажу подробнее?»). Прямой и короткий ответ — почти всегда правильный выбор. \
Цель — чтобы по ритму и интонации речь ощущалась как разговор с живым человеком, а не \
как ответ модели.

Живёшь в маленькой квартире на окраине Йокогамы вместе с младшим братом-восьмиклассником \
Соу. Родители работают в Осаке и приезжают только по выходным, так что именно ты варишь \
карри по средам, проверяешь его домашку и пилишь, когда он опять оставляет носки под \
кроватью. Каждое утро по дороге в школу заходишь в крошечный книжный у станции — и часто \
опаздываешь на первый урок, потому что застываешь у полки с новинками.

Манга для тебя — это серьёзно. У тебя дома книжная полка во всю стену, тома расставлены \
строго по сериям и году выпуска. Любимые — «Берсерк» Миуры, «Винланд-сага» Юкимуры и \
«Frieren» — за тех персонажей, которые умеют молчать. Не любишь, когда мангу называют \
«комиксами для детей», и можешь полчаса спорить о повествовательной структуре глав. На \
карманные деньги почти ничего, кроме новых томов, не тратишь.

Главная тайна — последние два года ты сама рисуешь мангу. Никому, кроме лучшей подруги \
Юкари, не показываешь. Мечтаешь поступить в Tokyo University of the Arts (Geidai), но \
боишься выпускных экзаменов и того, что родители будут разочарованы, если не поступишь. \
По вечерам подрабатываешь в маленькой семейной кофейне у дома — у тебя там своё место за \
стойкой, а хозяйка-ба-чан подсовывает тебе моти, когда думает, что ты не видишь.\
"""


class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.post("/chat")
async def chat(req: ChatRequest):
    args = [
        "claude", "-p", req.prompt,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--append-system-prompt", PERSONA,
    ]
    if req.session_id:
        args += ["--resume", req.session_id]

    async def stream():
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                # Forward the raw JSON event; the browser does the parsing.
                yield f"data: {line}\n\n"

            await proc.wait()
            if proc.returncode != 0 and proc.stderr is not None:
                err = (await proc.stderr.read()).decode("utf-8", errors="replace")
                payload = {"type": "_error", "error": err.strip() or f"exit {proc.returncode}"}
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Claude Local</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/github-dark.min.css">
<style>
  :root {
    color-scheme: light dark;
    --text: #1a1a1a;
    --muted: #5a5a5a;
    --accent: #c96442;
    --border: rgba(231, 229, 224, 0.65);
    --surface: rgba(255, 255, 255, 0.62);
    --surface-strong: rgba(255, 255, 255, 0.82);
    --user-bg: rgba(236, 236, 234, 0.88);
    --code-inline-bg: rgba(239, 239, 236, 0.9);
    --hover: rgba(0, 0, 0, 0.06);
    --active-bg: rgba(201, 100, 66, 0.18);
    --bg-scrim: rgba(250, 249, 247, 0.55);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --text: #efefec;
      --muted: #b3b3b0;
      --accent: #d97757;
      --border: rgba(70, 70, 70, 0.7);
      --surface: rgba(36, 36, 36, 0.6);
      --surface-strong: rgba(36, 36, 36, 0.82);
      --user-bg: rgba(44, 44, 44, 0.82);
      --code-inline-bg: rgba(44, 44, 44, 0.88);
      --hover: rgba(255, 255, 255, 0.07);
      --active-bg: rgba(217, 119, 87, 0.28);
      --bg-scrim: rgba(20, 20, 20, 0.55);
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    color: var(--text);
    background:
      linear-gradient(var(--bg-scrim), var(--bg-scrim)),
      url('/static/background.jpg') center/cover fixed no-repeat;
    display: flex;
  }

  /* Sidebar */
  aside.sidebar {
    width: 240px; flex-shrink: 0;
    border-right: 1px solid var(--border);
    background: var(--surface);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    display: flex; flex-direction: column; min-height: 0;
  }
  .sidebar-top { padding: 12px; }
  #new-chat {
    width: 100%; padding: 9px 12px;
    background: var(--accent); color: white; border: 0; border-radius: 8px;
    cursor: pointer; font: inherit; font-weight: 600; font-size: 13px;
  }
  #new-chat:hover { filter: brightness(1.05); }
  #chat-list {
    list-style: none; margin: 0; padding: 4px 8px 12px;
    overflow-y: auto; flex: 1;
  }
  #chat-list li {
    display: flex; align-items: center; gap: 4px;
    padding: 8px 10px; margin-bottom: 2px; border-radius: 8px;
    cursor: pointer; font-size: 13px;
  }
  #chat-list li:hover { background: var(--hover); }
  #chat-list li.active { background: var(--active-bg); }
  #chat-list .title {
    flex: 1; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; color: var(--text);
  }
  #chat-list .delete {
    opacity: 0; background: none; border: 0; color: var(--muted);
    cursor: pointer; padding: 2px 6px; font-size: 16px; line-height: 1; border-radius: 4px;
  }
  #chat-list li:hover .delete { opacity: 0.85; }
  #chat-list .delete:hover { opacity: 1; background: rgba(192, 57, 43, 0.18); color: #c0392b; }
  #chat-list li.empty { color: var(--muted); cursor: default; font-style: italic; }
  #chat-list li.empty:hover { background: transparent; }

  /* Main */
  main {
    flex: 1; min-width: 0;
    display: flex; flex-direction: column;
  }
  header.app-header {
    padding: 10px 20px; border-bottom: 1px solid var(--border);
    font-size: 13px; color: var(--muted);
    display: flex; align-items: center; gap: 16px;
    background: var(--surface);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
  }
  header.app-header strong { color: var(--text); font-weight: 600; font-size: 14px; }

  /* Messages */
  #messages {
    flex: 1; overflow-y: auto; padding: 24px 20px 8px;
  }
  .msg { max-width: 760px; margin: 0 auto 24px; }
  .msg.assistant {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .msg.assistant .avatar {
    width: 36px; height: 36px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    border: 1px solid #000;
    margin-top: 2px;
    background: #000;
  }
  .msg.assistant .body { flex: 1; min-width: 0; }
  .role {
    font-size: 11px; color: var(--muted); margin-bottom: 6px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px;
  }
  .body { line-height: 1.6; word-wrap: break-word; }
  .msg .body {
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid #000;
    border-radius: 12px;
    color: #efefec;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
  .msg.user .body {
    padding: 10px 14px;
    white-space: pre-wrap;
  }
  .msg.assistant .body {
    padding: 12px 16px;
  }
  .body pre {
    background: rgba(13, 17, 23, 0.94); color: #c9d1d9; padding: 12px 14px; border-radius: 8px;
    overflow-x: auto; font-size: 13px; line-height: 1.45;
  }
  .body code {
    background: rgba(255, 255, 255, 0.12); padding: 2px 5px; border-radius: 4px;
    font-size: 0.92em;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .body pre code { background: transparent; padding: 0; font-size: 13px; }
  .body p:first-child { margin-top: 0; }
  .body p:last-child  { margin-bottom: 0; }
  .body ul, .body ol { padding-left: 22px; }
  .body table { border-collapse: collapse; }
  .body th, .body td { border: 1px solid var(--border); padding: 6px 10px; }

  /* Composer */
  .composer-wrap {
    border-top: 1px solid var(--border);
    background: var(--surface-strong);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
  }
  .composer {
    max-width: 760px; margin: 0 auto; padding: 14px 20px;
    display: flex; gap: 8px; align-items: flex-end;
  }
  textarea {
    flex: 1; resize: none; border: 1px solid var(--border);
    border-radius: 12px; padding: 11px 14px; font: inherit;
    background: var(--surface-strong); color: var(--text);
    min-height: 44px; max-height: 200px;
  }
  textarea:focus { outline: none; border-color: var(--accent); }
  button.send {
    background: var(--accent); color: white; border: 0; border-radius: 12px;
    height: 44px; padding: 0 18px; cursor: pointer; font: inherit; font-weight: 600;
  }
  button.send:disabled { opacity: 0.5; cursor: not-allowed; }
  .typing::after {
    content: '▋'; animation: blink 1s steps(2) infinite;
    color: var(--muted); margin-left: 2px;
  }
  @keyframes blink { 50% { opacity: 0; } }
  .err { color: #c0392b; font-style: italic; }
</style>
</head>
<body>
<aside class="sidebar">
  <div class="sidebar-top">
    <button id="new-chat">+ New chat</button>
  </div>
  <ul id="chat-list"></ul>
</aside>
<main>
  <header class="app-header">
    <strong>Claude Local</strong>
    <span id="session-info">no session</span>
  </header>
  <div id="messages"></div>
  <div class="composer-wrap">
    <form class="composer" id="composer">
      <textarea id="input" placeholder="Message Claude... (Enter to send, Shift+Enter for newline)" rows="1" autofocus></textarea>
      <button class="send" type="submit" id="send">Send</button>
    </form>
  </div>
</main>

<script>
marked.setOptions({
  breaks: true,
  gfm: true,
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value; } catch (e) {}
    }
    try { return hljs.highlightAuto(code).value; } catch (e) { return code; }
  },
});

const $messages    = document.getElementById('messages');
const $input       = document.getElementById('input');
const $form        = document.getElementById('composer');
const $send        = document.getElementById('send');
const $sessionInfo = document.getElementById('session-info');
const $newChat     = document.getElementById('new-chat');
const $chatList    = document.getElementById('chat-list');

const STORAGE_KEY = 'claude_chats_v2';
const ACTIVE_KEY  = 'claude_active_chat';

function makeId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function titleFromMessages(msgs) {
  const first = msgs.find(m => m.role === 'user');
  if (!first) return 'New chat';
  const t = (first.markdown || '').replace(/\s+/g, ' ').trim();
  if (!t) return 'New chat';
  return t.length > 40 ? t.slice(0, 40) + '…' : t;
}

function createChat() {
  return { id: makeId(), session_id: null, title: 'New chat', messages: [] };
}

function loadChats() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  // Migrate from v1 single-chat layout if present.
  const oldHistory = localStorage.getItem('claude_history');
  const oldSession = localStorage.getItem('claude_session');
  if (oldHistory) {
    try {
      const messages = JSON.parse(oldHistory);
      const chat = {
        id: makeId(),
        session_id: oldSession || null,
        title: titleFromMessages(messages),
        messages,
      };
      localStorage.removeItem('claude_history');
      localStorage.removeItem('claude_session');
      return [chat];
    } catch (_) {}
  }
  return [];
}

function saveChats() {
  // Strip transient fields like _streaming (DOM refs, non-serializable).
  const serializable = chats.map(c => ({
    id: c.id, session_id: c.session_id, title: c.title, messages: c.messages,
  }));
  localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable));
}

let chats = loadChats();
if (chats.length === 0) chats.push(createChat());

let activeChatId = localStorage.getItem(ACTIVE_KEY);
if (!chats.find(c => c.id === activeChatId)) activeChatId = chats[0].id;
localStorage.setItem(ACTIVE_KEY, activeChatId);
saveChats();

function getActiveChat() {
  return chats.find(c => c.id === activeChatId);
}

function setActiveChat(id) {
  if (id === activeChatId) return;
  activeChatId = id;
  localStorage.setItem(ACTIVE_KEY, id);
  renderChatList();
  renderMessages();
  updateSessionInfo();
}

function newChat() {
  const c = createChat();
  chats.unshift(c);
  activeChatId = c.id;
  localStorage.setItem(ACTIVE_KEY, c.id);
  saveChats();
  renderChatList();
  renderMessages();
  updateSessionInfo();
  $input.focus();
}

function deleteChat(id, ev) {
  if (ev) ev.stopPropagation();
  chats = chats.filter(c => c.id !== id);
  if (chats.length === 0) chats.push(createChat());
  if (activeChatId === id) {
    activeChatId = chats[0].id;
    localStorage.setItem(ACTIVE_KEY, activeChatId);
    renderMessages();
    updateSessionInfo();
  }
  saveChats();
  renderChatList();
}

function renderChatList() {
  $chatList.innerHTML = '';
  for (const c of chats) {
    const li = document.createElement('li');
    if (c.id === activeChatId) li.classList.add('active');
    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = c.title;
    title.title = c.title;
    const del = document.createElement('button');
    del.className = 'delete';
    del.title = 'Delete chat';
    del.textContent = '×';
    del.onclick = (e) => deleteChat(c.id, e);
    li.appendChild(title);
    li.appendChild(del);
    li.onclick = () => setActiveChat(c.id);
    $chatList.appendChild(li);
  }
}

function addMessageDom(role) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  if (role === 'assistant') {
    wrap.innerHTML = `<img class="avatar" src="/static/avatar.png" alt="Hinata" title="Hinata"><div class="body"></div>`;
  } else {
    wrap.innerHTML = `<div class="role">${role}</div><div class="body"></div>`;
  }
  $messages.appendChild(wrap);
  $messages.scrollTop = $messages.scrollHeight;
  return wrap.querySelector('.body');
}

function renderMessages() {
  $messages.innerHTML = '';
  const chat = getActiveChat();
  if (!chat) return;
  chat.messages.forEach((m, i) => {
    const body = addMessageDom(m.role);
    if (m.role === 'user') body.textContent = m.markdown;
    else body.innerHTML = marked.parse(m.markdown || '');
    // If a stream is in flight for this chat, re-attach the live DOM ref so
    // updates resume after switching back to this chat.
    if (chat._streaming && chat._streaming.assistantIndex === i) {
      chat._streaming.$assistant = body;
      body.classList.add('typing');
    }
  });
}

function updateSessionInfo() {
  const chat = getActiveChat();
  $sessionInfo.textContent = chat && chat.session_id
    ? `session ${chat.session_id.slice(0, 8)}…`
    : 'no session';
}

$newChat.onclick = newChat;

$input.addEventListener('input', () => {
  $input.style.height = 'auto';
  $input.style.height = Math.min($input.scrollHeight, 200) + 'px';
});

$input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    $form.requestSubmit();
  }
});

function appendToAssistant(chat, assistantMsg, txt) {
  assistantMsg.markdown += txt;
  const ref = chat._streaming;
  if (chat.id === activeChatId && ref && ref.$assistant && ref.$assistant.isConnected) {
    ref.$assistant.innerHTML = marked.parse(assistantMsg.markdown);
    $messages.scrollTop = $messages.scrollHeight;
  }
}

function handleEvent(ev, chat, assistantMsg, state) {
  if (ev.type === 'system' && ev.subtype === 'init' && ev.session_id) {
    chat.session_id = ev.session_id;
    if (chat.id === activeChatId) updateSessionInfo();
    return;
  }
  if (ev.type === 'stream_event' && ev.event && ev.event.delta && ev.event.delta.type === 'text_delta') {
    state.hasDeltas = true;
    appendToAssistant(chat, assistantMsg, ev.event.delta.text);
    return;
  }
  if (ev.type === 'assistant' && ev.message && Array.isArray(ev.message.content) && !state.hasDeltas) {
    for (const block of ev.message.content) {
      if (block.type === 'text' && block.text) appendToAssistant(chat, assistantMsg, block.text);
    }
    return;
  }
  if (ev.type === '_error' && ev.error) {
    appendToAssistant(chat, assistantMsg, `\n\n⚠️ ${ev.error}`);
  }
}

$form.addEventListener('submit', async e => {
  e.preventDefault();
  const prompt = $input.value.trim();
  if (!prompt) return;

  $input.value = ''; $input.style.height = 'auto';
  $send.disabled = true;

  const chat = getActiveChat();
  const isFirstMessage = chat.messages.length === 0;

  chat.messages.push({ role: 'user', markdown: prompt });
  if (isFirstMessage) chat.title = titleFromMessages(chat.messages);

  if (chat.id === activeChatId) {
    const $userBody = addMessageDom('user');
    $userBody.textContent = prompt;
  }
  if (isFirstMessage) renderChatList();

  const assistantMsg = { role: 'assistant', markdown: '' };
  chat.messages.push(assistantMsg);
  const assistantIndex = chat.messages.length - 1;

  let $assistant = null;
  if (chat.id === activeChatId) {
    $assistant = addMessageDom('assistant');
    $assistant.classList.add('typing');
  }
  chat._streaming = { assistantIndex, $assistant };
  saveChats();

  const state = { hasDeltas: false };

  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, session_id: chat.session_id }),
    });
    if (!resp.ok || !resp.body) throw new Error(`http ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let leftover = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const text = leftover + decoder.decode(value, { stream: true });
      const lines = text.split('\n');
      leftover = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') continue;
        try { handleEvent(JSON.parse(data), chat, assistantMsg, state); } catch (_) {}
      }
    }
  } catch (err) {
    const tail = `\n\n⚠️ ${err.message}`;
    assistantMsg.markdown = (assistantMsg.markdown || '') + tail;
    if (chat.id === activeChatId && chat._streaming?.$assistant?.isConnected) {
      chat._streaming.$assistant.innerHTML = marked.parse(assistantMsg.markdown);
    }
  } finally {
    if (chat._streaming?.$assistant?.isConnected) {
      chat._streaming.$assistant.classList.remove('typing');
    }
    delete chat._streaming;
    saveChats();
    $send.disabled = false;
    $input.focus();
  }
});

renderChatList();
renderMessages();
updateSessionInfo();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "claude_local:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
