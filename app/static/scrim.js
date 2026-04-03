/* ===== Scrim Tracker JS ===== */
(function () {
  "use strict";

  const ROLES = ["top", "jungle", "mid", "bot", "support"];
  let champions = [];
  let champByName = {};
  let currentSubTab = "input";
  let editingMatchId = null; // When set, saveMatch uses PUT instead of POST

  // ---- Open Series Teams ----
  // Open Series BR - Fase de Grupos
  const OPEN_SERIES_TEAMS = [
    // Grupo A
    "RMD E-SPORTS","Minerva UFRJ","Team Golden Wind","NFG POROS",
    // Grupo B
    "All Next","Genei ryodan Gaming","Goatz CN","Prime",
    // Grupo C
    "Goatz Galaxy","Tudo Passa","MonkeyTeam","Valhalla Ragnarok",
    // Grupo D
    "Pegasus","Sarapathongos","Dragões da Laguna","THC Atomic",
    // Grupo E
    "Os Cansados","Custa Nada","NFG FÊNIX","NFG Boys",
    // Grupo F
    "THC Thunderlords","Duck Team","Invictus Team","Valhalla Team",
    // Grupo G
    "Fui sem TP","AREMESSANDO ALTO","FalconFury","Synergy",
    // Grupo H
    "Hiro FLQ Esports","NEXT Gaming","Inimigos do Walski","NFG LINDOS",
  ].sort((a, b) => a.localeCompare(b, "pt-BR"));

  // ---- Init ----
  async function initScrim() {
    await loadChampions();
    renderSubTabs();
    renderInputTab();
    loadMatchHistory();
  }

  // Display name aliases (internal API name -> display name)
  const CHAMP_ALIASES = {"monkeyking": "wukong"};

  async function loadChampions() {
    try {
      const res = await fetch("/api/champions");
      if (res.ok) {
        champions = await res.json();
        champByName = {};
        for (const c of champions) {
          champByName[c.name.toLowerCase()] = c;
          if (c.name_cn) champByName[c.name_cn.toLowerCase()] = c;
        }
        // Register aliases so DB names also resolve
        for (const [alias, canonical] of Object.entries(CHAMP_ALIASES)) {
          if (champByName[canonical] && !champByName[alias]) {
            champByName[alias] = champByName[canonical];
          }
        }
      }
    } catch (e) {
      console.warn("Could not load champions", e);
    }
  }

  function getChampAvatar(name) {
    if (!name) return "";
    const c = champByName[name.toLowerCase()];
    return c ? c.avatar_url || "" : "";
  }

  function champAvatarHtml(name, size) {
    size = size || 24;
    const url = getChampAvatar(name);
    if (url) {
      return `<img src="${url}" alt="${escHtml(name)}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;background:#e5e7eb;flex-shrink:0" onerror="this.style.display='none'">`;
    }
    const letter = name ? name[0].toUpperCase() : "?";
    return `<span style="width:${size}px;height:${size}px;border-radius:50%;background:#2d6cdf;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:${Math.round(size * 0.45)}px;flex-shrink:0">${letter}</span>`;
  }

  // ---- Custom champion picker (replaces datalist) ----
  function createChampPicker(inputId) {
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "position:relative;display:inline-block";

    const input = document.createElement("input");
    input.type = "text";
    input.id = inputId;
    input.placeholder = "Champion";
    input.autocomplete = "off";
    input.style.cssText = "width:140px;min-width:100px;padding:0.3rem 0.5rem 0.3rem 28px;border:1px solid #ccc;border-radius:4px;font-size:0.85rem";

    const avatarPreview = document.createElement("span");
    avatarPreview.style.cssText = "position:absolute;left:4px;top:50%;transform:translateY(-50%);pointer-events:none";
    avatarPreview.className = "champ-preview";

    const dropdown = document.createElement("div");
    dropdown.style.cssText = "position:absolute;top:100%;left:0;width:220px;max-height:200px;overflow-y:auto;background:#1e2633;border:1px solid #252d3a;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.4);z-index:100;display:none";

    function updatePreview() {
      const val = input.value.trim();
      if (val && champByName[val.toLowerCase()]) {
        avatarPreview.innerHTML = champAvatarHtml(val, 20);
      } else {
        avatarPreview.innerHTML = "";
        input.style.paddingLeft = "0.5rem";
        return;
      }
      input.style.paddingLeft = "28px";
    }

    function showDropdown(filter) {
      const q = (filter || "").toLowerCase();
      const matches = champions.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          (c.name_cn && c.name_cn.toLowerCase().includes(q))
      ).slice(0, 20);

      if (!matches.length) {
        dropdown.style.display = "none";
        return;
      }

      dropdown.innerHTML = matches
        .map(
          (c) =>
            `<div class="champ-option" data-name="${escHtml(c.name)}" style="display:flex;align-items:center;gap:8px;padding:6px 10px;cursor:pointer;font-size:0.85rem;color:#e2e8f0;border-bottom:1px solid #252d3a">
              ${c.avatar_url ? `<img src="${c.avatar_url}" style="width:24px;height:24px;border-radius:50%;object-fit:cover" onerror="this.style.display='none'">` : ""}
              <span>${escHtml(c.name)}</span>
            </div>`
        )
        .join("");
      dropdown.style.display = "block";

      dropdown.querySelectorAll(".champ-option").forEach((opt) => {
        opt.onmousedown = (e) => {
          e.preventDefault();
          input.value = opt.dataset.name;
          dropdown.style.display = "none";
          updatePreview();
        };
        opt.onmouseenter = () => (opt.style.background = "#1c2230");
        opt.onmouseleave = () => (opt.style.background = "");
      });
    }

    input.oninput = () => {
      showDropdown(input.value);
      updatePreview();
    };
    input.onfocus = () => {
      if (input.value) showDropdown(input.value);
      else showDropdown("");
    };
    input.onblur = () => {
      setTimeout(() => (dropdown.style.display = "none"), 150);
      updatePreview();
    };

    wrapper.appendChild(avatarPreview);
    wrapper.appendChild(input);
    wrapper.appendChild(dropdown);
    return wrapper;
  }

  // ---- Sub-tab navigation ----
  function renderSubTabs() {
    const container = document.getElementById("scrimSubTabs");
    if (!container) return;
    container.innerHTML = "";
    const tabs = [
      { id: "input", label: "Input" },
      { id: "stats", label: "Stats" },
      { id: "champions", label: "Champions" },
      { id: "matchups", label: "Matchups" },
      { id: "duos", label: "Duos" },
      { id: "pickorder", label: "Pick Order" },
    ];
    tabs.forEach((t) => {
      const btn = document.createElement("button");
      btn.className = "scrim-tab" + (t.id === currentSubTab ? " active" : "");
      btn.textContent = t.label;
      btn.onclick = () => switchSubTab(t.id);
      container.appendChild(btn);
    });
  }

  function switchSubTab(tabId) {
    currentSubTab = tabId;
    renderSubTabs();
    const content = document.getElementById("scrimContent");
    content.innerHTML = "";
    if (tabId === "input") renderInputTab();
    else if (tabId === "stats") renderStatsTab();
    else if (tabId === "champions") renderChampionsTab();
    else if (tabId === "matchups") renderMatchupsTab();
    else if (tabId === "duos") renderDuosTab();
    else if (tabId === "pickorder") renderPickOrderTab();
  }

  // ================================================================
  // INPUT TAB
  // ================================================================
  function renderInputTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = `
      <div class="scrim-form">
        <div id="scrimMessage"></div>

        <!-- Screenshot Upload -->
        <div class="upload-area" id="uploadArea">
          <p><strong>Upload screenshots</strong></p>
          <p>Arraste, clique ou cole (CTRL+V) screenshots pos-jogo</p>
          <div style="margin:0.5rem 0">
            <span style="font-weight:600;font-size:0.85rem;color:#555">Meu time na screenshot:</span>
            <div class="side-selector" style="margin-left:0.5rem;display:inline-flex">
              <input type="radio" name="ocrSide" id="ocrSideBlue" value="blue">
              <label for="ocrSideBlue">Blue (Esquerda)</label>
              <input type="radio" name="ocrSide" id="ocrSideRed" value="red">
              <label for="ocrSideRed">Red (Direita)</label>
            </div>
            <div id="ocrSideWarning" style="color:#ef4444;font-size:0.8rem;margin-top:0.25rem;display:none">Selecione o lado do seu time antes de enviar a screenshot!</div>
          </div>
          <input type="file" id="screenshotInput" multiple accept="image/*" style="display:none">
          <div id="ocrStatus"></div>
        </div>

        <!-- Match info -->
        <div class="form-row">
          <label>Patch <input type="text" id="fPatch" placeholder="5.1a"></label>
          <label>Data <input type="date" id="fDate"></label>
          <label>Adversario
            <div style="display:flex;gap:0.25rem;align-items:center">
              <select id="fOpponentSelect" style="min-width:160px">
                <option value="">-- Selecionar --</option>
                <option value="__other__">Outro (digitar)</option>
                ${OPEN_SERIES_TEAMS.filter(t => t !== "Fui sem TP").map(t => `<option value="${escHtml(t)}">${escHtml(t)}</option>`).join("")}
              </select>
              <input type="text" id="fOpponentOther" placeholder="Nome do time" style="display:none;width:140px">
            </div>
          </label>
          <label>Duracao <input type="text" id="fDuration" placeholder="16:00"></label>
        </div>

        <div class="form-row">
          <div>
            <span style="font-weight:600;font-size:0.85rem;margin-right:0.5rem">Lado:</span>
            <div class="side-selector">
              <input type="radio" name="side" id="sideBlue" value="blue" checked>
              <label for="sideBlue">Blue</label>
              <input type="radio" name="side" id="sideRed" value="red">
              <label for="sideRed">Red</label>
            </div>
          </div>
          <div>
            <span style="font-weight:600;font-size:0.85rem;margin-right:0.5rem">Resultado:</span>
            <div class="side-selector result-selector">
              <input type="radio" name="result" id="resultWin" value="win" checked>
              <label for="resultWin">Win</label>
              <input type="radio" name="result" id="resultLoss" value="loss">
              <label for="resultLoss">Loss</label>
            </div>
          </div>
        </div>

        <!-- Our players -->
        <div class="players-section" id="ourPlayersSection">
          <h3>Nosso Time</h3>
        </div>

        <!-- Their players -->
        <div class="players-section" id="theirPlayersSection">
          <h3>Time Adversario</h3>
        </div>

        <!-- Bans -->
        <div class="bans-section" id="bansSection">
          <h3>Bans</h3>
        </div>

        <!-- Notes -->
        <div class="form-row">
          <label style="width:100%">Notas
            <textarea id="fNotes" rows="2" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;font-size:0.9rem" placeholder="Observacoes sobre a partida..."></textarea>
          </label>
        </div>

        <div class="form-row" style="margin-top:0.5rem">
          <button class="btn btn-primary" id="btnSaveMatch">Salvar Partida</button>
          <button class="btn btn-danger" id="btnCancelEdit" style="display:none">Cancelar Edicao</button>
          <button class="btn btn-secondary" id="btnClearForm">Limpar</button>
        </div>
      </div>

      <div class="match-list" id="matchList">
        <h3>Historico de Partidas</h3>
        <div id="matchListBody"></div>
      </div>
    `;

    // Build player rows with custom champion pickers
    buildPlayerRows("ourPlayersSection", "our");
    buildPlayerRows("theirPlayersSection", "their");
    buildBanRows();

    // Set today's date
    document.getElementById("fDate").value = new Date()
      .toISOString()
      .slice(0, 10);

    // Opponent select toggle
    const oppSelect = document.getElementById("fOpponentSelect");
    const oppOther = document.getElementById("fOpponentOther");
    oppSelect.onchange = () => {
      oppOther.style.display = oppSelect.value === "__other__" ? "" : "none";
      if (oppSelect.value !== "__other__") oppOther.value = "";
    };

    // Event listeners
    document.getElementById("btnSaveMatch").onclick = saveMatch;
    document.getElementById("btnClearForm").onclick = clearForm;
    document.getElementById("btnCancelEdit").onclick = () => { clearForm(); showMessage("Edicao cancelada", "success"); };

    // Auto-fill patch with last used value
    const patchField = document.getElementById("fPatch");
    if (!patchField.value) {
      fetch("/api/scrims/filters").then(r => r.json()).then(f => {
        if (f.patches?.length && !patchField.value) {
          patchField.value = f.patches[0];
        }
      }).catch(() => {});
    }

    // Upload area
    const uploadArea = document.getElementById("uploadArea");
    const fileInput = document.getElementById("screenshotInput");
    uploadArea.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "LABEL") return;
      fileInput.click();
    });
    fileInput.onchange = handleScreenshots;
    uploadArea.ondragover = (e) => {
      e.preventDefault();
      uploadArea.classList.add("dragover");
    };
    uploadArea.ondragleave = () => uploadArea.classList.remove("dragover");
    uploadArea.ondrop = (e) => {
      e.preventDefault();
      uploadArea.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        handleScreenshotFiles(e.dataTransfer.files);
      }
    };

    // Clipboard paste (CTRL+V)
    document.addEventListener("paste", handlePaste);
  }

  function handlePaste(e) {
    if (!document.getElementById("uploadArea")) return; // only on input tab
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault();
      handleScreenshotFiles(files);
    }
  }

  function buildPlayerRows(sectionId, teamPrefix) {
    const section = document.getElementById(sectionId);
    for (const r of ROLES) {
      const row = document.createElement("div");
      row.className = "player-row";

      const roleLabel = document.createElement("span");
      roleLabel.className = "role-label";
      roleLabel.textContent = r;
      row.appendChild(roleLabel);

      const picker = createChampPicker(`${teamPrefix}_${r}_champ`);
      row.appendChild(picker);

      for (const [suffix, placeholder, title] of [
        ["k", "K", "Kills"],
        ["d", "D", "Deaths"],
        ["a", "A", "Assists"],
        ["gold", "Gold", "Gold Earned"],
        ["pick", "P#", "Pick Order"],
      ]) {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.id = `${teamPrefix}_${r}_${suffix}`;
        inp.min = "0";
        inp.placeholder = placeholder;
        inp.title = title;
        if (suffix === "k" || suffix === "d" || suffix === "a") inp.value = "0";
        if (suffix === "pick") { inp.min = "1"; inp.max = "5"; }
        if (suffix === "gold") inp.style.width = "70px";
        row.appendChild(inp);
      }

      // MVP/SVP checkboxes
      for (const [suffix, label, title] of [
        ["mvp", "MVP", "Most Valuable Player"],
        ["svp", "SVP", "Super Valuable Player (losing team)"],
      ]) {
        const lbl = document.createElement("label");
        lbl.style.cssText = "display:flex;align-items:center;gap:2px;font-size:0.75rem;cursor:pointer";
        lbl.title = title;
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = `${teamPrefix}_${r}_${suffix}`;
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(label));
        row.appendChild(lbl);
      }

      section.appendChild(row);
    }
  }

  function buildBanRows() {
    const section = document.getElementById("bansSection");
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "display:flex;gap:2rem;flex-wrap:wrap";

    for (const [teamLabel, prefix] of [["Nossos Bans", "our"], ["Bans Adversarios", "their"]]) {
      const col = document.createElement("div");
      const title = document.createElement("strong");
      title.style.fontSize = "0.85rem";
      title.textContent = teamLabel;
      col.appendChild(title);

      for (let i = 1; i <= 5; i++) {
        const row = document.createElement("div");
        row.className = "bans-row";
        const num = document.createElement("span");
        num.style.cssText = "font-size:0.75rem;width:20px";
        num.textContent = `${i}.`;
        row.appendChild(num);
        row.appendChild(createChampPicker(`${prefix}Ban${i}`));
        col.appendChild(row);
      }
      wrapper.appendChild(col);
    }
    section.appendChild(wrapper);
  }

  function computeKP(players) {
    // Auto-calculate KP% for each team
    const teamKills = { ours: 0, theirs: 0 };
    for (const p of players) {
      teamKills[p.team] = (teamKills[p.team] || 0) + p.kills;
    }
    for (const p of players) {
      const total = teamKills[p.team] || 0;
      p.kp_percent = total > 0 ? Math.round(((p.kills + p.assists) / total) * 1000) / 10 : 0;
    }
  }

  function collectFormData() {
    const side = document.querySelector('input[name="side"]:checked').value;
    const result = document.querySelector('input[name="result"]:checked').value;

    // Get opponent from select or other input
    const oppSelect = document.getElementById("fOpponentSelect");
    let opponent = "";
    if (oppSelect.value === "__other__") {
      opponent = document.getElementById("fOpponentOther").value.trim();
    } else {
      opponent = oppSelect.value;
    }

    const players = [];
    for (const team of ["our", "their"]) {
      const teamVal = team === "our" ? "ours" : "theirs";
      for (const role of ROLES) {
        const champ = document.getElementById(`${team}_${role}_champ`).value.trim();
        if (!champ) continue;
        const p = {
          role,
          team: teamVal,
          champion: champ,
          kills: parseInt(document.getElementById(`${team}_${role}_k`).value) || 0,
          deaths: parseInt(document.getElementById(`${team}_${role}_d`).value) || 0,
          assists: parseInt(document.getElementById(`${team}_${role}_a`).value) || 0,
          is_mvp: document.getElementById(`${team}_${role}_mvp`).checked,
          is_svp: document.getElementById(`${team}_${role}_svp`).checked,
        };
        const gold = document.getElementById(`${team}_${role}_gold`).value;
        if (gold) p.gold_earned = parseFloat(gold);
        const pick = document.getElementById(`${team}_${role}_pick`).value;
        if (pick) p.pick_order = parseInt(pick);
        players.push(p);
      }
    }

    // Auto-calculate KP%
    computeKP(players);

    const bans = [];
    for (const team of ["our", "their"]) {
      const teamVal = team === "our" ? "ours" : "theirs";
      for (let i = 1; i <= 5; i++) {
        const champ = document.getElementById(`${team}Ban${i}`).value.trim();
        if (champ) {
          bans.push({ champion: champ, team: teamVal, ban_order: i });
        }
      }
    }

    return {
      patch: document.getElementById("fPatch").value.trim(),
      date: document.getElementById("fDate").value,
      opponent,
      side,
      result,
      duration: document.getElementById("fDuration").value.trim() || null,
      notes: document.getElementById("fNotes").value.trim() || null,
      players,
      bans,
    };
  }

  async function saveMatch() {
    const data = collectFormData();
    if (!data.patch || !data.date || !data.opponent) {
      showMessage("Preencha patch, data e adversario", "error");
      return;
    }

    try {
      const url = editingMatchId
        ? `/api/scrims/matches/${editingMatchId}`
        : "/api/scrims/matches";
      const method = editingMatchId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        showMessage("Erro: " + (err.detail || res.statusText), "error");
        return;
      }
      showMessage(editingMatchId ? "Partida atualizada!" : "Partida salva com sucesso!", "success");
      editingMatchId = null;
      updateSaveButton();
      clearForm();
      loadMatchHistory();
    } catch (e) {
      showMessage("Erro ao salvar: " + e.message, "error");
    }
  }

  function updateSaveButton() {
    const btn = document.getElementById("btnSaveMatch");
    const cancelBtn = document.getElementById("btnCancelEdit");
    if (!btn) return;
    btn.textContent = editingMatchId ? "Atualizar Partida" : "Salvar Partida";
    if (cancelBtn) cancelBtn.style.display = editingMatchId ? "" : "none";
  }

  function clearForm() {
    editingMatchId = null;
    updateSaveButton();
    // Keep patch value — it rarely changes between scrims
    document.getElementById("fDate").value = new Date().toISOString().slice(0, 10);
    document.getElementById("fOpponentSelect").value = "";
    document.getElementById("fOpponentOther").value = "";
    document.getElementById("fOpponentOther").style.display = "none";
    document.getElementById("fDuration").value = "";
    document.getElementById("fNotes").value = "";
    document.getElementById("sideBlue").checked = true;
    document.getElementById("resultWin").checked = true;

    for (const team of ["our", "their"]) {
      for (const role of ROLES) {
        document.getElementById(`${team}_${role}_champ`).value = "";
        document.getElementById(`${team}_${role}_k`).value = "0";
        document.getElementById(`${team}_${role}_d`).value = "0";
        document.getElementById(`${team}_${role}_a`).value = "0";
        document.getElementById(`${team}_${role}_gold`).value = "";
        document.getElementById(`${team}_${role}_pick`).value = "";
        document.getElementById(`${team}_${role}_mvp`).checked = false;
        document.getElementById(`${team}_${role}_svp`).checked = false;
        const preview = document.getElementById(`${team}_${role}_champ`)?.closest("div")?.querySelector(".champ-preview");
        if (preview) preview.innerHTML = "";
      }
      for (let i = 1; i <= 5; i++) {
        document.getElementById(`${team}Ban${i}`).value = "";
      }
    }
  }

  async function loadMatchHistory() {
    const body = document.getElementById("matchListBody");
    if (!body) return;

    try {
      const res = await fetch("/api/scrims/matches");
      if (!res.ok) return;
      const matches = await res.json();

      if (!matches.length) {
        body.innerHTML = '<p style="color:#999;font-size:0.85rem">Nenhuma partida registrada ainda.</p>';
        return;
      }

      body.innerHTML = matches
        .map(
          (m) => `
        <div class="match-card ${m.result}">
          <div class="match-info">
            <span class="result-badge ${m.result}">${m.result === "win" ? "W" : "L"}</span>
            <span><strong>vs ${escHtml(m.opponent)}</strong></span>
            <span>${m.date}</span>
            <span>Patch ${escHtml(m.patch)}</span>
            <span style="text-transform:capitalize">${m.side}</span>
            ${m.duration ? `<span>${escHtml(m.duration)}</span>` : ""}
            <span style="display:flex;gap:4px;align-items:center">
              ${(m.players || [])
                .filter((p) => p.team === "ours")
                .map((p) => {
                  const badge = p.is_mvp
                    ? `<span style="position:absolute;bottom:-2px;right:-2px;background:#f59e0b;color:#000;font-size:9px;font-weight:700;border-radius:3px;padding:0 2px;line-height:1.4">MVP</span>`
                    : p.is_svp
                    ? `<span style="position:absolute;bottom:-2px;right:-2px;background:#a78bfa;color:#000;font-size:9px;font-weight:700;border-radius:3px;padding:0 2px;line-height:1.4">SVP</span>`
                    : "";
                  return `<span style="position:relative;display:inline-block">${champAvatarHtml(p.champion, 22)}${badge}</span>`;
                })
                .join("")}
            </span>
          </div>
          <div class="match-actions">
            <button class="btn btn-secondary" onclick="window._scrimEditMatch(${m.id})">Editar</button>
            <button class="btn btn-danger" onclick="window._scrimDeleteMatch(${m.id})">Excluir</button>
          </div>
        </div>`
        )
        .join("");
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro ao carregar partidas</p>';
    }
  }

  window._scrimDeleteMatch = async function (id) {
    if (!confirm("Excluir esta partida?")) return;
    try {
      await fetch(`/api/scrims/matches/${id}`, { method: "DELETE" });
      if (editingMatchId === id) {
        editingMatchId = null;
        updateSaveButton();
      }
      loadMatchHistory();
    } catch (e) {
      alert("Erro ao excluir");
    }
  };

  window._scrimEditMatch = async function (id) {
    try {
      const res = await fetch(`/api/scrims/matches/${id}`);
      if (!res.ok) { alert("Erro ao carregar partida"); return; }
      const m = await res.json();

      // Switch to Input tab
      switchSubTab("input");

      // Fill form fields
      document.getElementById("fPatch").value = m.patch || "";
      document.getElementById("fDate").value = m.date || "";
      document.getElementById("fDuration").value = m.duration || "";
      document.getElementById("fNotes").value = m.notes || "";

      // Opponent
      const oppSelect = document.getElementById("fOpponentSelect");
      const oppOther = document.getElementById("fOpponentOther");
      const optValues = Array.from(oppSelect.options).map(o => o.value);
      if (optValues.includes(m.opponent)) {
        oppSelect.value = m.opponent;
        oppOther.style.display = "none";
      } else {
        oppSelect.value = "__other__";
        oppOther.value = m.opponent;
        oppOther.style.display = "";
      }

      // Side and result
      document.getElementById(m.side === "blue" ? "sideBlue" : "sideRed").checked = true;
      document.getElementById(m.result === "win" ? "resultWin" : "resultLoss").checked = true;

      // Clear all player fields first
      for (const team of ["our", "their"]) {
        for (const role of ROLES) {
          document.getElementById(`${team}_${role}_champ`).value = "";
          document.getElementById(`${team}_${role}_k`).value = "0";
          document.getElementById(`${team}_${role}_d`).value = "0";
          document.getElementById(`${team}_${role}_a`).value = "0";
          document.getElementById(`${team}_${role}_gold`).value = "";
          document.getElementById(`${team}_${role}_pick`).value = "";
          document.getElementById(`${team}_${role}_mvp`).checked = false;
          document.getElementById(`${team}_${role}_svp`).checked = false;
        }
        for (let i = 1; i <= 5; i++) {
          document.getElementById(`${team}Ban${i}`).value = "";
        }
      }

      // Fill players
      for (const p of (m.players || [])) {
        const team = p.team === "ours" ? "our" : "their";
        const champEl = document.getElementById(`${team}_${p.role}_champ`);
        if (!champEl) continue;
        champEl.value = p.champion || "";
        champEl.dispatchEvent(new Event("blur"));
        document.getElementById(`${team}_${p.role}_k`).value = p.kills || 0;
        document.getElementById(`${team}_${p.role}_d`).value = p.deaths || 0;
        document.getElementById(`${team}_${p.role}_a`).value = p.assists || 0;
        if (p.gold_earned != null) document.getElementById(`${team}_${p.role}_gold`).value = p.gold_earned;
        if (p.pick_order != null) document.getElementById(`${team}_${p.role}_pick`).value = p.pick_order;
        document.getElementById(`${team}_${p.role}_mvp`).checked = !!p.is_mvp;
        document.getElementById(`${team}_${p.role}_svp`).checked = !!p.is_svp;
      }

      // Fill bans
      for (const b of (m.bans || [])) {
        const team = b.team === "ours" ? "our" : "their";
        const el = document.getElementById(`${team}Ban${b.ban_order}`);
        if (el) el.value = b.champion || "";
      }

      // Set editing mode
      editingMatchId = id;
      updateSaveButton();
      showMessage(`Editando partida #${id} — altere os campos e clique em Atualizar`, "success");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      alert("Erro ao carregar partida: " + e.message);
    }
  };

  // ---- Screenshot OCR ----
  function handleScreenshots(e) {
    handleScreenshotFiles(e.target.files);
  }

  async function handleScreenshotFiles(files) {
    if (!files.length) return;

    const ocrSide = document.querySelector('input[name="ocrSide"]:checked');
    if (!ocrSide) {
      const warn = document.getElementById("ocrSideWarning");
      if (warn) warn.style.display = "block";
      showMessage("Selecione Blue ou Red antes de enviar a screenshot!", "error");
      return;
    }
    const warnEl = document.getElementById("ocrSideWarning");
    if (warnEl) warnEl.style.display = "none";

    const status = document.getElementById("ocrStatus");
    status.innerHTML = '<span class="spinner"></span> Processando screenshots...';

    const formData = new FormData();
    for (const f of files) {
      formData.append("files", f);
    }
    formData.append("our_side", ocrSide.value);

    try {
      const res = await fetch("/api/scrims/ocr", {
        method: "POST",
        body: formData,
      });

      if (res.status === 501) {
        status.innerHTML =
          '<span style="color:#c00">OCR nao disponivel. Configure OPENAI_API_KEY.</span>';
        return;
      }

      if (!res.ok) {
        const err = await res.json();
        status.innerHTML = `<span style="color:#c00">OCR falhou: ${escHtml(err.detail || "erro")}</span>`;
        return;
      }

      const data = await res.json();
      status.innerHTML = '<span style="color:#166534">Dados extraidos! Revise e salve.</span>';
      fillFormFromOCR(data);
    } catch (e) {
      status.innerHTML = `<span style="color:#c00">Erro: ${escHtml(e.message)}</span>`;
    }
  }

  function fillFormFromOCR(data) {
    if (data.side) {
      document.getElementById(data.side === "blue" ? "sideBlue" : "sideRed").checked = true;
    }
    if (data.result) {
      document.getElementById(data.result === "win" ? "resultWin" : "resultLoss").checked = true;
    }
    if (data.duration) {
      document.getElementById("fDuration").value = data.duration;
    }

    if (data.players) {
      for (const p of data.players) {
        const team = p.team === "ours" ? "our" : "their";
        const role = p.role;
        const champEl = document.getElementById(`${team}_${role}_champ`);
        if (champEl) {
          // Clear placeholder names the AI writes when it can't identify
          const name = p.champion || "";
          const isPlaceholder = /^champion\s*(name)?$/i.test(name.trim()) || /^unknown$/i.test(name.trim());
          champEl.value = isPlaceholder ? "" : name;
          champEl.dispatchEvent(new Event("blur"));
          document.getElementById(`${team}_${role}_k`).value = p.kills || 0;
          document.getElementById(`${team}_${role}_d`).value = p.deaths || 0;
          document.getElementById(`${team}_${role}_a`).value = p.assists || 0;
          if (p.gold_earned != null) {
            document.getElementById(`${team}_${role}_gold`).value = p.gold_earned;
          }
          if (p.is_mvp) {
            document.getElementById(`${team}_${role}_mvp`).checked = true;
          }
          if (p.is_svp) {
            document.getElementById(`${team}_${role}_svp`).checked = true;
          }
        }
      }
    }

    // Auto-suggest opponent from player name matching
    if (data.suggested_opponent) {
      const oppSelect = document.getElementById("fOpponentSelect");
      const oppOther = document.getElementById("fOpponentOther");
      const optValues = Array.from(oppSelect.options).map((o) => o.value);
      if (optValues.includes(data.suggested_opponent)) {
        oppSelect.value = data.suggested_opponent;
        oppOther.style.display = "none";
      } else {
        oppSelect.value = "__other__";
        oppOther.value = data.suggested_opponent;
        oppOther.style.display = "";
      }
    }
  }

  // ================================================================
  // Shared filter builder
  // ================================================================
  function buildFilterParams(prefix) {
    const params = new URLSearchParams();
    const opp = document.getElementById(`${prefix}Opponent`).value;
    const df = document.getElementById(`${prefix}DateFrom`).value;
    const dt = document.getElementById(`${prefix}DateTo`).value;
    const patch = document.getElementById(`${prefix}Patch`).value;
    if (opp) params.set("opponent", opp);
    if (df) params.set("date_from", df);
    if (dt) params.set("date_to", dt);
    if (patch) params.set("patch", patch);
    return params;
  }

  function filtersBarHtml(prefix) {
    return `
      <div class="filters-bar" id="${prefix}Filters">
        <label>Adversario <select id="${prefix}Opponent"><option value="">Todos</option></select></label>
        <label>De <input type="date" id="${prefix}DateFrom"></label>
        <label>Ate <input type="date" id="${prefix}DateTo"></label>
        <label>Patch <select id="${prefix}Patch"><option value="">Todos</option></select></label>
        <button class="btn btn-primary" id="${prefix}Btn">Filtrar</button>
      </div>
    `;
  }

  async function populateFilters(prefix) {
    try {
      const res = await fetch("/api/scrims/filters");
      if (!res.ok) return;
      const f = await res.json();
      const oppSel = document.getElementById(`${prefix}Opponent`);
      f.opponents.forEach((o) => {
        const opt = document.createElement("option");
        opt.value = o;
        opt.textContent = o;
        oppSel.appendChild(opt);
      });
      const patchSel = document.getElementById(`${prefix}Patch`);
      f.patches.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        patchSel.appendChild(opt);
      });
    } catch (e) {}
  }

  // ================================================================
  // STATS TAB
  // ================================================================
  async function renderStatsTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = filtersBarHtml("sf") + '<div id="statsBody"><p style="color:#999">Carregando...</p></div>';
    await populateFilters("sf");
    document.getElementById("sfBtn").onclick = loadStats;
    loadStats();
  }

  async function loadStats() {
    const params = buildFilterParams("sf");
    const body = document.getElementById("statsBody");
    try {
      const [statsRes, roleAvgRes, allChampsRes, generalRes, mvpSvpRes, enemyChampsRes] = await Promise.all([
        fetch("/api/scrims/stats?" + params.toString()),
        fetch("/api/scrims/role-averages?" + params.toString()),
        fetch("/api/scrims/all-champions-by-role?" + params.toString()),
        fetch("/api/scrims/all-champions-general?" + params.toString()),
        fetch("/api/scrims/mvp-svp?" + params.toString()),
        fetch("/api/scrims/enemy-champions-by-role?" + params.toString()),
      ]);
      if (!statsRes.ok) { body.innerHTML = '<p style="color:#c00">Erro ao carregar stats</p>'; return; }
      const data = await statsRes.json();
      const roleAvg = roleAvgRes.ok ? await roleAvgRes.json() : [];
      const allChamps = allChampsRes.ok ? await allChampsRes.json() : {};
      const generalChamps = generalRes.ok ? await generalRes.json() : [];
      const mvpSvp = mvpSvpRes.ok ? await mvpSvpRes.json() : {};
      const enemyChamps = enemyChampsRes.ok ? await enemyChampsRes.json() : {};
      renderStatsBody(data, body, roleAvg, allChamps, generalChamps, mvpSvp, enemyChamps);
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro: ' + escHtml(e.message) + "</p>";
    }
  }

  // ---- Tier Score Formula ----
  function computeTierScore(champ, maxGames) {
    const wr = (champ.winrate || 0) / 100;
    const kda = Math.min((champ.kda || 0) / 8, 1);
    const gpm = Math.min((champ.avg_gpm || 0) / 600, 1);
    const sample = maxGames > 0 ? Math.min(champ.games / maxGames, 1) : 0;
    const raw = wr * 0.45 + kda * 0.25 + gpm * 0.15 + sample * 0.15;
    const penalty = Math.min(champ.games / 3, 1);
    return raw * penalty;
  }

  function getTierLabel(score) {
    if (score >= 0.75) return "S";
    if (score >= 0.55) return "A";
    if (score >= 0.40) return "B";
    if (score >= 0.25) return "C";
    return "D";
  }

  function renderTierList(roles, title) {
    title = title || "Tier List por Rota";
    let html = `<div class="tier-lists"><h2 style="margin-bottom:0.75rem">${escHtml(title)}</h2>`;
    for (const role of ROLES) {
      const roleData = roles[role] || [];
      if (!roleData.length) continue;
      const maxGames = Math.max(...roleData.map((c) => c.games));
      const scored = roleData.map((c) => ({
        ...c,
        tierScore: computeTierScore(c, maxGames),
      }));
      scored.sort((a, b) => b.tierScore - a.tierScore);

      const tiers = { S: [], A: [], B: [], C: [], D: [] };
      for (const c of scored) {
        tiers[getTierLabel(c.tierScore)].push(c);
      }

      html += `<div class="tier-role"><h3 style="text-transform:capitalize;margin-bottom:0.4rem">${role}</h3>`;
      for (const [label, champs] of Object.entries(tiers)) {
        if (!champs.length) continue;
        html += `<div class="tier-row tier-${label.toLowerCase()}">
          <span class="tier-label">${label}</span>
          <div class="tier-champs">
            ${champs.map((c) => `<span class="tier-champ" title="${escHtml(c.champion)} — ${c.games}g | ${c.winrate}% WR | ${c.kda} KDA${c.avg_gpm ? " | " + c.avg_gpm + " GPM" : ""} (score: ${(c.tierScore * 100).toFixed(0)})">${champAvatarHtml(c.champion, 30)}</span>`).join("")}
          </div>
        </div>`;
      }
      html += "</div>";
    }
    html += "</div>";
    return html;
  }

  function renderGeneralTierList(champList, title) {
    title = title || "Tier List Geral";
    if (!champList.length) return "";
    const maxGames = Math.max(...champList.map((c) => c.games));
    const scored = champList.map((c) => ({
      ...c,
      tierScore: computeTierScore(c, maxGames),
    }));
    scored.sort((a, b) => b.tierScore - a.tierScore);

    const tiers = { S: [], A: [], B: [], C: [], D: [] };
    for (const c of scored) {
      tiers[getTierLabel(c.tierScore)].push(c);
    }

    let html = `<div class="tier-lists"><h2 style="margin-bottom:0.75rem">${escHtml(title)}</h2>`;
    for (const [label, champs] of Object.entries(tiers)) {
      if (!champs.length) continue;
      html += `<div class="tier-row tier-${label.toLowerCase()}">
        <span class="tier-label">${label}</span>
        <div class="tier-champs">
          ${champs.map((c) => `<span class="tier-champ" title="${escHtml(c.champion)} — ${c.games}g | ${c.winrate}% WR | ${c.kda} KDA${c.avg_gpm ? " | " + c.avg_gpm + " GPM" : ""} (score: ${(c.tierScore * 100).toFixed(0)})">${champAvatarHtml(c.champion, 30)}</span>`).join("")}
        </div>
      </div>`;
    }
    html += "</div>";
    return html;
  }

  const ROLE_LABELS = { top: "Top", jungle: "Jungle", mid: "Mid", bot: "Bot", support: "Support" };

  function renderStatsBody(data, container, roleAvg, allChamps, generalChamps, mvpSvp, enemyChamps) {
    const ov = data.overall || {};
    const roles = data.roles || {};
    const sideStats = data.side_stats || {};
    roleAvg = roleAvg || [];
    allChamps = allChamps || {};
    generalChamps = generalChamps || [];
    mvpSvp = mvpSvp || {};
    enemyChamps = enemyChamps || {};

    const blue = sideStats.blue || null;
    const red = sideStats.red || null;
    const blueWrHtml = blue
      ? `<div class="number" style="color:#3b82f6">${blue.winrate}%</div><div class="label">Blue WR <small>(${blue.games}g)</small></div>`
      : `<div class="number" style="color:#3b82f6">—</div><div class="label">Blue WR</div>`;
    const redWrHtml = red
      ? `<div class="number" style="color:#ef4444">${red.winrate}%</div><div class="label">Red WR <small>(${red.games}g)</small></div>`
      : `<div class="number" style="color:#ef4444">—</div><div class="label">Red WR</div>`;

    let html = `
      <div class="overall-banner">
        <div class="overall-stat">
          <div class="number">${ov.total_games || 0}</div>
          <div class="label">Partidas</div>
        </div>
        <div class="overall-stat">
          <div class="number">${ov.total_wins || 0}</div>
          <div class="label">Vitorias</div>
        </div>
        <div class="overall-stat">
          <div class="number">${ov.winrate || 0}%</div>
          <div class="label">Winrate</div>
        </div>
        <div class="overall-stat">${blueWrHtml}</div>
        <div class="overall-stat">${redWrHtml}</div>
      </div>
    `;

    // Role averages cards
    if (roleAvg.length) {
      html += '<h2 style="margin:1rem 0 0.5rem">Desempenho por Rota</h2>';
      html += '<div class="stats-grid">';
      for (const role of ROLES) {
        const ra = roleAvg.find((r) => r.role === role);
        if (!ra) continue;
        html += `
          <div class="stat-card">
            <h3>${ROLE_LABELS[role] || role}</h3>
            <div class="stat-row"><span>Partidas</span><span class="value">${ra.games}</span></div>
            <div class="stat-row"><span>KDA Medio</span><span class="value">${ra.kda}</span></div>
            <div class="stat-row"><span>KP% Medio</span><span class="value">${ra.avg_kp != null ? ra.avg_kp + "%" : "—"}</span></div>
            <div class="stat-row"><span>GPM Medio</span><span class="value">${ra.avg_gpm || "—"}</span></div>
            <div class="stat-row"><span>K / D / A</span><span class="value">${ra.avg_kills} / ${ra.avg_deaths} / ${ra.avg_assists}</span></div>
          </div>
        `;
      }
      html += "</div>";
    }

    // MVP / SVP leaderboard
    const mvpChamps = (mvpSvp.by_champion || []).filter(c => c.mvp_count > 0 || c.svp_count > 0);
    if (mvpChamps.length) {
      html += '<h2 style="margin:1.25rem 0 0.5rem">🏅 Leaderboard MVP / SVP</h2>';
      html += '<div class="stats-grid">';
      // Top MVPs
      const topMvps = [...mvpChamps].sort((a, b) => b.mvp_count - a.mvp_count).slice(0, 5);
      html += '<div class="stat-card"><h3>Top MVP</h3>';
      for (const c of topMvps) {
        if (!c.mvp_count) continue;
        html += `<div class="stat-row" style="display:flex;align-items:center;gap:6px">
          ${champAvatarHtml(c.champion, 22)}
          <span style="flex:1">${escHtml(c.champion)} <small style="text-transform:capitalize">(${c.role})</small></span>
          <span class="value" style="color:#f59e0b;font-weight:700">${c.mvp_count}×MVP</span>
        </div>`;
      }
      html += '</div>';
      // Top SVPs
      const topSvps = [...mvpChamps].sort((a, b) => b.svp_count - a.svp_count).slice(0, 5);
      html += '<div class="stat-card"><h3>Top SVP</h3>';
      for (const c of topSvps) {
        if (!c.svp_count) continue;
        html += `<div class="stat-row" style="display:flex;align-items:center;gap:6px">
          ${champAvatarHtml(c.champion, 22)}
          <span style="flex:1">${escHtml(c.champion)} <small style="text-transform:capitalize">(${c.role})</small></span>
          <span class="value" style="color:#a78bfa;font-weight:700">${c.svp_count}×SVP</span>
        </div>`;
      }
      html += '</div>';
      // Awards by role
      const byRole = mvpSvp.by_role || [];
      if (byRole.length) {
        html += '<div class="stat-card"><h3>Awards por Rota</h3>';
        for (const r of byRole) {
          html += `<div class="stat-row">
            <span style="text-transform:capitalize">${r.role}</span>
            <span class="value">
              <span style="color:#f59e0b">${r.mvp_count} MVP</span>
              &nbsp;/&nbsp;
              <span style="color:#a78bfa">${r.svp_count} SVP</span>
            </span>
          </div>`;
        }
        html += '</div>';
      }
      html += '</div>';
    }

    // General tier list (all champions, all roles)
    if (generalChamps.length) {
      html += renderGeneralTierList(generalChamps, "Tier List Geral");
    }

    // Tier list by role (our team)
    html += renderTierList(roles, "Tier List por Rota (Nosso Time)");

    // Tier list by role (all champions)
    if (Object.keys(allChamps).length) {
      html += renderTierList(allChamps, "Tier List por Rota (Todos)");
    }

    // Enemy team tier list by role
    if (Object.keys(enemyChamps).length) {
      html += renderTierList(enemyChamps, "Tier List por Rota (Time Inimigo)");
    }

    html += '<div class="stats-grid">';
    for (const role of ROLES) {
      const roleData = roles[role] || [];
      html += `
        <div class="stat-card">
          <h3 style="text-transform:capitalize">${role}</h3>
          ${
            roleData.length
              ? roleData
                  .slice(0, 5)
                  .map(
                    (c) => `
                  <div class="stat-row" style="display:flex;align-items:center;gap:6px">
                    ${champAvatarHtml(c.champion, 22)}
                    <span style="flex:1">${escHtml(c.champion)} <small>(${c.games}g)</small></span>
                    <span class="value">${c.winrate}% WR | ${c.kda} KDA${c.avg_gpm ? ` | ${c.avg_gpm} GPM` : ""}</span>
                  </div>`
                  )
                  .join("")
              : '<p style="color:#999;font-size:0.8rem">Sem dados</p>'
          }
        </div>
      `;
    }
    html += "</div>";
    container.innerHTML = html;
  }

  // ================================================================
  // CHAMPIONS TAB
  // ================================================================
  async function renderChampionsTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = filtersBarHtml("cf") + '<div id="champsBody"><p style="color:#999">Carregando...</p></div>';
    await populateFilters("cf");
    document.getElementById("cfBtn").onclick = loadChampionStats;
    loadChampionStats();
  }

  async function loadChampionStats() {
    const params = buildFilterParams("cf");
    const body = document.getElementById("champsBody");
    try {
      const res = await fetch("/api/scrims/champion-stats?" + params.toString());
      if (!res.ok) { body.innerHTML = '<p style="color:#c00">Erro ao carregar champion stats</p>'; return; }
      const data = await res.json();
      renderChampionTable(data, body);
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro: ' + escHtml(e.message) + "</p>";
    }
  }

  let champSortKey = "total_games";
  let champSortDir = "desc";
  let champLastData = [];
  let champLastContainer = null;

  function renderChampionTable(data, container) {
    champLastData = data;
    champLastContainer = container;

    if (!data.length) {
      container.innerHTML = '<p style="color:#999">Nenhum dado de campeao ainda.</p>';
      return;
    }

    const cols = [
      { key: null, label: "Champion" },
      { key: "total_games", label: "Games" },
      { key: "presence", label: "Presence%" },
      { key: "winrate", label: "WR%" },
      { key: "avg_gpm", label: "Avg GPM" },
      { key: "our_picks", label: "Our Picks" },
      { key: "their_picks", label: "Their Picks" },
      { key: "our_bans", label: "Our Bans" },
      { key: "their_bans", label: "Their Bans" },
    ];

    const sorted = [...data].sort((a, b) => {
      const va = a[champSortKey] ?? -Infinity;
      const vb = b[champSortKey] ?? -Infinity;
      return champSortDir === "desc" ? vb - va : va - vb;
    });

    let html = `<table class="champ-table"><thead><tr>`;
    for (const col of cols) {
      const arrow = col.key === champSortKey ? (champSortDir === "desc" ? " ▼" : " ▲") : "";
      const activeClass = col.key === champSortKey ? "sort-active" : "";
      const sortAttr = col.key ? `data-sort="${col.key}"` : "";
      html += `<th class="${activeClass}" ${sortAttr}>${col.label}${arrow}</th>`;
    }
    html += `</tr></thead><tbody>`;

    for (const c of sorted) {
      html += `
        <tr>
          <td><div style="display:flex;align-items:center;gap:6px">${champAvatarHtml(c.champion, 24)}<strong>${escHtml(c.champion)}</strong></div></td>
          <td>${c.total_games}</td>
          <td>${c.presence}%</td>
          <td>${c.winrate}%</td>
          <td>${c.avg_gpm || "-"}</td>
          <td>${c.our_picks}</td>
          <td>${c.their_picks}</td>
          <td>${c.our_bans}</td>
          <td>${c.their_bans}</td>
        </tr>`;
    }

    html += "</tbody></table>";
    container.innerHTML = html;

    // Attach sort handlers
    container.querySelectorAll("th[data-sort]").forEach((th) => {
      th.onclick = () => {
        const key = th.dataset.sort;
        if (champSortKey === key) {
          champSortDir = champSortDir === "desc" ? "asc" : "desc";
        } else {
          champSortKey = key;
          champSortDir = "desc";
        }
        renderChampionTable(champLastData, champLastContainer);
      };
    });
  }

  // ================================================================
  // GENERIC SORTABLE TABLE HELPERS
  // ================================================================
  function genericSort(data, key, dir) {
    return [...data].sort((a, b) => {
      const va = a[key] ?? "";
      const vb = b[key] ?? "";
      if (typeof va === "string" && typeof vb === "string") {
        return dir === "desc" ? vb.localeCompare(va) : va.localeCompare(vb);
      }
      return dir === "desc" ? (vb || 0) - (va || 0) : (va || 0) - (vb || 0);
    });
  }

  function sortTh(label, key, activeKey, dir) {
    const arrow = key === activeKey ? (dir === "desc" ? " ▼" : " ▲") : "";
    const cls = key === activeKey ? "sort-active" : "";
    return `<th class="${cls}" data-sort="${key}">${label}${arrow}</th>`;
  }

  function attachSortHandlers(container, state, renderFn) {
    container.querySelectorAll("th[data-sort]").forEach((th) => {
      th.onclick = () => {
        const key = th.dataset.sort;
        if (state.key === key) {
          state.dir = state.dir === "desc" ? "asc" : "desc";
        } else {
          state.key = key;
          state.dir = "desc";
        }
        renderFn();
      };
    });
  }

  // ================================================================
  // MATCHUPS TAB
  // ================================================================
  const matchupSort = { key: "games", dir: "desc" };
  let matchupData = [];

  async function renderMatchupsTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = filtersBarHtml("mf") + '<div id="matchupsBody"><p style="color:#999">Carregando...</p></div>';
    await populateFilters("mf");
    document.getElementById("mfBtn").onclick = loadMatchups;
    loadMatchups();
  }

  async function loadMatchups() {
    const params = buildFilterParams("mf");
    const body = document.getElementById("matchupsBody");
    try {
      const res = await fetch("/api/scrims/matchups?" + params.toString());
      if (!res.ok) { body.innerHTML = '<p style="color:#c00">Erro</p>'; return; }
      matchupData = await res.json();
      if (!matchupData.length) { body.innerHTML = '<p style="color:#999">Sem dados de matchup.</p>'; return; }
      renderMatchupsTable();
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro: ' + escHtml(e.message) + "</p>";
    }
  }

  function renderMatchupsTable() {
    const body = document.getElementById("matchupsBody");
    const sorted = genericSort(matchupData, matchupSort.key, matchupSort.dir);
    let html = `<table class="champ-table"><thead><tr>
      ${sortTh("Role", "role", matchupSort.key, matchupSort.dir)}
      ${sortTh("Nosso Champ", "our_champion", matchupSort.key, matchupSort.dir)}
      <th>vs</th>
      ${sortTh("Champ Deles", "their_champion", matchupSort.key, matchupSort.dir)}
      ${sortTh("Games", "games", matchupSort.key, matchupSort.dir)}
      ${sortTh("W", "wins", matchupSort.key, matchupSort.dir)}
      ${sortTh("L", "losses", matchupSort.key, matchupSort.dir)}
      ${sortTh("WR%", "winrate", matchupSort.key, matchupSort.dir)}
    </tr></thead><tbody>`;
    for (const m of sorted) {
      html += `<tr>
        <td style="text-transform:capitalize">${m.role}</td>
        <td><div style="display:flex;align-items:center;gap:4px">${champAvatarHtml(m.our_champion, 20)} ${escHtml(m.our_champion)}</div></td>
        <td>vs</td>
        <td><div style="display:flex;align-items:center;gap:4px">${champAvatarHtml(m.their_champion, 20)} ${escHtml(m.their_champion)}</div></td>
        <td>${m.games}</td><td>${m.wins}</td><td>${m.losses}</td>
        <td style="font-weight:600;color:${m.winrate >= 50 ? '#16a34a' : '#dc2626'}">${m.winrate}%</td>
      </tr>`;
    }
    html += "</tbody></table>";
    body.innerHTML = html;
    attachSortHandlers(body, matchupSort, renderMatchupsTable);
  }

  // ================================================================
  // DUOS TAB
  // ================================================================
  const duoSort = { key: "games", dir: "desc" };
  let duoData = [];

  async function renderDuosTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = filtersBarHtml("df") + '<div id="duosBody"><p style="color:#999">Carregando...</p></div>';
    await populateFilters("df");
    document.getElementById("dfBtn").onclick = loadDuos;
    loadDuos();
  }

  async function loadDuos() {
    const params = buildFilterParams("df");
    const body = document.getElementById("duosBody");
    try {
      const res = await fetch("/api/scrims/duos?" + params.toString());
      if (!res.ok) { body.innerHTML = '<p style="color:#c00">Erro</p>'; return; }
      duoData = await res.json();
      if (!duoData.length) { body.innerHTML = '<p style="color:#999">Sem dados de duos.</p>'; return; }
      renderDuosTable();
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro: ' + escHtml(e.message) + "</p>";
    }
  }

  function renderDuosTable() {
    const body = document.getElementById("duosBody");
    const sorted = genericSort(duoData, duoSort.key, duoSort.dir);
    let html = `<table class="champ-table"><thead><tr>
      ${sortTh("Role 1", "role1", duoSort.key, duoSort.dir)}
      ${sortTh("Champ 1", "champion1", duoSort.key, duoSort.dir)}
      ${sortTh("Role 2", "role2", duoSort.key, duoSort.dir)}
      ${sortTh("Champ 2", "champion2", duoSort.key, duoSort.dir)}
      ${sortTh("Games", "games", duoSort.key, duoSort.dir)}
      ${sortTh("W", "wins", duoSort.key, duoSort.dir)}
      ${sortTh("L", "losses", duoSort.key, duoSort.dir)}
      ${sortTh("WR%", "winrate", duoSort.key, duoSort.dir)}
    </tr></thead><tbody>`;
    for (const d of sorted) {
      html += `<tr>
        <td style="text-transform:capitalize">${d.role1}</td>
        <td><div style="display:flex;align-items:center;gap:4px">${champAvatarHtml(d.champion1, 20)} ${escHtml(d.champion1)}</div></td>
        <td style="text-transform:capitalize">${d.role2}</td>
        <td><div style="display:flex;align-items:center;gap:4px">${champAvatarHtml(d.champion2, 20)} ${escHtml(d.champion2)}</div></td>
        <td>${d.games}</td><td>${d.wins}</td><td>${d.losses}</td>
        <td style="font-weight:600;color:${d.winrate >= 50 ? '#16a34a' : '#dc2626'}">${d.winrate}%</td>
      </tr>`;
    }
    html += "</tbody></table>";
    body.innerHTML = html;
    attachSortHandlers(body, duoSort, renderDuosTable);
  }

  // ================================================================
  // PICK ORDER TAB
  // ================================================================
  const pickSort = { key: "pick_order", dir: "asc" };
  let pickData = [];

  async function renderPickOrderTab() {
    const content = document.getElementById("scrimContent");
    content.innerHTML = filtersBarHtml("pf") + '<div id="pickBody"><p style="color:#999">Carregando...</p></div>';
    await populateFilters("pf");
    document.getElementById("pfBtn").onclick = loadPickOrder;
    loadPickOrder();
  }

  async function loadPickOrder() {
    const params = buildFilterParams("pf");
    const body = document.getElementById("pickBody");
    try {
      const res = await fetch("/api/scrims/pick-priority?" + params.toString());
      if (!res.ok) { body.innerHTML = '<p style="color:#c00">Erro</p>'; return; }
      pickData = await res.json();
      if (!pickData.length) { body.innerHTML = '<p style="color:#999">Sem dados de pick order.</p>'; return; }
      renderPickOrderTable();
    } catch (e) {
      body.innerHTML = '<p style="color:#c00">Erro: ' + escHtml(e.message) + "</p>";
    }
  }

  function renderPickOrderTable() {
    const body = document.getElementById("pickBody");
    const sorted = genericSort(pickData, pickSort.key, pickSort.dir);
    let html = `<table class="champ-table"><thead><tr>
      ${sortTh("Pick #", "pick_order", pickSort.key, pickSort.dir)}
      ${sortTh("Side", "side", pickSort.key, pickSort.dir)}
      ${sortTh("Champion", "champion", pickSort.key, pickSort.dir)}
      ${sortTh("Role", "role", pickSort.key, pickSort.dir)}
      ${sortTh("Games", "games", pickSort.key, pickSort.dir)}
      ${sortTh("W", "wins", pickSort.key, pickSort.dir)}
      ${sortTh("L", "losses", pickSort.key, pickSort.dir)}
      ${sortTh("WR%", "winrate", pickSort.key, pickSort.dir)}
    </tr></thead><tbody>`;
    for (const p of sorted) {
      html += `<tr>
        <td>${p.pick_order}</td>
        <td style="text-transform:capitalize">${p.side}</td>
        <td><div style="display:flex;align-items:center;gap:4px">${champAvatarHtml(p.champion, 20)} ${escHtml(p.champion)}</div></td>
        <td style="text-transform:capitalize">${p.role}</td>
        <td>${p.games}</td><td>${p.wins}</td><td>${p.losses}</td>
        <td style="font-weight:600;color:${p.winrate >= 50 ? '#16a34a' : '#dc2626'}">${p.winrate}%</td>
      </tr>`;
    }
    html += "</tbody></table>";
    body.innerHTML = html;
    attachSortHandlers(body, pickSort, renderPickOrderTable);
  }

  // ---- Helpers ----
  function showMessage(text, type) {
    const el = document.getElementById("scrimMessage");
    if (!el) return;
    el.className = "scrim-message " + type;
    el.textContent = text;
    setTimeout(() => {
      el.textContent = "";
      el.className = "";
    }, 4000);
  }

  function escHtml(str) {
    if (!str) return "";
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  // ---- Expose init ----
  window.initScrim = initScrim;
})();
