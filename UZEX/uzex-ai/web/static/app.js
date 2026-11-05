/**
 * UZEX AI — Minimal Premium Web Chat
 * 
 * Strict privacy: Zero client storage or browser caching.
 * All chat turns live in RAM only and vanish on page reload.
 */

(function () {
  "use strict";

  // In-memory state only
  const state = {
    messages: [],
    isBusy: false,
    lang: "uz_latn", // 'uz_latn' | 'uz_cyrl' | 'ru'
  };

  const UI_TEXT = {
    uz_latn: {
      title: "UZEX AI",
      badge: "Spot Analitika",
      subtitle: "500 000 ta birja bitimi bo‘yicha tasdiqlangan ma’lumotlar",
      status_ready: "Baza faol (500k bitim)",
      status_loading: "Ulanmoqda...",
      status_offline: "Xizmat tayyor emas",
      disclaimer: "Javoblar faqat tasdiqlangan UZEX spot bitimlari datasetiga asoslanadi. Chat tarixi saqlanmaydi.",
      welcome_title: "UZEX AI birja tahlil tizimiga xush kelibsiz",
      welcome_desc: "Savdo bitimlari, shartnomalar, sotuvchi/xaridor kompaniyalar va tovarlar bo‘yicha rasmiy ma’lumotlarni oling.",
      examples_title: "Namuna savollar:",
      placeholder: "Savolingizni kiriting... (Enter — yuborish, Shift+Enter — yangi qator)",
      send: "Yuborish",
      clear: "Tozalash",
      hint: "Enter — yuborish, Shift+Enter — yangi qator",
      evidence: "Audited Manba Dalillari (Evidence)",
      dataset_version: "Dataset versiyasi",
      tables: "Jadvallar",
      filters: "Filtrlar",
      source_count: "Bitimlar soni",
      copy: "Nusxalash",
      copied: "Nusxalandi!",
      loading: "Hisoblanmoqda...",
      no_evidence: "Bu so‘rov uchun ombor dalillari yo‘q.",
      error_generic: "So‘rovni bajarib bo‘lmadi. Qayta urinib ko‘ring.",
    },
    uz_cyrl: {
      title: "UZEX AI",
      badge: "Спот Аналитика",
      subtitle: "500 000 та биржа битими бўйича тасдиқланган маълумотлар",
      status_ready: "База фаол (500к битим)",
      status_loading: "Уланмоқда...",
      status_offline: "Хизмат тайёр эмас",
      disclaimer: "Жавоблар фақат тасдиқланган UZEX спот битимлари датасетига асосланади. Чат тарихи сақланмайди.",
      welcome_title: "UZEX AI биржа таҳлил тизимига хуш келибсиз",
      welcome_desc: "Савдо битимлари, шартномалар, сотувчи/харидор компаниялар ва товарлар бўйича расмий маълумотларни олинг.",
      examples_title: "Намуна саволлар:",
      placeholder: "Саволингизни киритинг... (Enter — юбориш, Shift+Enter — янги қатор)",
      send: "Юбориш",
      clear: "Тозалаш",
      hint: "Enter — юбориш, Shift+Enter — янги қатор",
      evidence: "Аудитланган Манба Далиллари (Evidence)",
      dataset_version: "Датасет версияси",
      tables: "Жадваллар",
      filters: "Фильтрлар",
      source_count: "Битимлар сони",
      copy: "Нусхалаш",
      copied: "Нусхаланди!",
      loading: "Ҳисобланмоқда...",
      no_evidence: "Бу сўров учун омбор далиллари йўқ.",
      error_generic: "Сўровни бажариб бўлмади. Қайта уриниб кўринг.",
    },
    ru: {
      title: "UZEX AI",
      badge: "Спот Аналитика",
      subtitle: "Проверенные данные по 500 000 биржевым сделкам",
      status_ready: "База активна (500k сделок)",
      status_loading: "Подключение...",
      status_offline: "Служба не готова",
      disclaimer: "Ответы основаны исключительно на проверенном датасете спотовых торгов UZEX. История чата не сохраняется.",
      welcome_title: "Добро пожаловать в аналитическую систему UZEX AI",
      welcome_desc: "Получайте официальные проверенные данные по биржевым сделкам, контрактам, участникам и товарам.",
      examples_title: "Примеры запросов:",
      placeholder: "Введите ваш запрос... (Enter — отправить, Shift+Enter — новая строка)",
      send: "Отправить",
      clear: "Очистить",
      hint: "Enter — отправить, Shift+Enter — новая строка",
      evidence: "Аудированные свидетельства (Evidence)",
      dataset_version: "Версия датасета",
      tables: "Таблицы",
      filters: "Фильтры",
      source_count: "Количество сделок",
      copy: "Копировать",
      copied: "Скопировано!",
      loading: "Вычисление...",
      no_evidence: "Для этого запроса свидетельства отсутствуют.",
      error_generic: "Не удалось выполнить запрос. Повторите попытку.",
    },
  };

  const EXAMPLES = [
    { text: "2025 yilda nechta bitim bor?", label: "🇺🇿 2025 bitimlar soni", lang: "uz_latn" },
    { text: "bitim 100001", label: "🇺🇿 Bitim 100001", lang: "uz_latn" },
    { text: "STIR 915688255", label: "🇺🇿 STIR 915688255", lang: "uz_latn" },
    { text: "Сколько сделок в 2025 году?", label: "🇷🇺 Сделки в 2025", lang: "ru" },
    { text: "сделка 100001", label: "🇷🇺 Сделка 100001", lang: "ru" },
    { text: "2025 yilda tonnada eng ko‘p sement olgan firma", label: "🇺🇿 Sement reytingi (Noaniq)", lang: "uz_latn" },
  ];

  // DOM Elements
  const feed = document.getElementById("messages-feed");
  const welcomeCard = document.getElementById("welcome-card");
  const inputEl = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const clearBtn = document.getElementById("clear-btn");
  const typingIndicator = document.getElementById("typing-indicator");
  const charCounter = document.getElementById("char-counter");
  const themeToggle = document.getElementById("theme-toggle");
  const statusBadge = document.getElementById("status-badge");
  const statusText = document.getElementById("status-text");

  // Multi-language UI texts
  function applyLanguage(newLang) {
    if (!UI_TEXT[newLang]) return;
    state.lang = newLang;
    const t = UI_TEXT[newLang];

    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (t[key]) el.textContent = t[key];
    });

    if (inputEl) inputEl.placeholder = t.placeholder;

    document.querySelectorAll(".lang-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-lang") === newLang);
    });
  }

  // Check Backend Status
  async function checkStatus() {
    try {
      const res = await fetch("/api/v1/status");
      if (res.ok) {
        const data = await res.json();
        if (data.status === "ready" && data.warehouse_ready) {
          statusBadge.classList.add("online");
          statusText.textContent = UI_TEXT[state.lang].status_ready;
          return;
        }
      }
      statusBadge.classList.remove("online");
      statusText.textContent = UI_TEXT[state.lang].status_offline;
    } catch {
      statusBadge.classList.remove("online");
      statusText.textContent = UI_TEXT[state.lang].status_offline;
    }
  }

  // Render Example Chips
  function renderExamples() {
    const container = document.getElementById("examples-grid");
    if (!container) return;
    container.innerHTML = "";
    EXAMPLES.forEach((ex) => {
      const chip = document.createElement("button");
      chip.className = "example-chip";
      chip.type = "button";
      chip.textContent = ex.label;
      chip.addEventListener("click", () => {
        inputEl.value = ex.text;
        updateCharCount();
        inputEl.focus();
        sendMessage(ex.text);
      });
      container.appendChild(chip);
    });
  }

  // Auto-resize textarea
  function autoResize() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
  }

  function updateCharCount() {
    const len = inputEl.value.length;
    charCounter.textContent = `${len} / 4096`;
    sendBtn.disabled = len === 0 || state.isBusy;
  }

  // Copy to clipboard helper
  function copyText(text, btn) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        const originalText = btn.textContent;
        btn.textContent = UI_TEXT[state.lang].copied;
        setTimeout(() => {
          btn.textContent = originalText;
        }, 1800);
      });
    }
  }

  // Detect key-value items in text (e.g. Bitim raqami: 100001; Bitim sanasi: ...)
  function parseStructuredItems(text) {
    const lines = text.split("\n");
    for (const line of lines) {
      if (line.includes("; ") && line.includes(": ")) {
        const parts = line.split("; ");
        const items = [];
        for (const part of parts) {
          const colonIdx = part.indexOf(": ");
          if (colonIdx > 0) {
            items.push({
              key: part.substring(0, colonIdx).trim(),
              val: part.substring(colonIdx + 2).trim(),
            });
          }
        }
        if (items.length >= 3) {
          return { items, rawLine: line };
        }
      }
    }
    return null;
  }

  // Append user message
  function appendUserMessage(text) {
    if (welcomeCard) welcomeCard.style.display = "none";

    const row = document.createElement("div");
    row.className = "message-row user";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;

    row.appendChild(bubble);
    feed.appendChild(row);
    scrollToBottom();
  }

  // Append assistant message
  function appendBotMessage(data) {
    if (welcomeCard) welcomeCard.style.display = "none";

    // Auto-align UI language with response if detected
    if (data.language === "ru") {
      applyLanguage("ru");
    } else if (data.language === "uz") {
      applyLanguage(data.script === "cyrillic" ? "uz_cyrl" : "uz_latn");
    }

    const row = document.createElement("div");
    row.className = "message-row bot";

    const card = document.createElement("div");
    card.className = "message-card";

    // Header meta
    const meta = document.createElement("div");
    meta.className = "message-meta";

    const badges = document.createElement("div");
    badges.className = "meta-badges";

    const statusPill = document.createElement("span");
    statusPill.className = `status-pill ${data.status}`;
    statusPill.textContent = data.status;
    badges.appendChild(statusPill);

    if (typeof data.latency_ms === "number" && data.latency_ms > 0) {
      const latPill = document.createElement("span");
      latPill.className = "latency-pill";
      latPill.textContent = `⚡ ${data.latency_ms.toFixed(1)} ms`;
      badges.appendChild(latPill);
    }

    meta.appendChild(badges);

    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.type = "button";
    copyBtn.textContent = UI_TEXT[state.lang].copy;
    copyBtn.addEventListener("click", () => copyText(data.answer, copyBtn));
    meta.appendChild(copyBtn);

    card.appendChild(meta);

    // Answer body
    const body = document.createElement("div");
    body.className = "answer-body";

    const structured = parseStructuredItems(data.answer);
    if (structured) {
      // Split text around structured key-value line
      const lines = data.answer.split("\n");
      for (const line of lines) {
        if (line === structured.rawLine) {
          const grid = document.createElement("div");
          grid.className = "analytical-grid";
          structured.items.forEach((item) => {
            const el = document.createElement("div");
            el.className = "analytical-item";
            const k = document.createElement("span");
            k.className = "analytical-label";
            k.textContent = item.key;
            const v = document.createElement("span");
            v.className = "analytical-value";
            v.textContent = item.val;
            el.appendChild(k);
            el.appendChild(v);
            grid.appendChild(el);
          });
          body.appendChild(grid);
        } else if (line.trim()) {
          const p = document.createElement("div");
          p.textContent = line;
          body.appendChild(p);
        }
      }
    } else {
      body.textContent = data.answer;
    }

    card.appendChild(body);

    // Evidence Drawer
    if (data.evidence) {
      const drawer = document.createElement("div");
      drawer.className = "evidence-drawer";

      const toggle = document.createElement("button");
      toggle.className = "evidence-toggle";
      toggle.type = "button";
      toggle.innerHTML = `
        <span>📊 ${UI_TEXT[state.lang].evidence}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      `;

      const content = document.createElement("div");
      content.className = "evidence-content";

      const addRow = (k, v) => {
        const r = document.createElement("div");
        r.className = "evidence-row";
        const keySpan = document.createElement("span");
        keySpan.className = "evidence-key";
        keySpan.textContent = k;
        const valSpan = document.createElement("span");
        valSpan.className = "evidence-val";
        valSpan.textContent = v;
        r.appendChild(keySpan);
        r.appendChild(valSpan);
        content.appendChild(r);
      };

      addRow(UI_TEXT[state.lang].source_count, Number(data.evidence.source_count).toLocaleString());
      addRow(UI_TEXT[state.lang].tables, data.evidence.tables.join(", "));
      if (data.evidence.filters && data.evidence.filters.length > 0) {
        const filterStr = data.evidence.filters
          .map((f) => `${f.field} ${f.op} ${JSON.stringify(f.values)}`)
          .join("; ");
        addRow(UI_TEXT[state.lang].filters, filterStr);
      }
      addRow(UI_TEXT[state.lang].dataset_version, data.evidence.dataset_version);

      toggle.addEventListener("click", () => {
        toggle.classList.toggle("open");
        content.classList.toggle("open");
      });

      drawer.appendChild(toggle);
      drawer.appendChild(content);
      card.appendChild(drawer);
    }

    row.appendChild(card);
    feed.appendChild(row);
    scrollToBottom();
  }

  function scrollToBottom() {
    feed.scrollTop = feed.scrollHeight;
  }

  // Send message pipeline
  async function sendMessage(text) {
    const query = text.trim();
    if (!query || state.isBusy) return;

    state.isBusy = true;
    updateCharCount();
    appendUserMessage(query);

    inputEl.value = "";
    autoResize();
    updateCharCount();

    // Show loading
    typingIndicator.style.display = "flex";
    scrollToBottom();

    try {
      const res = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: query }),
      });

      typingIndicator.style.display = "none";

      if (res.ok) {
        const data = await res.json();
        state.messages.push({ role: "assistant", ...data });
        appendBotMessage(data);
      } else {
        const errData = await res.json().catch(() => ({}));
        const errMsg = errData.error && errData.error.message ? errData.error.message : UI_TEXT[state.lang].error_generic;
        appendBotMessage({
          status: "ERROR",
          language: state.lang === "ru" ? "ru" : "uz",
          script: state.lang === "uz_cyrl" ? "cyrillic" : state.lang === "uz_latn" ? "latin" : "unknown",
          answer: errMsg,
          evidence: null,
          latency_ms: 0,
        });
      }
    } catch {
      typingIndicator.style.display = "none";
      appendBotMessage({
        status: "ERROR",
        language: state.lang === "ru" ? "ru" : "uz",
        script: state.lang === "uz_cyrl" ? "cyrillic" : "latin",
        answer: UI_TEXT[state.lang].error_generic,
        evidence: null,
        latency_ms: 0,
      });
    } finally {
      state.isBusy = false;
      updateCharCount();
      inputEl.focus();
    }
  }

  // Clear chat (memory only)
  function clearChat() {
    state.messages = [];
    feed.innerHTML = "";
    if (welcomeCard) {
      feed.appendChild(welcomeCard);
      welcomeCard.style.display = "block";
    }
    inputEl.value = "";
    autoResize();
    updateCharCount();
    inputEl.focus();
  }

  // Event Listeners
  inputEl.addEventListener("input", () => {
    autoResize();
    updateCharCount();
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputEl.value);
    }
  });

  sendBtn.addEventListener("click", () => {
    sendMessage(inputEl.value);
  });

  clearBtn.addEventListener("click", clearChat);

  // Language buttons
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyLanguage(btn.getAttribute("data-lang"));
    });
  });

  // Theme toggle
  themeToggle.addEventListener("click", () => {
    document.documentElement.classList.toggle("dark");
  });

  // Initialization
  renderExamples();
  applyLanguage("uz_latn");
  checkStatus();
  updateCharCount();
  inputEl.focus();
})();
