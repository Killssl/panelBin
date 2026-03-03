const els = {
  rows: document.getElementById("rows"),
  detailsJson: document.getElementById("detailsJson"),
  cards: document.getElementById("cards"),
  serverTime: document.getElementById("serverTime"),
  countPill: document.getElementById("countPill"),
  detailsTitle: document.getElementById("detailsTitle"),
  detailsSub: document.getElementById("detailsSub"),
  detailsMeta: document.getElementById("detailsMeta"),
  detailsSearchWrap: document.getElementById("detailsSearchWrap"),
  offerSearch: document.getElementById("offerSearch"),
  offerSearchCount: document.getElementById("offerSearchCount"),
  q: document.getElementById("q"),
  status: document.getElementById("status"),
  perPage: document.getElementById("perPage"),
  btnRefresh: document.getElementById("btnRefresh"),
  btnApply: document.getElementById("btnApply"),
};

let currentRotationId = null;
let selectedRotationIds = new Set(); // для мульти-аналитики

// ─── Helpers для дат ──────────────────────────────────────────────────────────

function getDefaultWeekRange() {
  // Среда прошлой недели → Вторник этой недели
  const today = new Date();
  const dow = today.getDay(); // 0=вс, 1=пн, ..., 3=ср, 5=пт

  // Найдём ближайший прошедший вторник (конец периода)
  const daysSinceTue = (dow + 7 - 2) % 7; // 2=вторник
  const tue = new Date(today);
  tue.setDate(today.getDate() - (daysSinceTue === 0 ? 7 : daysSinceTue));

  // Среда = вторник - 6 дней
  const wed = new Date(tue);
  wed.setDate(tue.getDate() - 6);

  return {
    from: wed.toISOString().slice(0, 10),
    to:   tue.toISOString().slice(0, 10),
  };
}

function roundUniq(n) {
  // Округляем вниз до красивого числа
  if (n >= 2000) return Math.floor(n / 500) * 500;
  if (n >= 1000) return Math.floor(n / 250) * 250;
  if (n >= 500)  return Math.floor(n / 100) * 100;
  if (n >= 200)  return Math.floor(n / 50)  * 50;
  return Math.floor(n / 50) * 50;
}

function formatCardText(rot) {
  const lines = [`${rot.rotationName}:`];
  rot.countries.forEach(c => {
    const r = roundUniq(c.uniq);
    lines.push(`${c.country} - более ${r.toLocaleString()} уников в неделю`);
  });
  return lines.join("\n");
}

function fmtDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function badgeFor(status) {
  const st = (status || "").toLowerCase();
  let dot = "warn";
  if (st.includes("active")) dot = "ok";
  if (st.includes("pause") || st.includes("stop")) dot = "warn";
  if (st.includes("delete") || st.includes("trash")) dot = "bad";
  return `<span class="badge"><span class="dot ${dot}"></span>${escapeHtml(status || "—")}</span>`;
}

function setLoading() {
  els.rows.innerHTML = `<tr><td colspan="5" class="muted">Загрузка...</td></tr>`;
}
function setError(msg) {
  els.rows.innerHTML = `<tr><td colspan="5" class="muted">Ошибка: ${escapeHtml(msg)}</td></tr>`;
}

function showCards(mode = "grid") {
  if (els.cards) els.cards.style.display = (mode === "accordion" || mode === "analytics") ? "block" : "grid";
  if (els.detailsJson) els.detailsJson.style.display = "none";
  if (mode !== "analytics") hideOfferSearch();
}
function showJson() {
  if (els.cards) els.cards.style.display = "none";
  if (els.detailsJson) els.detailsJson.style.display = "block";
  hideOfferSearch();
}
function showOfferSearch() {
  if (els.detailsSearchWrap) els.detailsSearchWrap.style.display = "flex";
}
function hideOfferSearch() {
  if (els.detailsSearchWrap) els.detailsSearchWrap.style.display = "none";
  if (els.offerSearch) els.offerSearch.value = "";
  if (els.offerSearchCount) els.offerSearchCount.textContent = "—";
}

function extractRotationArray(payload) {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload;
  const d = payload.data;
  if (d && Array.isArray(d.data)) return d.data;
  if (d && Array.isArray(d.items)) return d.items;
  if (d && Array.isArray(d.result)) return d.result;
  if (Array.isArray(d)) return d;
  return [];
}

async function fetchJsonSafe(url, opts = {}) {
  const options = {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  };
  const r = await fetch(url, options);
  const text = await r.text();
  if (text.trim().startsWith("<")) throw new Error(`Сервер вернул HTML вместо JSON: ${url}`);
  let json;
  try { json = JSON.parse(text); } catch { throw new Error(`Не JSON ответ: ${url}`); }
  return { r, json };
}

// ─── Offer search ─────────────────────────────────────────────────────────────

function highlightText(text, query) {
  if (!query) return escapeHtml(text);
  const escaped = escapeHtml(text);
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return escaped.replace(new RegExp(`(${escapedQuery})`, 'gi'), '<mark>$1</mark>');
}

function applyOfferSearch(query) {
  if (!els.cards) return;
  const geoBlocks = els.cards.querySelectorAll("[data-geo]");
  const q = query.trim().toLowerCase();
  let totalMatches = 0;

  geoBlocks.forEach(geo => {
    const offerRows = geo.querySelectorAll(".offer-row");
    let geoMatches = 0;
    offerRows.forEach(row => {
      const nameEl = row.querySelector(".offer-name");
      const originalName = nameEl.dataset.original || nameEl.textContent;
      nameEl.dataset.original = originalName;
      if (!q) {
        nameEl.innerHTML = escapeHtml(originalName);
        row.style.display = "";
        row.classList.remove("match");
      } else {
        const matches = originalName.toLowerCase().includes(q);
        if (matches) {
          nameEl.innerHTML = highlightText(originalName, q);
          row.style.display = "";
          row.classList.add("match");
          geoMatches++;
          totalMatches++;
        } else {
          nameEl.innerHTML = escapeHtml(originalName);
          row.style.display = "none";
          row.classList.remove("match");
        }
      }
    });
    if (!q) {
      geo.classList.remove("search-hidden");
    } else {
      if (geoMatches > 0) {
        geo.classList.remove("search-hidden");
        geo.classList.add("open");
      } else {
        geo.classList.add("search-hidden");
      }
    }
  });

  if (els.offerSearchCount) {
    els.offerSearchCount.textContent = q ? `${totalMatches} найдено` : "—";
  }
}

// ─── DPU helpers ──────────────────────────────────────────────────────────────

function dpuBadge(item) {
  if (item.dpu === null || item.dpu === undefined) return "";

  const dpu = parseFloat(item.dpu) || 0;
  const period = item.dpu_period || "—";
  const uniq = item.dpu_uniq || 0;
  const note = item.dpu_note;

  // цвет по значению
  let cls = "dpu-zero";
  if (note === "insufficient_data") {
    cls = "dpu-nodata";
  } else if (dpu > 0.3) {
    cls = "dpu-high";
  } else if (dpu > 0.1) {
    cls = "dpu-mid";
  } else if (dpu > 0) {
    cls = "dpu-low";
  }

  const label = note === "insufficient_data"
    ? `<span class="dpu-val">n/a</span>`
    : `<span class="dpu-val">$${dpu.toFixed(3)}</span>`;

  return `
    <div class="dpu-badge ${cls}" title="Период: ${escapeHtml(period)} | Уников: ${uniq}">
      ${label}
      <span class="dpu-period">${escapeHtml(period)}</span>
    </div>
  `;
}

// ─── Render accordion ─────────────────────────────────────────────────────────

function renderGeoAccordion(groups, withDpu = false, rotId = null) {
  if (rotId) currentRotationId = rotId;
  showCards("accordion");
  showOfferSearch();

  if (!els.cards) return;

  if (!groups || !groups.length) {
    els.cards.innerHTML = `<div class="muted">Нет активных офферов (weight > 0).</div>`;
    els.detailsMeta.textContent = "0 offers";
    hideOfferSearch();
    return;
  }

  const totalOffers = groups.reduce((acc, g) => acc + (g.items?.length || 0), 0);
  els.detailsMeta.textContent = `${totalOffers} offers`;

  els.cards.innerHTML = `
    <div class="accordion">
      ${groups.map((g, idx) => {
        const rotId = currentRotationId;
        const count = g.items?.length || 0;
        const tw = (g.totalWeight ?? 0).toFixed(0);
        return `
          <div class="geo open" data-geo>
            <div class="geo-head" data-geo-head>
              <div class="geo-title">${escapeHtml(g.geoTitle || "—")}</div>
              <div class="geo-meta">
                <span>${count} offers</span>
                <span>∑w ${escapeHtml(tw)}</span>
                <button class="btn dpu-geo-btn" data-dpu-geo="${escapeHtml(g.geoTitle || "")}" data-rotation-id="${escapeHtml(String(rotId || ""))}" title="Посчитать DPU для этого GEO">$Unic</button>
                <span class="chevron">▾</span>
              </div>
            </div>
            <div class="geo-body">
              ${(g.items || []).map(it => `
                <div class="offer-row">
                  <div class="offer-left">
                    <div class="offer-name">${escapeHtml(it.offerName || "—")}</div>
                    <div class="offer-sub">
                      Path: ${escapeHtml(it.pathName || "—")}
                      ${it.affiliateNetworkName ? `<br/>Net: ${escapeHtml(it.affiliateNetworkName)}` : ""}
                    </div>
                  </div>
                  <div class="offer-right">
                    ${withDpu ? dpuBadge(it) : ""}
                    <div class="offer-weight">Weight: ${escapeHtml(it.weight)}</div>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;

  if (els.offerSearch && els.offerSearch.value.trim()) {
    applyOfferSearch(els.offerSearch.value);
  }
}

// ─── Render cards (fallback) ──────────────────────────────────────────────────

function renderOfferCards(items) {
  showCards("grid");
  hideOfferSearch();
  if (!els.cards) return;
  if (!items || !items.length) {
    els.cards.innerHTML = `<div class="muted">Нет активных офферов (weight &gt; 0).</div>`;
    els.detailsMeta.textContent = "0 offers";
    return;
  }
  els.detailsMeta.textContent = `${items.length} offers`;
  els.cards.innerHTML = items.map((it) => `
    <div class="card">
      <div class="card-top">
        <div>
          <div class="card-title">${escapeHtml(it.offerName || "—")}</div>
          <div class="card-sub">GEO: ${escapeHtml(it.geo || "—")}<br/>Weight: ${escapeHtml(it.weight)}</div>
        </div>
        <div class="weight">${escapeHtml(it.weight)}</div>
      </div>
      <div class="card-sub" style="margin-top:10px;">
        Rule: ${escapeHtml(it.ruleName || "—")}<br/>
        Path: ${escapeHtml(it.pathName || "—")}
        ${it.affiliateNetworkName ? `<br/>Net: ${escapeHtml(it.affiliateNetworkName)}` : ""}
      </div>
    </div>
  `).join("");
}

// ─── Multi-Rotation Analytics ─────────────────────────────────────────────────

function _updateMultiAnalyticsBtn() {
  let btn = document.getElementById("multiAnalyticsBtn");
  const count = selectedRotationIds.size;

  if (count < 2) {
    if (btn) btn.remove();
    return;
  }

  if (!btn) {
    btn = document.createElement("button");
    btn.id = "multiAnalyticsBtn";
    btn.className = "btn multi-analytics-btn";
    btn.addEventListener("click", () => loadMultiAnalytics([...selectedRotationIds]));
    // Вставляем рядом с btnRefresh
    const ref = els.btnRefresh || els.btnApply;
    if (ref) ref.parentNode.insertBefore(btn, ref.nextSibling);
    else document.body.appendChild(btn);
  }
  btn.textContent = `📊 Analytics (${count})`;
}

async function loadMultiAnalytics(rotIds, preset = "last_7_days") {
  els.detailsTitle.textContent = `Multi-Analytics — ${rotIds.length} ротации`;
  els.detailsSub.textContent   = "Сравнение офферов по GEO";
  els.detailsMeta.textContent  = "—";
  showCards("analytics");
  if (els.cards) els.cards.innerHTML = `<div class="an-loading"><span class="an-spinner"></span>Загрузка ${rotIds.length} ротаций…</div>`;

  // Загружаем все ротации параллельно
  const results = await Promise.all(rotIds.map(async (id) => {
    try {
      const { r, json } = await fetchJsonSafe(`/api/rotation/${encodeURIComponent(id)}/analytics?preset=${preset}`);
      // Получаем имя ротации из таблицы
      const cb = document.querySelector(`.rot-checkbox[data-rot-id="${id}"]`);
      const rotName = cb ? cb.dataset.rotName : `Rotation #${id}`;
      return { id, name: rotName, groups: json.ok ? (json.groups || []) : [] };
    } catch(e) {
      return { id, name: `Rotation #${id}`, groups: [] };
    }
  }));

  renderMultiAnalytics(rotIds, results, preset);
}

function renderMultiAnalytics(rotIds, results, preset) {
  if (!els.cards) return;

  const presetLabels = {
    "today": "Сегодня", "yesterday": "Вчера",
    "last_7_days": "7 дней", "last_14_days": "14 дней", "last_30_days": "30 дней",
  };

  // Индекс: rotId -> name
  const rotNames = {};
  results.forEach(r => { rotNames[r.id] = r.name; });

  // Собираем все GEO → все уникальные офферы → данные по каждой ротации
  // Структура: geo -> offerName -> { offerId, offerName, byRot: { rotId: itemData } }
  const geoMap = new Map();
  for (const rot of results) {
    for (const g of rot.groups) {
      if (!geoMap.has(g.geo)) geoMap.set(g.geo, new Map());
      const offerMap = geoMap.get(g.geo);
      for (const item of g.items) {
        const key = item.offerId;
        if (!offerMap.has(key)) offerMap.set(key, { offerId: item.offerId, offerName: item.offerName, byRot: {} });
        offerMap.get(key).byRot[rot.id] = item;
      }
    }
  }

  // Сортируем GEO по суммарному uniq
  const sortedGeos = [...geoMap.entries()].sort((a, b) => {
    const sum = (e) => [...e[1].values()].reduce((s, o) => s + Object.values(o.byRot).reduce((x, i) => x + (i.uniq||0), 0), 0);
    return sum(b) - sum(a);
  });

  const totalGeos = sortedGeos.length;
  const totalOffers = sortedGeos.reduce((s, [,om]) => s + om.size, 0);
  els.detailsMeta.textContent = `${totalOffers} offers · ${totalGeos} GEO · ${rotIds.length} ротации`;

  const presetBar = Object.entries(presetLabels).map(([val, label]) =>
    `<button class="an-preset-btn ${val === preset ? "active" : ""}" data-preset="${val}" data-multi-rot-ids="${rotIds.join(",")}">${label}</button>`
  ).join("");

  // Цвета для ротаций
  const rotColors = ["#6da0ff","#22d47a","#fbbf24","#f87171","#a78bfa","#34d4c8"];
  const rotColorMap = {};
  rotIds.forEach((id, i) => { rotColorMap[id] = rotColors[i % rotColors.length]; });

  // Легенда ротаций с цветами
  const legend = rotIds.map(id =>
    `<span class="an-rot-legend-item" style="border-color:${rotColorMap[id]};color:${rotColorMap[id]}">
      <span class="an-rot-legend-dot" style="background:${rotColorMap[id]}"></span>
      ${escapeHtml(rotNames[id])}
    </span>`
  ).join("");

  // Метрики которые показываем для каждой ротации в ячейке
  function cellHtml(item, rotId, maxDpu) {
    if (!item) return `<td class="mpv-cell mpv-empty" style="border-left:2px solid ${rotColorMap[rotId]}22" colspan="3"><span class="an-nd">—</span></td>`;
    const dpu = item.dpu || 0;
    const dpuRatio = maxDpu > 0 ? dpu / maxDpu : 0;
    const crStr = item.cr !== null && item.cr !== undefined
      ? `${item.cr}% <span class="mpv-ratio">${item.uniq>0&&item.reg>0?"1:"+Math.round(item.uniq/item.reg):""}</span>` : "—";
    const ftdStr = item.ftd_rate !== null && item.ftd_rate !== undefined
      ? `${item.ftd_rate}% <span class="mpv-ratio">${item.reg>0&&item.fd>0?"1:"+Math.round(item.reg/item.fd):""}</span>` : "—";
    const dpuStr = dpu > 0
      ? `<span class="mpv-dpu" style="color:${rotColorMap[rotId]}">$${dpu.toFixed(2)}</span>
         <div class="an-dpu-bar-wrap"><div class="an-dpu-bar" style="width:${Math.round(dpuRatio*100)}%;background:${rotColorMap[rotId]}"></div></div>`
      : `<span class="an-nd">—</span>`;
    const recCls = {"увеличить вес":"an-rec-up","держать":"an-rec-hold","снизить вес":"an-rec-down","минимальный вес":"an-rec-min","стоп":"an-rec-stop"}[item.rec] || "an-rec-dim";
    return `
      <td class="mpv-cell mpv-cr" style="border-left:2px solid ${rotColorMap[rotId]}55">${crStr}</td>
      <td class="mpv-cell mpv-ftd">${ftdStr}</td>
      <td class="mpv-cell mpv-dpu-col">
        ${dpuStr}
        <div class="mpv-wt">
          <span class="an-weight-val">${item.weight}</span>
          <button class="an-weight-edit-btn" data-offer-id="${item.offerId}" data-rot-id="${rotId}" data-current="${item.weight}" title="Изменить вес">✎</button>
        </div>
        <span class="an-rec ${recCls}" style="font-size:.55rem;padding:1px 5px">${item.rec}</span>
      </td>`;
  }

  const geoBlocks = sortedGeos.map(([geo, offerMap]) => {
    // Глобальный maxDpu для этого GEO по всем ротациям
    const maxDpu = Math.max(...[...offerMap.values()].flatMap(o => Object.values(o.byRot).map(i => i.dpu||0)), 0);

    // Сортируем офферы по max dpu среди ротаций
    const sortedOffers = [...offerMap.values()].sort((a, b) => {
      const maxA = Math.max(...Object.values(a.byRot).map(i => i.dpu||0), 0);
      const maxB = Math.max(...Object.values(b.byRot).map(i => i.dpu||0), 0);
      return maxB - maxA;
    });

    // Заголовок: Оффер | [Uniq] rot1: CR% FTD% DPU | rot2: CR% FTD% DPU ...
    const rotHeaders = rotIds.map(rid =>
      `<th class="mpv-rot-header" colspan="3" style="border-bottom:2px solid ${rotColorMap[rid]};color:${rotColorMap[rid]}">
        ${escapeHtml(rotNames[rid])}
        <div class="mpv-rot-sub">Uniq→Reg &nbsp; Reg→FD &nbsp; DPU / Вес</div>
      </th>`
    ).join("");

    // Итоги
    const totals = {};
    rotIds.forEach(rid => {
      totals[rid] = { uniq:0, reg:0, fd:0 };
      for (const o of offerMap.values()) {
        const item = o.byRot[rid];
        if (item) { totals[rid].uniq += item.uniq||0; totals[rid].reg += item.reg||0; totals[rid].fd += item.fd||0; }
      }
    });
    const totalCells = rotIds.map(rid => {
      const t = totals[rid];
      const cr = t.uniq > 0 ? (t.reg/t.uniq*100).toFixed(1)+"%" : "—";
      const ftd = t.reg > 0 ? (t.fd/t.reg*100).toFixed(1)+"%" : "—";
      return `<td class="mpv-cell mpv-total" colspan="3" style="border-top:1px solid ${rotColorMap[rid]}40">
        <span style="color:#94a3b8">${t.uniq.toLocaleString()} uniq</span>
        <span class="an-cr"> ${cr}</span> · <span class="an-ftd">${ftd}</span>
      </td>`;
    }).join("");

    const offerRows = sortedOffers.map((o) => {
      const lowData = rotIds.some(rid => o.byRot[rid] && o.byRot[rid].uniq > 0 && o.byRot[rid].uniq < 30);
      const uniqCells = rotIds.map(rid => {
        const item = o.byRot[rid];
        return item
          ? `<span class="mpv-uniq" style="color:${rotColorMap[rid]}">${item.uniq.toLocaleString()}${item.uniq<30&&item.uniq>0?' <span class="an-low-data">~</span>':''}</span>`
          : `<span class="an-nd">—</span>`;
      }).join(" / ");

      return `<tr class="an-row mpv-row">
        <td class="an-name mpv-offer-name" title="${escapeHtml(o.offerName)}">
          ${escapeHtml(o.offerName)}
          <div class="mpv-uniq-row">${uniqCells}</div>
        </td>
        ${rotIds.map(rid => cellHtml(o.byRot[rid] ? {...o.byRot[rid], offerId: o.offerId} : null, rid, maxDpu)).join("")}
      </tr>`;
    }).join("");

    const geoPresetBar = Object.entries(presetLabels).map(([val, label]) =>
      `<button class="an-geo-preset-btn ${val === preset ? "active" : ""}"
        data-geo-preset="${val}" data-geo="${escapeHtml(geo)}" data-multi-rot-ids="${rotIds.join(",")}">${label}</button>`
    ).join("");

    return `
      <div class="an-geo-block" data-geo-name="${escapeHtml(geo)}">
        <div class="an-geo-header">
          <div class="an-geo-title">${escapeHtml(geo)}</div>
          <div class="an-geo-preset-bar">${geoPresetBar}</div>
        </div>
        <div class="mpv-scroll">
          <table class="an-table mpv-table">
            <thead>
              <tr>
                <th class="mpv-offer-th">Оффер / Uniq</th>
                ${rotHeaders}
              </tr>
            </thead>
            <tbody>${offerRows}</tbody>
            <tfoot><tr class="an-total-row">
              <td class="an-total-label">Итого</td>
              ${totalCells}
            </tr></tfoot>
          </table>
        </div>
      </div>`;
  }).join("");

  els.cards.innerHTML = `
    <div class="an-preset-bar an-preset-bar--global">${presetBar}</div>
    <div class="an-multi-rot-legend">${legend}</div>
    <div class="an-blocks">${geoBlocks}</div>`;

  els.cards.querySelectorAll(".an-preset-btn[data-multi-rot-ids]").forEach(btn => {
    btn.addEventListener("click", () => loadMultiAnalytics(btn.dataset.multiRotIds.split(","), btn.dataset.preset));
  });

  // Per-geo preset в мульти режиме — перезагружаем только один GEO блок
  els.cards.querySelectorAll(".an-geo-preset-btn[data-multi-rot-ids]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const geo    = btn.dataset.geo;
      const newPreset = btn.dataset.geoPreset;
      const rIds   = btn.dataset.multiRotIds.split(",");
      const geoBlock = btn.closest(".an-geo-block");
      if (!geoBlock) return;

      geoBlock.querySelectorAll(".an-geo-preset-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      const wrap = geoBlock.querySelector(".mpv-scroll");
      if (wrap) wrap.innerHTML = `<div class="an-loading"><span class="an-spinner"></span>Загрузка…</div>`;

      // Загружаем этот GEO по всем ротациям
      const geoResults = await Promise.all(rIds.map(async (id) => {
        try {
          const { r, json } = await fetchJsonSafe(`/api/rotation/${id}/analytics_geo?geo=${encodeURIComponent(geo)}&preset=${newPreset}`);
          return { id, items: json.ok ? (json.items || []) : [] };
        } catch(e) { return { id, items: [] }; }
      }));

      // Перестраиваем offerMap для этого GEO
      const offerMap = new Map();
      for (const { id: rid, items } of geoResults) {
        for (const item of items) {
          if (!offerMap.has(item.offerId)) offerMap.set(item.offerId, { offerId: item.offerId, offerName: item.offerName, byRot: {} });
          offerMap.get(item.offerId).byRot[rid] = item;
        }
      }

      const maxDpu = Math.max(...[...offerMap.values()].flatMap(o => Object.values(o.byRot).map(i => i.dpu||0)), 0);
      const sortedOffers = [...offerMap.values()].sort((a,b) =>
        Math.max(...Object.values(b.byRot).map(i=>i.dpu||0),0) - Math.max(...Object.values(a.byRot).map(i=>i.dpu||0),0)
      );

      // Перерисовываем таблицу — используем те же функции что и при полной загрузке
      const totals = {};
      rIds.forEach(rid => {
        totals[rid] = {uniq:0,reg:0,fd:0};
        for (const o of offerMap.values()) {
          const item = o.byRot[rid];
          if (item) { totals[rid].uniq+=item.uniq||0; totals[rid].reg+=item.reg||0; totals[rid].fd+=item.fd||0; }
        }
      });

      const rotColors = ["#6da0ff","#22d47a","#fbbf24","#f87171","#a78bfa","#34d4c8"];
      const rotColorMap = {};
      rIds.forEach((id,i) => { rotColorMap[id] = rotColors[i % rotColors.length]; });

      const rotHeaders = rIds.map(rid =>
        `<th class="mpv-rot-header" colspan="3" style="border-bottom:2px solid ${rotColorMap[rid]};color:${rotColorMap[rid]}">
          ${escapeHtml(rotNames[rid])}
          <div class="mpv-rot-sub">Uniq→Reg &nbsp; Reg→FD &nbsp; DPU / Вес</div>
        </th>`
      ).join("");

      const totalCells = rIds.map(rid => {
        const t = totals[rid];
        const cr = t.uniq>0 ? (t.reg/t.uniq*100).toFixed(1)+"%" : "—";
        const ftd = t.reg>0 ? (t.fd/t.reg*100).toFixed(1)+"%" : "—";
        return `<td class="mpv-cell mpv-total" colspan="3" style="border-top:1px solid ${rotColorMap[rid]}40">
          <span style="color:#94a3b8">${t.uniq.toLocaleString()} uniq</span>
          <span class="an-cr"> ${cr}</span> · <span class="an-ftd">${ftd}</span>
        </td>`;
      }).join("");

      const offerRows = sortedOffers.map(o => {
        const uniqCells = rIds.map(rid => {
          const item = o.byRot[rid];
          return item ? `<span class="mpv-uniq" style="color:${rotColorMap[rid]}">${item.uniq.toLocaleString()}${item.uniq<30&&item.uniq>0?' <span class="an-low-data">~</span>':''}</span>` : `<span class="an-nd">—</span>`;
        }).join(" / ");
        return `<tr class="an-row mpv-row">
          <td class="an-name mpv-offer-name" title="${escapeHtml(o.offerName)}">${escapeHtml(o.offerName)}<div class="mpv-uniq-row">${uniqCells}</div></td>
          ${rIds.map(rid => cellHtml(o.byRot[rid] ? {...o.byRot[rid], offerId: o.offerId} : null, rid, maxDpu, rotColorMap)).join("")}
        </tr>`;
      }).join("");

      if (wrap) wrap.innerHTML = `<table class="an-table mpv-table">
        <thead><tr><th class="mpv-offer-th">Оффер / Uniq</th>${rotHeaders}</tr></thead>
        <tbody>${offerRows}</tbody>
        <tfoot><tr class="an-total-row"><td class="an-total-label">Итого</td>${totalCells}</tr></tfoot>
      </table>`;
    });
  });
}


// ─── Analytics ───────────────────────────────────────────────────────────────

async function loadRotationAnalytics(id, preset = "last_7_days") {
  els.detailsTitle.textContent = `Rotation #${id} — Analytics`;
  els.detailsSub.textContent   = "CR / FTD Rate / DPU / Рекомендация веса";
  els.detailsMeta.textContent  = "—";
  showCards("analytics");
  if (els.cards) els.cards.innerHTML = `<div class="an-loading"><span class="an-spinner"></span>Загрузка данных…</div>`;

  try {
    const { r, json } = await fetchJsonSafe(`/api/rotation/${encodeURIComponent(id)}/analytics?preset=${preset}`);
    if (!r.ok || !json.ok) throw new Error(json?.error || "failed");
    renderAnalytics(id, json.groups || [], preset);
  } catch(e) {
    if (els.cards) els.cards.innerHTML = `<div class="muted">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

function renderAnalytics(rotId, groups, preset) {
  if (!els.cards) return;

  const totalOffers = groups.reduce((a, g) => a + g.items.length, 0);
  els.detailsMeta.textContent = `${totalOffers} offers`;

  const presetLabels = {
    "today":        "Сегодня",
    "yesterday":    "Вчера",
    "last_7_days":  "7 дней",
    "last_14_days": "14 дней",
    "last_30_days": "30 дней",
  };

  if (!groups.length) {
    els.cards.innerHTML = `<div class="muted" style="padding:20px">Нет данных.</div>`;
    return;
  }

  const geoBlocks = groups.map(g => {
    const maxDpu  = Math.max(...g.items.map(i => i.dpu || 0), 0);
    const maxUniq = Math.max(...g.items.map(i => i.uniq || 0), 1);

    const geoPresetBar = Object.entries(presetLabels).map(([val, label]) =>
      `<button class="an-geo-preset-btn ${val === preset ? "active" : ""}"
        data-geo-preset="${val}" data-geo="${escapeHtml(g.geo)}" data-rot-id="${rotId}">${label}</button>`
    ).join("");

    return `
      <div class="an-geo-block" data-geo-name="${escapeHtml(g.geo)}">
        <div class="an-geo-header">
          <div class="an-geo-title">${escapeHtml(g.geo)}</div>
          <div class="an-geo-preset-bar">${geoPresetBar}</div>
        </div>
        <div class="an-geo-table-wrap">
          ${renderGeoTable(g.items, maxDpu, maxUniq, rotId)}
        </div>
      </div>`;
  }).join("");

  els.cards.innerHTML = `<div class="an-blocks">${geoBlocks}</div>`;

  // Per-geo preset switcher
  els.cards.querySelectorAll(".an-geo-preset-btn").forEach(btn => {
    btn.addEventListener("click", () => reloadGeoAnalytics(btn));
  });
}

function renderGeoTable(items, maxDpu, maxUniq, rotId = "") {
  // Итоги по GEO
  const total = {
    uniq: items.reduce((s, i) => s + (i.uniq || 0), 0),
    reg:  items.reduce((s, i) => s + (i.reg  || 0), 0),
    fd:   items.reduce((s, i) => s + (i.fd   || 0), 0),
  };
  total.cr    = total.uniq > 0 ? (total.reg / total.uniq * 100).toFixed(1) : null;
  total.ftd_r = total.reg  > 0 ? (total.fd  / total.reg  * 100).toFixed(1) : null;

  const rows = items.map((item, idx) => {
    const hasData  = item.uniq > 0;
    const lowData  = item.uniq > 0 && item.uniq < 30;
    const dpuRatio = maxDpu > 0 ? (item.dpu || 0) / maxDpu : 0;

    const rowCls = !hasData ? "an-row-dim"
                 : idx === 0 && dpuRatio >= 0.85 ? "an-row-best"
                 : dpuRatio < 0.3 && hasData && item.dpu > 0 ? "an-row-worst" : "";

    const recCls = {
      "увеличить вес":   "an-rec-up",
      "держать":         "an-rec-hold",
      "снизить вес":     "an-rec-down",
      "минимальный вес": "an-rec-min",
    }[item.rec] || "an-rec-dim";

    const bar = (val, max, cls) => {
      const pct = max > 0 ? Math.round(val / max * 100) : 0;
      return `<div class="an-bar-wrap"><div class="an-bar ${cls}" style="width:${pct}%"></div></div>`;
    };

    const fmt = (v, suffix="") => v !== null && v !== undefined ? `${v}${suffix}` : `<span class="an-nd">—</span>`;

    return `
      <tr class="an-row ${rowCls}" data-offer-id="${item.offerId}">
        <td class="an-name" title="${escapeHtml(item.offerName)}">${escapeHtml(item.offerName)}</td>
        <td class="an-num">
          ${bar(item.uniq, maxUniq, "an-bar-uniq")}
          <span>${item.uniq.toLocaleString()}${lowData ? ' <span class="an-low-data" title="Мало данных">~</span>' : ''}</span>
        </td>
        <td class="an-num">${fmt(item.reg)}</td>
        <td class="an-num an-cr">
          ${item.cr !== null && item.cr !== undefined
            ? `<span class="an-conv-pct">${item.cr}%</span><span class="an-conv-ratio">${item.uniq > 0 && item.reg > 0 ? "1:" + Math.round(item.uniq / item.reg) : "—"}</span>`
            : `<span class="an-nd">—</span>`}
        </td>
        <td class="an-num">${fmt(item.fd)}</td>
        <td class="an-num an-ftd">
          ${item.ftd_rate !== null && item.ftd_rate !== undefined
            ? `<span class="an-conv-pct">${item.ftd_rate}%</span><span class="an-conv-ratio">${item.reg > 0 && item.fd > 0 ? "1:" + Math.round(item.reg / item.fd) : "—"}</span>`
            : `<span class="an-nd">—</span>`}
        </td>
        <td class="an-num an-dpu">
          ${item.dpu ? `$${item.dpu.toFixed(2)}` : `<span class="an-nd">—</span>`}
          ${hasData && maxDpu > 0 ? `<div class="an-dpu-bar-wrap"><div class="an-dpu-bar" style="width:${Math.round(dpuRatio*100)}%"></div></div>` : ""}
        </td>
        <td class="an-num an-weight-cell">
          <span class="an-weight-val">${item.weight}</span>
          <button class="an-weight-edit-btn" data-offer-id="${item.offerId}" data-rot-id="${rotId}" data-current="${item.weight}" title="Изменить вес">✎</button>
          ${item.ideal_weight !== undefined && item.ideal_weight !== item.weight
            ? `<span class="an-ideal-wt" title="Идеальный вес">→${item.ideal_weight}</span>` : ""}
        </td>
        <td><span class="an-rec ${recCls}">${item.rec}</span></td>
      </tr>`;
  }).join("");

  return `
    <table class="an-table">
      <thead>
        <tr>
          <th>Оффер</th>
          <th class="an-num">Uniq</th>
          <th class="an-num">Reg</th>
          <th class="an-num">Uniq→Reg</th>
          <th class="an-num">FD</th>
          <th class="an-num">Reg→FD</th>
          <th class="an-num">DPU</th>
          <th class="an-num">Вес</th>
          <th>Рекомендация</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr class="an-total-row">
          <td class="an-total-label">Итого по GEO</td>
          <td class="an-num an-total-val">${total.uniq.toLocaleString()}</td>
          <td class="an-num an-total-val">${total.reg.toLocaleString()}</td>
          <td class="an-num an-total-cr">
            ${total.cr !== null
              ? `<span class="an-conv-pct">${total.cr}%</span><span class="an-conv-ratio">${total.uniq > 0 && total.reg > 0 ? "1:" + Math.round(total.uniq / total.reg) : ""}</span>`
              : "—"}
          </td>
          <td class="an-num an-total-val">${total.fd.toLocaleString()}</td>
          <td class="an-num an-total-ftd">
            ${total.ftd_r !== null
              ? `<span class="an-conv-pct">${total.ftd_r}%</span><span class="an-conv-ratio">${total.reg > 0 && total.fd > 0 ? "1:" + Math.round(total.reg / total.fd) : ""}</span>`
              : "—"}
          </td>
          <td colspan="3"></td>
        </tr>
      </tfoot>
    </table>`;
}

// Weight edit handler — делегирование на .an-blocks
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".an-weight-edit-btn");
  if (!btn) return;

  // В single analytics кнопка внутри .an-weight-cell
  // В multi analytics кнопка внутри .mpv-wt внутри .mpv-dpu-col
  let cell = btn.closest(".an-weight-cell");
  let isMpv = false;
  if (!cell) {
    cell = btn.closest(".mpv-dpu-col");
    isMpv = true;
  }
  if (!cell) return;

  const offerId = btn.dataset.offerId;
  const rotId   = btn.dataset.rotId;
  const current = parseFloat(btn.dataset.current) || 0;

  // Сохраняем оригинальный контент чтобы восстановить
  const originalHtml = cell.innerHTML;

  // Рендерим input поверх
  const inputWrap = document.createElement("div");
  inputWrap.className = "an-weight-input-wrap";
  inputWrap.innerHTML = `
    <input class="an-weight-input" type="number" min="0" step="1" value="${current}" />
    <button class="an-weight-save" title="Сохранить">✓</button>
    <button class="an-weight-cancel" title="Отмена">✕</button>`;

  if (isMpv) {
    // В mpv заменяем только mpv-wt
    const wt = btn.closest(".mpv-wt");
    if (wt) { wt.replaceWith(inputWrap); }
  } else {
    cell.innerHTML = "";
    cell.appendChild(inputWrap);
  }

  const input = cell.querySelector(".an-weight-input") || inputWrap.querySelector(".an-weight-input");
  input?.focus(); input?.select();

  const restore = () => {
    cell.innerHTML = originalHtml;
  };

  cell.querySelector(".an-weight-cancel")?.addEventListener("click", restore);

  const doSave = async () => {
    const inp = cell.querySelector(".an-weight-input");
    const newWeight = parseFloat(inp?.value);
    if (isNaN(newWeight) || newWeight < 0) { restore(); return; }

    cell.innerHTML = `<span class="an-weight-saving">…</span>`;
    try {
      const { r, json } = await fetchJsonSafe(
        `/api/rotation/${rotId}/offer_weight`,
        { method: "PATCH", body: JSON.stringify({ offer_id: offerId, weight: newWeight }) }
      );
      if (json?.ok) {
        const newHtml = `
          <span class="an-weight-val an-weight-updated">${newWeight}</span>
          <button class="an-weight-edit-btn" data-offer-id="${offerId}" data-rot-id="${rotId}" data-current="${newWeight}" title="Изменить вес">✎</button>`;
        if (isMpv) {
          cell.innerHTML = `<span class="mpv-dpu" style="${cell.querySelector?.('.mpv-dpu')?.getAttribute('style')||''}">
            ${cell.textContent.includes('$') ? cell.innerHTML.split('<div class="mpv-wt">')[0] : ''}
          </span>
          <div class="mpv-wt">${newHtml}</div>`;
          // Проще — просто обновляем вес в mpv-wt
          cell.innerHTML = originalHtml.replace(
            /data-current="[\d.]+"/, `data-current="${newWeight}"`
          ).replace(
            /<span class="an-weight-val">[\d.]+<\/span>/,
            `<span class="an-weight-val an-weight-updated">${newWeight}</span>`
          );
        } else {
          cell.innerHTML = newHtml;
        }
        setTimeout(() => cell.querySelector(".an-weight-val")?.classList.remove("an-weight-updated"), 2000);
      } else {
        alert("Ошибка: " + (json?.error || "unknown"));
        restore();
      }
    } catch(err) {
      alert("Ошибка сети");
      restore();
    }
  };

  cell.querySelector(".an-weight-save")?.addEventListener("click", doSave);
  cell.querySelector(".an-weight-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSave();
    if (e.key === "Escape") restore();
  });
});

async function reloadGeoAnalytics(btn) {
  const geo    = btn.dataset.geo;
  const preset = btn.dataset.geoPreset;
  const rotId  = btn.dataset.rotId;

  const geoBlock = btn.closest(".an-geo-block");
  if (!geoBlock) return;

  // Отмечаем активную кнопку
  geoBlock.querySelectorAll(".an-geo-preset-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");

  const tableWrap = geoBlock.querySelector(".an-geo-table-wrap");
  if (tableWrap) tableWrap.innerHTML = `<div class="an-loading"><span class="an-spinner"></span>Загрузка…</div>`;

  try {
    const url = `/api/rotation/${rotId}/analytics_geo?geo=${encodeURIComponent(geo)}&preset=${preset}`;
    const { r, json } = await fetchJsonSafe(url);
    if (!r.ok || !json.ok) throw new Error(json?.error || "failed");

    const items   = json.items || [];
    const maxDpu  = Math.max(...items.map(i => i.dpu || 0), 0);
    const maxUniq = Math.max(...items.map(i => i.uniq || 0), 1);
    if (tableWrap) tableWrap.innerHTML = renderGeoTable(items, maxDpu, maxUniq, rotId);
  } catch(e) {
    if (tableWrap) tableWrap.innerHTML = `<div class="muted" style="padding:12px">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}

// ─── Load functions ───────────────────────────────────────────────────────────

async function loadRotations() {
  setLoading();
  hideOfferSearch();

  const params = new URLSearchParams();
  const q = els.q.value.trim();
  const status = els.status.value.trim();
  const perPage = els.perPage.value.trim();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (perPage) params.set("per_page", perPage);

  try {
    const { r, json } = await fetchJsonSafe(`/api/rotations?${params}`);
    if (!r.ok || !json.ok) throw new Error(json?.details || JSON.stringify(json));

    els.serverTime.textContent = `Server (MSK): ${json.server_time_local || "—"}`;
    const items = extractRotationArray(json);
    els.countPill.textContent = `Rotations: ${items.length}`;

    if (!items.length) {
      els.rows.innerHTML = `<tr><td colspan="5" class="muted">Пусто.</td></tr>`;
      return;
    }

    selectedRotationIds.clear();
    _updateMultiAnalyticsBtn();

    els.rows.innerHTML = items.map((it) => {
      const id = it.id ?? it.rotation_id ?? "—";
      const name = it.name ?? it.title ?? `Rotation #${id}`;
      const statusText = it.status ?? it.state ?? "—";
      return `
        <tr data-rot-row="${escapeHtml(id)}">
          <td>
            <label class="rot-checkbox-wrap" title="Выбрать для сравнения">
              <input type="checkbox" class="rot-checkbox" data-rot-id="${escapeHtml(id)}" data-rot-name="${escapeHtml(name)}">
            </label>
          </td>
          <td>${escapeHtml(id)}</td>
          <td><span class="link" data-open="${escapeHtml(id)}">${escapeHtml(name)}</span></td>
          <td>${badgeFor(statusText)}</td>
          <td style="display:flex; gap:6px; flex-wrap:wrap;">
            <button class="btn" data-action="json" data-id="${escapeHtml(id)}">JSON</button>
            <button class="btn primary" data-action="rules" data-id="${escapeHtml(id)}">Rules</button>
            <button class="btn analytics-btn" data-action="analytics" data-id="${escapeHtml(id)}">📊</button>
          </td>
        </tr>
      `;
    }).join("");

    // Checkbox listener
    els.rows.querySelectorAll(".rot-checkbox").forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) selectedRotationIds.add(cb.dataset.rotId);
        else selectedRotationIds.delete(cb.dataset.rotId);
        _updateMultiAnalyticsBtn();
      });
    });

  } catch (e) {
    setError(e.message || "unknown");
  }
}

async function loadRotationDetails(id) {
  els.detailsTitle.textContent = `Rotation #${id} — JSON`;
  els.detailsSub.textContent = "Сырой ответ /api/rotation/<id>";
  els.detailsMeta.textContent = "—";
  showJson();
  els.detailsJson.textContent = "Загрузка...";
  try {
    const { r, json } = await fetchJsonSafe(`/api/rotation/${encodeURIComponent(id)}`);
    if (!r.ok || !json.ok) throw new Error(json?.details || "failed");
    els.detailsJson.textContent = JSON.stringify(json.data, null, 2);
  } catch (e) {
    els.detailsJson.textContent = `Ошибка: ${e.message || "unknown"}`;
  }
}

async function loadRotationActiveOffers(id) {
  currentRotationId = id;
  els.detailsTitle.textContent = `Rotation #${id} — GEO → Offers`;
  els.detailsSub.textContent = "Группировка по Rule name. Только weight > 0.";
  els.detailsMeta.textContent = "—";
  showCards("accordion");
  if (els.cards) els.cards.innerHTML = "Загрузка...";
  try {
    const { r, json } = await fetchJsonSafe(`/api/rotation/${encodeURIComponent(id)}/active_offers_grouped`);
    if (!r.ok || !json.ok) throw new Error(json?.details || "failed");
    renderGeoAccordion(json.groups || [], false);
  } catch (e) {
    if (els.cards) els.cards.innerHTML = `<div class="muted">Ошибка: ${escapeHtml(e.message || "unknown")}</div>`;
  }
}

// ─── DPU per GEO ──────────────────────────────────────────────────────────────

async function loadGeoDpu(rotationId, geoTitle, geoBlock) {
  // Находим все offer-row в этом GEO
  const offerRows = geoBlock.querySelectorAll(".offer-row");

  // Показываем лоадер в каждой строке
  offerRows.forEach(row => {
    let dpuEl = row.querySelector(".dpu-badge");
    if (!dpuEl) {
      dpuEl = document.createElement("div");
      dpuEl.className = "dpu-badge dpu-zero";
      const right = row.querySelector(".offer-right");
      if (right) right.prepend(dpuEl);
    }
    dpuEl.innerHTML = `<span class="dpu-val">...</span><span class="dpu-period"></span>`;
    dpuEl.className = "dpu-badge dpu-zero";
  });

  try {
    const url = `/api/rotation/${rotationId}/dpu_geo?geo=${encodeURIComponent(geoTitle)}`;
    const { r, json } = await fetchJsonSafe(url);
    if (!r.ok || !json.ok) throw new Error(json?.error || "failed");

    // Обновляем каждую строку по offerName (или offerId)
    const itemMap = {};
    (json.items || []).forEach(it => {
      itemMap[String(it.offerId)] = it;
      itemMap[it.offerName] = it;
    });

    offerRows.forEach(row => {
      const nameEl = row.querySelector(".offer-name");
      const name   = (nameEl?.dataset?.original || nameEl?.textContent || "").trim();

      // ищем совпадение по имени
      let item = null;
      for (const [k, v] of Object.entries(itemMap)) {
        if (k === name || name.startsWith(k) || k.startsWith(name)) {
          item = v; break;
        }
      }
      if (!item) return;

      let dpuEl = row.querySelector(".dpu-badge");
      if (!dpuEl) {
        dpuEl = document.createElement("div");
        const right = row.querySelector(".offer-right");
        if (right) right.prepend(dpuEl);
      }

      // Рендерим badge
      const dpu    = parseFloat(item.dpu) || 0;
      const period = item.dpu_period || "—";
      const note   = item.dpu_note;

      let cls = "dpu-zero";
      if (note === "insufficient_data" || note === "no_data") cls = "dpu-nodata";
      else if (dpu > 0.3)  cls = "dpu-high";
      else if (dpu > 0.1)  cls = "dpu-mid";
      else if (dpu > 0)    cls = "dpu-low";

      const label = (note === "insufficient_data" || note === "no_data")
        ? `<span class="dpu-val">n/a</span>`
        : `<span class="dpu-val">$${dpu.toFixed(3)}</span>`;

      dpuEl.className = `dpu-badge ${cls}`;
      dpuEl.title     = `Уников: ${item.dpu_uniq || 0}`;
      dpuEl.innerHTML = `${label}<span class="dpu-period">${escapeHtml(period)}</span>`;
    });

  } catch (e) {
    offerRows.forEach(row => {
      const dpuEl = row.querySelector(".dpu-badge");
      if (dpuEl) {
        dpuEl.className = "dpu-badge dpu-nodata";
        dpuEl.innerHTML = `<span class="dpu-val">err</span>`;
      }
    });
  }
}

// ─── Events ───────────────────────────────────────────────────────────────────

if (els.offerSearch) {
  els.offerSearch.addEventListener("input", (e) => applyOfferSearch(e.target.value));
  els.offerSearch.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { els.offerSearch.value = ""; applyOfferSearch(""); }
  });
}

document.addEventListener("click", (e) => {
  // Кнопка копирования карточки Weekly
  const copyBtn = e.target.closest(".wcopy-btn");
  if (copyBtn) {
    e.stopPropagation();
    const idx = parseInt(copyBtn.dataset.rotIdx);
    // Находим данные ротации из последнего результата
    const cards = document.querySelectorAll(".wcard");
    const card  = cards[idx];
    if (!card) return;

    const title    = card.querySelector(".wcard-title")?.textContent?.trim() || "";
    const rows     = card.querySelectorAll(".wrow");
    const lines    = [`${title}:`];
    rows.forEach(row => {
      const country  = row.querySelector(".wrow-country")?.textContent?.trim() || "";
      const uniqStr  = row.querySelector(".wrow-uniq")?.textContent?.replace(/[^0-9]/g,"") || "0";
      const uniq     = parseInt(uniqStr) || 0;
      const r        = roundUniq(uniq);
      const tagEl    = row.querySelector(".wrow-tag");
      const hasTag   = tagEl && tagEl.classList.contains("active");
      const tagText  = hasTag ? " (Нужен оффер)" : "";
      lines.push(`${country} - более ${r.toLocaleString("ru-RU")} уников в неделю${tagText}`);
    });

    const text = lines.join("\n");
    navigator.clipboard.writeText(text).then(() => {
      copyBtn.textContent = "✓ Скопировано";
      copyBtn.classList.add("wcopy-done");
      setTimeout(() => {
        copyBtn.textContent = "⎘ Копировать";
        copyBtn.classList.remove("wcopy-done");
      }, 2000);
    }).catch(() => {
      // fallback
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      copyBtn.textContent = "✓ Скопировано";
      setTimeout(() => { copyBtn.textContent = "⎘ Копировать"; }, 2000);
    });
    return;
  }

  // Тег "Готовы" — toggle
  const tagEl = e.target.closest(".wrow-tag");
  if (tagEl) {
    tagEl.style.opacity = "0";
    tagEl.style.pointerEvents = "none";
    return;
  }

  // Кнопка $Unic — не пропускать клик дальше (не открывать/закрывать accordion)
  const dpuBtn = e.target.closest("[data-dpu-geo]");
  if (dpuBtn) {
    e.stopPropagation();
    const geoTitle  = dpuBtn.dataset.dpuGeo;
    const geoBlock  = dpuBtn.closest("[data-geo]");
    const rotationId = dpuBtn.dataset.rotationId || currentRotationId;
    if (!rotationId || !geoTitle || !geoBlock) return;

    dpuBtn.textContent = "...";
    dpuBtn.disabled    = true;

    loadGeoDpu(rotationId, geoTitle, geoBlock).finally(() => {
      dpuBtn.textContent = "$Unic";
      dpuBtn.disabled    = false;
    });
    return;
  }

  const head = e.target.closest("[data-geo-head]");
  if (!head) return;
  const box = head.closest("[data-geo]");
  if (box) box.classList.toggle("open");
});

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action], [data-open]");
  if (!el) return;

  const openId = el.getAttribute("data-open");
  if (openId) { loadRotationDetails(openId); return; }

  const action = el.getAttribute("data-action");
  const id = el.getAttribute("data-id");
  if (!id) return;

  if (action === "json")      loadRotationDetails(id);
  if (action === "rules")     loadRotationActiveOffers(id);
  if (action === "analytics") loadRotationAnalytics(id);
});

els.btnRefresh.addEventListener("click", loadRotations);
els.btnApply.addEventListener("click", loadRotations);
els.q.addEventListener("keydown", (e) => { if (e.key === "Enter") loadRotations(); });

// ─── Weekly Uniques ──────────────────────────────────────────────────────────

function initWeeklyUniques() {
  // Создаём панель если её нет
  if (document.getElementById("weeklyPanel")) return;

  const panel = document.createElement("div");
  panel.id = "weeklyPanel";
  panel.className = "weekly-panel";
  panel.innerHTML = `
    <div class="weekly-header">
      <span class="weekly-title">📊 Weekly Uniques</span>
      <div class="weekly-controls">
        <label>С <input type="date" id="wDateFrom" class="date-inp"></label>
        <label>По <input type="date" id="wDateTo" class="date-inp"></label>
        <label>Мин. уников <input type="number" id="wMinUniq" value="100" min="1" class="num-inp"></label>
        <button class="btn primary" id="wRunBtn">Запустить</button>
        <button class="btn" id="wCloseBtn">✕</button>
      </div>
    </div>
    <div id="weeklyResult" class="weekly-result"></div>
  `;
  document.body.appendChild(panel);

  // Заполняем даты по умолчанию (Ср прошлой нед → Вт этой нед)
  const { from, to } = getDefaultWeekRange();
  document.getElementById("wDateFrom").value = from;
  document.getElementById("wDateTo").value   = to;

  document.getElementById("wRunBtn").addEventListener("click", runWeeklyReport);
  document.getElementById("wCloseBtn").addEventListener("click", () => {
    panel.style.display = "none";
  });
}


// Группы ротаций — загружаем из localStorage или дефолт
const DEFAULT_MERGE_GROUPS = [
  { label: "Casino / Fortune Tiger", rotations: ["casino", "fortune tiger"] },
  { label: "Betting",                rotations: ["betting", "betano"] },
  { label: "Crash / Plinko",         rotations: ["crash", "plinko"] },
];

function loadMergeGroups() {
  try {
    const saved = localStorage.getItem("rotation_merge_groups");
    if (saved) return JSON.parse(saved);
  } catch(e) {}
  return DEFAULT_MERGE_GROUPS.map(g => ({ ...g, rotations: [...g.rotations] }));
}

function saveMergeGroups(groups) {
  try { localStorage.setItem("rotation_merge_groups", JSON.stringify(groups)); } catch(e) {}
}

let ROTATION_MERGE_GROUPS = loadMergeGroups();

function findMergeGroup(rotationName) {
  const lower = rotationName.toLowerCase();
  for (const group of ROTATION_MERGE_GROUPS) {
    if (group.rotations.some(k => lower.includes(k))) return group.label;
  }
  return null;
}

function mergeRotations(rotations, minUniq = 100) {
  const mergedMap = {};
  const standalone = [];

  for (const rot of rotations) {
    const groupLabel = findMergeGroup(rot.rotationName);
    if (groupLabel) {
      if (!mergedMap[groupLabel]) {
        mergedMap[groupLabel] = { rotationName: groupLabel, rotationId: "", isMerged: true, sourceNames: [], countries: new Map() };
      }
      const g = mergedMap[groupLabel];
      g.sourceNames.push(rot.rotationName);
      for (const c of rot.countries) {
        g.countries.set(c.country, (g.countries.get(c.country) || 0) + c.uniq);
      }
    } else {
      standalone.push({ ...rot, countries: rot.countries.filter(c => c.uniq >= minUniq) });
    }
  }

  const merged = Object.values(mergedMap).map(g => ({
    rotationName: g.rotationName,
    rotationId:   g.sourceNames.join(" + "),
    isMerged:     true,
    countries:    Array.from(g.countries.entries())
      .map(([country, uniq]) => ({ country, uniq }))
      .filter(c => c.uniq >= minUniq)
      .sort((a, b) => b.uniq - a.uniq),
  }));

  return [...merged, ...standalone.filter(r => r.countries.length > 0)];
}

async function runWeeklyReport() {
  const dateFrom = document.getElementById("wDateFrom").value;
  const dateTo   = document.getElementById("wDateTo").value;
  const minUniq  = parseInt(document.getElementById("wMinUniq").value) || 100;
  const result   = document.getElementById("weeklyResult");

  if (!dateFrom || !dateTo) {
    result.innerHTML = `<div class="muted">Укажите даты</div>`;
    return;
  }

  document.getElementById("wRunBtn").disabled = true;
  document.getElementById("wRunBtn").textContent = "...";
  result.innerHTML = `<div class="muted">Загружаем данные Binom…</div>`;

  try {
    // Запрашиваем с min_uniq=1 — фильтрацию делаем сами после слияния
    const url = `/api/report/weekly_uniques?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&min_uniq=1`;
    const { r, json } = await fetchJsonSafe(url);
    if (!r.ok || !json.ok) throw new Error(json?.error || "failed");

    const rotations = mergeRotations(json.rotations || [], minUniq);

    if (!rotations.length) {
      result.innerHTML = `<div class="muted">Нет данных за ${fmtDate(dateFrom)} — ${fmtDate(dateTo)} с униками ≥ ${minUniq}</div>`;
      return;
    }

    // Общее кол-во стран
    const totalCountries = rotations.reduce((s, r) => s + r.countries.length, 0);

    // Находим максимум уников для визуального бара
    const globalMax = Math.max(...rotations.flatMap(r => r.countries.map(c => c.uniq)));

    result.innerHTML = `
      <div class="weekly-meta">
        <span>📅 <b>${fmtDate(dateFrom)} — ${fmtDate(dateTo)}</b></span>
        <span class="wmeta-sep">|</span>
        <span>Порог: <b>≥ ${minUniq}</b></span>
        <span class="wmeta-sep">|</span>
        <span>Ротаций: <b>${rotations.length}</b></span>
        <span class="wmeta-sep">|</span>
        <span>GEO: <b>${totalCountries}</b></span>
      </div>
      <div class="weekly-cards">
        ${rotations.map(rot => {
          const topUniq = rot.countries[0]?.uniq || 0;
          return `
            <div class="wcard">
              <div class="wcard-header">
                <div class="wcard-header-left">
                  <div class="wcard-title">${escapeHtml(rot.rotationName)}</div>
                  <div class="wcard-badge">${rot.countries.length} GEO</div>
                </div>
                <button class="wcopy-btn" data-rot-idx="${rotations.indexOf(rot)}" title="Копировать">⎘ Копировать</button>
              </div>
              <div class="wcard-rows">
                ${rot.countries.map((c, i) => {
                  const pct = globalMax > 0 ? (c.uniq / globalMax * 100).toFixed(1) : 0;
                  const isTop = i === 0;
                  return `
                    <div class="wrow ${isTop ? "wrow-top" : ""} ${c.needsOffer ? "wrow-needs-offer" : ""}">
                      <div class="wrow-rank">${i + 1}</div>
                      <div class="wrow-country">${escapeHtml(c.country)}</div>
                      <div class="wrow-bar-wrap">
                        <div class="wrow-bar" style="width:${pct}%"></div>
                      </div>
                      <div class="wrow-uniq">${c.uniq.toLocaleString()}</div>
                      ${c.needsOffer
                        ? `<div class="wrow-tag wrow-tag--alert active" title="Офферов без RS: ${c.offerCount ?? 0} из 3">⚠ Нужен Оффер (${c.offerCount ?? 0}/3)</div>`
                        : `<div class="wrow-tag active" title="Нажми чтобы убрать">Нужен Оффер</div>`
                      }
                    </div>
                  `;
                }).join("")}
              </div>
            </div>
          `;
        }).join("")}
      </div>
    `;

  } catch(e) {
    result.innerHTML = `<div class="muted">Ошибка: ${escapeHtml(e.message)}</div>`;
  } finally {
    document.getElementById("wRunBtn").disabled  = false;
    document.getElementById("wRunBtn").textContent = "Запустить";
  }
}

// Кнопка открытия Weekly Uniques — добавим в шапку
(function injectWeeklyBtn() {
  const toolbar = document.querySelector(".toolbar") || document.querySelector("header") || document.body;
  const btn = document.createElement("button");
  btn.className = "btn weekly-open-btn";
  btn.textContent = "📊 Weekly Uniques";
  btn.addEventListener("click", () => {
    initWeeklyUniques();
    const panel = document.getElementById("weeklyPanel");
    if (panel) panel.style.display = panel.style.display === "none" ? "flex" : "flex";
  });
  // Попробуем найти подходящее место
  const filterRow = document.querySelector(".filter-row") || document.querySelector(".controls");
  if (filterRow) filterRow.appendChild(btn);
  else document.body.insertBefore(btn, document.body.firstChild);
})();

loadRotations();

// Двойной клик по $perUniq — сброс и пересчёт
// Обновляет только Filled / Remain ячейки в DOM без перерисовки панели
function _applyFdToCells(caps) {
  for (const [offId, data] of Object.entries(caps)) {
    const row = document.querySelector(`tr[data-offer-id="${offId}"]`);
    if (!row) continue;
    const filled    = data.filled_cap !== null && data.filled_cap !== undefined ? data.filled_cap : "—";
    const remain    = data.cap === null ? "∞"
                    : (data.filled_cap !== null && data.filled_cap !== undefined)
                      ? data.cap - data.filled_cap : "—";
    const remainCls = typeof remain === "number" && remain <= 0 ? "op-full" : "op-remain";

    const cells = row.querySelectorAll("td");
    // Filled = 6-я колонка (index 5), Remain = 7-я (index 6)
    if (cells[5]) cells[5].textContent = typeof filled === "number" ? filled.toLocaleString() : filled;
    if (cells[6]) {
      cells[6].textContent  = typeof remain === "number" ? remain.toLocaleString() : remain;
      cells[6].className    = "num " + remainCls;
    }
  }
}

// Обновляет ячейку $perUniq по offer_id без перерисовки всей панели
function _applyDpuToCell(offerId, dpu, period, note) {
  const cell = document.querySelector(`.op-dpu-cell[data-offer-id="${offerId}"]`);
  if (!cell) return;
  const age = "сегодня";
  if (dpu !== null && dpu !== undefined) {
    cell.innerHTML = `$${parseFloat(dpu).toFixed(2)} <span class="op-dpu-period">${period || ""}</span><span class="op-dpu-age">${age}</span>`;
    cell.style.color = "";
  } else if (note === "insufficient_data") {
    cell.innerHTML = `<span class="op-dpu-low" title="Мало данных (< 80 уников)">мало данных</span><span class="op-dpu-age"> ${age}</span>`;
    cell.style.color = "";
  } else {
    cell.innerHTML = `<span class="op-dpu-none">—</span>`;
    cell.style.color = "";
  }
}

document.addEventListener("dblclick", async (e) => {
  const cell = e.target.closest(".op-dpu-cell");
  if (!cell || cell.dataset.loading) return;

  cell.dataset.loading = "1";
  const prev = cell.innerHTML;
  cell.innerHTML = `<span class="op-dpu-spinner">⟳</span> пересчёт…`;
  cell.style.color = "#94a3b8";

  try {
    const { r, json } = await fetchJsonSafe(
      `/api/panel/offer/${cell.dataset.offerId}/recalc_dpu`,
      { method: "POST" }
    );
    if (json?.ok) {
      // Обновляем ячейку сразу из ответа
      _applyDpuToCell(cell.dataset.offerId, json.dpu, json.period, json.note);
      // Синхронизируем panelData в памяти
      for (const rot of panelData.rotations)
        for (const geo of rot.geos)
          for (const off of geo.offers)
            if (off.id === cell.dataset.offerId) {
              off.dpu = json.dpu; off.dpu_period = json.period;
              off.dpu_note = json.note; off.dpu_updated_at = new Date().toISOString();
            }
    } else {
      cell.innerHTML = prev;
      cell.style.color = "";
    }
  } catch(e) {
    cell.innerHTML = prev;
    cell.style.color = "";
  } finally {
    delete cell.dataset.loading;
  }
});

// ─── CAP Report ──────────────────────────────────────────────────────────────

function initCapReport() {
  if (document.getElementById("capPanel")) return;

  const panel = document.createElement("div");
  panel.id = "capPanel";
  panel.className = "weekly-panel";
  panel.innerHTML = `
    <div class="weekly-header">
      <span class="weekly-title">🎯 CAP Report (FD)</span>
      <div class="weekly-controls">
        <label>С <input type="date" id="capDateFrom" class="date-inp"></label>
        <label>По <input type="date" id="capDateTo" class="date-inp"></label>
        <input type="text" id="capSearch" class="date-inp" placeholder="Поиск по офферу / сети..." style="width:220px">
        <button class="btn primary" id="capRunBtn">Запустить</button>
        <button class="btn" id="capCloseBtn">✕</button>
      </div>
    </div>
    <div id="capResult" class="weekly-result"></div>
  `;
  document.body.appendChild(panel);

  const { from, to } = getDefaultWeekRange();
  document.getElementById("capDateFrom").value = from;
  document.getElementById("capDateTo").value   = to;

  document.getElementById("capRunBtn").addEventListener("click", runCapReport);
  document.getElementById("capCloseBtn").addEventListener("click", () => {
    panel.style.display = "none";
  });
  document.getElementById("capSearch").addEventListener("input", filterCapCards);
}

let capData = [];

async function runCapReport() {
  const dateFrom = document.getElementById("capDateFrom").value;
  const dateTo   = document.getElementById("capDateTo").value;
  const result   = document.getElementById("capResult");

  if (!dateFrom || !dateTo) {
    result.innerHTML = `<div class="muted">Укажите даты</div>`;
    return;
  }

  document.getElementById("capRunBtn").disabled    = true;
  document.getElementById("capRunBtn").textContent = "...";
  result.innerHTML = `<div class="muted">Загружаем данные Binom…</div>`;

  try {
    const url = `/api/report/cap?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`;
    const { r, json } = await fetchJsonSafe(url);
    if (!r.ok || !json.ok) throw new Error(json?.error || "failed");

    capData = json.offers || [];
    renderCapCards(capData, json);

  } catch(e) {
    result.innerHTML = `<div class="muted">Ошибка: ${escapeHtml(e.message)}</div>`;
  } finally {
    document.getElementById("capRunBtn").disabled    = false;
    document.getElementById("capRunBtn").textContent = "Запустить";
  }
}

function filterCapCards() {
  const q = (document.getElementById("capSearch")?.value || "").toLowerCase();
  const filtered = q
    ? capData.filter(o =>
        o.offerName.toLowerCase().includes(q) ||
        o.network.toLowerCase().includes(q))
    : capData;
  renderCapCards(filtered, null);
}

function renderCapCards(offers, json) {
  const result = document.getElementById("capResult");
  if (!offers.length) {
    result.innerHTML = `<div class="muted">Нет данных</div>`;
    return;
  }

  const totalFd = offers.reduce((s, o) => s + o.fd, 0);

  result.innerHTML = `
    <div class="weekly-meta">
      ${json ? `<span>📅 <b>${fmtDate(json.date_from)} — ${fmtDate(json.date_to)}</b></span><span class="wmeta-sep">|</span>` : ""}
      <span>Офферов: <b>${offers.length}</b></span>
      <span class="wmeta-sep">|</span>
      <span>Всего FD: <b>${totalFd.toLocaleString()}</b></span>
    </div>
    <div class="cap-cards">
      ${offers.map(offer => `
        <div class="cap-card" data-offer-id="${escapeHtml(offer.offerId)}">
          <div class="cap-card-header">
            <div class="cap-card-left">
              <div class="cap-offer-name">${escapeHtml(offer.offerName)}</div>
              <div class="cap-offer-meta">
                ${offer.network ? `<span class="cap-network">${escapeHtml(offer.network)}</span>` : ""}
                <span class="cap-offer-id">#${escapeHtml(offer.offerId)}</span>
              </div>
            </div>
            <div class="cap-fd-total">${offer.fd.toLocaleString()} <span class="cap-fd-label">FD</span></div>
          </div>
          <div class="cap-rotations">
            ${offer.rotations.map(rot => `
              <div class="cap-rotation">
                <div class="cap-rot-header">
                  <span class="cap-rot-name">${escapeHtml(rot.rotationName)}</span>
                  <span class="cap-rot-fd">${rot.fd.toLocaleString()} FD</span>
                </div>
                <div class="cap-countries">
                  ${rot.countries.map(c => `
                    <div class="cap-country-row">
                      <span class="cap-country-name">${escapeHtml(c.country)}</span>
                      <span class="cap-country-fd">${c.fd.toLocaleString()}</span>
                    </div>
                  `).join("")}
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

// Кнопка открытия CAP
(function injectCapBtn() {
  const btn = document.createElement("button");
  btn.className = "btn cap-open-btn";
  btn.textContent = "🎯 CAP Report";
  btn.addEventListener("click", () => {
    initCapReport();
    const panel = document.getElementById("capPanel");
    if (panel) panel.style.display = "flex";
  });
  const filterRow = document.querySelector(".filter-row") || document.querySelector(".controls");
  if (filterRow) filterRow.appendChild(btn);
  else document.body.insertBefore(btn, document.body.firstChild);
})();

// ─── Offers Panel ────────────────────────────────────────────────────────────

let panelData = { rotations: [] };
const _collapsedRotations = new Set();

async function loadPanel() {
  const { r, json } = await fetchJsonSafe("/api/panel");
  if (r.ok && json.ok) {
    panelData = json.data;
    // Рендерим только если панель открыта и видима
    const panel = document.getElementById("offersPanel");
    if (panel && panel.style.display !== "none") {
      renderPanel();
    }
    // Уведомления проверяем только при авто-обновлении (через _autoPanelRefresh)
    // НЕ здесь — чтобы не срабатывало при каждом открытии панели
  }
}

function renderPanel() {
  const el = document.getElementById("offersPanelBody");
  if (!el) return;

  if (!panelData.rotations.length) {
    el.innerHTML = `<div class="muted" style="padding:24px">Нет ротаций. Добавьте первую.</div>`;
    return;
  }

  el.innerHTML = panelData.rotations.map(rot => {
    const collapsed = _collapsedRotations.has(rot.id);
    return `
    <div class="op-rotation" data-rot-id="${rot.id}">
      <div class="op-rot-header op-rot-toggle" data-action="toggle-rot" data-rot-id="${rot.id}">
        <div class="op-rot-left">
          <span class="op-rot-chevron ${collapsed ? "" : "open"}">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <polyline points="2,4 6,8 10,4"/>
            </svg>
          </span>
          <span class="op-rot-name">${escapeHtml(rot.name)}</span>
          ${rot.binom_rotation_id ? `<span class="op-rot-rid">#${rot.binom_rotation_id}</span>` : ""}
        </div>
        <div class="op-rot-actions">
          <button class="btn op-btn" data-action="add-geo" data-rot-id="${rot.id}">+ GEO</button>
          <button class="btn op-btn danger" data-action="del-rot" data-rot-id="${rot.id}">✕</button>
        </div>
      </div>
      <div class="op-rot-body ${collapsed ? "collapsed" : ""}">
      ${rot.geos.map(geo => `
        <div class="op-geo" data-geo-id="${geo.id}">
          <div class="op-geo-header">
            <span class="op-geo-name">${escapeHtml(geo.name)}</span>
            <div class="op-geo-right">
              <span class="op-cap-remain-label">Cap remain: <b>${geoCapRemain(geo)}</b></span>
              <button class="btn op-btn" data-action="add-offer" data-geo-id="${geo.id}" data-rot-id="${rot.id}">+ Оффер</button>
              <button class="btn op-btn" data-action="edit-geo" data-geo-id="${geo.id}" data-geo-name="${escapeHtml(geo.name)}">✏️</button>
              <button class="btn op-btn danger" data-action="del-geo" data-geo-id="${geo.id}">✕</button>
            </div>
          </div>
          <table class="op-table">
            <colgroup>
              <col/><col/><col/><col/><col/><col/><col/><col/>
            </colgroup>
            <thead>
              <tr>
                <th>Оффер</th>
                <th>Статус</th>
                <th class="num">Ставка</th>
                <th class="num">Cap</th>
                <th class="num">$perUniq</th>
                <th class="num">Filled</th>
                <th class="num">Remain</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${geo.offers.map(off => {
                const cap       = off.cap === null ? "∞" : off.cap;
                const rateSymbol = off.currency === "EUR" ? "€" : off.currency === "BRL" ? "R$" : "$";
                const rateStr    = off.rate ? `${rateSymbol}${off.rate}` : "—";
                // filled_cap уже содержит manual + binom (считается на сервере)
                const filledVal = off.filled_cap ?? null;
                const filled    = filledVal !== null ? filledVal : "—";
                const remain    = off.cap === null ? "∞" : (filledVal !== null ? off.cap - filledVal : "—");
                const dpuVal    = off.dpu !== null && off.dpu !== undefined;
                const dpuAge    = off.dpu_updated_at ? (() => {
                  const diff = (Date.now() - new Date(off.dpu_updated_at)) / 86400000;
                  return diff < 1 ? "сегодня" : `${Math.floor(diff)}d ago`;
                })() : "";
                const dpuNote   = off.dpu_note || "";
                let dpu;
                if (dpuVal) {
                  dpu = `$${parseFloat(off.dpu).toFixed(2)} <span class="op-dpu-period">${off.dpu_period || ""}</span><span class="op-dpu-age" title="Обновлён: ${dpuAge}">${dpuAge}</span>`;
                } else if (dpuNote === "insufficient_data") {
                  dpu = `<span class="op-dpu-low" title="Мало данных (< 80 уников)">мало данных</span><span class="op-dpu-age"> ${dpuAge}</span>`;
                } else {
                  dpu = `<span class="op-dpu-none">—</span>`;
                }
                const remainCls = typeof remain === "number" && remain <= 0 ? "op-full" : "op-remain";
                return `
                  <tr data-offer-id="${off.id}">
                    <td class="op-offer-name" title="${escapeHtml(off.name)}">${escapeHtml(off.name)}</td>
                    <td><span class="op-status op-status-${off.status || 'active'}" data-action="cycle-status" data-offer-id="${off.id}" title="Нажми чтобы сменить статус">${statusLabel(off.status)}</span></td>
                    <td class="num op-rate">${rateStr}</td>
                    <td class="num">${cap}</td>
                    <td class="num op-dpu op-dpu-cell" data-offer-id="${off.id}" title="Двойной клик — пересчитать">${dpu}</td>
                    <td class="num">${filled}</td>
                    <td class="num ${remainCls}">${typeof remain === "number" ? remain.toLocaleString() : remain}</td>
                    <td class="op-actions">
                      <button class="btn op-btn small" data-action="edit-offer" data-offer-id="${off.id}" title="Редактировать">✏️</button>
                      <button class="btn op-btn danger small" data-action="del-offer" data-offer-id="${off.id}">✕</button>
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      `).join("")}
      </div>
    </div>
  `;
  }).join("");
}

function statusLabel(status) {
  if (status === "stop")       return "Stop";
  if (status === "no_perform") return "No Perform";
  return "Active";
}

function geoCapRemain(geo) {
  let total = 0;
  for (const off of geo.offers) {
    if (off.cap === null) return "∞";
    total += off.cap - (off.filled_cap || 0);
  }
  return total;
}

// ─── Panel modal helpers ──────────────────────────────────────────────────────

function showModal(title, fields, onSave) {
  document.getElementById("opModal")?.remove();
  const modal = document.createElement("div");
  modal.id = "opModal";
  modal.className = "op-modal-overlay";
  modal.innerHTML = `
    <div class="op-modal">
      <div class="op-modal-title">${title}</div>
      ${fields.map(f => `
        <div class="op-modal-field">
          <label>${f.label}</label>
          ${f.type === "select"
            ? `<select class="date-inp" id="opf_${f.key}" style="width:100%">${(f.options||[]).map(o=>`<option value="${o.value}">${o.label}</option>`).join("")}</select>`
            : `<input class="date-inp" id="opf_${f.key}" type="${f.type||"text"}" placeholder="${f.placeholder||""}" value="${f.default||""}" style="width:100%">`
          }
        </div>
      `).join("")}
      <div class="op-modal-actions">
        <button class="btn primary" id="opModalSave">Сохранить</button>
        <button class="btn" id="opModalCancel">Отмена</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  document.getElementById("opModalCancel").onclick = () => modal.remove();
  document.getElementById("opModalSave").onclick = () => {
    const vals = {};
    fields.forEach(f => { vals[f.key] = document.getElementById("opf_"+f.key)?.value ?? ""; });
    onSave(vals);
    modal.remove();
  };
}

// ─── Panel event handlers ─────────────────────────────────────────────────────

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn || !btn.closest("#offersPanelBody, #opsPanelHeader")) return;
  const action = btn.dataset.action;

  if (action === "show-history") {
    initFdHistory();
    return;
  }

  if (action === "toggle-rot") {
    // Не сворачивать если кликнули по кнопке внутри
    if (e.target.closest(".op-rot-actions")) return;
    const rid = btn.dataset.rotId;
    if (_collapsedRotations.has(rid)) {
      _collapsedRotations.delete(rid);
    } else {
      _collapsedRotations.add(rid);
    }
    renderPanel();
    return;
  }

  if (action === "add-rot") {
    showModal("Новая ротация", [
      { key: "name",              label: "Название ротации",  placeholder: "Casino rotation" },
      { key: "binom_rotation_id", label: "Binom Rotation ID", placeholder: "118" },
    ], async (v) => {
      await fetchJsonSafe("/api/panel/rotation", { method: "POST", body: JSON.stringify({
        name:              v.name,
        binom_rotation_id: v.binom_rotation_id,
      })});
      loadPanel();
    });
  }

  if (action === "del-rot") {
    if (!confirm("Удалить ротацию?")) return;
    await fetchJsonSafe(`/api/panel/rotation/${btn.dataset.rotId}`, { method: "DELETE" });
    loadPanel();
  }

  if (action === "add-geo") {
    showModal("Новое GEO", [
      { key: "name", label: "Страна / GEO", placeholder: "Guinea" }
    ], async (v) => {
      await fetchJsonSafe(`/api/panel/rotation/${btn.dataset.rotId}/geo`, { method: "POST", body: JSON.stringify({ name: v.name }) });
      loadPanel();
    });
  }

  if (action === "edit-geo") {
    showModal("Переименовать GEO", [
      { key: "name", label: "Название GEO", default: btn.dataset.geoName }
    ], async (v) => {
      if (!v.name.trim()) return;
      await fetchJsonSafe(`/api/panel/geo/${btn.dataset.geoId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: v.name.trim() })
      });
      loadPanel();
    });
  }

  if (action === "del-geo") {
    if (!confirm("Удалить GEO?")) return;
    await fetchJsonSafe(`/api/panel/geo/${btn.dataset.geoId}`, { method: "DELETE" });
    loadPanel();
  }

  if (action === "add-offer") {
    // Находим binom_rotation_id из текущей ротации
    const rotId = btn.dataset.rotId;
    const parentRot = panelData.rotations.find(r => r.id === rotId);
    const autoRotId = parentRot?.binom_rotation_id || "";

    showModal("Новый оффер", [
      { key: "name",           label: "Название оффера",  placeholder: "CAP100!1xbet GN 12usd" },
      { key: "binom_offer_id", label: "Binom Offer ID",   placeholder: "1234" },
      { key: "cap",            label: "Cap (пусто = ∞)",  placeholder: "пусто = ∞", type: "number" },
      { key: "rate",           label: "Ставка",           placeholder: "100", type: "number" },
      { key: "currency",       label: "Валюта",           type: "select", options: [
          { value: "USD", label: "$ USD" },
          { value: "EUR", label: "€ EUR" },
          { value: "BRL", label: "R$ BRL" },
      ]},
    ], async (v) => {
      await fetchJsonSafe(`/api/panel/geo/${btn.dataset.geoId}/offer`, {
        method: "POST",
        body: JSON.stringify({
          name:           v.name,
          binom_offer_id: v.binom_offer_id,
          rotation_id:    autoRotId,
          cap:            v.cap || null,
          rate:           v.rate ? parseFloat(v.rate) : null,
          currency:       v.currency || "USD",
        })
      });
      loadPanel();
    });
  }

  if (action === "cycle-status") {
    const oid = btn.dataset.offerId;
    // Найдём текущий статус
    let current = "active";
    for (const rot of panelData.rotations)
      for (const geo of rot.geos)
        for (const off of geo.offers)
          if (off.id === oid) { current = off.status || "active"; break; }

    const next = current === "active" ? "stop" : current === "stop" ? "no_perform" : "active";
    await fetchJsonSafe(`/api/panel/offer/${oid}`, {
      method: "PATCH",
      body: JSON.stringify({ status: next })
    });
    loadPanel();
    return;
  }

  if (action === "reset-dpu") {
    await fetchJsonSafe(`/api/panel/offer/${btn.dataset.offerId}`, {
      method: "PATCH",
      body: JSON.stringify({ dpu_updated_at: null })
    });
    loadPanel();
    return;
  }

  if (action === "edit-offer") {
    const oid = btn.dataset.offerId;
    // Найдём оффер в panelData
    let found = null;
    for (const rot of panelData.rotations)
      for (const geo of rot.geos)
        for (const off of geo.offers)
          if (off.id === oid) { found = off; break; }
    if (!found) return;

    showModal("Редактировать оффер", [
      { key: "name",           label: "Название оффера",          default: found.name },
      { key: "binom_offer_id", label: "Binom Offer ID",           default: found.binom_offer_id || "" },
      { key: "cap",            label: "Cap (пусто = ∞)",          default: found.cap ?? "", type: "number", placeholder: "пусто = ∞" },
      { key: "rate",           label: "Ставка",                   default: found.rate ?? "", type: "number", placeholder: "100" },
      { key: "currency",       label: "Валюта",                   type: "select", options: [
          { value: "USD", label: "$ USD" },
          { value: "EUR", label: "€ EUR" },
          { value: "BRL", label: "R$ BRL" },
      ]},
      { key: "filled_cap",     label: "Filled Cap (база до начала учёта, Binom добавит сверху)", default: found.filled_cap_manual ?? "", type: "number", placeholder: "0" },
    ], async (v) => {
      await fetchJsonSafe(`/api/panel/offer/${oid}`, {
        method: "PATCH",
        body: JSON.stringify({
          name:              v.name,
          binom_offer_id:    v.binom_offer_id,
          cap:               v.cap.trim() === "" ? null : parseInt(v.cap),
          rate:              v.rate.trim() === "" ? null : parseFloat(v.rate),
          currency:          v.currency || "USD",
          filled_cap_manual: v.filled_cap.trim() === "" ? null : parseInt(v.filled_cap),
        })
      });
      loadPanel();
    });
  }

  if (action === "del-offer") {
    if (!confirm("Удалить оффер?")) return;
    await fetchJsonSafe(`/api/panel/offer/${btn.dataset.offerId}`, { method: "DELETE" });
    loadPanel();
  }

  if (action === "uncap") {
    await fetchJsonSafe(`/api/panel/offer/${btn.dataset.offerId}`, {
      method: "PATCH",
      body: JSON.stringify({ cap: null })
    });
    loadPanel();
  }

  if (action === "sync-from-binom") {
    openSyncModal();
    return;
  }

  if (action === "refresh-panel") {
    btn.textContent = "⟳ 0%";
    btn.disabled = true;

    try {
      const resp = await fetch("/api/panel/refresh_full", { method: "POST" });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Парсим все завершённые SSE-события из буфера
        const parts = buf.split("\n\n");
        buf = parts.pop(); // последний может быть неполным

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          let ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }

          if (ev.type === "dpu") {
            // Обновляем конкретную ячейку сразу
            _applyDpuToCell(ev.offer_id, ev.dpu, ev.period, ev.note);
            // Обновляем panelData в памяти
            for (const rot of panelData.rotations)
              for (const geo of rot.geos)
                for (const off of geo.offers)
                  if (off.id === ev.offer_id) {
                    off.dpu = ev.dpu; off.dpu_period = ev.period; off.dpu_note = ev.note;
                    off.dpu_updated_at = new Date().toISOString();
                  }
            const pct = ev.total > 0 ? Math.round(ev.done / ev.total * 100) : 100;
            btn.textContent = `⟳ ${pct}%`;
          } else if (ev.type === "done") {
            btn.textContent = "✓ Готово";
            await loadPanel();
            renderPanel();
            _updateAutoRefreshStatus();
            setTimeout(() => { btn.textContent = "🔄 Обновить"; }, 1500);
          }
        }
      }
    } catch(e) {
      btn.textContent = "🔄 Обновить";
    } finally {
      btn.disabled = false;
    }
  }
});



// ─── Init Offers Panel ────────────────────────────────────────────────────────

// ─── Notification Bell ───────────────────────────────────────────────────────

const _notifsSeen = new Set(); // offer.id — чтобы не дублировать уведомления

function initBell() {
  if (document.getElementById("bellBtn")) return;

  const bell = document.createElement("div");
  bell.id = "bellBtn";
  bell.className = "bell-btn";
  bell.innerHTML = `
    <div class="bell-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
    </div>
    <span class="bell-badge" id="bellBadge" style="display:none">0</span>
    <div class="bell-dropdown" id="bellDropdown" style="display:none"></div>
  `;
  document.body.appendChild(bell);

  bell.addEventListener("click", (e) => {
    e.stopPropagation();
    const dd = document.getElementById("bellDropdown");
    dd.style.display = dd.style.display === "none" ? "block" : "none";
    // сбрасываем бейдж при открытии
    document.getElementById("bellBadge").style.display = "none";
  });

  document.addEventListener("click", () => {
    const dd = document.getElementById("bellDropdown");
    if (dd) dd.style.display = "none";
  });
}

function checkCapAlerts(panelData) {
  const newNotifs = [];

  for (const rot of panelData.rotations) {
    for (const geo of rot.geos) {
      for (const off of geo.offers) {
        if (!off.cap) continue; // unlimited — не проверяем
        // filled_cap уже содержит manual + binom (считается на сервере)
        const filledVal = off.filled_cap ?? 0;
        const remain    = off.cap - filledVal;
        const threshold = 5; // фиксированный порог

        if (remain >= 0 && remain <= threshold) {
          const key = `${off.id}:${remain}`;
          if (!_notifsSeen.has(key)) {
            _notifsSeen.add(key);
            newNotifs.push({
              key,
              offerId:  off.id,
              offer:    off.name,
              geo:      geo.name,
              rotation: rot.name,
              cap:      off.cap,
              filled:   filledVal,
              remain,
              ts:       new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }),
            });
          }
        }
      }
    }
  }

  if (newNotifs.length) {
    addNotifications(newNotifs);
  }
}

let _allNotifs = [];

function addNotifications(notifs) {
  _allNotifs = [...notifs, ..._allNotifs].slice(0, 50);
  renderBell();
}

function renderBell() {
  const badge    = document.getElementById("bellBadge");
  const dropdown = document.getElementById("bellDropdown");
  if (!badge || !dropdown) return;

  const unread = _allNotifs.length;
  if (unread > 0) {
    badge.style.display = "flex";
    badge.textContent   = unread > 99 ? "99+" : unread;
  }

  if (!_allNotifs.length) {
    dropdown.innerHTML = `<div class="bell-empty">Нет уведомлений</div>`;
    return;
  }

  dropdown.innerHTML = `
    <div class="bell-header">
      <span>Уведомления</span>
      <button class="bell-clear" id="bellClear">Очистить</button>
    </div>
    ${_allNotifs.map(n => `
      <div class="bell-item ${n.remain <= 0 ? "bell-full" : "bell-warn"}" data-offer-id="${n.offerId}" style="cursor:pointer">
        <div class="bell-item-title">${escapeHtml(n.offer)}</div>
        <div class="bell-item-meta">${escapeHtml(n.rotation)} · ${escapeHtml(n.geo)}</div>
        <div class="bell-item-stat">
          Cap: <b>${n.cap}</b> · Filled: <b>${n.filled}</b> ·
          Remain: <b class="${n.remain <= 0 ? "bell-stat-full" : "bell-stat-warn"}">${n.remain}</b>
        </div>
        <div class="bell-item-time">${n.ts}</div>
      </div>
    `).join("")}
  `;

  document.getElementById("bellClear")?.addEventListener("click", (e) => {
    e.stopPropagation();
    _allNotifs = [];
    _notifsSeen.clear();
    renderBell();
    badge.style.display = "none";
  });

  dropdown.querySelectorAll(".bell-item[data-offer-id]").forEach(item => {
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      const oid = item.dataset.offerId;
      navigateToOffer(oid);
      dropdown.style.display = "none";
    });
  });
}

function navigateToOffer(offerId) {
  // Открываем панель офферов если закрыта
  initOffersPanel();
  const panel = document.getElementById("offersPanel");
  if (panel) panel.style.display = "flex";

  // Раскрываем нужную ротацию и скроллим к офферу
  setTimeout(() => {
    // Найдём ротацию содержащую оффер и раскроем её
    for (const rot of panelData.rotations) {
      for (const geo of rot.geos) {
        for (const off of geo.offers) {
          if (off.id === offerId) {
            _collapsedRotations.delete(rot.id);
            renderPanel();
            break;
          }
        }
      }
    }

    // Скроллим к строке
    setTimeout(() => {
      const row = document.querySelector(`tr[data-offer-id="${offerId}"]`);
      if (row) {
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        row.classList.add("op-highlight");
        setTimeout(() => row.classList.remove("op-highlight"), 2000);
      }
    }, 150);
  }, 100);
}

initBell();


// ─── Sync from Binom modal ────────────────────────────────────────────────────

async function openSyncModal() {
  // Remove old modal if exists
  document.getElementById("syncModal")?.remove();

  const modal = document.createElement("div");
  modal.id = "syncModal";
  modal.className = "sync-modal-backdrop";
  modal.innerHTML = `
    <div class="sync-modal">
      <div class="sync-modal-header">
        <span>⚡ Синхронизировать ротации</span>
        <button class="btn" id="syncModalClose">✕</button>
      </div>
      <div class="sync-modal-body">
        <div class="sync-loading">Загрузка ротаций…</div>
      </div>
      <div class="sync-modal-footer" style="display:none">
        <button class="btn" id="syncSelectAll">Выбрать все</button>
        <button class="btn" id="syncDeselectAll">Снять все</button>
        <button class="btn primary" id="syncDoBtn">⚡ Синхронизировать выбранные</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  modal.querySelector("#syncModalClose").onclick = () => modal.remove();
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  // Load rotations list
  try {
    const { json } = await fetchJsonSafe("/api/panel/sync_preview");
    const body = modal.querySelector(".sync-modal-body");
    const footer = modal.querySelector(".sync-modal-footer");

    if (!json?.ok || !json.rotations?.length) {
      body.innerHTML = `<div class="sync-error">Не удалось загрузить ротации</div>`;
      return;
    }

    body.innerHTML = json.rotations.map(rot => `
      <label class="sync-rot-item">
        <input type="checkbox" class="sync-rot-cb" value="${escapeHtml(rot.id)}" checked>
        <span class="sync-rot-name">${escapeHtml(rot.name)}</span>
        <span class="sync-rot-id">#${escapeHtml(rot.id)}</span>
      </label>`).join("");

    footer.style.display = "flex";

    modal.querySelector("#syncSelectAll").onclick   = () => body.querySelectorAll(".sync-rot-cb").forEach(cb => cb.checked = true);
    modal.querySelector("#syncDeselectAll").onclick = () => body.querySelectorAll(".sync-rot-cb").forEach(cb => cb.checked = false);

    modal.querySelector("#syncDoBtn").onclick = async () => {
      const selected = [...body.querySelectorAll(".sync-rot-cb:checked")].map(cb => cb.value);
      if (!selected.length) { alert("Выберите хотя бы одну ротацию"); return; }

      const doBtn = modal.querySelector("#syncDoBtn");
      doBtn.textContent = "⟳ Синхронизация…";
      doBtn.disabled = true;

      try {
        const { json: res } = await fetchJsonSafe("/api/panel/sync_from_binom", {
          method: "POST",
          body: JSON.stringify({ rotation_ids: selected }),
        });
        if (res?.ok) {
          modal.remove();
          await loadPanel();
          renderPanel();
          const statusEl = document.getElementById("opAutoStatus");
          if (statusEl) {
            statusEl.textContent = `✓ +${res.added_offers} офферов в ${res.added_rotations} ротациях`;
            setTimeout(() => { statusEl.textContent = "авто • каждые 5 мин"; }, 5000);
          }
        } else {
          alert("Ошибка: " + (res?.error || "unknown"));
          doBtn.textContent = "⚡ Синхронизировать выбранные";
          doBtn.disabled = false;
        }
      } catch(err) {
        alert("Ошибка: " + err.message);
        doBtn.textContent = "⚡ Синхронизировать выбранные";
        doBtn.disabled = false;
      }
    };
  } catch(err) {
    modal.querySelector(".sync-modal-body").innerHTML = `<div class="sync-error">${escapeHtml(err.message)}</div>`;
  }
}

function initOffersPanel() {
  if (document.getElementById("offersPanel")) {
    document.getElementById("offersPanel").style.display = "flex";
    loadPanel().then(() => renderPanel());
    startPanelAutoRefresh(); // возобновляем таймер если был остановлен
    return;
  }
  const panel = document.createElement("div");
  panel.id = "offersPanel";
  panel.className = "weekly-panel";
  panel.innerHTML = `
    <div class="weekly-header" id="opsPanelHeader">
      <span class="weekly-title">📋 Офферы & CAP</span>
      <div class="weekly-controls">
        <button class="btn primary op-btn" data-action="add-rot">+ Ротация</button>
        <button class="btn op-btn" data-action="sync-from-binom">⚡ Синхронизировать</button>
        <button class="btn op-btn" data-action="refresh-panel">🔄 Обновить</button>
        <button class="btn op-btn" data-action="show-history">📈 История</button>
        <span id="opAutoStatus" class="op-auto-status">авто • каждые 5 мин</span>
        <button class="btn" id="opCloseBtn">✕</button>
      </div>
    </div>
    <div class="weekly-result" id="offersPanelBody"></div>
  `;
  document.body.appendChild(panel);
  document.getElementById("opCloseBtn").onclick = () => {
    panel.style.display = "none";
    stopPanelAutoRefresh();
  };
  loadPanel();
  startPanelAutoRefresh();
}

(function injectOffersBtn() {
  const btn = document.createElement("button");
  btn.className = "btn offers-open-btn";
  btn.textContent = "📋 Офферы";
  btn.addEventListener("click", initOffersPanel);
  const filterRow = document.querySelector(".filter-row") || document.querySelector(".controls");
  if (filterRow) filterRow.appendChild(btn);
  else document.body.insertBefore(btn, document.body.firstChild);
})();

// ─── Auto-refresh Offers Panel ───────────────────────────────────────────────

let _panelAutoRefreshTimer = null;
const PANEL_REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 минут

async function _autoPanelRefresh() {
  if (!panelData || !panelData.rotations) return; // панель ещё не загружена
  console.log(`[autorefresh] firing at ${new Date().toLocaleTimeString()}`);
  try {
    const { r, json } = await fetchJsonSafe("/api/panel/refresh", { method: "POST" });
    if (!r.ok || !json.ok) return;

    const hadNewEvents = (json.new_events || 0) > 0;
    const caps = json.caps || {};

    // Патчим только filled_cap в panelData — dpu не трогаем
    for (const rot of panelData.rotations)
      for (const geo of rot.geos)
        for (const off of geo.offers)
          if (caps[off.id] !== undefined) {
            off.filled_cap = caps[off.id].filled_cap;
            off.cap        = caps[off.id].cap;
          }

    // Обновляем только FD-ячейки в DOM — dpu ячейки не трогаем
    _applyFdToCells(caps);
    _updateAutoRefreshStatus();

    if (hadNewEvents) {
      checkCapAlerts(panelData);
    }
  } catch(e) {
    // тихая ошибка
  }
}

function _updateAutoRefreshStatus() {
  const el = document.getElementById("opAutoStatus");
  if (!el) return;
  const now = new Date();
  const hh  = String(now.getHours()).padStart(2,"0");
  const mm  = String(now.getMinutes()).padStart(2,"0");
  el.textContent = `обновлено ${hh}:${mm}`;
}

function startPanelAutoRefresh() {
  stopPanelAutoRefresh(); // сначала чистим старый если был
  _panelAutoRefreshTimer = setInterval(_autoPanelRefresh, PANEL_REFRESH_INTERVAL_MS);
  console.log(`[autorefresh] started, interval=${PANEL_REFRESH_INTERVAL_MS/1000}s`);
}

function stopPanelAutoRefresh() {
  if (_panelAutoRefreshTimer) {
    clearInterval(_panelAutoRefreshTimer);
    _panelAutoRefreshTimer = null;
  }
}

// ─── FD History Panel ────────────────────────────────────────────────────────

function initFdHistory() {
  document.getElementById("fdHistModal")?.remove();

  const modal = document.createElement("div");
  modal.id = "fdHistModal";
  modal.className = "op-modal-overlay";
  modal.innerHTML = `
    <div class="op-modal fdh-modal">
      <div class="fdh-modal-header">
        <span class="fdh-modal-title">📈 История FD</span>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="text" id="fdHistSearch" class="date-inp" placeholder="Поиск..." style="width:180px">
          <button class="btn op-btn danger" id="fdHistClear">Очистить</button>
          <button class="btn" id="fdHistClose">✕</button>
        </div>
      </div>
      <div id="fdHistBody" class="fdh-modal-body"></div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("fdHistClose").onclick  = () => modal.remove();
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
  document.getElementById("fdHistClear").onclick  = async () => {
    if (!confirm("Очистить всю историю?")) return;
    await fetchJsonSafe("/api/panel/history", { method: "DELETE" });
    loadFdHistory();
  };
  document.getElementById("fdHistSearch").addEventListener("input", () => loadFdHistory());
  loadFdHistory();
}

async function loadFdHistory() {
  const body = document.getElementById("fdHistBody");
  if (!body) return;

  const { r, json } = await fetchJsonSafe("/api/panel/history?limit=200");
  if (!r.ok || !json.ok) return;

  const q = document.getElementById("fdHistSearch")?.value.toLowerCase() || "";
  let events = json.events || [];
  if (q) events = events.filter(e =>
    e.offer.toLowerCase().includes(q) ||
    e.geo.toLowerCase().includes(q) ||
    e.rotation.toLowerCase().includes(q)
  );

  if (!events.length) {
    body.innerHTML = `<div class="muted" style="padding:24px;text-align:center">Нет событий</div>`;
    return;
  }

  // Группируем по дате
  const byDate = {};
  for (const ev of events) {
    const date = ev.ts.split(" ")[0];
    if (!byDate[date]) byDate[date] = [];
    byDate[date].push(ev);
  }

  body.innerHTML = Object.entries(byDate).map(([date, evs]) => `
    <div class="fdh-group">
      <div class="fdh-date">${date}</div>
      <table class="fdh-table">
        <thead>
          <tr>
            <th>Время</th>
            <th>Оффер</th>
            <th>Ротация</th>
            <th>GEO</th>
            <th class="num">+FD</th>
            <th class="num">Итого</th>
            <th class="num">Cap</th>
          </tr>
        </thead>
        <tbody>
          ${evs.map(ev => {
            const remain  = ev.cap ? ev.cap - ev.total : null;
            const almostFull = remain !== null && remain <= 5;
            return `
              <tr class="${almostFull ? "fdh-warn" : ""}">
                <td class="fdh-time">${ev.ts.split(" ")[1] || ""}</td>
                <td class="fdh-offer">${escapeHtml(ev.offer)}</td>
                <td class="fdh-rot">${escapeHtml(ev.rotation)}</td>
                <td>${escapeHtml(ev.geo)}</td>
                <td class="num fdh-delta">+${ev.delta}</td>
                <td class="num fdh-total">${ev.total}</td>
                <td class="num fdh-cap">${ev.cap ?? "∞"}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `).join("");
}