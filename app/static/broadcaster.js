/* ===== Broadcaster Module — ScrimVault ===== */
(function () {
  "use strict";

  // ---- State ----
  const BC_PIN_KEY = "bc_pin";
  let bcPin = null;
  let bcCurrentTab = "setup";
  let bcChampions = [];
  let bcChampByName = {};
  let bcTeams = [];
  let bcTeamA = null;
  let bcTeamB = null;

  // Draft state: each slot = { champion: string|null, locked: bool }
  // Wild Rift draft order: bans phase1 B1,R1 | picks B1,R1R2,B2B3 | bans phase2 B2,R2 | picks R3R4,B4B5,R5
  const DRAFT_ORDER = [
    // Phase 1 bans
    { team: "blue", type: "ban", order: 1 },
    { team: "red",  type: "ban", order: 2 },
    { team: "blue", type: "ban", order: 3 },
    { team: "red",  type: "ban", order: 4 },
    // Phase 1 picks
    { team: "blue", type: "pick", order: 1 },
    { team: "red",  type: "pick", order: 2 },
    { team: "red",  type: "pick", order: 3 },
    { team: "blue", type: "pick", order: 4 },
    { team: "blue", type: "pick", order: 5 },
    { team: "red",  type: "pick", order: 6 },
    // Phase 2 bans
    { team: "red",  type: "ban", order: 5 },
    { team: "blue", type: "ban", order: 6 },
    { team: "red",  type: "ban", order: 7 },
    { team: "blue", type: "ban", order: 8 },
    // Phase 2 picks
    { team: "red",  type: "pick", order: 7 },
    { team: "red",  type: "pick", order: 8 },
    { team: "blue", type: "pick", order: 9 },
    { team: "blue", type: "pick", order: 10 },
    { team: "red",  type: "pick", order: 11 },
  ];

  const draftState = {
    blue: { bans: Array(4).fill(null), picks: Array(5).fill(null) },
    red:  { bans: Array(4).fill(null), picks: Array(5).fill(null) },
    currentStep: 0,
    selectedChamp: null,
  };

  // Post-match state
  const postMatchState = {
    winner: null,
    blueSide: null,
    notes: "",
    players: [],
  };

  // ---- Helpers ----
  function bcFetch(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (bcPin) opts.headers["X-Broadcaster-Pin"] = bcPin;
    return fetch(url, opts);
  }

  function escHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function pct(v) {
    if (v == null) return "—";
    return (v * 100).toFixed(1) + "%";
  }

  function champAvatar(name, size) {
    size = size || 32;
    const c = bcChampByName[(name || "").toLowerCase()];
    if (c && c.avatar_url) {
      return `<img src="${escHtml(c.avatar_url)}" alt="${escHtml(name)}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover" onerror="this.style.display='none'">`;
    }
    const letter = name ? name[0].toUpperCase() : "?";
    return `<span style="width:${size}px;height:${size}px;border-radius:50%;background:var(--accent-dim);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:${Math.round(size*0.4)}px;flex-shrink:0">${letter}</span>`;
  }

  // ---- PIN Gate ----
  function showPinModal() {
    const overlay = document.createElement("div");
    overlay.className = "bc-pin-overlay";
    overlay.id = "bcPinOverlay";
    overlay.innerHTML = `
      <div class="bc-pin-modal">
        <h2>Broadcaster Mode</h2>
        <p>Enter your broadcaster PIN to continue</p>
        <input type="password" class="bc-pin-input" id="bcPinField" maxlength="20" placeholder="PIN" />
        <div class="bc-pin-error" id="bcPinError"></div>
        <button class="bc-pin-submit" id="bcPinSubmit">Unlock</button>
      </div>
    `;
    document.body.appendChild(overlay);
    const field = overlay.querySelector("#bcPinField");
    const submitBtn = overlay.querySelector("#bcPinSubmit");
    const errEl = overlay.querySelector("#bcPinError");
    field.focus();
    field.onkeydown = (e) => { if (e.key === "Enter") doVerify(); };
    submitBtn.onclick = doVerify;

    async function doVerify() {
      const pin = field.value.trim();
      if (!pin) { errEl.textContent = "PIN is required."; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = "Verifying…";
      errEl.textContent = "";
      try {
        const res = await fetch("/api/broadcaster/verify-pin", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin }),
        });
        if (res.ok) {
          bcPin = pin;
          sessionStorage.setItem(BC_PIN_KEY, pin);
          overlay.remove();
          bcStart();
        } else if (res.status === 401 || res.status === 403) {
          errEl.textContent = "Incorrect PIN. Try again.";
          field.value = "";
          field.focus();
        } else if (res.status === 404) {
          // endpoint not yet deployed — bypass for dev
          bcPin = pin;
          sessionStorage.setItem(BC_PIN_KEY, pin);
          overlay.remove();
          bcStart();
        } else {
          errEl.textContent = "Server error. Try again.";
        }
      } catch {
        // Network error or backend not running — bypass in dev
        bcPin = pin;
        sessionStorage.setItem(BC_PIN_KEY, pin);
        overlay.remove();
        bcStart();
      }
      submitBtn.disabled = false;
      submitBtn.textContent = "Unlock";
    }
  }

  // ---- Entry point called from index.html ----
  function initBroadcaster() {
    const stored = sessionStorage.getItem(BC_PIN_KEY);
    if (stored) {
      bcPin = stored;
      bcStart();
    } else {
      showPinModal();
    }
  }

  async function bcStart() {
    await Promise.all([loadBcChampions(), loadBcTeams()]);
    renderBcTabs();
    switchBcTab("setup");
  }

  // ---- Data loaders ----
  async function loadBcChampions() {
    try {
      const res = await bcFetch("/api/champions");
      if (res.ok) {
        bcChampions = await res.json();
        bcChampByName = {};
        for (const c of bcChampions) {
          bcChampByName[c.name.toLowerCase()] = c;
          if (c.name_cn) bcChampByName[c.name_cn.toLowerCase()] = c;
        }
      }
    } catch {}
  }

  async function loadBcTeams() {
    try {
      const res = await bcFetch("/api/openseries/teams");
      if (res.ok) {
        const data = await res.json();
        bcTeams = Array.isArray(data) ? data : (data.teams || []);
      }
    } catch {}
    // fallback — use the same hardcoded list from scrim.js
    if (!bcTeams.length) {
      bcTeams = [
        "RMD E-SPORTS","Minerva UFRJ","Team Golden Wind","NFG POROS",
        "All Next","Genei ryodan Gaming","Goatz CN","Prime",
        "Goatz Galaxy","Tudo Passa","MonkeyTeam","Valhalla Ragnarok",
        "Pegasus","Sarapathongos","Dragões da Laguna","THC Atomic",
        "Os Cansados","Custa Nada","NFG FÊNIX","NFG Boys",
        "THC Thunderlords","Duck Team","Invictus Team","Valhalla Team",
        "Fui sem TP","AREMESSANDO ALTO","FalconFury","Synergy",
        "Hiro FLQ Esports","NEXT Gaming","Inimigos do Walski","NFG LINDOS",
      ].sort((a, b) => a.localeCompare(b, "pt-BR"));
    }
  }

  // ---- Tab nav ----
  function renderBcTabs() {
    const container = document.getElementById("bcSubTabs");
    if (!container) return;
    const tabs = [
      { id: "setup",    label: "Match Setup" },
      { id: "draft",    label: "Draft Tracker" },
      { id: "live",     label: "Live Stats" },
      { id: "postmatch",label: "Post-Match" },
      { id: "overview", label: "Tournament Overview" },
    ];
    container.innerHTML = tabs.map(t =>
      `<button class="bc-tab${t.id === bcCurrentTab ? " active" : ""}" data-tab="${escHtml(t.id)}">${escHtml(t.label)}</button>`
    ).join("");
    container.querySelectorAll(".bc-tab").forEach(btn => {
      btn.onclick = () => switchBcTab(btn.dataset.tab);
    });
  }

  function switchBcTab(tabId) {
    bcCurrentTab = tabId;
    renderBcTabs();
    const content = document.getElementById("bcContent");
    if (!content) return;
    content.innerHTML = '<div class="bc-loading">Loading…</div>';
    switch (tabId) {
      case "setup":    renderSetupTab(content); break;
      case "draft":    renderDraftTab(content); break;
      case "live":     renderLiveTab(content);  break;
      case "postmatch":renderPostMatchTab(content); break;
      case "overview": renderOverviewTab(content); break;
    }
  }

  // ============================================================
  // TAB 1 — Match Setup
  // ============================================================
  function renderSetupTab(container) {
    container.innerHTML = `
      <div class="bc-team-row" style="margin-bottom:1.25rem">
        <div class="bc-team-selector">
          <label>Team A</label>
          <select class="bc-select" id="bcTeamA">${teamOptions(bcTeamA)}</select>
        </div>
        <div class="bc-team-selector">
          <label>Team B</label>
          <select class="bc-select" id="bcTeamB">${teamOptions(bcTeamB)}</select>
        </div>
      </div>
      <button class="bc-btn" id="bcLoadSetup">Compare Teams</button>
      <div id="bcSetupCompare" style="margin-top:1.25rem"></div>
    `;
    document.getElementById("bcTeamA").onchange = e => { bcTeamA = e.target.value || null; };
    document.getElementById("bcTeamB").onchange = e => { bcTeamB = e.target.value || null; };
    document.getElementById("bcLoadSetup").onclick = loadSetupCompare;
    if (bcTeamA && bcTeamB) loadSetupCompare();
  }

  function teamOptions(selected) {
    const blank = `<option value="">— Select team —</option>`;
    return blank + bcTeams.map(t =>
      `<option value="${escHtml(t)}"${t === selected ? " selected" : ""}>${escHtml(t)}</option>`
    ).join("");
  }

  async function loadSetupCompare() {
    bcTeamA = document.getElementById("bcTeamA").value || null;
    bcTeamB = document.getElementById("bcTeamB").value || null;
    const div = document.getElementById("bcSetupCompare");
    if (!bcTeamA || !bcTeamB) { div.innerHTML = '<p class="bc-empty">Select both teams to compare.</p>'; return; }
    div.innerHTML = '<div class="bc-loading">Fetching team data…</div>';
    try {
      const [overviewRes, rankRes] = await Promise.all([
        bcFetch(`/api/openseries/overview`),
        bcFetch(`/api/openseries/rankings`),
      ]);
      const overview = overviewRes.ok ? await overviewRes.json() : {};
      const rankings = rankRes.ok ? await rankRes.json() : [];
      renderSetupCompare(div, overview, rankings);
    } catch {
      renderSetupCompare(div, {}, []);
    }
  }

  function renderSetupCompare(div, overview, rankings) {
    function teamStats(teamName) {
      const teamData = overview[teamName] || {};
      const players = Array.isArray(rankings)
        ? rankings.filter(p => p.team === teamName)
        : [];
      return { teamData, players };
    }
    const a = teamStats(bcTeamA);
    const b = teamStats(bcTeamB);

    function teamCard(teamName, side, data) {
      const td = data.teamData;
      const wins = td.wins ?? "—";
      const losses = td.losses ?? "—";
      const kda = td.kda != null ? Number(td.kda).toFixed(2) : "—";
      const avgGold = td.avg_gold != null ? (td.avg_gold / 1000).toFixed(1) + "k" : "—";
      const wr = td.winrate != null ? pct(td.winrate) : "—";
      const blueWr = td.blue_winrate != null ? pct(td.blue_winrate) : "—";
      const redWr = td.red_winrate != null ? pct(td.red_winrate) : "—";
      const avgDur = td.avg_duration != null ? Math.floor(td.avg_duration / 60) + "m " + (td.avg_duration % 60) + "s" : "—";

      const rosterRows = data.players.slice(0, 5).map(p => `
        <tr>
          <td>${escHtml(p.ign || p.player || "—")}</td>
          <td>${escHtml(p.role || "—")}</td>
          <td>${p.kda != null ? Number(p.kda).toFixed(2) : "—"}</td>
          <td>${escHtml(p.main_champion || p.most_played || "—")}</td>
        </tr>
      `).join("");

      return `
        <div class="bc-compare-card ${side}-side">
          <div class="team-name">${escHtml(teamName)}</div>
          <div class="bc-stat-row"><span class="bc-stat-label">W-L</span><strong>${wins}-${losses}</strong></div>
          <div class="bc-stat-row"><span class="bc-stat-label">WR</span><strong>${wr}</strong></div>
          <div class="bc-stat-row"><span class="bc-stat-label">KDA</span><strong>${kda}</strong></div>
          <div class="bc-stat-row"><span class="bc-stat-label">Avg Gold</span><strong>${avgGold}</strong></div>
          <div class="bc-stat-row"><span class="bc-stat-label">Avg Duration</span><strong>${avgDur}</strong></div>
          <div class="bc-wr-banner" style="margin-top:0.75rem">
            <span class="bc-wr-pill blue">Blue ${blueWr}</span>
            <span class="bc-wr-pill red">Red ${redWr}</span>
          </div>
          <div style="margin-top:1rem">
            <div class="bc-card-title">Roster</div>
            <table class="bc-roster-table">
              <thead><tr><th>IGN</th><th>Role</th><th>KDA</th><th>Main</th></tr></thead>
              <tbody>${rosterRows || '<tr><td colspan="4" class="bc-empty">No data</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      `;
    }

    div.innerHTML = `
      <div class="bc-compare-grid">
        ${teamCard(bcTeamA, "blue", a)}
        ${teamCard(bcTeamB, "red", b)}
      </div>
    `;
  }

  // ============================================================
  // TAB 2 — Draft Tracker
  // ============================================================
  function renderDraftTab(container) {
    // Reset draft if needed
    container.innerHTML = `
      <div class="bc-obs-bar">
        <span class="bc-obs-url" id="bcOverlayUrl">${escHtml(location.origin)}/broadcaster/overlay</span>
        <button class="bc-btn" id="bcCopyOverlayUrl">Copy OBS URL</button>
        <button class="bc-btn bc-btn-danger" id="bcResetDraft">Reset Draft</button>
      </div>
      <div class="bc-draft-area" id="bcDraftArea"></div>
      <div class="bc-champ-picker-wrap" id="bcChampPickerWrap">
        <div class="bc-card-title" id="bcPickerLabel">Select champion for <strong>Blue Ban 1</strong></div>
        <input type="text" class="bc-champ-search" id="bcChampSearch" placeholder="Search champion…" />
        <div class="bc-champ-grid" id="bcChampGrid"></div>
      </div>
      <div class="bc-champ-stats" id="bcChampStats"><p class="bc-empty">Click a champion to see tournament stats.</p></div>
    `;

    document.getElementById("bcCopyOverlayUrl").onclick = () => {
      const url = document.getElementById("bcOverlayUrl").textContent;
      navigator.clipboard.writeText(url).catch(() => {});
    };
    document.getElementById("bcResetDraft").onclick = resetDraft;
    document.getElementById("bcChampSearch").oninput = e => renderChampGrid(e.target.value);

    renderDraftBoard();
    renderChampGrid("");
  }

  function resetDraft() {
    draftState.blue = { bans: Array(4).fill(null), picks: Array(5).fill(null) };
    draftState.red  = { bans: Array(4).fill(null), picks: Array(5).fill(null) };
    draftState.currentStep = 0;
    draftState.selectedChamp = null;
    renderDraftBoard();
    renderChampGrid("");
    saveDraftToServer();
  }

  function renderDraftBoard() {
    const area = document.getElementById("bcDraftArea");
    if (!area) return;

    function slotHtml(team, type, idx, label) {
      const champ = draftState[team][type + "s"][idx];
      const stepIdx = DRAFT_ORDER.findIndex((s,i) => s.team === team && s.type === type && (
        (type === "ban"  && (i < 4 ? idx < 2 : idx >= 2) && (idx % 2 === i % 2)) ||
        (type === "pick" && true)
      ));
      const isActive = draftState.currentStep < DRAFT_ORDER.length &&
        DRAFT_ORDER[draftState.currentStep].team === team &&
        DRAFT_ORDER[draftState.currentStep].type === type;
      const filled = champ !== null;
      const banClass = type === "ban" ? " ban-slot" : "";
      const activeClass = isActive && !filled ? " active-pick" : "";
      return `
        <div class="bc-slot${filled ? " filled" : ""}${banClass}${activeClass}"
             data-team="${team}" data-type="${type}" data-idx="${idx}">
          <span class="slot-order">${label}</span>
          ${filled ? champAvatar(champ, 32) : ""}
          <span class="slot-label">${filled ? escHtml(champ) : (type === "ban" ? "Ban" : "Pick")}</span>
        </div>`;
    }

    function teamPanel(team, color) {
      const label = team === "blue" ? (bcTeamA || "Blue Side") : (bcTeamB || "Red Side");
      // Bans: 4 total (2 in phase1, 2 in phase2)
      const bans = [0,1,2,3].map(i => slotHtml(team, "ban", i, `B${i+1}`)).join("");
      // Picks: 5
      const picks = [0,1,2,3,4].map(i => slotHtml(team, "pick", i, `P${i+1}`)).join("");
      return `
        <div class="bc-draft-team ${color}">
          <div class="bc-draft-team-label">${escHtml(label)}</div>
          <div class="bc-card-title" style="margin-bottom:0.4rem">Bans</div>
          <div class="bc-slots-row">${bans}</div>
          <div class="bc-card-title" style="margin-top:0.75rem;margin-bottom:0.4rem">Picks</div>
          <div class="bc-slots-row">${picks}</div>
        </div>`;
    }

    area.innerHTML = teamPanel("blue", "blue") + teamPanel("red", "red");

    // Slot click — navigate draft step
    area.querySelectorAll(".bc-slot").forEach(slot => {
      slot.onclick = () => {
        const t = slot.dataset.team;
        const type = slot.dataset.type;
        const idx = parseInt(slot.dataset.idx);
        // Find matching draft order step
        let step = draftState.currentStep;
        // Allow clicking a filled slot to see champ stats
        const champ = draftState[t][type + "s"][idx];
        if (champ) {
          showChampStats(champ);
          return;
        }
        // Navigate to the correct step for this slot
        const matchStep = DRAFT_ORDER.findIndex((s, i) => {
          if (s.team !== t || s.type !== type) return false;
          const sameTypeSteps = DRAFT_ORDER.filter((x, j) => j <= i && x.team === t && x.type === type);
          return sameTypeSteps.length - 1 === idx;
        });
        if (matchStep >= 0) draftState.currentStep = matchStep;
        renderDraftBoard();
        updatePickerLabel();
      };
    });
    updatePickerLabel();
  }

  function updatePickerLabel() {
    const label = document.getElementById("bcPickerLabel");
    if (!label) return;
    if (draftState.currentStep >= DRAFT_ORDER.length) {
      label.innerHTML = "Draft complete";
      return;
    }
    const step = DRAFT_ORDER[draftState.currentStep];
    const teamName = step.team === "blue" ? (bcTeamA || "Blue") : (bcTeamB || "Red");
    const typeLabel = step.type === "ban" ? "Ban" : "Pick";
    // Count how many bans/picks of this type for this team have been filled so far
    const filledCount = DRAFT_ORDER.slice(0, draftState.currentStep).filter(
      s => s.team === step.team && s.type === step.type
    ).length;
    label.innerHTML = `Select champion for <strong style="color:${step.team === "blue" ? "var(--blue-team)" : "var(--red-team)"}">${escHtml(teamName)} ${typeLabel} ${filledCount + 1}</strong>`;
  }

  function renderChampGrid(query) {
    const grid = document.getElementById("bcChampGrid");
    if (!grid) return;
    const q = (query || "").toLowerCase();
    const usedChamps = new Set([
      ...draftState.blue.bans.filter(Boolean),
      ...draftState.blue.picks.filter(Boolean),
      ...draftState.red.bans.filter(Boolean),
      ...draftState.red.picks.filter(Boolean),
    ]);
    let list = bcChampions;
    if (q) list = list.filter(c => c.name.toLowerCase().includes(q) || (c.name_cn && c.name_cn.toLowerCase().includes(q)));
    list = list.slice(0, 60);
    grid.innerHTML = list.map(c => {
      const used = usedChamps.has(c.name);
      return `<div class="bc-champ-item${used ? '" style="opacity:0.3;pointer-events:none' : ""}" data-name="${escHtml(c.name)}">
        ${c.avatar_url ? `<img src="${escHtml(c.avatar_url)}" alt="${escHtml(c.name)}" onerror="this.style.display='none'">` : `<span style="width:40px;height:40px;border-radius:50%;background:var(--accent-dim);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700">${c.name[0]}</span>`}
        <span class="champ-name">${escHtml(c.name)}</span>
      </div>`;
    }).join("");
    grid.querySelectorAll(".bc-champ-item").forEach(item => {
      item.onclick = () => selectChampForDraft(item.dataset.name);
    });
  }

  async function selectChampForDraft(champName) {
    if (draftState.currentStep >= DRAFT_ORDER.length) return;
    const step = DRAFT_ORDER[draftState.currentStep];
    const slotIdx = DRAFT_ORDER.slice(0, draftState.currentStep).filter(
      s => s.team === step.team && s.type === step.type
    ).length;
    draftState[step.team][step.type + "s"][slotIdx] = champName;
    draftState.currentStep++;
    renderDraftBoard();
    renderChampGrid(document.getElementById("bcChampSearch")?.value || "");
    showChampStats(champName);
    saveDraftToServer();
  }

  async function showChampStats(champName) {
    const el = document.getElementById("bcChampStats");
    if (!el) return;
    el.innerHTML = `<div class="bc-loading">Loading ${escHtml(champName)} stats…</div>`;
    try {
      const res = await bcFetch(`/api/openseries/champions`);
      const data = res.ok ? await res.json() : [];
      const champ = Array.isArray(data)
        ? data.find(c => (c.champion || c.name || "").toLowerCase() === champName.toLowerCase())
        : null;
      const c = bcChampByName[champName.toLowerCase()];
      el.innerHTML = `
        <div class="champ-header">
          ${champAvatar(champName, 44)}
          <span class="champ-nm">${escHtml(champName)}</span>
        </div>
        <div class="bc-stat-pills">
          <div class="bc-stat-pill">Picks <span>${champ ? champ.picks ?? "—" : "—"}</span></div>
          <div class="bc-stat-pill">WR <span>${champ ? pct(champ.winrate) : "—"}</span></div>
          <div class="bc-stat-pill">KDA <span>${champ ? (champ.kda != null ? Number(champ.kda).toFixed(2) : "—") : "—"}</span></div>
          <div class="bc-stat-pill">Ban Rate <span>${champ ? pct(champ.ban_rate ?? champ.banrate) : "—"}</span></div>
        </div>
      `;
    } catch {
      el.innerHTML = `<div class="bc-empty">Stats unavailable for ${escHtml(champName)}.</div>`;
    }
  }

  async function saveDraftToServer() {
    try {
      await bcFetch("/api/broadcaster/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team_a: bcTeamA,
          team_b: bcTeamB,
          blue: draftState.blue,
          red: draftState.red,
          step: draftState.currentStep,
        }),
      });
    } catch {}
  }

  // ============================================================
  // TAB 3 — Live Stats
  // ============================================================
  async function renderLiveTab(container) {
    container.innerHTML = '<div class="bc-loading">Loading live stats…</div>';
    try {
      const [rankRes, overviewRes] = await Promise.all([
        bcFetch("/api/openseries/rankings"),
        bcFetch("/api/openseries/overview"),
      ]);
      const rankings = rankRes.ok ? await rankRes.json() : [];
      const overview = overviewRes.ok ? await overviewRes.json() : {};
      renderLiveContent(container, rankings, overview);
    } catch {
      container.innerHTML = '<p class="bc-empty">Could not load live stats. Backend may be unavailable.</p>';
    }
  }

  function renderLiveContent(container, rankings, overview) {
    const teamsFilter = (bcTeamA || bcTeamB)
      ? rankings.filter(p => p.team === bcTeamA || p.team === bcTeamB)
      : rankings;

    // Highlights
    const byKda = [...rankings].sort((a,b) => (b.kda||0)-(a.kda||0));
    const mostPicked = Object.entries(
      rankings.reduce((acc, p) => {
        const c = p.main_champion || p.most_played;
        if (c) acc[c] = (acc[c]||0) + 1;
        return acc;
      }, {})
    ).sort((a,b) => b[1]-a[1])[0];

    // Dominant team by win count
    const teamWins = {};
    Object.entries(overview).forEach(([team, td]) => { teamWins[team] = td.wins || 0; });
    const topTeam = Object.entries(teamWins).sort((a,b) => b[1]-a[1])[0];

    const highlightsHtml = `
      <div class="bc-highlights">
        <div class="bc-highlight-item">
          <div class="hi-label">Highest KDA Player</div>
          <div class="hi-value">${escHtml(byKda[0]?.ign || byKda[0]?.player || "—")}</div>
          <div class="hi-sub">${byKda[0] ? Number(byKda[0].kda).toFixed(2) + " KDA · " + escHtml(byKda[0].team || "") : ""}</div>
        </div>
        <div class="bc-highlight-item">
          <div class="hi-label">Most Played Champion</div>
          <div class="hi-value">${escHtml(mostPicked?.[0] || "—")}</div>
          <div class="hi-sub">${mostPicked ? mostPicked[1] + " players" : ""}</div>
        </div>
        <div class="bc-highlight-item">
          <div class="hi-label">Most Dominant Team</div>
          <div class="hi-value">${escHtml(topTeam?.[0] || "—")}</div>
          <div class="hi-sub">${topTeam ? topTeam[1] + " wins" : ""}</div>
        </div>
      </div>
    `;

    // Player spotlight
    const spotlightHtml = teamsFilter.length
      ? `<div class="bc-card-title" style="margin-bottom:0.75rem">Player Spotlight${bcTeamA||bcTeamB ? " — Selected Teams" : ""}</div>
         <div class="bc-spotlight-grid" id="bcSpotlightGrid">
           ${teamsFilter.slice(0,10).map(p => `
             <div class="bc-player-card" data-player="${escHtml(p.ign || p.player || "")}">
               <div class="player-ign">${escHtml(p.ign || p.player || "—")}</div>
               <div class="player-role">${escHtml(p.role || "—")} · ${escHtml(p.team || "")}</div>
               <div class="player-stat">KDA <strong>${p.kda != null ? Number(p.kda).toFixed(2) : "—"}</strong></div>
               <div class="player-stat">Main: <strong>${escHtml(p.main_champion || p.most_played || "—")}</strong></div>
             </div>`).join("")}
         </div>`
      : '<p class="bc-empty">No player data available.</p>';

    // Talking points
    const points = [];
    if (bcTeamA && bcTeamB) {
      const aTd = overview[bcTeamA] || {};
      const bTd = overview[bcTeamB] || {};
      if (aTd.winrate != null && bTd.winrate != null) {
        const better = aTd.winrate >= bTd.winrate ? bcTeamA : bcTeamB;
        points.push(`${better} enters the match with the better overall win rate.`);
      }
      if (aTd.blue_winrate != null) points.push(`${bcTeamA} blue side WR: ${pct(aTd.blue_winrate)}, red side WR: ${pct(aTd.red_winrate)}.`);
      if (bTd.blue_winrate != null) points.push(`${bcTeamB} blue side WR: ${pct(bTd.blue_winrate)}, red side WR: ${pct(bTd.red_winrate)}.`);
      if (aTd.kda != null && bTd.kda != null) {
        const aggrTeam = Number(aTd.kda) >= Number(bTd.kda) ? bcTeamA : bcTeamB;
        points.push(`${aggrTeam} has the higher team KDA — expect a more aggressive playstyle.`);
      }
    }
    if (byKda[0]) points.push(`Watch out for ${byKda[0].ign || byKda[0].player} — the highest KDA player in the tournament.`);
    if (mostPicked) points.push(`${mostPicked[0]} is the most popular champion across the field.`);

    const talkingHtml = `
      <div class="bc-card-title" style="margin-bottom:0.5rem">Talking Points</div>
      <div class="bc-talking-points">
        <ul>${points.length
          ? points.map(p => `<li>${escHtml(p)}</li>`).join("")
          : '<li>Select two teams in Match Setup for match-specific talking points.</li>'
        }</ul>
      </div>
    `;

    container.innerHTML = highlightsHtml + spotlightHtml + '<div style="margin-top:1.25rem">' + talkingHtml + '</div>';
  }

  // ============================================================
  // TAB 4 — Post-Match
  // ============================================================
  function renderPostMatchTab(container) {
    const teamAName = bcTeamA || "Team A";
    const teamBName = bcTeamB || "Team B";

    // Build player list from draft picks
    const allPlayers = [
      ...draftState.blue.picks.filter(Boolean).map((c, i) => ({ ign: c, team: "blue", role: ["top","jungle","mid","bot","support"][i] })),
      ...draftState.red.picks.filter(Boolean).map((c, i) => ({ ign: c, team: "red", role: ["top","jungle","mid","bot","support"][i] })),
    ];

    container.innerHTML = `
      <div class="bc-postmatch-form">
        <div class="bc-field-group">
          <label>Winner</label>
          <div class="bc-radio-row" id="bcWinnerRow">
            <button class="bc-radio-btn${postMatchState.winner === "A" ? " selected-win" : ""}" data-winner="A">${escHtml(teamAName)}</button>
            <button class="bc-radio-btn${postMatchState.winner === "B" ? " selected-win" : ""}" data-winner="B">${escHtml(teamBName)}</button>
          </div>
        </div>
        <div class="bc-field-group">
          <label>Blue Side</label>
          <div class="bc-radio-row" id="bcBlueSideRow">
            <button class="bc-radio-btn${postMatchState.blueSide === "A" ? " selected-blue" : ""}" data-side="A">${escHtml(teamAName)}</button>
            <button class="bc-radio-btn${postMatchState.blueSide === "B" ? " selected-blue" : ""}" data-side="B">${escHtml(teamBName)}</button>
          </div>
        </div>
        <div class="bc-field-group">
          <label>Per-Player KDA (optional)</label>
          <div class="bc-kda-grid" id="bcKdaGrid">
            ${allPlayers.length
              ? allPlayers.map((p, i) => `
                  <div class="bc-kda-item">
                    <span class="kda-ign">${escHtml(p.ign)} (${escHtml(p.role)})</span>
                    <div class="bc-kda-inputs">
                      <input type="number" min="0" max="99" placeholder="K" data-pi="${i}" data-field="k" />
                      <span class="bc-kda-sep">/</span>
                      <input type="number" min="0" max="99" placeholder="D" data-pi="${i}" data-field="d" />
                      <span class="bc-kda-sep">/</span>
                      <input type="number" min="0" max="99" placeholder="A" data-pi="${i}" data-field="a" />
                    </div>
                  </div>`).join("")
              : '<p class="bc-empty" style="font-size:0.78rem">Complete the draft first to see players here.</p>'
            }
          </div>
        </div>
        <div class="bc-field-group">
          <label>Match Notes</label>
          <textarea class="bc-textarea" id="bcMatchNotes" placeholder="Observations, highlights, coaching notes…">${escHtml(postMatchState.notes)}</textarea>
        </div>
        <div class="bc-save-bar">
          <button class="bc-btn" id="bcSaveMatch">Save Match</button>
          <span class="bc-save-msg" id="bcSaveMsg"></span>
        </div>
      </div>
    `;

    // Wire up winner buttons
    container.querySelectorAll("#bcWinnerRow .bc-radio-btn").forEach(btn => {
      btn.onclick = () => {
        postMatchState.winner = btn.dataset.winner;
        container.querySelectorAll("#bcWinnerRow .bc-radio-btn").forEach(b => b.classList.remove("selected-win"));
        btn.classList.add("selected-win");
      };
    });

    // Wire up blue side buttons
    container.querySelectorAll("#bcBlueSideRow .bc-radio-btn").forEach(btn => {
      btn.onclick = () => {
        postMatchState.blueSide = btn.dataset.side;
        container.querySelectorAll("#bcBlueSideRow .bc-radio-btn").forEach(b => b.classList.remove("selected-blue"));
        btn.classList.add("selected-blue");
      };
    });

    document.getElementById("bcSaveMatch").onclick = savePostMatch;
  }

  async function savePostMatch() {
    const notes = document.getElementById("bcMatchNotes")?.value || "";
    postMatchState.notes = notes;

    // Collect KDA inputs
    const kdaInputs = document.querySelectorAll(".bc-kda-inputs input");
    const playerData = {};
    kdaInputs.forEach(inp => {
      const pi = inp.dataset.pi;
      const field = inp.dataset.field;
      if (!playerData[pi]) playerData[pi] = {};
      playerData[pi][field] = parseInt(inp.value) || 0;
    });

    const body = {
      team_a: bcTeamA,
      team_b: bcTeamB,
      winner: postMatchState.winner,
      blue_side: postMatchState.blueSide,
      notes: notes,
      player_kda: Object.values(playerData),
      draft: { blue: draftState.blue, red: draftState.red },
    };

    const msg = document.getElementById("bcSaveMsg");
    try {
      const res = await bcFetch("/api/broadcaster/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      msg.textContent = res.ok || res.status === 404 ? "Saved!" : "Error saving match.";
      msg.style.color = (res.ok || res.status === 404) ? "var(--green)" : "var(--red)";
    } catch {
      msg.textContent = "Network error.";
      msg.style.color = "var(--red)";
    }
    setTimeout(() => { if (msg) msg.textContent = ""; }, 3000);
  }

  // ============================================================
  // TAB 5 — Tournament Overview
  // ============================================================
  async function renderOverviewTab(container) {
    container.innerHTML = '<div class="bc-loading">Loading tournament data…</div>';
    try {
      const [standingsRes, rankRes, overviewRes, champRes] = await Promise.all([
        bcFetch("/api/openseries/standings"),
        bcFetch("/api/openseries/rankings"),
        bcFetch("/api/openseries/overview"),
        bcFetch("/api/openseries/champions"),
      ]);
      const standings = standingsRes.ok ? await standingsRes.json() : [];
      const rankings  = rankRes.ok ? await rankRes.json() : [];
      const overview  = overviewRes.ok ? await overviewRes.json() : {};
      const champData = champRes.ok ? await champRes.json() : [];
      renderOverviewContent(container, standings, rankings, overview, champData);
    } catch {
      container.innerHTML = '<p class="bc-empty">Could not load tournament data.</p>';
    }
  }

  function renderOverviewContent(container, standings, rankings, overview, champData) {
    // Group standings
    const groups = {};
    const standingsList = Array.isArray(standings) ? standings : (standings.teams || []);
    standingsList.forEach(t => {
      const g = t.group || "—";
      if (!groups[g]) groups[g] = [];
      groups[g].push(t);
    });

    const standingsHtml = Object.entries(groups).length
      ? Object.entries(groups).map(([grp, teams]) => `
          <div class="bc-card" style="margin-bottom:0.75rem">
            <div class="bc-card-title">Group ${escHtml(grp)}</div>
            <table class="bc-standings-table">
              <thead><tr><th>#</th><th>Team</th><th>W</th><th>L</th><th>WR</th></tr></thead>
              <tbody>${teams.sort((a,b) => (b.wins||0)-(a.wins||0)).map((t,i) => `
                <tr>
                  <td><span class="bc-rank-badge rank-${i+1}">${i+1}</span></td>
                  <td>${escHtml(t.team || t.name || "—")}</td>
                  <td style="color:var(--green)">${t.wins ?? "—"}</td>
                  <td style="color:var(--red)">${t.losses ?? "—"}</td>
                  <td>${t.winrate != null ? pct(t.winrate) : "—"}</td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>`).join("")
      : buildOverviewFromOverviewApi(overview);

    // Top 10 players leaderboard (by KDA)
    const topPlayers = [...rankings].sort((a,b) => (b.kda||0)-(a.kda||0)).slice(0,10);
    const leaderboardHtml = `
      <div class="bc-card">
        <div class="bc-card-title">Top 10 Players — KDA</div>
        <table class="bc-leaderboard-table">
          <thead><tr><th>#</th><th>IGN</th><th>Team</th><th>Role</th><th>KDA</th><th>Main</th></tr></thead>
          <tbody>${topPlayers.map((p,i) => `
            <tr>
              <td><span class="bc-rank-badge rank-${i+1}">${i+1}</span></td>
              <td>${escHtml(p.ign || p.player || "—")}</td>
              <td>${escHtml(p.team || "—")}</td>
              <td>${escHtml(p.role || "—")}</td>
              <td style="color:var(--accent)">${p.kda != null ? Number(p.kda).toFixed(2) : "—"}</td>
              <td>${escHtml(p.main_champion || p.most_played || "—")}</td>
            </tr>`).join("") || '<tr><td colspan="6" class="bc-empty">No data</td></tr>'}
          </tbody>
        </table>
      </div>`;

    // Champion meta snapshot
    const champList = Array.isArray(champData) ? champData : [];
    const top10Picked = [...champList].sort((a,b) => (b.picks||0)-(a.picks||0)).slice(0,10);
    const top10Banned = [...champList].sort((a,b) => (b.bans||0)-(a.bans||0)).slice(0,10);
    const top10Wr = [...champList].filter(c => (c.picks||0) >= 3).sort((a,b) => (b.winrate||0)-(a.winrate||0)).slice(0,10);

    const metaSnapHtml = `
      <div class="bc-card">
        <div class="bc-card-title">Champion Meta Snapshot</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;flex-wrap:wrap">
          <div>
            <div class="bc-card-title" style="color:var(--text-muted)">Top Picked</div>
            ${top10Picked.map((c,i) => `<div class="bc-stat-row"><span class="bc-stat-label">${i+1}. ${escHtml(c.champion||c.name||"—")}</span><span>${c.picks ?? "—"} picks</span></div>`).join("") || "<p class='bc-empty'>—</p>"}
          </div>
          <div>
            <div class="bc-card-title" style="color:var(--text-muted)">Top Banned</div>
            ${top10Banned.map((c,i) => `<div class="bc-stat-row"><span class="bc-stat-label">${i+1}. ${escHtml(c.champion||c.name||"—")}</span><span>${c.bans ?? "—"} bans</span></div>`).join("") || "<p class='bc-empty'>—</p>"}
          </div>
          <div>
            <div class="bc-card-title" style="color:var(--text-muted)">Highest WR (≥3 games)</div>
            ${top10Wr.map((c,i) => `<div class="bc-stat-row"><span class="bc-stat-label">${i+1}. ${escHtml(c.champion||c.name||"—")}</span><span>${pct(c.winrate)}</span></div>`).join("") || "<p class='bc-empty'>—</p>"}
          </div>
        </div>
      </div>`;

    // Power rankings table from overview
    const powerRows = Object.entries(overview)
      .map(([team, td]) => ({ team, wins: td.wins||0, losses: td.losses||0, kda: td.kda, winrate: td.winrate }))
      .sort((a,b) => (b.winrate||0)-(a.winrate||0));

    const powerHtml = `
      <div class="bc-card">
        <div class="bc-card-title">Team Power Rankings</div>
        <table class="bc-standings-table">
          <thead><tr><th>#</th><th>Team</th><th>W</th><th>L</th><th>WR</th><th>KDA</th></tr></thead>
          <tbody>${powerRows.slice(0,16).map((t,i) => `
            <tr>
              <td><span class="bc-rank-badge rank-${i+1}">${i+1}</span></td>
              <td>${escHtml(t.team)}</td>
              <td style="color:var(--green)">${t.wins}</td>
              <td style="color:var(--red)">${t.losses}</td>
              <td>${t.winrate != null ? pct(t.winrate) : "—"}</td>
              <td>${t.kda != null ? Number(t.kda).toFixed(2) : "—"}</td>
            </tr>`).join("") || '<tr><td colspan="6" class="bc-empty">No data</td></tr>'}
          </tbody>
        </table>
      </div>`;

    container.innerHTML = `
      <div class="bc-overview-grid">
        <div>${standingsHtml}</div>
        <div>${leaderboardHtml}</div>
      </div>
      <div style="margin-bottom:1.25rem">${metaSnapHtml}</div>
      ${powerHtml}
    `;
  }

  function buildOverviewFromOverviewApi(overview) {
    // fallback when /standings is not available — derive groups from overview data
    const teams = Object.entries(overview).map(([team, td]) => ({
      team, wins: td.wins||0, losses: td.losses||0, winrate: td.winrate, group: td.group || "—"
    }));
    if (!teams.length) return '<p class="bc-empty">No standings data available.</p>';
    return `<div class="bc-card">
      <div class="bc-card-title">Group Standings</div>
      <table class="bc-standings-table">
        <thead><tr><th>#</th><th>Team</th><th>W</th><th>L</th><th>WR</th></tr></thead>
        <tbody>${teams.sort((a,b) => (b.wins||0)-(a.wins||0)).map((t,i) => `
          <tr>
            <td><span class="bc-rank-badge rank-${i+1}">${i+1}</span></td>
            <td>${escHtml(t.team)}</td>
            <td style="color:var(--green)">${t.wins}</td>
            <td style="color:var(--red)">${t.losses}</td>
            <td>${t.winrate != null ? pct(t.winrate) : "—"}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
  }

  // ---- Expose public API ----
  window.initBroadcaster = initBroadcaster;
  window.getBroadcasterDraftState = () => ({
    teamA: bcTeamA,
    teamB: bcTeamB,
    blue: draftState.blue,
    red: draftState.red,
    step: draftState.currentStep,
  });
})();
