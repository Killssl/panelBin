/* ══════════════════════════════════════════════
   Admin Panel — admin.js
   API architecture:
     - Networks live in Binom (fetched via /api/admin/networks)
     - Partner accounts live in SQLite (linked by binom_network_id)
   ══════════════════════════════════════════════ */

const ADM = {
  token:        '',  // всегда берём из сессии, не из localStorage
  reqFilter:    null,
  pendingReqId: null,

  drawerNetId:  null,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const h = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function _getPrefix() {
  if (window.APP_PREFIX) return String(window.APP_PREFIX).replace(/\/+$/, '');
  const m = window.location.pathname.match(/^(\/[^/]+)\//);
  return (m && m[1] !== '/static') ? m[1] : '';
}

async function admApi(method, path, body) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + ADM.token,
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(_getPrefix() + path, opts);
    return r.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

function admModalClose() { admCloseModal('admModal'); }

function admCloseModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

// Close modals on backdrop click
document.addEventListener('click', e => {
  if (e.target.classList.contains('adm-overlay')) {
    e.target.style.display = 'none';
  }
});

// ESC key
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const openModal = document.querySelector('.adm-overlay[style*="flex"]');
    if (openModal) { openModal.style.display = 'none'; return; }
    const drawer = document.getElementById('admDrawer');
    if (drawer?.classList.contains('open')) { admCloseDrawer(); return; }
    closeAdmin();
  }
});

// ─── Auto-fetch token from Flask session on page load ─────────────────────────

(async function autoFetchSessionToken() {
  if (ADM.token) return; // уже есть
  try {
    const r = await fetch(_getPrefix() + '/api/auth/session_token');
    if (r.ok) {
      const j = await r.json();
      if (j.ok && j.token) {
        ADM.token = j.token;
              }
    }
  } catch(e) {}
})();


// ─── Rotations config ────────────────────────────────────────────────────────
const ADM_ROTATIONS = [
  { id: "121", name: "Crash" },
  { id: "124", name: "Casino" },
  { id: "118", name: "Betting" },
  { id: "61",  name: "Slots" },
  { id: "117", name: "Mixed" },
];

function admInitRotationsList() {
  const el = document.getElementById('admRotationsList');
  if (!el) return;
  el.innerHTML = ADM_ROTATIONS.map(r => `
    <label style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:6px 10px;
                  background:var(--bg3);border:0.5px solid var(--border);border-radius:6px">
      <input type="checkbox" class="adm-rot-check" data-rot-id="${r.id}"
             style="accent-color:#6366f1;width:14px;height:14px">
      <span style="color:var(--text);font-size:.85em">${h(r.name)}</span>
      <span style="color:var(--text3);font-size:.75em">#${r.id}</span>
    </label>
  `).join('');
}

function admGetSelectedRotations() {
  return [...document.querySelectorAll('.adm-rot-check:checked')].map(cb => cb.dataset.rotId);
}

// ─── Open / Close overlay ─────────────────────────────────────────────────────

function openAdmin() {
  document.getElementById('adminOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';
  if (ADM.token) {
    admApi('GET', '/api/auth/me').then(j => {
      if (j.ok && j.role === 'admin') admShowApp(j.username);
      else { ADM.token = ''; }
    });
  }
}

function closeAdmin() {
  document.getElementById('adminOverlay')?.classList.remove('open');
  document.body.style.overflow = '';
  admCloseDrawer();
  admStopTrackingAutoRefresh();
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

async function admDoLogin() {
  const u = document.getElementById('admLoginUser').value.trim();
  const p = document.getElementById('admLoginPass').value.trim();
  const errEl = document.getElementById('admLoginErr');
  errEl.textContent = '';

  const j = await admApi('POST', '/api/auth/login', { username: u, password: p });
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }
  if (j.role !== 'admin') { errEl.textContent = 'Нет доступа'; return; }

  ADM.token = j.token;
    admShowApp(j.username);
}

function admLogout() {
    ADM.token = '';
  document.getElementById('adminApp').classList.remove('visible');
  document.getElementById('adminLoginScreen').style.display = 'flex';
  document.getElementById('admLoginPass').value = '';
  document.getElementById('admLoginErr').textContent = '';
}

function admShowApp(username) {
  document.getElementById('adminLoginScreen').style.display = 'none';
  document.getElementById('adminApp').classList.add('visible');
  document.getElementById('admSidebarUser').textContent = username || '—';
  // Set avatar initials
  const av = document.getElementById('admAvatarLetters');
  if (av && username) av.textContent = username.slice(0,2).toUpperCase();
  // Restore saved theme
  const savedTheme = localStorage.getItem('admTheme');
  if (savedTheme === 'dark') _admApplyTheme(true);
  admLoadNetworks();
  admLoadPendingCount();
}

function admToggleTheme() {
  const isDark = document.getElementById('adminOverlay').classList.contains('dark-theme');
  _admApplyTheme(!isDark);
}

function _admApplyTheme(dark) {
  const overlay = document.getElementById('adminOverlay');
  if (dark) {
    overlay.classList.add('dark-theme');
    document.getElementById('admThemeBtn').textContent = '☀️';
    localStorage.setItem('admTheme', 'dark');
  } else {
    overlay.classList.remove('dark-theme');
    document.getElementById('admThemeBtn').textContent = '🌙';
    localStorage.setItem('admTheme', 'light');
  }
}

['admLoginUser', 'admLoginPass'].forEach(id => {
  document.getElementById(id)?.addEventListener('keydown', e => {
    if (e.key === 'Enter') admDoLogin();
  });
});

// ─── Navigation ───────────────────────────────────────────────────────────────

const ADM_TITLES = { networks: 'Сети', requests: 'Заявки', users: 'Пользователи', tracking: 'Трекинг офферов', rates: 'Ставки', stop: 'Стоп оффера', rotations: 'Ротации', weekly: 'Weekly Uniques' };

function admNav(name) {
  document.querySelectorAll('.adm-nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('adm-nav-' + name)?.classList.add('active');
  document.querySelectorAll('.adm-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('adm-panel-' + name)?.classList.add('active');
  document.getElementById('admTopbarTitle').textContent = ADM_TITLES[name] || name;
  admCloseDrawer();
  if (name === 'networks') admLoadNetworks();
  if (name === 'requests') admLoadRequests();
  if (name === 'users')    admLoadUsers();
  if (name === 'tracking') { admLoadTracking(); admStartTrackingAutoRefresh(); admStartFdCountdown(); }
  if (name === 'rotations') { admLoadRotationsPanel(); }
  if (name === 'weekly') { admInitWeeklyPanel(); }
  if (name === 'rates') admLoadRates();
  if (!_notifInterval) admStartNotifications();
  if (name === 'invoices') admLoadInvoices();
  if (name === 'holds') admLoadHolds();
  else { admStopTrackingAutoRefresh(); if (_fdCountdownTimer) { clearInterval(_fdCountdownTimer); _fdCountdownTimer = null; } }
}

// ─── Networks (from Binom) ────────────────────────────────────────────────────

async function admLoadNetworks() {
  const tbody = document.getElementById('admNetworksTbody');
  tbody.innerHTML = `<tr><td colspan="6" class="adm-empty">Загрузка из Binom…</td></tr>`;

  const j = await admApi('GET', '/api/admin/networks');

  if (!j.ok) {
    tbody.innerHTML = `<tr><td colspan="6" class="adm-empty" style="color:var(--red)">
      Ошибка: ${h(j.error || 'не удалось получить список сетей из Binom')}
    </td></tr>`;
    return;
  }

  const networks = j.networks || [];
  if (!networks.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="adm-empty">В Binom нет аффилейт партнёров</td></tr>`;
    return;
  }

  tbody.innerHTML = networks.map(n => {
    const netId  = n.id || n.binom_id;
    const name   = n.name || '—';
    const uid    = n.partner_uid;
    const user   = n.partner_username;
    const pb     = n.postback_url || n.postbackUrl || '';

    return `<tr>
      <td class="adm-td-name">${h(name)}</td>
      <td class="adm-muted" style="font-size:.8em">#${h(String(netId))}</td>
      <td>
        ${uid
          ? `<span class="adm-uid-pill" title="Нажмите чтобы скопировать"
               onclick="navigator.clipboard.writeText('${h(uid)}')">${h(uid)}</span>
             <span class="adm-muted" style="font-size:.78em;margin-left:4px">${h(user || '')}</span>`
          : `<span class="adm-muted" style="font-size:.78em">нет аккаунта</span>`}
      </td>
      <td class="adm-td-url">
        ${pb ? `<a href="${h(pb)}" target="_blank">${h(pb)}</a>` : '<span class="adm-muted">—</span>'}
      </td>
      <td>
        ${n.has_account
          ? `<span class="adm-badge approved">✓ Активен</span>`
          : `<span class="adm-badge manual">Без аккаунта</span>`}
      </td>
      <td>
        <div class="adm-td-actions">
          <button class="adm-btn sm" onclick="admOpenDrawer('${h(String(netId))}')">⚙️ Настройки</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ─── Network Drawer ───────────────────────────────────────────────────────────

// Поля Binom affiliate network — метаданные для рендера
const BINOM_NET_FIELDS = [
  // Основное
  { key: "name",         label: "Name",              section: "General",    type: "text",     required: true },
  { key: "notes",        label: "Notes",             section: "General",    type: "textarea"  },
  { key: "tags",         label: "Tags",              section: "General",    type: "tags",
    hint: "Теги через запятую" },
  { key: "offer_url",    label: "Offer URL Template",section: "General",    type: "text",     wide: true,
    hint: "Шаблон URL оффера, напр. https://go.network.com/offer/{offer_id}" },
  { key: "currency_id",  label: "Currency",          section: "General",    type: "text"      },
  { key: "status",       label: "Status",            section: "General",    type: "select",
    options: ["active","paused","deleted"] },

  // Postback
  { key: "postback_url",       label: "Postback URL",          section: "Postback", type: "text", wide: true },
  { key: "postback_statuses",  label: "Postback Whitelist",    section: "Postback", type: "multicheck",
    options: ["approved","pending","declined","trashed","hold","unknown"],
    hint: "Статусы конверсий для которых отправляется postback" },
  { key: "offer_param",        label: "Offer Param",           section: "Postback", type: "text",
    hint: "Параметр в postback URL для передачи ID оффера" },
  { key: "click_id",           label: "Click ID Macro",        section: "Postback", type: "text",
    hint: "Макрос click ID, напр. {clickid}" },
  { key: "payout_param",       label: "Payout Param",          section: "Postback", type: "text" },
  { key: "txid_param",         label: "TxID Param",            section: "Postback", type: "text" },

  // Status–Payout Relation
  { key: "status_group",  label: "Status-Payout Relation", section: "Status–Payout Relation", type: "status_payout",
    hint: "Маппинг статусов конверсий на типы выплат" },

  // Sub ID параметры
  { key: "s1",  label: "Sub 1",  section: "Sub ID Params", type: "text" },
  { key: "s2",  label: "Sub 2",  section: "Sub ID Params", type: "text" },
  { key: "s3",  label: "Sub 3",  section: "Sub ID Params", type: "text" },
  { key: "s4",  label: "Sub 4",  section: "Sub ID Params", type: "text" },
  { key: "s5",  label: "Sub 5",  section: "Sub ID Params", type: "text" },
  { key: "s6",  label: "Sub 6",  section: "Sub ID Params", type: "text" },
  { key: "s7",  label: "Sub 7",  section: "Sub ID Params", type: "text" },
  { key: "s8",  label: "Sub 8",  section: "Sub ID Params", type: "text" },

  // Трафик
  { key: "traffic_loss",   label: "Traffic Loss (%)", section: "Traffic", type: "number" },
  { key: "min_payout",     label: "Min Payout",       section: "Traffic", type: "number" },
];

// Ключи только для чтения
const BINOM_NET_READONLY = new Set(["id","created","updated","offers_count","clicks","unique_clicks"]);

async function admOpenDrawer(netId) {
  ADM.drawerNetId = netId;
  const drawer  = document.getElementById('admDrawer');
  const bodyEl  = document.getElementById('admDrawerBody');
  const titleEl = document.getElementById('admDrawerTitle');

  titleEl.textContent = 'Загрузка…';
  bodyEl.innerHTML    = `<div class="adm-empty">⟳ Получаем данные из Binom…</div>`;
  drawer.classList.add('open');

  const j = await admApi('GET', `/api/admin/networks/${netId}`);
  if (!j.ok) {
    bodyEl.innerHTML = `<div class="adm-empty" style="color:var(--red)">Ошибка: ${h(j.error)}</div>`;
    return;
  }

  const net = j.network || {};
  const acc = j.account || {};
  titleEl.textContent = net.name || `Сеть #${netId}`;

  // Собираем все поля которые есть в ответе Binom + из метаданных
  const knownKeys = new Set(BINOM_NET_FIELDS.map(f => f.key));
  const extraFields = Object.keys(net)
    .filter(k => !knownKeys.has(k) && !BINOM_NET_READONLY.has(k))
    .map(k => ({ key: k, label: k, section: "Дополнительно", type: "text" }));

  const allFields = [...BINOM_NET_FIELDS, ...extraFields]
    .filter(f => f.key in net || f.required);

  // Группируем по секциям
  const sections = {};
  for (const f of allFields) {
    if (!sections[f.section]) sections[f.section] = [];
    sections[f.section].push(f);
  }

  // Readonly поля из Binom (показываем как info)
  const readonlyInfo = Object.entries(net)
    .filter(([k]) => BINOM_NET_READONLY.has(k) && net[k] !== null && net[k] !== undefined);

  // Render
  let html = '';

  // Raw keys debug — если поля не совпали, показываем все ключи из Binom напрямую
  const matchedCount = allFields.filter(f => f._val !== undefined && f._val !== '').length;
  if (matchedCount <= 1 && Object.keys(net).length > 1) {
    html += `<div class="adm-raw-debug">
      <div class="adm-drawer-section-title" style="margin-bottom:8px">⚠ Реальные поля Binom (raw)</div>
      <div class="adm-raw-fields">
        ${Object.entries(net).map(([k,v]) => `
          <div class="adm-raw-row">
            <span class="adm-net-info-key">${h(k)}</span>
            <input class="adm-inp adm-net-field" data-key="${h(k)}" type="text"
              value="${h(typeof v === 'object' ? JSON.stringify(v) : String(v??''))}"
              style="font-size:.78em;font-family:monospace">
          </div>`).join('')}
      </div>
    </div>`;
  }

  // Info strip
  if (readonlyInfo.length) {
    html += `<div class="adm-net-info-strip">
      ${readonlyInfo.map(([k,v]) =>
        `<span class="adm-net-info-item"><span class="adm-net-info-key">${h(k)}</span><span class="adm-net-info-val">${h(String(v))}</span></span>`
      ).join('')}
    </div>`;
  }

  // Editable sections
  for (const [sName, fields] of Object.entries(sections)) {
    html += `<div class="adm-drawer-section">
      <div class="adm-drawer-section-title">${h(sName)}</div>`;

    // Sub ID fields — grid 2 cols
    if (sName === 'Sub ID параметры') {
      html += `<div class="adm-sub-grid">`;
      for (const f of fields) {
        const val = f._val ?? '';
        html += `<div class="adm-field">
          <label>${h(f.label)}</label>
          <input class="adm-inp adm-net-field" data-key="${h(f.key)}" type="text" value="${h(String(val))}">
        </div>`;
      }
      html += `</div>`;
    } else {
      for (const f of fields) {
        const val = f._val ?? '';
        html += `<div class="adm-field">
          <label>${h(f.label)}${f.required ? ' <span style="color:var(--red)">*</span>' : ''}</label>`;

        if (f.type === 'textarea') {
          html += `<textarea class="adm-inp adm-net-field" data-key="${h(f.key)}" rows="3">${h(String(val))}</textarea>`;

        } else if (f.type === 'select') {
          html += `<select class="adm-inp adm-net-field" data-key="${h(f.key)}">
            ${(f.options||[]).map(o => `<option value="${h(o)}" ${val==o?'selected':''}>${h(o)}</option>`).join('')}
          </select>`;

        } else if (f.type === 'tags') {
          // Tags: array stored as comma-separated or array in JSON
          const tagsVal = Array.isArray(val) ? val.join(', ') : String(val||'');
          html += `<input class="adm-inp adm-net-field" data-key="${h(f.key)}" data-type="tags"
            type="text" value="${h(tagsVal)}" placeholder="tag1, tag2, tag3">`;

        } else if (f.type === 'multicheck') {
          // Postback Whitelist — checkboxes
          const checked = Array.isArray(val) ? val : (val ? String(val).split(',').map(s=>s.trim()) : []);
          html += `<div class="adm-multicheck adm-net-field" data-key="${h(f.key)}" data-type="multicheck">
            ${(f.options||[]).map(o => `
              <label class="adm-multicheck-item">
                <input type="checkbox" value="${h(o)}" ${checked.includes(o)?'checked':''}>
                <span>${h(o)}</span>
              </label>`).join('')}
          </div>`;

        } else if (f.type === 'status_payout') {
          // Status–Payout Relation table
          const statuses = ['approved','pending','declined','trashed','hold','unknown'];
          const payoutTypes = ['revenue','cpa','cpl','cps','none'];
          // val could be object like {approved:'cpa', pending:'none', ...}
          const mapping = (val && typeof val === 'object') ? val : {};
          html += `<div class="adm-status-payout adm-net-field" data-key="${h(f.key)}" data-type="status_payout">
            <div class="adm-sp-header">
              <span>Статус конверсии</span><span>Тип выплаты</span>
            </div>
            ${statuses.map(s => `
              <div class="adm-sp-row">
                <span class="adm-sp-status adm-badge adm-sp-${s}">${s}</span>
                <select class="adm-inp adm-sp-sel" data-status="${s}">
                  ${payoutTypes.map(p => `<option value="${p}" ${(mapping[s]||'none')===p?'selected':''}>${p}</option>`).join('')}
                </select>
              </div>`).join('')}
          </div>`;

        } else {
          const inputType = f.type === 'number' ? 'number' : 'text';
          const monoStyle = f.wide ? 'style="font-family:monospace;font-size:.82em"' : '';
          html += `<input class="adm-inp adm-net-field" data-key="${h(f.key)}" type="${inputType}" value="${h(String(val))}" ${monoStyle}>`;
        }

        if (f.hint) html += `<div class="adm-hint">${h(f.hint)}</div>`;
        html += `</div>`;
      }
    }

    html += `</div>`;
  }

  // Partner access section
  html += `<div class="adm-drawer-section">
    <div class="adm-drawer-section-title">Доступ партнёра</div>
    ${acc.exists ? `
      <div class="adm-partner-acc-info">
        <div class="adm-partner-acc-row">
          <span class="adm-net-info-key">Логин</span>
          <b style="color:var(--text)">${h(acc.username || '—')}</b>
        </div>
        <div class="adm-partner-acc-row">
          <span class="adm-net-info-key">UID входа</span>
          <span class="adm-uid-pill" onclick="admCopyText('${h(acc.uid||'')}')" title="Нажмите скопировать">${h(acc.uid||'—')}</span>
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
        <button class="adm-btn sm" onclick="admRegenUID('${h(String(netId))}')">🎲 Новый UID</button>
        <button class="adm-btn sm" onclick="admChangePassword('${h(String(netId))}','${h(acc.username||'')}')">🔑 Сменить пароль</button>
        <button class="adm-btn sm danger" onclick="admDeleteAccount('${h(String(netId))}')">✕ Удалить аккаунт</button>
      </div>
    ` : `
      <div class="adm-hint" style="margin-bottom:12px">Нет аккаунта партнёра.</div>
      <div class="adm-form-row">
        <div class="adm-field">
          <label>Логин *</label>
          <input class="adm-inp" id="dAccUser" type="text" placeholder="partner_name">
        </div>
        <div class="adm-field">
          <label>Пароль <span style="color:var(--text3)">(авто)</span></label>
          <input class="adm-inp" id="dAccPass" type="text" placeholder="авто">
        </div>
      </div>
      <button class="adm-btn success" onclick="admCreateAccount('${h(String(netId))}')">+ Создать аккаунт</button>
      <div class="adm-err" id="dAccErr" style="margin-top:6px"></div>
    `}
  </div>

  <div style="display:flex;align-items:center;gap:12px;padding-bottom:8px">
    <button class="adm-btn primary" onclick="admSaveNetwork()">💾 Сохранить в Binom</button>
    <span id="admNetSaveMsg" class="adm-save-msg"></span>
  </div>`;

  bodyEl.innerHTML = html;
}

async function admSaveNetwork() {
  const fields = document.querySelectorAll('.adm-net-field');
  const body = {};
  fields.forEach(el => {
    const key = el.dataset.key;
    if (!key) return;
    const type = el.dataset.type;

    if (type === 'tags') {
      // tags → array
      body[key] = el.value.trim() ? el.value.split(',').map(s=>s.trim()).filter(Boolean) : [];
    } else if (type === 'multicheck') {
      // multicheck → array of checked values
      const checked = [...el.querySelectorAll('input[type=checkbox]:checked')].map(cb => cb.value);
      body[key] = checked;
    } else if (type === 'status_payout') {
      // status_payout → object
      const obj = {};
      el.querySelectorAll('.adm-sp-sel').forEach(sel => {
        obj[sel.dataset.status] = sel.value;
      });
      body[key] = obj;
    } else {
      body[key] = el.value.trim();
    }
  });

  const msg = document.getElementById('admNetSaveMsg');
  msg.style.color   = '#10b981';
  msg.textContent   = '⟳ Сохраняем…';
  msg.style.display = 'inline';

  const j = await admApi('PUT', `/api/admin/networks/${ADM.drawerNetId}`, body);

  if (j.ok) {
    msg.textContent = '✓ Сохранено в Binom';
    setTimeout(() => { msg.style.display = 'none'; }, 2500);
    const titleEl = document.getElementById('admDrawerTitle');
    if (body.name) titleEl.textContent = body.name;
    admLoadNetworks();
  } else {
    msg.style.color = '#ef4444';
    msg.textContent = '✗ ' + (j.error || 'Ошибка');
  }
}

function admCloseDrawer() {
  document.getElementById('admDrawer')?.classList.remove('open');
}

// ─── Requests ─────────────────────────────────────────────────────────────────

function admSetReqFilter(f, el) {
  ADM.reqFilter = f;
  document.querySelectorAll('.adm-filter-chips .adm-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  admLoadRequests();
}

async function admLoadPendingCount() {
  const j = await admApi('GET', '/api/admin/requests?status=pending');
  const cnt = j.requests?.length || 0;
  const el = document.getElementById('admPendingBadge');
  if (!el) return;
  el.style.display = cnt > 0 ? 'inline' : 'none';
  if (cnt > 0) el.textContent = cnt;
}

async function admLoadRequests() {
  const url = '/api/admin/requests' + (ADM.reqFilter ? '?status=' + ADM.reqFilter : '');
  const j = await admApi('GET', url);
  const tbody = document.getElementById('admRequestsTbody');
  if (!tbody) return;

  if (!j.ok || !j.requests?.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="adm-empty">Нет заявок</td></tr>`;
    return;
  }

  const SL = { pending: '⏳ Ожидает', approved: '✅ Одобрена', rejected: '❌ Отклонена' };
  tbody.innerHTML = j.requests.map(r => `<tr>
    <td class="adm-muted">${h(r.partner_name)}</td>
    <td class="adm-td-name">${h(r.offer_name)}</td>
    <td>${h(r.geo)}</td>
    <td>${h(r.rate) || '—'}</td>
    <td class="adm-td-url">
      ${r.offer_url ? `<a href="${h(r.offer_url)}" target="_blank">${h(r.offer_url)}</a>` : '—'}
    </td>
    <td class="adm-muted" style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
        title="${h(r.comment)}">${h(r.comment) || '—'}</td>
    <td><span class="adm-badge ${r.status}">${SL[r.status] || r.status}</span></td>
    <td class="adm-muted" style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
        title="${h(r.admin_comment)}">${h(r.admin_comment) || '—'}</td>
    <td class="adm-muted" style="white-space:nowrap">${r.created_at.slice(0, 10)}</td>
    <td>
      <div class="adm-td-actions">
        ${r.status !== 'approved' ? `<button class="adm-btn sm success" onclick="admOpenApprove(${r.id})">✓</button>` : ''}
        ${r.status !== 'rejected' ? `<button class="adm-btn sm danger"  onclick="admOpenReject(${r.id})">✗</button>` : ''}
        ${r.status !== 'pending'  ? `<button class="adm-btn sm" onclick="admSetPending(${r.id})" title="Вернуть">↺</button>` : ''}
      </div>
    </td>
  </tr>`).join('');
}

function admOpenApprove(id) {
  ADM.pendingReqId   = id;
  ADM.pendingReqData = null;
  ADM.altOffers      = [];

  // Reset fields
  ['admApproveOfferName','admApproveUrl','admApprovePostback',
   'admApproveCountry','admApproveRotId','admApproveComment',
   'admApprovePayout','admApproveMaxCap','admApproveWeight',
   'admApproveResetSec','admApproveResetFrom','admAltOfferSearch'].forEach(fid => {
    const el = document.getElementById(fid);
    if (el) el.value = fid === 'admApproveWeight' ? '50' : '';
  });
  document.getElementById('admApproveAutoPayout').checked = true;
  document.getElementById('admApproveConvCap').checked    = false;
  document.getElementById('admCapFields').style.display   = 'none';
  admInitRotationsList();
  document.getElementById('admApproveCurrency').value     = 'USD';
  document.getElementById('admApprovePriority').value     = 'offers_alternative';
  document.getElementById('admApproveBindomErr').textContent = '';
  document.getElementById('admApproveAltOffer').innerHTML = '<option value="">— нет —</option>';
  const geoSel = document.getElementById('admApproveGeo');
  geoSel.innerHTML = '<option value="">— нажмите GEO ↓ —</option>';

  // Load affiliate networks
  admApi('GET', '/api/binom/affiliate_networks').then(j => {
    const sel = document.getElementById('admApproveAffNet');
    if (j.ok && j.networks?.length) {
      ADM._affNetworks = j.networks;
      sel.innerHTML = '<option value="">— выберите сеть —</option>' +
        j.networks.map(n => `<option value="${n.id}">${h(n.name)}</option>`).join('');
    } else {
      sel.innerHTML = '<option value="">Нет сетей</option>';
    }
    admAutoSelectAffNet();
  });

  // Load countries from Binom
  ADM._countries = [];
  admApi('GET', '/api/binom/countries').then(j => {
    if (j.ok && j.countries?.length) {
      ADM._countries = j.countries.filter(c => c.code && c.name);
    }
    // Render initial full list in hidden dropdown
    admRenderCountryDrop('');
  });

  // Load alternative offers
  admApi('GET', '/api/binom/offers_list').then(j => {
    if (j.ok) {
      ADM.altOffers = j.offers || [];
      admRenderAltOffers(ADM.altOffers);
    }
  });

  // Load request info
  admApi('GET', '/api/admin/requests').then(j => {
    const req = (j.requests || []).find(r => r.id === id);
    if (!req) return;
    ADM.pendingReqData = req;

    const info = document.getElementById('admApproveInfo');
    info.innerHTML = [
      `<b style="color:var(--text);font-size:1.05em">${h(req.offer_name)}</b>`,
      `GEO: <b style="color:var(--accent)">${h(req.geo)}</b>`,
      req.rate     ? `Ставка: <b style="color:#3ecf8e">${h(req.rate)}</b>` : null,
      `Партнёр: <b>${h(req.partner_name)}</b>`,
      req.binom_network_id ? `Сеть: <b style="color:#818cf8">#${h(req.binom_network_id)}</b>` : null,
      req.offer_url ? `<br>🔗 <a href="${h(req.offer_url)}" target="_blank" style="color:#818cf8">${h(req.offer_url.slice(0,70))}...</a>` : null,
      req.comment   ? `<br>💬 ${h(req.comment)}` : null,
    ].filter(Boolean).join(' &nbsp;·&nbsp; ');

    // Pre-fill name
    const rawName  = req.offer_name || '';
    const capMatch = rawName.match(/\[([^\]]+)\]/);
    const capPart  = capMatch ? capMatch[1].replace('Unlimited','∞') : '';
    const nameBody = capMatch ? rawName.slice(capMatch[0].length).trim() : rawName;
    const geo      = (req.geo || '').trim().toUpperCase().slice(0,2);
    const rate     = req.rate ? ` + ${req.rate}` : '';
    const capPfx   = capPart ? `${capPart}! ` : '';
    document.getElementById('admApproveOfferName').value = `${capPfx}${nameBody}${rate}${geo ? ` (${geo})` : ''}`;

    if (req.offer_url) document.getElementById('admApproveUrl').value = req.offer_url;
    // Set country field (searchable)
    document.getElementById('admApproveCountryQ').value = geo;
    document.getElementById('admApproveCountry').value  = geo;
    admRenderCountryDrop(geo);

    const rateNum = parseFloat((req.rate || '').replace(/[^0-9.]/g, ''));
    if (!isNaN(rateNum) && rateNum > 0) document.getElementById('admApprovePayout').value = rateNum;

    const currMatch = (req.rate || '').match(/USD|EUR|BRL|GBP|CAD|AUD|TRY|UAH|KZT|PLN/);
    if (currMatch) document.getElementById('admApproveCurrency').value = currMatch[0];

    const capNum = (capPart || '').match(/CAP(\d+)/);
    if (capNum) {
      document.getElementById('admApproveConvCap').checked = true;
      document.getElementById('admCapFields').style.display = 'block';
      document.getElementById('admApproveMaxCap').value = capNum[1];
      // Default: 86400s (1 day), resetFrom stays empty until user fills it
      document.getElementById('admApproveResetSec').value = '86400';
      // Год вперёд от сейчас
      const d = new Date();
      d.setFullYear(d.getFullYear() + 1);
      const pad = n => String(n).padStart(2, '0');
      const resetFromVal = d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) +
                           'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
      document.getElementById('admApproveResetFrom').value = resetFromVal;
    }

    // Auto-select affiliate network by partner's binom_network_id
    admAutoSelectAffNet();

    // Подтягиваем postback URL партнёрки
    if (req.binom_network_id) {
      admApi('GET', `/api/admin/networks/${req.binom_network_id}`).then(netJ => {
        if (!netJ.ok) return;
        const net = netJ.network || {};
        const pb  = net.postback_url || net.postbackUrl || net.postback || '';
        const pbEl = document.getElementById('admApprovePostback');
        if (pbEl && !pbEl.value && pb) {
          pbEl.value = pb;
        }
      });
    }
  });

  document.getElementById('admModalApprove').style.display = 'flex';
}

function admShowCountryDrop() {
  const drop = document.getElementById('admCountryDrop');
  drop.style.display = 'block';
  admRenderCountryDrop(document.getElementById('admApproveCountryQ').value);
  // Close on outside click
  setTimeout(() => {
    const close = (e) => {
      if (!drop.contains(e.target) && e.target.id !== 'admApproveCountryQ') {
        drop.style.display = 'none';
        document.removeEventListener('click', close);
      }
    };
    document.addEventListener('click', close);
  }, 0);
}

function admFilterCountries(q) {
  admRenderCountryDrop(q);
  document.getElementById('admCountryDrop').style.display = 'block';
  // If exact 2-char match, set value directly
  if (q.length === 2) {
    document.getElementById('admApproveCountry').value = q.toUpperCase();
  }
}

function admRenderCountryDrop(q) {
  const drop = document.getElementById('admCountryDrop');
  if (!drop) return;
  const ql = (q || '').toLowerCase().trim();
  let list = ADM._countries || [];
  if (ql) {
    list = list.filter(c =>
      c.code.toLowerCase().startsWith(ql) ||
      c.name.toLowerCase().includes(ql)
    );
  }
  // Limit to 80 items
  list = list.slice(0, 80);
  if (!list.length) {
    drop.innerHTML = `<div style="padding:8px 12px;color:var(--text3);font-size:.8em">Не найдено — введите код вручную</div>`;
    return;
  }
  drop.innerHTML = list.map(c =>
    `<div onclick="admSelectCountry('${h(c.code)}','${h(c.name)}')"
          style="padding:7px 12px;cursor:pointer;font-size:.82em;display:flex;gap:10px;align-items:center;border-bottom:0.5px solid var(--border)"
          onmouseover="this.style.background='#1e2d45'" onmouseout="this.style.background=''">
       <span style="color:var(--accent);font-weight:600;min-width:28px">${h(c.code)}</span>
       <span style="color:var(--text2)">${h(c.name)}</span>
     </div>`
  ).join('');
}

function admSelectCountry(code, name) {
  document.getElementById('admApproveCountryQ').value = `${code} — ${name}`;
  document.getElementById('admApproveCountry').value  = code;
  document.getElementById('admCountryDrop').style.display = 'none';
}

function admAutoSelectAffNet() {
  const req = ADM.pendingReqData;
  if (!req?.binom_network_id) return;
  const sel = document.getElementById('admApproveAffNet');
  // Try exact match by id
  for (const opt of sel.options) {
    if (String(opt.value) === String(req.binom_network_id)) {
      opt.selected = true;
      return;
    }
  }
}

function admRenderAltOffers(offers) {
  const sel = document.getElementById('admApproveAltOffer');
  sel.innerHTML = '<option value="">— нет —</option>' +
    offers.map(o => `<option value="${h(String(o.id))}">${h(o.name)}${o.country ? ' · ' + h(o.country) : ''}</option>`).join('');
}

let _altSearchTm = null;
function admSearchAltOffers(q) {
  clearTimeout(_altSearchTm);
  _altSearchTm = setTimeout(() => {
    if (!q) { admRenderAltOffers(ADM.altOffers); return; }
    const ql = q.toLowerCase();
    admRenderAltOffers(ADM.altOffers.filter(o =>
      (o.name || '').toLowerCase().includes(ql) ||
      (o.country || '').toLowerCase().includes(ql)
    ));
  }, 200);
}

function admInsertToken(token) {
  const inp = document.getElementById('admApproveUrl');
  const pos = inp.selectionStart || inp.value.length;
  inp.value = inp.value.slice(0, pos) + token + inp.value.slice(pos);
  inp.focus();
  inp.setSelectionRange(pos + token.length, pos + token.length);
}

async function admLoadAllGeos() {
  const selected = admGetSelectedRotations();
  if (!selected.length) {
    document.getElementById('admApproveBindomErr').textContent = 'Выберите хотя бы одну ротацию';
    return;
  }
  const btn = document.getElementById('admLoadGeosBtn');
  btn.textContent = '⏳';
  btn.disabled = true;

  // Грузим GEO из всех выбранных ротаций параллельно
  const results = await Promise.all(
    selected.map(rotId => admApi('GET', `/api/rotation/${rotId}/active_offers_grouped`))
  );

  btn.textContent = 'GEO ↓';
  btn.disabled = false;

  const errEl = document.getElementById('admApproveBindomErr');
  errEl.textContent = '';

  // Собираем уникальные GEO из всех ротаций
  const geoSet = new Map(); // geoTitle → count of rotations
  for (const j of results) {
    if (!j.ok) continue;
    for (const g of (j.groups || [])) {
      const key = g.geoTitle;
      geoSet.set(key, (geoSet.get(key) || 0) + 1);
    }
  }

  if (!geoSet.size) { errEl.textContent = 'Нет GEO в выбранных ротациях'; return; }

  // Сортируем — сначала те что есть во всех ротациях
  const geosSorted = [...geoSet.entries()]
    .sort(([,a],[,b]) => b - a)
    .map(([title, cnt]) => ({ title, cnt }));

  const geoSel = document.getElementById('admApproveGeo');
  geoSel.innerHTML = '<option value="">— выберите GEO —</option>' +
    geosSorted.map(g => {
      const badge = g.cnt === selected.length ? '' : ` (${g.cnt}/${selected.length} ротаций)`;
      return `<option value="${h(g.title)}">${h(g.title)}${badge}</option>`;
    }).join('');

  // Автовыбор по GEO заявки
  const reqGeo = (ADM.pendingReqData?.geo || '').toUpperCase().slice(0,2);
  if (reqGeo) {
    for (const opt of geoSel.options) {
      if (opt.value.toUpperCase().includes(reqGeo)) { opt.selected = true; break; }
    }
  }
}

// Совместимость со старым кодом
async function admLoadGeos() { return admLoadAllGeos(); }

function admOpenReject(id) {
  ADM.pendingReqId = id;
  document.getElementById('admRejectComment').value = '';
  document.getElementById('admModalReject').style.display = 'flex';
}

async function admSubmitApproveOnly() {
  const comment = document.getElementById('admApproveComment').value.trim();
  await admApi('POST', `/api/admin/requests/${ADM.pendingReqId}/approve`, { comment });
  admCloseModal('admModalApprove');
  admLoadRequests();
  admLoadPendingCount();
}

async function admSubmitApprove() {
  const errEl = document.getElementById('admApproveBindomErr');
  errEl.textContent = '';
  errEl.style.color  = '#e05050';

  const name       = document.getElementById('admApproveOfferName').value.trim();
  const url        = document.getElementById('admApproveUrl').value.trim();
  const postback   = document.getElementById('admApprovePostback').value.trim();
  const affNet     = document.getElementById('admApproveAffNet').value;
  const country    = document.getElementById('admApproveCountry').value.trim();
  const payout     = parseFloat(document.getElementById('admApprovePayout').value) || 0;
  const currency   = document.getElementById('admApproveCurrency').value;
  const autoPay    = document.getElementById('admApproveAutoPayout').checked;
  const convCap    = document.getElementById('admApproveConvCap').checked;
  const maxCap     = parseInt(document.getElementById('admApproveMaxCap').value) || null;
  const resetSec   = parseInt(document.getElementById('admApproveResetSec').value) || null;
  // resetFrom only valid together with resetSec — Binom 500s on strtoupper(null) otherwise
  const _resetFromRaw = document.getElementById('admApproveResetFrom').value;
  const resetFrom  = (resetSec && _resetFromRaw) ? _resetFromRaw : null;
  const altOffer   = document.getElementById('admApproveAltOffer').value || null;
  // priority — не поле оффера в Binom, убираем из payload
  // const priority = document.getElementById('admApprovePriority').value;
  const rotIds     = admGetSelectedRotations();
  const geo        = document.getElementById('admApproveGeo').value.trim();
  const weight     = parseInt(document.getElementById('admApproveWeight').value) || 50;
  const comment    = document.getElementById('admApproveComment').value.trim();

  if (!name) { errEl.textContent = 'Укажите название оффера'; return; }
  if (!url)  { errEl.textContent = 'Укажите URL оффера'; return; }
  if (rotIds.length && !geo) { errEl.textContent = 'Выберите GEO для ротаций'; return; }

  errEl.style.color = '#94a3b8';
  errEl.textContent = '⏳ Создаю оффер в Binom...';

  // Создаём оффер (без ротации — потом добавим в каждую)
  const payload = {
    name, url,
    postback_url:          postback   || undefined,
    affiliate_network_id:  affNet     || undefined,
    country:               country    || undefined,
    payout:                payout     || undefined,
    currency,
    auto_payout:           autoPay,
    conversion_cap:        convCap,
    max_cap:               convCap && maxCap ? maxCap : undefined,
    reset_cap_seconds:     convCap && resetSec ? resetSec : undefined,
    reset_cap_from:        convCap && resetFrom ? resetFrom : undefined,
    alternative_offer_id:  altOffer   || undefined,
  };

  const j = await admApi('POST', '/api/binom/offers', payload);
  if (!j.ok) {
    errEl.style.color = '#e05050';
    errEl.textContent = '❌ ' + (j.error || 'Ошибка создания оффера');
    return;
  }

  const offerId    = j.binom_offer_id;
  const offerIdMsg = offerId ? ` (ID: ${offerId})` : '';
  errEl.textContent = `✅ Оффер создан${offerIdMsg}`;

  // Добавляем в каждую выбранную ротацию отдельным запросом
  console.log('[approve] rotIds:', rotIds, 'geo:', geo, 'offerId:', offerId);
  const rotResults = [];
  for (const rotId of rotIds) {
    errEl.textContent = `⏳ Добавляю в ротацию #${rotId}...`;
    const partnerName = ADM.pendingReqData?.partner_name || '';
    const rj = await admApi('POST', '/api/binom/offers/add_to_rotation', {
      offer_id: offerId, rotation_id: rotId, geo, weight,
      offer_name: name,
      max_cap:      (convCap && maxCap) ? maxCap : undefined,
      partner_name: partnerName,
      rate:         payout || undefined,
      currency:     currency || 'USD',
    });
    console.log('[add_to_rotation] rotId:', rotId, 'response:', rj);
    rotResults.push({ rotId, ok: rj.ok, error: rj.rotation_error || rj.error });
  }

  const rotOk  = rotResults.filter(r => r.ok).map(r => '#' + r.rotId).join(', ');
  const rotFail = rotResults.filter(r => !r.ok).map(r => `#${r.rotId}: ${r.error}`).join('; ');
  const rotMsg  = rotOk ? ` + ротации: ${rotOk} ✓` : '';
  const rotErrMsg = rotFail ? ` ⚠️ ${rotFail}` : '';

  errEl.style.color = '#3ecf8e';
  errEl.textContent = `✅ Оффер создан${offerIdMsg}${rotMsg}${rotErrMsg}`;

  await admApi('POST', `/api/admin/requests/${ADM.pendingReqId}/approve`, {
    comment: comment || `Оффер создан в Binom${offerIdMsg}${rotMsg}`,
    rotation_id: rotIds[0] || undefined,
  });

  setTimeout(() => {
    admCloseModal('admModalApprove');
    admLoadRequests();
    admLoadPendingCount();
  }, 1500);
}
async function admSetPending(id) {
  await admApi('POST', `/api/admin/requests/${id}/pending`);
  admLoadRequests();
}

// ─── Users ────────────────────────────────────────────────────────────────────

async function admLoadUsers() {
  const j = await admApi('GET', '/api/admin/partners');
  const tbody = document.getElementById('admUsersTbody');
  if (!tbody) return;

  if (!j.ok || !j.partners?.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="adm-empty">Нет пользователей</td></tr>`;
    return;
  }

  tbody.innerHTML = j.partners.map(u => `<tr>
    <td class="adm-td-name">${h(u.username)}</td>
    <td><span class="adm-badge ${u.role}">${u.role}</span></td>
    <td>${u.uid ? `<span class="adm-uid-pill" onclick="navigator.clipboard.writeText('${h(u.uid)}')">${h(u.uid)}</span>` : '—'}</td>
    <td class="adm-muted">${(u.created_at || '').slice(0, 10)}</td>
    <td>
      <div class="adm-td-actions">
        <button class="adm-btn sm" onclick="admResetTok(${u.id})" title="Сбросить токен">🔑</button>
        <button class="adm-btn sm danger" onclick="admDeleteUser(${u.id})">✕</button>
      </div>
    </td>
  </tr>`).join('');
}

function admOpenCreateUser() {
  ['admCuUser', 'admCuPass'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('admCuErr').textContent = '';
  document.getElementById('admModalCreateUser').style.display = 'flex';
  document.getElementById('admCuUser').focus();
}
async function admSubmitCreateUser() {
  const j = await admApi('POST', '/api/admin/partners', {
    username: document.getElementById('admCuUser').value.trim(),
    password: document.getElementById('admCuPass').value.trim(),
    role:     document.getElementById('admCuRole').value,
  });
  if (!j.ok) { document.getElementById('admCuErr').textContent = j.error || 'Ошибка'; return; }
  admCloseModal('admModalCreateUser');
  admLoadUsers();
}
async function admDeleteUser(id) {
  if (!confirm('Удалить пользователя?')) return;
  await admApi('DELETE', `/api/admin/partners/${id}`);
  admLoadUsers();
}
async function admResetTok(id) {
  const j = await admApi('POST', `/api/admin/partners/${id}/reset_token`);
  if (j.ok) alert('Новый токен: ' + j.token);
}



// ─── Partner account helpers ──────────────────────────────────────────────────

function admCopyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    const msg = document.createElement('div');
    msg.textContent = 'Скопировано!';
    msg.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#10b981;color:#fff;padding:8px 16px;border-radius:8px;font-size:.85em;z-index:9999';
    document.body.appendChild(msg);
    setTimeout(() => msg.remove(), 1500);
  });
}

async function admCreateAccount(netId) {
  const errEl = document.getElementById('dAccErr');
  const username = document.getElementById('dAccUser')?.value.trim();
  const password = document.getElementById('dAccPass')?.value.trim();
  if (!username) { if (errEl) errEl.textContent = 'Укажите логин'; return; }
  if (errEl) errEl.textContent = '';
  const j = await admApi('POST', `/api/admin/networks/${netId}/create_account`, {
    username, password: password || undefined,
  });
  if (!j.ok) { if (errEl) errEl.textContent = j.error || 'Ошибка создания'; return; }
  admOpenDrawer(netId);
  admLoadNetworks();
}

async function admChangePassword(netId, username) {
  // Убираем старый модал если есть
  document.getElementById('admChangePassModal')?.remove();

  const modal = document.createElement('div');
  modal.id = 'admChangePassModal';
  modal.className = 'adm-overlay';
  modal.style.cssText = 'z-index:9000';
  modal.innerHTML = `
    <div style="background:var(--bg2);border:0.5px solid var(--border2);border-radius:12px;padding:24px;width:360px">
      <div style="font-size:1em;font-weight:600;color:var(--text);margin-bottom:16px">🔑 Сменить пароль</div>
      <div style="color:var(--text2);font-size:.85em;margin-bottom:12px">Партнёр: <b style="color:var(--text)">${username}</b></div>
      <div class="adm-field">
        <label>Новый пароль *</label>
        <input class="adm-inp" id="newPassInp" type="text" placeholder="Введите пароль">
      </div>
      <div style="display:flex;gap:6px;margin-top:4px;margin-bottom:12px">
        <button class="adm-btn sm" onclick="document.getElementById('newPassInp').value=Math.random().toString(36).slice(2,10)">🎲 Авто</button>
      </div>
      <div class="adm-err" id="changePassErr" style="margin-bottom:8px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="adm-btn" onclick="document.getElementById('admChangePassModal').remove()">Отмена</button>
        <button class="adm-btn primary" onclick="admSubmitChangePassword('${netId}')">💾 Сохранить</button>
      </div>
    </div>`;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  (document.getElementById('adminOverlay') || document.body).appendChild(modal);
  document.getElementById('newPassInp').focus();
}

async function admSubmitChangePassword(netId) {
  const errEl = document.getElementById('changePassErr');
  const pass  = document.getElementById('newPassInp').value.trim();
  if (!pass) { errEl.textContent = 'Введите пароль'; return; }

  // Получаем user id через детали сети
  const jNet = await admApi('GET', `/api/admin/networks/${netId}`);
  if (!jNet.ok || !jNet.account?.id) { errEl.textContent = 'Не удалось получить данные'; return; }

  const userId = jNet.account.id;
  const j = await admApi('POST', `/api/admin/partners/${userId}/change_password`, { password: pass });
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }

  document.getElementById('admChangePassModal').remove();
  // Показываем новый пароль
  alert(`✅ Пароль изменён!

Логин: ${jNet.account.username || ''}
Пароль: ${pass}`);
}

async function admRegenUID(netId) {
  if (!confirm('Сгенерировать новый UID? Старый перестанет работать.')) return;
  const j = await admApi('POST', `/api/admin/networks/${netId}/regen_uid`);
  if (j.ok) { admOpenDrawer(netId); }
  else { alert('Ошибка: ' + (j.error || 'не удалось обновить UID')); }
}

async function admDeleteAccount(netId) {
  if (!confirm('Удалить аккаунт партнёра?')) return;
  const j = await admApi('DELETE', `/api/admin/networks/${netId}/account`);
  if (j.ok) { admOpenDrawer(netId); admLoadNetworks(); }
  else { alert('Ошибка: ' + (j.error || 'не удалось удалить аккаунт')); }
}

async function admSubmitReject() {
  const comment = document.getElementById('admRejectComment').value.trim();
  const j = await admApi('POST', `/api/admin/requests/${ADM.pendingReqId}/reject`, { comment });
  if (!j.ok) { alert('Ошибка: ' + (j.error || 'не удалось отклонить')); return; }
  admCloseModal('admModalReject');
  admLoadRequests();
  admLoadPendingCount();
}

async function admSubmitCreateNet() {
  const errEl = document.getElementById('admCnErr');
  errEl.textContent = '';
  const name     = document.getElementById('admCnName').value.trim();
  const postback = document.getElementById('admCnPostback').value.trim();
  const notes    = document.getElementById('admCnNotes').value.trim();
  if (!name) { errEl.textContent = 'Укажите название'; return; }
  const j = await admApi('POST', '/api/admin/networks', { name, postback_url: postback, notes });
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }
  admCloseModal('admModalCreateNet');
  admLoadNetworks();
}



// ══════════════════════════════════════════════════════════
// ADMIN NOTIFICATIONS
// ══════════════════════════════════════════════════════════

let _notifInterval = null;

function admStartNotifications() {
  admPollNotifications();
  _notifInterval = setInterval(admPollNotifications, 30000); // every 30s
}

async function admPollNotifications() {
  const j = await admApi('GET', '/api/admin/notifications');
  if (!j.ok) return;
  const unread = j.unread || 0;
  const bell   = document.getElementById('admNotifBell');
  const badge  = document.getElementById('admNotifBadge');
  if (badge) {
    badge.textContent = unread;
    badge.style.display = unread ? '' : 'none';
  }
  if (bell) bell.classList.toggle('adm-bell--active', unread > 0);
  window._admNotifications = j.notifications || [];
}

function admToggleNotifications() {
  const panel = document.getElementById('admNotifPanel');
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  if (!open) {
    admRenderNotifications();
    // Mark all read
    admApi('POST', '/api/admin/notifications/read', {});
    setTimeout(() => {
      const badge = document.getElementById('admNotifBadge');
      if (badge) badge.style.display = 'none';
      const bell = document.getElementById('admNotifBell');
      if (bell) bell.classList.remove('adm-bell--active');
    }, 500);
  }
}

function admRenderNotifications() {
  const list = document.getElementById('admNotifList');
  if (!list) return;
  const notifs = window._admNotifications || [];
  if (!notifs.length) {
    list.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text3);font-size:.82rem">Нет уведомлений</div>';
    return;
  }
  const icons = { hold_paid: '💰', invoice_review: '📋' };
  list.innerHTML = notifs.map(n => `
    <div class="adm-notif-item ${n.read ? '' : 'adm-notif-item--unread'}"
      onclick="${n.invoice_id ? `admInvOpenModal(${n.invoice_id});admToggleNotifications()` : ''}">
      <div class="adm-notif-icon">${icons[n.type] || '🔔'}</div>
      <div class="adm-notif-body">
        <div class="adm-notif-text">${h(n.text)}</div>
        <div class="adm-notif-time">${(n.created_at||'').slice(5,16)}</div>
      </div>
    </div>`).join('');
}

// Close on outside click
document.addEventListener('click', e => {
  const panel = document.getElementById('admNotifPanel');
  const bell  = document.getElementById('admNotifBell');
  if (panel && bell && !panel.contains(e.target) && !bell.contains(e.target)) {
    panel.style.display = 'none';
  }
});

const APPROACHES = ['Crash', 'Betting', 'Casino', 'Slots', 'Mixed', 'Другое'];

async function admLoadRates() {
  // Предзагружаем кеш офферов чтобы знать в каких ротациях стоит каждый оффер
  await _getOffersCache();
  const el = document.getElementById('admRatesContent');
  if (!el) return;

  // Грузим сохранённые ставки и трекинг параллельно
  const [jr, jt] = await Promise.all([
    admApi('GET', '/api/rates'),
    admApi('GET', '/api/tracking/offers?_=' + Date.now()),
  ]);

  _rates = (jr.ok ? jr.rates : null) || {};

  // Подмешиваем ставки из трекинга
  const tracking = jt.ok ? (jt.offers || {}) : {};

  // Маппинг rotation_id → подход
  const rotToApproach = { '121': 'Crash', '118': 'Betting', '124': 'Casino', '61': 'Slots', '117': 'Mixed' };

  // Кеш ротаций для поиска оффера во всех ротациях
  const cachedRots = _offersCache || [];

  for (const [id, o] of Object.entries(tracking)) {
    if (!o.rate) continue;
    const geo = (o.geo || '').toUpperCase();
    if (!geo) continue;

    // Ищем этот оффер во всех ротациях кеша
    const foundApproaches = new Set();
    for (const rot of cachedRots) {
      const inRot = (rot.geos || []).some(g => (g.offers || []).some(off => String(off.offer_id) === String(id)));
      if (inRot) {
        const app = rotToApproach[String(rot.id)] || rot.name || 'Другое';
        foundApproaches.add(app);
      }
    }

    // Если кеш пустой — fallback на rotation_id из трекинга
    if (!foundApproaches.size) {
      const app = rotToApproach[o.rotation_id] || o.rotation_id || 'Другое';
      if (app) foundApproaches.add(app);
    }

    for (const approach of foundApproaches) {
      if (!_rates[approach]) _rates[approach] = {};
      if (!_rates[approach][geo]) _rates[approach][geo] = [];
      const exists = _rates[approach][geo].some(r => r.rate === o.rate && r.currency === (o.currency || 'USD'));
      if (!exists) {
        _rates[approach][geo].push({
          rate:     o.rate,
          currency: o.currency || 'USD',
          note:     o.partner_name ? `Партнёр: ${o.partner_name}` : '',
          from_tracking: true,
          rotation: approach,
        });
      }
    }
  }

  admRenderRates();
}

function admRenderRates() {
  const el = document.getElementById('admRatesContent');
  if (!el) return;

  let html = '';
  for (const approach of APPROACHES) {
    const geos = _rates[approach] || {};
    const geoEntries = Object.entries(geos).sort(([a],[b]) => a.localeCompare(b));
    const totalRates = geoEntries.reduce((s,[,rows]) => s + (rows||[]).length, 0);

    html += `<div class="rates-section">
      <div class="rates-approach-title">${h(approach)}
        <span class="rates-approach-count">${totalRates} ставок · ${geoEntries.length} GEO</span>
      </div>
      <div class="rates-geos">
        ${geoEntries.length ? geoEntries.map(([geo, rows]) => {
          const ratesHtml = (rows||[]).map((r, ri) => `
            <div class="rates-row">
              <span class="rates-val">${h(String(r.rate||''))}</span>
              <span class="rates-cur">${h(r.currency||'USD')}</span>
              ${r.note ? `<span class="rates-note">${h(r.note)}</span>` : ''}
              ${r.from_tracking ? `<span class="rates-tag">📌 трекинг</span>` + (r.rotation ? `<span class="rates-tag" style="background:rgba(99,102,241,.12);color:#818cf8">${h(r.rotation)}</span>` : '') + `` : `
                <div class="rates-row-actions">
                  <button class="trkc-act" onclick="admRatesEdit('${h(approach)}','${h(geo)}',${ri})" title="Редактировать">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button class="trkc-act trkc-act--del" onclick="admRatesDelete('${h(approach)}','${h(geo)}',${ri})" title="Удалить">
                    <svg width="10" height="10" viewBox="0 0 10 10"><line x1="1" y1="1" x2="9" y2="9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><line x1="9" y1="1" x2="1" y2="9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
                  </button>
                </div>`}
            </div>`).join('');

          return `<div class="rates-geo-item" id="rg-${h(approach)}-${h(geo)}">
            <div class="rates-geo-head" onclick="admToggleGeo('rg-${h(approach)}-${h(geo)}')">
              <span class="rates-geo-dot"></span>
              <span class="rates-geo-name">${h(geo)}</span>
              <span class="rates-geo-count">${(rows||[]).length} ставок</span>
              <svg class="rates-geo-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </div>
            <div class="rates-geo-body">${ratesHtml}</div>
          </div>`;
        }).join('') : `<div class="adm-empty" style="padding:12px">Нет ставок</div>`}
      </div>
    </div>`;
  }
  el.innerHTML = html;
}

function admFilterRates(q) {
  const ql = q.trim().toUpperCase();
  document.querySelectorAll('.rates-geo-item').forEach(el => {
    const geo = el.querySelector('.rates-geo-name')?.textContent || '';
    const match = !ql || geo.toUpperCase().includes(ql);
    el.style.display = match ? '' : 'none';
    if (match && ql) el.classList.add('open'); // auto-open on search
  });
}

function admToggleGeo(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('open');
}

function admRatesAddRow() {
  admRatesModal(null, null, null);
}

function admRatesEdit(approach, geo, idx) {
  const r = (_rates[approach]?.[geo] || [])[idx] || {};
  admRatesModal(approach, geo, { ...r, _idx: idx });
}

function admRatesModal(approach, geo, data) {
  document.getElementById('admRatesModal')?.remove();
  const isNew = data === null;
  const modal = document.createElement('div');
  modal.id = 'admRatesModal';
  modal.className = 'adm-overlay';
  modal.style.cssText = 'z-index:9000';
  modal.innerHTML = `
    <div style="background:var(--bg2);border:0.5px solid var(--border2);;border:0.5px solid var(--border);border-radius:12px;padding:24px;width:420px">
      <div style="font-size:1em;font-weight:600;color:var(--text);margin-bottom:16px">
        ${isNew ? '+ Добавить ставку' : '✏️ Редактировать ставку'}
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field">
          <label>Подход *</label>
          <select class="adm-inp" id="rateApproach">
            ${APPROACHES.map(a => `<option value="${a}" ${approach===a?'selected':''}>${a}</option>`).join('')}
          </select>
        </div>
        <div class="adm-field">
          <label>GEO *</label>
          <input class="adm-inp" id="rateGeo" type="text" placeholder="BR, FR, TR..." value="${h(geo||'')}" style="text-transform:uppercase">
        </div>
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field">
          <label>Ставка *</label>
          <input class="adm-inp" id="rateValue" type="number" step="0.01" placeholder="25" value="${h(String(data?.rate||''))}">
        </div>
        <div class="adm-field">
          <label>Валюта</label>
          <select class="adm-inp" id="rateCurrency">
            ${CURRENCIES.map(c => `<option value="${c}" ${(data?.currency||'USD')===c?'selected':''}>${c}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="adm-field">
        <label>Заметка</label>
        <input class="adm-inp" id="rateNote" type="text" placeholder="Например: RevShare 30%" value="${h(data?.note||'')}">
      </div>
      <div class="adm-err" id="rateErr" style="margin-bottom:8px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="adm-btn" onclick="document.getElementById('admRatesModal').remove()">Отмена</button>
        <button class="adm-btn primary" onclick="admRatesSave(${isNew ? 'null' : `'${h(approach)}','${h(geo)}',${data?._idx}`})">💾 Сохранить</button>
      </div>
    </div>`;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  (document.getElementById('adminOverlay') || document.body).appendChild(modal);
  document.getElementById('rateGeo').focus();
}

async function admRatesSave(oldApproach, oldGeo, oldIdx) {
  const errEl    = document.getElementById('rateErr');
  const approach = document.getElementById('rateApproach').value;
  const geo      = document.getElementById('rateGeo').value.trim().toUpperCase();
  const rate     = parseFloat(document.getElementById('rateValue').value);
  const currency = document.getElementById('rateCurrency').value;
  const note     = document.getElementById('rateNote').value.trim();

  if (!geo || isNaN(rate)) { errEl.textContent = 'Укажите GEO и ставку'; return; }

  // Удаляем старую если редактирование
  if (oldApproach !== null && oldApproach !== undefined) {
    const arr = _rates[oldApproach]?.[oldGeo] || [];
    arr.splice(oldIdx, 1);
    if (!arr.length) delete _rates[oldApproach][oldGeo];
    else _rates[oldApproach][oldGeo] = arr;
  }

  // Добавляем новую
  if (!_rates[approach]) _rates[approach] = {};
  if (!_rates[approach][geo]) _rates[approach][geo] = [];
  _rates[approach][geo].push({ rate, currency, note });

  const j = await admApi('POST', '/api/rates', { rates: _rates });
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }
  document.getElementById('admRatesModal').remove();
  admRenderRates();
}

async function admRatesDelete(approach, geo, idx) {
  if (!confirm('Удалить эту ставку?')) return;
  const arr = _rates[approach]?.[geo] || [];
  arr.splice(idx, 1);
  if (!arr.length) delete _rates[approach][geo];
  else _rates[approach][geo] = arr;
  await admApi('POST', '/api/rates', { rates: _rates });
  admRenderRates();
}

// ── Stop offer ───────────────────────────────────────────────────────────────






// ── FD Countdown ─────────────────────────────────────────────────────────────
let _fdCountdownTimer  = null;
let _fdCountdownSecs   = 600; // 10 min

function admStartFdCountdown() {
  if (_fdCountdownTimer) clearInterval(_fdCountdownTimer);
  _fdCountdownSecs = 600;
  _admUpdateFdBtn();
  _fdCountdownTimer = setInterval(() => {
    _fdCountdownSecs--;
    if (_fdCountdownSecs < 0) _fdCountdownSecs = 600;
    _admUpdateFdBtn();
  }, 1000);
}

function _admUpdateFdBtn() {
  const btn = document.getElementById('trkFdBtn');
  if (!btn) return;
  const s = _fdCountdownSecs;
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  const isNear = s <= 30;
  btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> FD · <span style="font-family:monospace;letter-spacing:.02em;color:${isNear ? 'var(--green)' : 'inherit'}">${mm}:${ss}</span>`;
}

let _trackingSort   = { col: 'pct', dir: -1 }; // -1 = desc
let _trackingFilter = 'active'; // active | stopped | no_perform | all
let _trackingSearch = '';

let _trackingRefreshTimer = null;
let _trackingLastUpdated  = null;

function admStartTrackingAutoRefresh() {
  admStopTrackingAutoRefresh();
  // Перезагружаем трекинг каждые 10 минут — синхронно с scheduler
  _trackingRefreshTimer = setInterval(() => {
    admLoadTracking();
  }, 600000);
}

function admStopTrackingAutoRefresh() {
  if (_trackingRefreshTimer) {
    clearInterval(_trackingRefreshTimer);
    _trackingRefreshTimer = null;
  }
  _trackingLastUpdated = null;
}

function trkSetFilter(f, btn) {
  _trackingFilter = f;
  document.querySelectorAll('.trk-filter').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  admRenderTracking();
}

function trkSetSearch(val) {
  _trackingSearch = val.trim().toLowerCase();
  admRenderTrackingCards();  // не перезапрашивает сервер, только перерисовывает
}

function trkToggleSort(col) {
  if (_trackingSort.col === col) _trackingSort.dir *= -1;
  else { _trackingSort.col = col; _trackingSort.dir = -1; }
  admRenderTracking();
}

function trkSortArrow(col) {
  if (_trackingSort.col !== col) return '<span style="color:#334155;font-size:.8em">⇅</span>';
  return _trackingSort.dir === -1 ? '▼' : '▲';
}

async function admRefreshTrackingFD() {
  _fdCountdownSecs = 600;
  _admUpdateFdBtn();
  const btn = event?.target;
  if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }
  const j = await admApi('POST', '/api/tracking/fd/refresh');
  if (btn) { btn.disabled = false; btn.textContent = 'Обновить FD'; }
  if (j.ok) {
    const msg = document.getElementById('admNetSaveMsg'); if(msg){msg.textContent='FD обновляется...';msg.style.display='inline';setTimeout(()=>msg.style.display='none',5000);}
    setTimeout(() => admLoadTracking(), 15000);
  } else {
    alert(j.error || 'Ошибка');
  }
}

async function admLoadTracking() {
  const el = document.getElementById('admTrackingTable');
  el.innerHTML = '<div class="adm-empty"><div class="spinner"></div></div>';


  if (!el) return;

  const [j, jfd] = await Promise.all([
    admApi('GET', '/api/tracking/offers?_=' + Date.now()),
    admApi('GET', '/api/tracking/fd?_=' + Date.now()),
  ]);
  if (!j.ok) { el.innerHTML = '<div class="adm-empty">Ошибка загрузки</div>'; return; }

  const offers = Object.entries(j.offers || {});
  // Нормализуем ключи fdMap в строки — Binom может возвращать числовые id
  const rawFd  = jfd.fd || {};
  const fdMap  = Object.fromEntries(Object.entries(rawFd).map(([k,v]) => [String(k), v]));

  // Filter
  // Сохраняем данные для быстрой перерисовки
  window._trkData = { j, jfd, fdMap, offers };
  admRenderTracking();
}

function admRenderTracking() {
  admRenderTrackingCards();
}
function admRenderTrackingCards() {
  if (!window._trkData) return;
  const { j, jfd, fdMap, offers } = window._trkData;

  const byStatus = _trackingFilter === 'all' ? offers
    : offers.filter(([,o]) => (o.status || 'active') === _trackingFilter);

  // Умный поиск: по названию, GEO, партнёру, ID
  const filtered = !_trackingSearch ? byStatus : byStatus.filter(([id, o]) => {
    const q = _trackingSearch;
    const name    = (o.name || '').toLowerCase();
    const geo     = (o.geo  || '').toLowerCase();
    const partner = (o.partner_name || '').toLowerCase();
    const oid     = String(id).toLowerCase();
    const groupIds = (o.group_ids || '').toLowerCase();

    // Точное совпадение GEO (напр. "BR")
    if (geo === q) return true;
    // Совпадение ID
    if (oid === q) return true;
    // Частичное по имени, партнёру, GEO, group_ids
    return name.includes(q) || geo.includes(q) || partner.includes(q) || groupIds.includes(q);
  });

  // Sort
  const sorted = filtered.slice().sort(([ia, a], [ib, b]) => {
    const fda = fdMap[ia]?.fd ?? -1, fdb = fdMap[ib]?.fd ?? -1;
    const ca = a.max_cap || 0, cb = b.max_cap || 0;
    if (_trackingSort.col === 'pct') {
      const pa = ca ? fda/ca : -1, pb = cb ? fdb/cb : -1;
      return _trackingSort.dir * (pa - pb);
    }
    if (_trackingSort.col === 'fd') return _trackingSort.dir * (fda - fdb);
    return 0;
  });

  const statusDefs = {
    active:     { color: '#10b981', label: 'Активен' },
    stopped:    { color: '#ef4444', label: 'Стоп' },
    no_perform: { color: '#f59e0b', label: 'Не перф' },
    unknown:    { color: '#6b7280', label: 'Неизв.' },
  };

  const filterBar = `
    <div class="trk-filter-row">
      <button class="trk-chip ${_trackingFilter==='active'?'trk-chip--active':''}"
        onclick="trkSetFilter('active',this)">
        <span class="trk-chip-dot" style="background:#10b981"></span>Активные
      </button>
      <button class="trk-chip ${_trackingFilter==='stopped'?'trk-chip--active':''}"
        onclick="trkSetFilter('stopped',this)">
        <span class="trk-chip-dot" style="background:#ef4444"></span>Стопнутые
      </button>
      <button class="trk-chip ${_trackingFilter==='no_perform'?'trk-chip--active':''}"
        onclick="trkSetFilter('no_perform',this)">
        <span class="trk-chip-dot" style="background:#f59e0b"></span>Не перформ
      </button>
      <button class="trk-chip ${_trackingFilter==='all'?'trk-chip--active':''}"
        onclick="trkSetFilter('all',this)">Все</button>
      <button class="trk-chip trk-chip--sort" onclick="trkToggleSort('pct')">
        FD ${trkSortArrow('pct')}
      </button>
      <div class="trk-search-wrap">
        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        <input class="trk-search-inp" id="trkSearchInput" type="text"
          placeholder="Поиск по названию, GEO, партнёру..."
          value="${h(_trackingSearch)}"
          oninput="trkSetSearch(this.value)"
          onkeydown="if(event.key==='Escape'){trkSetSearch('');this.value=''}">
        ${_trackingSearch ? `<button class="trk-search-clear" onclick="trkSetSearch('');document.getElementById('trkSearchInput').value=''">✕</button>` : ''}
      </div>
    </div>`;

  if (!sorted.length) {
    const listEl = document.getElementById('trkCardsList');
    if (listEl) {
      listEl.innerHTML = '<div class="adm-empty">Нет офферов в этой категории</div>';
    } else {
      el.innerHTML = filterBar + '<div id="trkCardsList"><div class="adm-empty">Нет офферов в этой категории</div></div>';
    }
    return;
  }

  const cards = sorted.map(([id, o]) => {
    const fdInfo  = fdMap[String(id)] || fdMap[id] || {};
    const fd      = fdInfo.fd;
    const maxCap  = o.max_cap;
    const pct     = (maxCap && fd != null) ? Math.min(100, Math.round(fd / maxCap * 100)) : null;
    const capColor = pct >= 90 ? '#ef4444' : pct >= 70 ? '#f59e0b' : '#10b981';
    const status   = o.status || 'active';
    const sd       = statusDefs[status] || statusDefs.unknown;
    const updAt    = fdInfo.updated_at ? fdInfo.updated_at.slice(11,16) : '';
    const rotName  = { '121':'Crash','118':'Betting','124':'Casino','61':'Slots','117':'Mixed' }[o.rotation_id] || (o.rotation_id ? '#'+o.rotation_id : '—');

    return `<div class="trkc">
      <div class="trkc-dot" style="background:${sd.color}"></div>
      <div class="trkc-body">

        <div class="trkc-row1">
          <div class="trkc-name" onclick="admEditTrackingName('${h(id)}')" title="Редактировать">
            ${h(o.name || '—')}
            ${o.auto_stop_pct ? `<span class="trkc-tag trkc-tag-stop" title="Авто-стоп при ${o.auto_stop_pct} FD">⚡${o.auto_stop_pct} FD</span>` : ''}
          ${o.group_ids ? `<span class="trkc-tag trkc-tag-group" title="Группа: ${h(o.group_ids)}">⛓ группа</span>` : ''}
          ${o.geo_cap ? `<span class="trkc-tag" style="background:rgba(99,102,241,.12);color:#818cf8;border:0.5px solid rgba(99,102,241,.3)" title="Кап на каждое GEO: ${o.geo_cap}">🌍 ${o.geo_cap}/GEO</span>` : ''}
            ${o.auto_stopped  ? `<span class="trkc-tag trkc-tag-autostopped">🛑 авто-стоп</span>` : ''}
          </div>
          <div class="trkc-actions">
            ${status !== 'stopped'    ? `<button class="trkc-act" data-color="#ef4444" onclick="trkSetStatus('${h(id)}','stopped')" title="Стоп">
              <svg width="10" height="10" viewBox="0 0 10 10"><rect width="10" height="10" rx="1.5" fill="currentColor"/></svg>
            </button>` : ''}
            ${status !== 'no_perform' ? `<button class="trkc-act" data-color="#f59e0b" onclick="trkSetStatus('${h(id)}','no_perform')" title="Не перформ">
              <svg width="11" height="11" viewBox="0 0 11 11"><path d="M5.5 1L10 9.5H1L5.5 1z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><line x1="5.5" y1="4.5" x2="5.5" y2="6.5" stroke="currentColor" stroke-width="1.5"/><circle cx="5.5" cy="8" r=".7" fill="currentColor"/></svg>
            </button>` : ''}
            ${status !== 'active'     ? `<button class="trkc-act" data-color="#10b981" onclick="trkSetStatus('${h(id)}','active')" title="Активировать">
              <svg width="11" height="11" viewBox="0 0 11 11"><polygon points="2,1 10,5.5 2,10" fill="currentColor"/></svg>
            </button>` : ''}
            <div class="trkc-act-sep"></div>
            <button class="trkc-act trkc-act--del" onclick="admDeleteTracking('${h(id)}')" title="Удалить">
              <svg width="10" height="10" viewBox="0 0 10 10"><line x1="1" y1="1" x2="9" y2="9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><line x1="9" y1="1" x2="1" y2="9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>

        <div class="trkc-row2">
          ${o.partner_name ? `<span class="trkc-pill">${h(o.partner_name)}</span>` : ''}
          <span class="trkc-pill trkc-pill--geo">${h(o.geo || '—')}</span>
          <span class="trkc-pill">${rotName}</span>
          <span class="trkc-pill">с ${h(o.start_date || '—')}</span>
        </div>

        <div class="trkc-row3">
          <div class="trkc-rate">
            ${o.rate
              ? `<span class="trkc-rate-val">${o.rate}</span><span class="trkc-rate-cur">${h(o.currency||'USD')}</span>`
              : `<span class="trkc-rate-empty">—</span>`}
          </div>

          ${fdInfo.geo_breakdown && o.geo_cap ? `
            <button class="trkc-geo-expand" onclick="admToggleGeoBreakdown(this)" title="GEO разбивка">
              🌍 GEO <span class="trkc-geo-arrow">▸</span>
            </button>
            <div class="trkc-geo-breakdown" style="display:none">
              ${Object.entries(fdInfo.geo_breakdown).sort((a,b) => b[1]-a[1]).map(([geo, gfd]) => {
                const gpct = Math.min(100, Math.round(gfd / o.geo_cap * 100));
                const gclr = gpct >= 90 ? '#ef4444' : gpct >= 70 ? '#f59e0b' : '#10b981';
                return `<div class="trkc-geo-row">
                  <span class="trkc-geo-code">${h(geo)}</span>
                  <span style="color:${gclr};font-size:11px">${gfd}/${o.geo_cap}</span>
                  <div class="trkc-bar" style="flex:1"><div class="trkc-bar-fill" style="width:${gpct}%;background:${gclr}"></div></div>
                  <span style="font-size:10px;color:var(--text3)">${gpct}%</span>
                </div>`;
              }).join('')}
            </div>
          ` : ''}
          <div class="trkc-cap">
            <div class="trkc-cap-nums">
              ${fd != null ? `<b style="color:${capColor}">${fd}</b>` : ''}
              ${fd != null && maxCap ? `<span style="color:var(--text3)">/ ${maxCap}</span>` : ''}
              ${updAt ? `<span class="trkc-upd">${updAt}</span>` : ''}
            </div>
            ${fd != null && maxCap ? `
              <div class="trkc-bar"><div class="trkc-bar-fill" style="width:${pct}%;background:${capColor}"></div></div>
            ` : ''}
            ${(() => {
              // Если есть группа — показываем кап каждого ленда
              const groupCaps = fdInfo.group_binom_caps || {};
              const hasGroup  = Object.keys(groupCaps).length > 0;
              const mainCap   = fdInfo.binom_max_cap;

              if (!mainCap && !hasGroup) return '';

              const renderCapRow = (bid, bcur, bmax) => {
                const bpct = bmax ? Math.min(100, Math.round(bcur / bmax * 100)) : 0;
                const bclr = bpct >= 90 ? '#ef4444' : bpct >= 70 ? '#f59e0b' : '#60a5fa';
                return `<div class="trkc-binom-row">
                  <div class="trkc-binom-row-info">
                    ${hasGroup ? `<span style="font-size:9px;color:var(--text3);font-family:monospace">#${bid}</span>` : ''}
                    <b style="color:${bclr}">${bcur}</b>
                    <span style="color:var(--text3)">/ </span>
                    <span class="trkc-binom-max" onclick="admEditBinomCap('${bid}',${bmax},this)" title="Нажмите чтобы изменить">${bmax}</span>
                    <span style="font-size:10px;color:var(--text3)">${bpct}%</span>
                  </div>
                  <div style="display:flex;align-items:center;gap:6px;flex:1">
                    <div class="trkc-bar" style="flex:1"><div class="trkc-bar-fill" style="width:${bpct}%;background:${bclr}"></div></div>
                  </div>
                </div>`;
              };

              let html = `<div class="trkc-binom-cap">
                <div class="trkc-binom-label">
                  <span style="font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em">Binom Cap${hasGroup ? ' (ленды)' : ''}</span>
                </div>`;

              // Основной оффер
              if (mainCap) html += renderCapRow(h(id), fdInfo.binom_current_cap ?? 0, mainCap);

              // Каждый ленд группы
              Object.entries(groupCaps).forEach(([gid, gc]) => {
                html += renderCapRow(h(gid), gc.current ?? 0, gc.max ?? 0);
              });

              html += '</div>';
              return html;
            })()}
          </div>

          <div class="trkc-status" style="--sc:${sd.color}">
            <span class="trkc-status-dot"></span>${sd.label}
          </div>
        </div>
      </div>
    </div>`;
  }).join('');

  const el2 = document.getElementById('admTrackingTable');
  if (!el2) return;
  // Если поле поиска в фокусе — только обновляем карточки, не трогаем filterBar
  const searchFocused = document.activeElement?.id === 'trkSearchInput';
  const searchVal     = document.activeElement?.id === 'trkSearchInput' ? document.activeElement.value : null;
  const searchPos     = document.activeElement?.id === 'trkSearchInput' ? document.activeElement.selectionStart : null;

  const listEl2 = document.getElementById('trkCardsList');
  if (listEl2 && searchFocused) {
    // Только обновляем карточки, не трогаем filterBar/input
    listEl2.innerHTML = '<div class="trkc-list">' + cards + '</div>';
  } else {
    el2.innerHTML = filterBar + '<div id="trkCardsList"><div class="trkc-list">' + cards + '</div></div>';
    // Восстанавливаем фокус если был
    if (searchFocused) {
      const inp = document.getElementById('trkSearchInput');
      if (inp) { inp.focus(); inp.setSelectionRange(searchPos, searchPos); }
    }
  }
}





function admCancelTrackingName(id) {
  document.getElementById('trkNameDisplay_' + id).style.display = 'inline';
  document.getElementById('trkNameInput_' + id).style.display = 'none';
}

async function admSaveTrackingName(id) {
  const inp = document.getElementById('trkNameInput_' + id);
  if (!inp) return;
  const newName = inp.value.trim();
  if (!newName) { admCancelTrackingName(id); return; }

  const j = await admApi('POST', `/api/tracking/offers/${id}`, { name: newName });
  if (j.ok) {
    admLoadTracking();
  } else {
    admCancelTrackingName(id);
  }
}


function admTrackSort(key) {
  const cur = ADM._trackSort || '';
  if (cur === key + '_desc') ADM._trackSort = key + '_asc';
  else ADM._trackSort = key + '_desc';
  admLoadTracking();
}

function admSortIcon(key) {
  const cur = ADM._trackSort || '';
  if (cur === key + '_desc') return '▼';
  if (cur === key + '_asc')  return '▲';
  return '⇅';
}

async function admEditTrackingName(id) {
  // Берём свежие данные с сервера
  const j = await admApi('GET', '/api/tracking/offers?_=' + Date.now());
  if (!j.ok) return;
  const o = j.offers[id];
  if (!o) return;

  // Убираем старый модал если есть
  document.getElementById('trkEditModal')?.remove();

  const modal = document.createElement('div');
  modal.id = 'trkEditModal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center';
  modal.innerHTML = `
    <div style="background:var(--bg2);border:0.5px solid var(--border2);border-radius:12px;padding:24px;width:480px;max-width:95vw">
      <div style="font-size:14px;font-weight:500;color:var(--text);margin-bottom:16px">✏️ Редактировать оффер</div>
      <div class="adm-field"><label>Название</label>
        <input class="adm-inp" id="trkEditName" type="text" value="${h(o.name||'')}">
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field"><label>Партнёр</label>
          <input class="adm-inp" id="trkEditPartner" type="text" value="${h(o.partner_name||'')}">
        </div>
        <div class="adm-field"><label>GEO</label>
          <input class="adm-inp" id="trkEditGeo" type="text" value="${h(o.geo||'')}">
        </div>
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field"><label>Дата старта</label>
          <input class="adm-inp" id="trkEditDate" type="date" value="${h(o.start_date||'')}">
        </div>
        <div class="adm-field"><label>Ротация</label>
          <select class="adm-inp" id="trkEditRot">
            <option value="">— не выбрано —</option>
            ${[['121','Crash'],['118','Betting'],['124','Casino'],['61','Slots'],['117','Mixed']].map(([v,n]) =>
              `<option value="${v}" ${(o.rotation_id||'')==v?'selected':''}>${n} (#${v})</option>`
            ).join('')}
          </select>
        </div>
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field"><label>Ставка</label>
          <input class="adm-inp" id="trkEditRate" type="number" step="0.01" value="${h(String(o.rate||''))}">
        </div>
        <div class="adm-field"><label>Валюта</label>
          <select class="adm-inp" id="trkEditCurrency">
            ${['USD','EUR','BRL','GBP','TRY','UAH','PLN'].map(c =>
              `<option value="${c}" ${(o.currency||'USD')==c?'selected':''}>${c}</option>`
            ).join('')}
          </select>
        </div>
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field"><label>Макс. кап</label>
          <input class="adm-inp" id="trkEditCap" type="number" placeholder="30" value="${h(String(o.max_cap||''))}">
        </div>
        <div class="adm-field">
          <label>Авто-стоп при FD</label>
          <input class="adm-inp" id="trkEditAutoStop" type="number" min="1"
            placeholder="напр. 45" value="${h(String(o.auto_stop_pct||''))}">
          <div style="font-size:11px;color:var(--text3);margin-top:4px">Пусто — авто-стоп отключён</div>
        </div>
      </div>
      <div class="adm-form-row" style="grid-template-columns:1fr 1fr">
        <div class="adm-field"><label>Группа ID <span style="font-size:.8em;color:var(--text3)">(через :)</span></label>
          <input class="adm-inp" id="trkEditGroupIds" type="text" placeholder="1040:1071" value="${h(o.group_ids||'')}">
        </div>
        <div class="adm-field"><label>Кап на GEO <span style="font-size:.8em;color:var(--text3)">(CAP/geo)</span></label>
          <input class="adm-inp" id="trkEditGeoCap" type="number" min="1" placeholder="20" value="${h(String(o.geo_cap||''))}">
        </div>
        <div class="adm-field"><label>Binom ID</label>
          <input class="adm-inp" id="trkEditId" type="text" value="${h(id)}" readonly style="opacity:.5">
        </div>
      </div>
      <div class="adm-err" id="trkEditErr" style="margin-bottom:8px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="adm-btn" onclick="document.getElementById('trkEditModal').remove()">Отмена</button>
        <button class="adm-btn primary" onclick="admSaveTrackingEdit('${h(id)}')">💾 Сохранить</button>
      </div>
    </div>`;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  (document.getElementById('adminOverlay') || document.body).appendChild(modal);
  document.getElementById('trkEditName')?.focus();
}

async function admSaveTrackingEdit(id) {
  const errEl    = document.getElementById('trkEditErr');
  const name     = document.getElementById('trkEditName').value.trim();
  const cap      = document.getElementById('trkEditCap')?.value.trim();
  const editRate = document.getElementById('trkEditRate')?.value.trim();
  const autoStop = document.getElementById('trkEditAutoStop')?.value.trim();

  if (!name) { errEl.textContent = 'Укажите название'; return; }

  const upd = await admApi('POST', `/api/tracking/offers/${id}`, {
    name,
    partner_name:  document.getElementById('trkEditPartner').value.trim(),
    max_cap:       cap ? parseInt(cap) : null,
    start_date:    document.getElementById('trkEditDate').value.trim(),
    geo:           document.getElementById('trkEditGeo').value.trim(),
    rotation_id:   document.getElementById('trkEditRot').value.trim(),
    rate:          editRate ? parseFloat(editRate) : null,
    currency:      document.getElementById('trkEditCurrency')?.value || 'USD',
    auto_stop_pct: autoStop ? parseInt(autoStop) : null,
    auto_stopped:  autoStop ? null : undefined,
    group_ids:     document.getElementById('trkEditGroupIds')?.value.trim() || null,
    geo_cap:       (() => { const v = document.getElementById('trkEditGeoCap')?.value.trim(); return v ? parseInt(v) : null; })(),
  });

  if (!upd.ok) { errEl.textContent = upd.error || 'Ошибка'; return; }
  document.getElementById('trkEditModal')?.remove();
  admLoadTracking();
}

function admEditBinomCap(offerId, currentMax, triggerEl) {
  // Находим элемент который кликнули или его родитель
  const el = triggerEl || event?.target;
  if (!el) return;

  // Создаём inline input вместо числа
  const orig = el.outerHTML;
  const input = document.createElement('input');
  input.type = 'number';
  input.value = currentMax;
  input.min = 1;
  input.style.cssText = `
    width: ${Math.max(60, String(currentMax).length * 9 + 20)}px;
    padding: 1px 5px; border-radius: 4px;
    border: 1px solid var(--accent); background: var(--bg);
    color: var(--text); font-size: 12px; font-family: inherit;
    outline: none;
  `;

  el.replaceWith(input);
  input.focus();
  input.select();

  async function save() {
    const val = parseInt(input.value);
    if (!val || val < 1) { input.replaceWith(el); return; }
    if (val === currentMax) { input.replaceWith(el); return; }

    input.disabled = true;
    input.style.opacity = '.5';
    const j = await admApi('PUT', `/api/tracking/offers/${offerId}/binom_cap`, { maxCap: val });
    if (j.ok) {
      admLoadTracking();
    } else {
      const err = document.createElement('span');
      err.textContent = j.error || 'Ошибка';
      err.style.cssText = 'font-size:11px;color:var(--red);margin-left:6px';
      input.replaceWith(el);
      el.after(err);
      setTimeout(() => err.remove(), 3000);
    }
  }

  input.addEventListener('blur', save);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { e.preventDefault(); input.replaceWith(el); }
  });
}

async function admEditCap(offerId, currentMax) {
  const newCap = prompt(`Новый Max Cap для оффера #${offerId}:`, currentMax);
  if (!newCap || isNaN(newCap) || parseInt(newCap) < 1) return;
  const j = await admApi('POST', `/api/tracking/offers/${offerId}/update_cap`, { max_cap: parseInt(newCap) });
  if (j.ok) {
    admLoadTracking();
  } else {
    alert(j.error || 'Ошибка обновления капа');
  }
}

function admToggleTrackingForm() {
  const el = document.getElementById('admTrackingForm');
  if (!el) return;
  const shown = el.style.display !== 'none';
  el.style.display = shown ? 'none' : 'block';
  if (!shown) {
    // Ставим сегодняшнюю дату по умолчанию
    const d = new Date().toISOString().slice(0, 10);
    const dateEl = document.getElementById('trkStartDate');
    if (dateEl && !dateEl.value) dateEl.value = d;
  }
}

// ── Lookup offer rotations by ID ─────────────────────────────────────────
let _offersCache = null;

async function _getOffersCache() {
  if (_offersCache) return _offersCache;
  const j = await admApi('GET', '/api/offers/cached');
  _offersCache = j.ok ? (j.rotations || []) : [];
  return _offersCache;
}

let _trkLookupTimer = null;
async function trkLookupOffer(val) {
  const hint = document.getElementById('trkOfferRotHint');
  if (!hint) return;
  const id = val.trim();
  if (!id || id.length < 3) { hint.style.display = 'none'; return; }

  clearTimeout(_trkLookupTimer);
  _trkLookupTimer = setTimeout(async () => {
    const rotations = await _getOffersCache();
    // Find all rotations this offer is in
    const found = [];
    for (const rot of rotations) {
      for (const geo of (rot.geos || [])) {
        const off = (geo.offers || []).find(o => String(o.offer_id) === String(id));
        if (off) {
          found.push({
            rot_id:   rot.id,
            rot_name: rot.name,
            geo:      geo.name,
            name:     off.offer_name,
          });
        }
      }
    }

    if (!found.length) { hint.style.display = 'none'; return; }

    // Pre-fill name if empty
    const nameInp = document.getElementById('trkName');
    if (nameInp && !nameInp.value.trim()) {
      nameInp.value = found[0].name || '';
    }

    // Group by rotation
    const byRot = {};
    for (const f of found) {
      if (!byRot[f.rot_id]) byRot[f.rot_id] = { name: f.rot_name, geos: [] };
      byRot[f.rot_id].geos.push(f.geo);
    }

    // Авто-заполняем первую ротацию
    const firstRot = Object.entries(byRot)[0];
    if (firstRot) {
      const rotSel = document.getElementById('trkRotId');
      if (rotSel && !rotSel.value) rotSel.value = firstRot[0];
      const geoInp = document.getElementById('trkGeo');
      if (geoInp && !geoInp.value) geoInp.value = firstRot[1].geos[0] || '';
    }

    hint.style.display = 'block';
    hint.innerHTML = `<span style="font-size:11px;color:var(--text3)">Найден в: </span>` +
      Object.entries(byRot).map(([rotId, rot]) =>
        `<span class="trk-rot-hint trk-rot-hint--info" title="GEO: ${h(rot.geos.join(', '))}">
          ${h(rot.name)}
          <span style="opacity:.6;font-size:.85em">${rot.geos.length > 1 ? rot.geos.length + ' GEO' : h(rot.geos[0]||'')}</span>
        </span>`
      ).join('');
  }, 400);
}

async function admSubmitTrackingManual() {
  const errEl = document.getElementById('trkErr');
  errEl.textContent = '';
  const offerId   = document.getElementById('trkOfferId').value.trim();
  const name      = document.getElementById('trkName').value.trim();
  const startDate = document.getElementById('trkStartDate').value.trim();
  const partner   = document.getElementById('trkPartner').value.trim();
  const maxCap    = document.getElementById('trkMaxCap').value.trim();
  const rotId     = document.getElementById('trkRotId').value.trim();
  const geo       = document.getElementById('trkGeo').value.trim();

  if (!offerId || !name || !startDate) {
    errEl.textContent = 'Заполните Binom ID, название и дату старта';
    return;
  }

  const rate = document.getElementById('trkRate')?.value.trim();
  const currency = document.getElementById('trkCurrency')?.value || 'USD';
  if (!rate) { errEl.textContent = 'Укажите ставку'; return; }

  const groupIds = document.getElementById('trkGroupIds')?.value.trim();
  const geoCap   = document.getElementById('trkGeoCap')?.value.trim();

  const j = await admApi('POST', '/api/tracking/manual', {
    offer_id:     offerId,
    name,
    start_date:   startDate,
    partner_name: partner,
    max_cap:      maxCap ? parseInt(maxCap) : undefined,
    rotation_id:  rotId,
    geo,
    rate:         parseFloat(rate),
    currency,
    group_ids:    groupIds || undefined,
    geo_cap:      geoCap ? parseInt(geoCap) : undefined,
  });

  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }

  // Очищаем поля формы
  ['trkOfferId','trkName','trkPartner','trkMaxCap','trkRotId','trkGeo'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  document.getElementById('admTrackingForm').style.display = 'none';
  admLoadTracking();
}

async function trkSetStatus(offerId, status) {
  const j = await admApi('POST', `/api/tracking/offers/${offerId}/status`, { status });
  if (j.ok) admLoadTracking();
}

async function admDeleteTracking(offerId) {
  if (!confirm('Удалить оффер из трекинга? Синк вернётся к стандартной логике.')) return;
  const j = await admApi('DELETE', `/api/tracking/offers/${offerId}`);
  if (j.ok) admLoadTracking();
}


let _stopReason = 'no_perform';

function admSelectStopReason(btn) {
  document.querySelectorAll('#stopReasonGroup .trk-chip').forEach(b => b.classList.remove('trk-chip--active'));
  btn.classList.add('trk-chip--active');
  _stopReason = btn.dataset.val;
}

function admToggleGeoBreakdown(btn) {
  const card   = btn.closest('.trkc-card') || btn.parentElement;
  const panel  = btn.nextElementSibling;
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  const arrow = btn.querySelector('.trkc-geo-arrow');
  if (arrow) arrow.textContent = open ? '▸' : '▾';
}

function admStopSearchOffer(val) { /* поиск по мере ввода — опционально */ }

async function admStopOffer() {
  const errEl    = document.getElementById('stopErr');
  const resultEl = document.getElementById('stopResultLog');
  const btn      = document.getElementById('stopBtn');

  const offerId = (document.getElementById('stopOfferId')?.value || '').trim();
  const reason  = document.getElementById('stopReason')?.value || 'no_perform';
  const comment = (document.getElementById('stopComment')?.value || '').trim();

  if (errEl) errEl.textContent = '';
  if (resultEl) resultEl.innerHTML = '';

  if (!offerId) {
    if (errEl) errEl.textContent = 'Укажите Binom ID оффера';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 10 10" fill="currentColor"><rect width="10" height="10" rx="1.5"/></svg> Ищу...`;

  const j = await admApi('POST', '/api/admin/stop_offer', {
    offer_id: offerId,
    reason,
    comment:  comment || undefined,
  });

  btn.disabled = false;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 10 10" fill="currentColor"><rect width="10" height="10" rx="1.5"/></svg> Остановить оффер`;

  if (!j.ok) {
    if (errEl) errEl.textContent = j.error || 'Ошибка';
    return;
  }

  if (!resultEl) return;

  const reasonLabels = {
    no_perform: 'No Perform', cap_filled: 'Кап заполнен',
    partner_request: 'Запрос партнёра', manual: 'Вручную',
  };
  const rLabel = reasonLabels[reason] || reason;

  resultEl.innerHTML = `
    <div style="background:var(--bg2);border:0.5px solid var(--border);border-radius:10px;padding:16px">
      <div style="font-size:13px;font-weight:500;color:var(--text);margin-bottom:10px">
        ${j.stopped_count > 0 ? '✅ Оффер остановлен' : 'ℹ️ Результат'}
      </div>
      <div style="font-size:13px;color:var(--text2);margin-bottom:6px">
        📋 <b style="color:var(--text)">${h(j.offer_name || offerId)}</b>
      </div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:10px">
        Причина: <span style="color:var(--amber)">${rLabel}</span>${comment ? ' · ' + h(comment) : ''}
      </div>
      ${(j.stopped_rots||[]).length ? `
        <div style="font-size:12px;color:var(--green);margin-bottom:4px">Остановлено:</div>
        ${(j.stopped_rots||[]).map(r => `<div style="font-size:12px;color:var(--text2);padding:2px 0 2px 12px">⏹ ${h(r)}</div>`).join('')}
      ` : ''}
      ${(j.already_stopped||[]).length ? `
        <div style="font-size:12px;color:var(--text3);margin-top:8px">Уже было 0: ${(j.already_stopped||[]).map(r=>h(r)).join(', ')}</div>
      ` : ''}
      ${j.not_found ? `<div style="font-size:12px;color:var(--red);margin-top:8px">⚠ Не найден ни в одной ротации</div>` : ''}
      ${j.tg_sent ? `<div style="font-size:12px;color:var(--accent-txt);margin-top:8px">📨 Пуш отправлен</div>` : ''}
    </div>`;
}

// ── Rotations Panel ───────────────────────────────────────────────────────────


























// ── Weekly Uniques Panel (in admin) ──────────────────────────────────────────

function admInitWeeklyPanel() {
  const fromEl = document.getElementById('admWDateFrom');
  const toEl   = document.getElementById('admWDateTo');
  if (!fromEl || fromEl.value) return;  // Already initialized
  const { from, to } = (() => {
    const today = new Date();
    const dow = today.getDay();
    const daysSinceTue = (dow + 7 - 2) % 7;
    const tue = new Date(today);
    tue.setDate(today.getDate() - (daysSinceTue === 0 ? 7 : daysSinceTue));
    const wed = new Date(tue); wed.setDate(tue.getDate() - 6);
    return { from: wed.toISOString().slice(0,10), to: tue.toISOString().slice(0,10) };
  })();
  fromEl.value = from;
  toEl.value   = to;
}

async function admRunWeekly() {
  const dateFrom = document.getElementById('admWDateFrom')?.value;
  const dateTo   = document.getElementById('admWDateTo')?.value;
  const minUniq  = parseInt(document.getElementById('admWMinUniq')?.value) || 100;
  const exclude1x = document.getElementById('admWExclude1x')?.checked ? 'true' : 'false';
  const result   = document.getElementById('admWeeklyResult');
  if (!result) return;

  if (!dateFrom || !dateTo) { result.innerHTML = '<div class="adm-empty">Укажите даты</div>'; return; }

  result.innerHTML = '<div class="adm-empty"><div class="spinner"></div> Загрузка данных Binom…</div>';

  const j = await admApi('GET', `/api/report/weekly_uniques?date_from=${dateFrom}&date_to=${dateTo}&min_uniq=1&exclude_1x=${exclude1x}`);
  if (!j.ok) { result.innerHTML = `<div class="adm-empty">Ошибка: ${h(j.error||'')}</div>`; return; }

  // Merge rotations using same logic as app.js
  const mergeGroups = [
    { label: 'Casino',  rotations: ['casino', 'fortune tiger'] },
    { label: 'Betting', rotations: ['betting', 'betano'] },
    { label: 'Crash',   rotations: ['crash', 'plinko'] },
  ];
  const findGroup = name => {
    const lower = name.toLowerCase();
    for (const g of mergeGroups) { if (g.rotations.some(k => lower.includes(k))) return g.label; }
    return null;
  };

  // Только Crash, Betting, Casino — остальные игнорируем
  const ALLOWED = ['Casino', 'Betting', 'Crash'];

  const mergedMap = {};
  for (const rot of (j.rotations||[])) {
    const gl = findGroup(rot.rotationName);
    if (gl && ALLOWED.includes(gl)) {
      if (!mergedMap[gl]) mergedMap[gl] = { name: gl, countries: new Map() };
      for (const c of rot.countries) mergedMap[gl].countries.set(c.country, (mergedMap[gl].countries.get(c.country)||0) + c.uniq);
    }
  }
  const all = ALLOWED
    .filter(label => mergedMap[label])
    .map(label => ({
      name: mergedMap[label].name,
      countries: Array.from(mergedMap[label].countries.entries())
        .map(([country,uniq]) => ({country,uniq}))
        .filter(c => c.uniq >= minUniq)
        .sort((a,b) => b.uniq - a.uniq),
    }))
    .filter(r => r.countries.length > 0);

  if (!all.length) { result.innerHTML = '<div class="adm-empty">Нет данных с такими параметрами</div>'; return; }

  const globalMax = Math.max(...all.flatMap(r => r.countries.map(c => c.uniq)));

  const geoFlag = code => {
    if (!code || code.length !== 2) return '';
    const a = code.toUpperCase().charCodeAt(0)-65, b = code.toUpperCase().charCodeAt(1)-65;
    if (a<0||a>25||b<0||b>25) return '';
    return String.fromCodePoint(0x1F1E6+a) + String.fromCodePoint(0x1F1E6+b);
  };
  const geoCodeFn = s => { const m = (s||'').match(/([A-Z]{2})\s*$/); return m?m[1]:(s?.length===2?s.toUpperCase():''); };
  const geoNameFn = s => (s||'').replace(/\s+[A-Z]{2}\s*$/,'').trim() || s;

  result.innerHTML = `
    <div style="font-size:.78rem;color:var(--text3);margin-bottom:12px">
      📅 <b style="color:var(--text2)">${dateFrom} — ${dateTo}</b>
      · Порог: ≥${minUniq} · Ротаций: ${all.length}
      ${j.excluded_count > 0 ? `· 🚫 1x: ${j.excluded_count} исключено` : ''}
    </div>
    <div class="weekly-cards">
      ${all.map((rot, ri) => {
        const topUniq = rot.countries[0]?.uniq || 1;
        return `<div class="wcard">
          <div class="wcard-header">
            <div class="wcard-header-left">
              <div class="wcard-title">${h(rot.name)}</div>
              <div class="wcard-badge">${rot.countries.length} GEO</div>
            </div>
            <button class="wcopy-btn" data-rot-name="${h(rot.name)}" onclick="admWeeklyCopy(this,${ri})" title="Копировать">⎘ Копировать</button>
          </div>
          <div class="wcard-rows">
            ${rot.countries.map((c, i) => {
              const code = geoCodeFn(c.country);
              const pct  = (c.uniq / topUniq * 100).toFixed(1);
              return `<div class="wrow ${i===0?'wrow-top':''}">
                <div class="wrow-rank">${i+1}</div>
                <div class="wrow-country">
                  <span class="wrow-flag">${geoFlag(code)}</span>
                  <span class="wrow-geo-name">${h(geoNameFn(c.country))}</span>
                  <span class="wrow-geo-code">${h(code)}</span>
                </div>
                <div class="wrow-bar-wrap"><div class="wrow-bar" style="width:${pct}%"></div></div>
                <div class="wrow-uniq">${c.uniq.toLocaleString()}</div>
                <div class="wrow-tag active" title="Нажми чтобы убрать">Нужен оффер</div>
              </div>`;
            }).join('')}
          </div>
        </div>`;
      }).join('')}
    </div>`;

  // Store for copy
  window._admWeeklyData = all;
}

function admWeeklyCopy(btn, idx) {
  const rot = (window._admWeeklyData||[])[idx];
  if (!rot) return;
  const geoCodeFn = s => { const m=(s||'').match(/([A-Z]{2})\s*$/); return m?m[1]:(s?.length===2?s.toUpperCase():''); };
  const geoNameFn = s => (s||'').replace(/\s+[A-Z]{2}\s*$/,'').trim()||s;
  const roundUniq = n => n>=2000?Math.floor(n/500)*500:n>=1000?Math.floor(n/250)*250:n>=500?Math.floor(n/100)*100:Math.floor(n/50)*50;
  const lines = [`${rot.name}:`];
  rot.countries.forEach(c => {
    const code = geoCodeFn(c.country);
    const name = geoNameFn(c.country);
    const r    = roundUniq(c.uniq);
    lines.push(`${code} ${name} - более ${r.toLocaleString('ru-RU')} уников в неделю`);
  });
  navigator.clipboard.writeText(lines.join('\n')).then(() => {
    btn.textContent = '✓ Скопировано';
    btn.classList.add('wcopy-done');
    setTimeout(() => { btn.textContent = '⎘ Копировать'; btn.classList.remove('wcopy-done'); }, 2000);
  });
}

// ══ Rotations Panel B ════════════════════════════════════════════════════════

let _admRot = {
  selected: new Set(),
  currentRotId: null,
  currentGeo: null,
  currentTab: 'offers',
  rotItems: [],         // [{id,name,status}]
  geoItems: [],         // [{geo, items}]
};

const ROT_COLORS = ['#4f8ef7','#a78bfa','#22d47a','#fbbf24','#f87171','#34d4c8'];

function admRotSetStatus(btn) {
  document.querySelectorAll('.rb-stab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  admLoadRotationsPanel();
}

function admRotClearSelection() {
  _admRot.selected.clear();
  document.querySelectorAll('.rb-rot-cb').forEach(cb => {
    cb.checked = false;
    cb.closest('.rb-rot-card')?.classList.remove('selected');
  });
  _admRotUpdateMultiBar();
}

function _admRotUpdateMultiBar() {
  const bar = document.getElementById('admRotMultiBar');
  const btn = document.getElementById('admRotMultiAnalyticsBtn');
  const n   = _admRot.selected.size;
  if (bar) bar.style.display = n >= 2 ? 'flex' : 'none';
  if (btn) btn.textContent   = `Мульти-аналитика (${n})`;
}

async function admLoadRotationsPanel() {
  const list = document.getElementById('admRotList');
  const meta = document.getElementById('admRotMeta');
  if (!list) return;
  list.innerHTML = '<div class="adm-empty"><div class="spinner"></div></div>';

  const q      = document.getElementById('admRotQ')?.value.trim() || '';
  const status = document.querySelector('.rb-stab.active')?.dataset.val || '';
  const params = new URLSearchParams();
  if (q)      params.set('q', q);
  if (status) params.set('status', status);
  params.set('per_page', '200');

  const j = await admApi('GET', '/api/rotations?' + params);
  if (!j.ok) { list.innerHTML = '<div class="adm-empty">Ошибка</div>'; return; }

  const raw   = j.data ?? j;
  const items = Array.isArray(raw) ? raw
    : Array.isArray(raw.data)   ? raw.data
    : Array.isArray(raw.items)  ? raw.items
    : Array.isArray(raw.result) ? raw.result : [];

  _admRot.rotItems = items;
  _admRot.selected.clear();
  _admRotUpdateMultiBar();
  if (meta) meta.textContent = items.length;

  if (!items.length) { list.innerHTML = '<div class="rb-empty-hint">Пусто</div>'; return; }

  const indCls = s => {
    const sl = (s||'').toLowerCase();
    if (sl.includes('active'))  return '#10b981';
    if (sl.includes('pause'))   return '#f59e0b';
    if (sl.includes('delete') || sl.includes('stop')) return '#ef4444';
    return 'var(--text3)';
  };

  list.innerHTML = items.map(it => {
    const id   = String(it.id ?? it.rotation_id ?? '');
    const name = it.name ?? it.title ?? `#${id}`;
    const st   = it.status ?? it.state ?? '';
    return `<div class="rb-rot-card" data-id="${h(id)}"
      onclick="admRotSelectRot(event,'${h(id)}','${h(name.replace(/'/g,'\\\''))}')">
      <div class="rb-rot-indicator" style="background:${indCls(st)}"></div>
      <div class="rb-rot-info">
        <div class="rb-rot-name" title="${h(name)}">${h(name)}</div>
        <div class="rb-rot-id">#${h(id)}</div>
      </div>
      <input type="checkbox" class="rb-rot-cb" data-id="${h(id)}"
        onclick="event.stopPropagation()" onchange="admRotToggleCb(this)">
    </div>`;
  }).join('');
}

async function admRotSelectRot(e, id, name) {
  document.querySelectorAll('.rb-rot-card').forEach(c => c.classList.remove('active'));
  e.currentTarget.classList.add('active');
  _admRot.currentRotId = id;
  _admRot.currentGeo   = null;

  const geoTitle = document.getElementById('admRotGeoTitle');
  const geoCount = document.getElementById('admRotGeoCount');
  const geoList  = document.getElementById('admRotGeoList');
  if (geoTitle) geoTitle.textContent = h(name);
  if (geoCount) geoCount.textContent = '…';
  if (geoList)  geoList.innerHTML    = '<div class="adm-empty"><div class="spinner"></div></div>';

  const j = await admApi('GET', `/api/rotation/${id}/active_offers_grouped`);
  if (!j.ok) { if (geoList) geoList.innerHTML = '<div class="rb-empty-hint">Ошибка</div>'; return; }

  _admRot.geoItems = j.groups || [];
  if (geoCount) geoCount.textContent = _admRot.geoItems.length;

  if (!_admRot.geoItems.length) {
    if (geoList) geoList.innerHTML = '<div class="rb-empty-hint">Нет активных офферов</div>';
    return;
  }

  geoList.innerHTML = _admRot.geoItems.map(g => {
    const cnt = g.items?.length || 0;
    const tw  = (g.totalWeight||0).toFixed(0);
    return `<div class="rb-geo-item" onclick="admRotOpenGeoModal('${h(g.geoTitle||'')}')">
      <span class="rb-geo-name">${h(g.geoTitle||'—')}</span>
      <span class="rb-geo-cnt">${cnt} офф · ∑${tw}</span>
    </div>`;
  }).join('');
}

function admRotOpenGeoModal(geo) {
  document.querySelectorAll('.rb-geo-item').forEach(g => g.classList.remove('active'));
  document.querySelector(`.rb-geo-item[onclick*="'${geo}'"]`)?.classList.add('active');
  _admRot.currentGeo = geo;
  _admRot.currentTab = 'offers';

  // Default dates: last 7 days (excluding today)
  const today = new Date();
  const toD   = new Date(today); toD.setDate(today.getDate() - 1);
  const fromD = new Date(toD);   fromD.setDate(toD.getDate() - 6);
  const fmt   = d => d.toISOString().slice(0,10);

  const overlay = document.createElement('div');
  overlay.id = 'rbModal';
  overlay.className = 'rb-modal-overlay';
  overlay.innerHTML = `
    <div class="rb-modal">
      <div class="rb-modal-head">
        <div class="rb-modal-title">${h(geo)}</div>
        <div class="rb-modal-tabs">
          <button class="rb-modal-tab active" onclick="admRotModalTab(this,'offers')">Офферы</button>
          <button class="rb-modal-tab" onclick="admRotModalTab(this,'analytics')">Аналитика</button>
        </div>
        <button class="rb-modal-close" onclick="document.getElementById('rbModal').remove()">✕</button>
      </div>
      <div id="rbModalDateBar" style="display:none" class="rb-geo-datebar">
        <label>С</label>
        <input type="date" id="rbDateFrom" class="rb-geo-dateinp" value="${fmt(fromD)}">
        <label>По</label>
        <input type="date" id="rbDateTo" class="rb-geo-dateinp" value="${fmt(toD)}">
        <button class="rb-geo-apply" onclick="admRotLoadModalAnalytics('${h(geo)}')">Показать</button>
        <span id="rbPresetBar" style="display:flex;gap:4px;margin-left:4px">
          ${[['today','Сегодня'],['yesterday','Вчера'],['7','7д'],['14','14д'],['30','30д']].map(([v,l]) =>
            `<button class="rb-geo-apply" style="padding:5px 10px;font-size:11px" onclick="admRotSetPreset('${v}','${h(geo)}')">${l}</button>`
          ).join('')}
        </span>
      </div>
      <div class="rb-modal-body" id="rbModalBody">
        <div class="adm-empty"><div class="spinner"></div></div>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  (document.getElementById('adminOverlay') || document.body).appendChild(overlay);

  admRotLoadModalOffers(geo);
}

function admRotSetPreset(preset, geo) {
  const today = new Date();
  const toD   = new Date(today); toD.setDate(today.getDate() - 1);
  const fmt   = d => d.toISOString().slice(0,10);
  let fromD;
  if (preset === 'today')     { fromD = new Date(today); }
  else if (preset === 'yesterday') { fromD = new Date(toD); }
  else { fromD = new Date(toD); fromD.setDate(toD.getDate() - (parseInt(preset)-1)); }

  const fi = document.getElementById('rbDateFrom');
  const ti = document.getElementById('rbDateTo');
  if (fi) fi.value = fmt(fromD);
  if (ti) ti.value = preset === 'today' ? fmt(today) : fmt(toD);
  admRotLoadModalAnalytics(geo);
}

function admRotModalTab(btn, tab) {
  document.querySelectorAll('.rb-modal-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _admRot.currentTab = tab;
  const datebar = document.getElementById('rbModalDateBar');
  if (datebar) datebar.style.display = tab === 'analytics' ? 'flex' : 'none';
  if (tab === 'offers')    admRotLoadModalOffers(_admRot.currentGeo);
  if (tab === 'analytics') admRotLoadModalAnalytics(_admRot.currentGeo);
}

function admRotLoadModalOffers(geo) {
  const body = document.getElementById('rbModalBody');
  if (!body) return;
  const g = _admRot.geoItems.find(g => g.geoTitle === geo);
  if (!g?.items?.length) { body.innerHTML = '<div class="rb-empty-hint" style="padding:24px">Нет офферов</div>'; return; }

  body.innerHTML = `<table class="rb-offers-table">
    <thead><tr>
      <th>Оффер</th>
      <th>Path</th>
      <th style="text-align:right">Вес</th>
    </tr></thead>
    <tbody>
      ${g.items.map((it, i) => {
        const wid = `rmo_${i}`;
        return `<tr>
          <td title="${h(it.offerName||'')}" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(it.offerName||'—')}</td>
          <td style="font-size:11px;color:var(--text3)">${h(it.pathName||'—')}</td>
          <td>
            <div class="rb-w-cell" id="${wid}-cell" style="justify-content:flex-end">
              <span class="rb-w-val" id="${wid}-val">${it.weight}</span>
              <button class="rb-w-btn" style="opacity:1" onclick="admRotEditWeight('${wid}','${h(String(it.offerId))}','${h(_admRot.currentRotId)}')" title="Изменить вес">✎</button>
            </div>
          </td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

async function admRotLoadModalAnalytics(geo) {
  const body = document.getElementById('rbModalBody');
  if (!body) return;
  body.innerHTML = '<div class="adm-empty"><div class="spinner"></div></div>';

  const dateFrom = document.getElementById('rbDateFrom')?.value;
  const dateTo   = document.getElementById('rbDateTo')?.value;
  const geoQuery = (dateFrom && dateTo)
    ? `date_from=${dateFrom}&date_to=${dateTo}`
    : `preset=last_7_days`;
  const j = await admApi('GET', `/api/rotation/${_admRot.currentRotId}/analytics_geo?geo=${encodeURIComponent(geo)}&${geoQuery}`);
  if (!j.ok || !j.items?.length) { body.innerHTML = '<div class="rb-empty-hint" style="padding:24px">Нет данных</div>'; return; }

  const items = j.items;
  body.innerHTML = `<table class="rb-offers-table">
    <thead><tr>
      <th>Оффер</th>
      <th style="text-align:right">Uniq</th>
      <th style="text-align:right">CR%</th>
      <th style="text-align:right">DPU</th>
      <th style="text-align:right">Вес</th>
    </tr></thead>
    <tbody>
      ${items.map((it, i) => {
        const dpuClr = (it.dpu||0)>0.3?'#10b981':(it.dpu||0)>0.1?'#f59e0b':'var(--text3)';
        const wid = `rma_${i}`;
        return `<tr>
          <td title="${h(it.offerName||'')}" style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px">${h(it.offerName||'—')}</td>
          <td style="text-align:right;font-family:monospace;font-size:13px">${(it.uniq||0).toLocaleString()}</td>
          <td style="text-align:right;font-family:monospace;font-size:13px">${it.cr!=null?it.cr+'%':'—'}</td>
          <td style="text-align:right;font-family:monospace;font-size:13px;color:${dpuClr}">${it.dpu?'$'+it.dpu.toFixed(2):'—'}</td>
          <td>
            <div class="rb-w-cell" id="${wid}-cell" style="justify-content:flex-end">
              <span class="rb-w-val" id="${wid}-val">${it.weight}</span>
              <button class="rb-w-btn" style="opacity:1" onclick="admRotEditWeight('${wid}','${h(String(it.offerId))}','${h(_admRot.currentRotId)}')" title="Изменить вес">✎</button>
            </div>
          </td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

function admRotDetailTab(btn, tab) {}  // kept for compat

function admRotSetMaPreset(preset) {
  const today = new Date();
  const toD   = new Date(today); toD.setDate(today.getDate()-1);
  const fmt   = d => d.toISOString().slice(0,10);
  let fromD;
  if (preset === 'today')      { fromD = new Date(today); document.getElementById('rbMaDateTo').value = fmt(today); }
  else if (preset === 'yesterday') { fromD = new Date(toD); document.getElementById('rbMaDateTo').value = fmt(toD); }
  else { fromD = new Date(toD); fromD.setDate(toD.getDate()-(parseInt(preset)-1)); }
  document.getElementById('rbMaDateFrom').value = fmt(fromD);
  admRotRunMultiAnalytics();
}

async function admRotRunMultiAnalytics() {
  const body = document.getElementById('rbModalBody');
  if (!body) return;
  body.innerHTML = '<div class="adm-empty"><div class="spinner"></div></div>';
  await admRotMultiAnalytics();
}

function admRotToggleCb(cb) {
  const id   = cb.dataset.id;
  const card = cb.closest('.rb-rot-card');
  if (cb.checked) { _admRot.selected.add(id); card?.classList.add('selected'); }
  else            { _admRot.selected.delete(id); card?.classList.remove('selected'); }
  _admRotUpdateMultiBar();
}

function admRotEditWeight(wid, offerId, rotId) {
  const cell = document.getElementById(wid+'-cell');
  const cur  = document.getElementById(wid+'-val')?.textContent || '0';
  cell.innerHTML = `
    <input class="rb-w-inp" id="${wid}-inp" type="number" min="0" max="9999" step="1" value="${cur}">
    <button class="rb-w-btn" style="opacity:1;background:var(--accent-bg);border-color:var(--accent);color:var(--accent-txt)"
      onclick="admRotSaveWeight('${wid}','${offerId}','${rotId}')">✓</button>
    <button class="rb-w-btn" style="opacity:1"
      onclick="admRotCancelWeight('${wid}','${cur}')">✕</button>`;
  const inp = document.getElementById(wid+'-inp');
  inp.focus(); inp.select();
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter')  admRotSaveWeight(wid, offerId, rotId);
    if (e.key === 'Escape') admRotCancelWeight(wid, cur);
  });
}

async function admRotSaveWeight(wid, offerId, rotId) {
  const val = parseInt(document.getElementById(wid+'-inp')?.value);
  if (isNaN(val) || val < 0) { admRotCancelWeight(wid, document.getElementById(wid+'-val')?.textContent||0); return; }

  const j = await admApi('PATCH', `/api/rotation/${rotId}/offer_weight`, { offer_id: offerId, weight: val });
  const cell = document.getElementById(wid+'-cell');
  if (j?.ok) {
    cell.innerHTML = `<span class="rb-w-val" id="${wid}-val" style="color:var(--accent-txt)">${val}</span>
      <button class="rb-w-btn" onclick="admRotEditWeight('${wid}','${offerId}','${rotId}')">✎</button>`;
    setTimeout(() => { const v = document.getElementById(wid+'-val'); if (v) v.style.color=''; }, 2000);
  } else {
    admRotCancelWeight(wid, val);
  }
}

function admRotCancelWeight(wid, orig) {
  const cell = document.getElementById(wid+'-cell');
  // Get offerId and rotId from sibling button if possible
  cell.innerHTML = `<span class="rb-w-val" id="${wid}-val">${orig}</span>
    <button class="rb-w-btn" onclick="admRotEditWeight('${wid}','','')">✎</button>`;
}

async function admRotMultiAnalytics() {
  const ids = [..._admRot.selected];
  if (ids.length < 2) return;

  // Open modal
  document.getElementById('rbModal')?.remove();
  const overlay = document.createElement('div');
  overlay.id = 'rbModal';
  overlay.className = 'rb-modal-overlay';
  // Default dates
  const _today = new Date();
  const _toD   = new Date(_today); _toD.setDate(_today.getDate()-1);
  const _fromD = new Date(_toD);   _fromD.setDate(_toD.getDate()-6);
  const _fmt   = d => d.toISOString().slice(0,10);

  overlay.innerHTML = `
    <div class="rb-modal" style="width:min(1200px,96vw)">
      <div class="rb-modal-head">
        <div class="rb-modal-title">Мульти-аналитика</div>
        <button class="rb-modal-close" onclick="document.getElementById('rbModal').remove()">✕</button>
      </div>
      <div class="rb-geo-datebar">
        <label>С</label>
        <input type="date" id="rbMaDateFrom" class="rb-geo-dateinp" value="${_fmt(_fromD)}">
        <label>По</label>
        <input type="date" id="rbMaDateTo" class="rb-geo-dateinp" value="${_fmt(_toD)}">
        <button class="rb-geo-apply" onclick="admRotRunMultiAnalytics()">Показать</button>
        <span style="display:flex;gap:4px;margin-left:4px">
          ${[['7','7д'],['14','14д'],['30','30д'],['yesterday','Вчера'],['today','Сегодня']].map(([v,l]) =>
            `<button class="rb-geo-apply" style="padding:5px 10px;font-size:11px"
              onclick="admRotSetMaPreset('${v}')">${l}</button>`
          ).join('')}
        </span>
      </div>
      <div class="rb-modal-body" id="rbModalBody">
        <div class="adm-empty"><div class="spinner"></div></div>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  (document.getElementById('adminOverlay') || document.body).appendChild(overlay);

  const detail = document.getElementById('rbModalBody');

  const _maDateFrom = document.getElementById('rbMaDateFrom')?.value;
  const _maDateTo   = document.getElementById('rbMaDateTo')?.value;
  const _maQuery = (_maDateFrom && _maDateTo)
    ? `date_from=${_maDateFrom}&date_to=${_maDateTo}`
    : `preset=last_7_days`;

  const results = await Promise.all(ids.map(async (id, i) => {
    const j = await admApi('GET', `/api/rotation/${id}/analytics?${_maQuery}`);
    const card = document.querySelector(`.rb-rot-card[data-id="${id}"]`);
    const name = card?.querySelector('.rb-rot-name')?.textContent?.trim() || `#${id}`;
    return { id, name, color: ROT_COLORS[i % ROT_COLORS.length], groups: j.groups || [] };
  }));

  // geo → offerId → {name, byRot: {rotId: item}}
  const geoMap = new Map();
  for (const rot of results) {
    for (const g of rot.groups) {
      if (!geoMap.has(g.geo)) geoMap.set(g.geo, new Map());
      for (const item of g.items) {
        const om = geoMap.get(g.geo);
        if (!om.has(item.offerId)) om.set(item.offerId, { name: item.offerName, byRot: {} });
        om.get(item.offerId).byRot[rot.id] = item;
      }
    }
  }

  // Sort GEO by total uniq
  const sortedGeos = [...geoMap.entries()].sort((a, b) => {
    const sum = m => [...m.values()].reduce((s,o) => s + Object.values(o.byRot).reduce((x,it)=>x+(it.uniq||0),0), 0);
    return sum(b[1]) - sum(a[1]);
  });

  const legend = results.map(r =>
    `<span class="rb-ma-leg" style="border-color:${r.color}55;color:${r.color};background:${r.color}11">
      <span class="rb-ma-dot" style="background:${r.color}"></span>${h(r.name)}
    </span>`
  ).join('');

  const totalGeos = sortedGeos.length;
  const totalOffers = sortedGeos.reduce((s,[,m]) => s+m.size, 0);

  // Single unified table with GEO separator rows
  const colHeaders = results.map(r =>
    `<th class="rb-ma-th-num" style="border-left:2px solid ${r.color}">Uniq</th>
     <th class="rb-ma-th-num">DPU</th>
     <th class="rb-ma-th-num">Вес</th>`
  ).join('');

  const tableRows = sortedGeos.map(([geo, offerMap]) => {
    const rotMeta = results.map(r => {
      const cnt = [...offerMap.values()].filter(o => o.byRot[r.id]).length;
      return cnt ? `<span style="color:${r.color}">${r.name.split(' ')[0]}: ${cnt}</span>` : '';
    }).filter(Boolean).join(' · ');

    const geoRow = `<tr class="rb-ma-geo-row">
      <td colspan="${1 + results.length * 3}" style="padding:7px 14px;background:var(--bg2);font-size:11px;font-weight:500;color:var(--text2);border-top:0.5px solid var(--border2);border-bottom:0.5px solid var(--border)">
        ${h(geo)} &nbsp;<span style="font-weight:400;color:var(--text3);font-size:10px">${rotMeta}</span>
      </td>
    </tr>`;

    const offerRows = [...offerMap.entries()].map(([oid, o]) => {
      const cells = results.map((r, ri) => {
        const it  = o.byRot[r.id];
        const wid = `ma_${String(oid).replace(/[^a-z0-9]/gi,'_')}_${ri}`;
        if (!it) return `
          <td style="border-left:2px solid ${r.color};text-align:right;color:var(--text3)">—</td>
          <td style="text-align:right;color:var(--text3)">—</td>
          <td style="text-align:right;color:var(--text3)">—</td>`;
        const dpuClr = (it.dpu||0)>0.3?'#10b981':(it.dpu||0)>0.1?'#f59e0b':'var(--text3)';
        return `
          <td style="border-left:2px solid ${r.color};text-align:right;font-family:monospace;font-size:12px">${(it.uniq||0).toLocaleString()}</td>
          <td style="text-align:right;font-family:monospace;font-size:12px;color:${dpuClr}">${it.dpu?'$'+it.dpu.toFixed(2):'—'}</td>
          <td style="text-align:right">
            <div class="rb-w-cell" id="${wid}-cell" style="justify-content:flex-end">
              <span class="rb-w-val" id="${wid}-val">${it.weight}</span>
              <button class="rb-w-btn" onclick="admRotEditWeight('${wid}','${h(String(oid))}','${h(String(r.id))}')" title="Изменить вес">✎</button>
            </div>
          </td>`;
      }).join('');

      return `<tr class="rb-ma-offer-row">
        <td style="padding:7px 14px;font-size:12px;color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${h(o.name)}">${h(o.name)}</td>
        ${cells}
      </tr>`;
    }).join('');

    return geoRow + offerRows;
  }).join('');

  if (detail) detail.innerHTML = `
    <div class="rb-ma-legend">
      ${legend}
      <span style="margin-left:auto;font-size:11px;color:var(--text3)">${totalGeos} GEO · ${totalOffers} офф</span>
    </div>
    <div style="overflow:auto">
      <table class="rb-ma-unified">
        <thead>
          <tr>
            <th style="text-align:left;min-width:200px">Оффер</th>
            ${colHeaders}
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>`;
}


// ══════════════════════════════════════════════════════════
// INVOICES — admin panel
// ══════════════════════════════════════════════════════════

let _invMonth = (() => {
  const d = new Date(); d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 7);
})();
let _invList = [];

async function admLoadInvoices() {
  const el = document.getElementById('admInvoicesContent');
  if (!el) return;
  el.innerHTML = admInvLoadingHtml();

  const j = await admApi('GET', `/api/admin/invoices?month=${_invMonth}`);
  if (!j.ok) { el.innerHTML = `<div class="adm-empty">Ошибка: ${h(j.error||'')}</div>`; return; }

  _invList = j.invoices || [];
  admRenderInvoices(el);
}

function admRenderInvoices(el) {
  const statusLabels = {
    pending:    '⏳ Ожидает',
    filled:     '✏️ Заполнен',
    review:     '🔍 На проверке',
    confirmed:  '✅ Подтверждён',
    rejected:   '❌ Отклонён',
    questioned: '❓ Вопрос',
  };
  const statusColors = {
    pending:    'var(--text3)',
    filled:     '#818cf8',
    review:     '#f59e0b',
    confirmed:  'var(--green)',
    rejected:   'var(--red)',
    questioned: '#ef4444',
  };

  const toolbar = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
    <input type="month" value="${_invMonth}" onchange="_invMonth=this.value;admLoadInvoices()"
      style="background:var(--bg2);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:5px 10px;font-size:.82rem;font-family:inherit">
    <button class="btn" onclick="admInvCreateModal()" style="margin-left:auto;padding:5px 14px;font-size:.8rem">+ Создать счёт</button>
  </div>`;

  if (!_invList.length) {
    el.innerHTML = toolbar + '<div class="adm-empty">Счетов за этот период нет</div>';
    return;
  }

  const rows = _invList.map(inv => {
    const diff     = ((inv.paid_amount || 0) + (inv.hold_amount || 0)) - inv.binom_amount;
    const diffPct  = inv.binom_amount ? (diff / inv.binom_amount * 100).toFixed(1) : 0;
    const diffStr  = inv.binom_amount
      ? `<span style="color:${diff >= 0 ? 'var(--green)' : 'var(--red)'}">
           ${diff >= 0 ? '+' : ''}$${Math.abs(diff).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}
           (${diffPct}%)
         </span>` : '—';
    return `<tr style="cursor:pointer" onclick="admInvOpenModal(${inv.id})">
      <td style="font-weight:500">${h(inv.partner_name || inv.network_id)}</td>
      <td class="mono">$${(inv.binom_amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      <td class="mono">${inv.paid_amount != null ? '$'+inv.paid_amount.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'}</td>
      <td>${diffStr}</td>
      <td class="mono">
        ${(inv.hold_amount||0)>0
          ? (inv.hold_paid
              ? `<span style="color:var(--green)">✓ $${inv.hold_amount.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`
              : `<span style="color:#f59e0b">$${inv.hold_amount.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>`)
          : '—'}
      </td>
      <td><span style="font-size:.75rem;padding:2px 8px;border-radius:20px;background:rgba(128,128,128,.12);color:${statusColors[inv.status]||'var(--text3)'}">${statusLabels[inv.status]||inv.status}</span></td>
      <td style="font-size:.75rem;color:var(--text3)">${(inv.updated_at||'').slice(5,10)}</td>
    </tr>`;
  }).join('');

  el.innerHTML = toolbar + `
    <div style="background:var(--bg1);border:1px solid var(--border);border-radius:10px;overflow:hidden">
      <table style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead>
          <tr style="background:var(--bg2)">
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Партнёрка</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">По Binom</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Оплачено</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Разница</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Холд</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Статус</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Обновлён</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── Create invoice modal ───────────────────────────────────
async function admInvCreateModal() {
  const m = document.getElementById('admModal');
  if (!m) return;
  m.style.display = 'flex';
  document.getElementById('admModalTitle').textContent = 'Новый счёт';
  document.getElementById('admModalBody').innerHTML = '<div style="color:var(--text3);padding:20px;text-align:center">Загрузка партнёров...</div>';

  // Load partners list
  const jp = await admApi('GET', '/api/admin/partners');
  const partners = (jp.ok ? jp.partners || [] : []).filter(p => p.binom_network_id);

  document.getElementById('admModalBody').innerHTML = `
    <div style="margin-bottom:12px">
      <label style="font-size:.78rem;color:var(--text3);display:block;margin-bottom:3px">Партнёр <span style="color:var(--red)">*</span></label>
      <input class="adm-inp" id="invPartnerSearch" placeholder="Поиск по имени..."
        oninput="admInvFilterPartners(this.value)"
        style="margin-bottom:6px">
      <div id="invPartnerList" style="max-height:180px;overflow-y:auto;border:1px solid var(--border);border-radius:7px;background:var(--bg2)">
        ${partners.map(p => `
          <div class="inv-partner-opt" data-netid="${p.binom_network_id}" data-name="${h(p.username)}"
            onclick="admInvSelectPartner('${p.binom_network_id}','${h(p.username)}')"
            style="padding:8px 12px;cursor:pointer;font-size:.82rem;display:flex;justify-content:space-between;align-items:center;border-bottom:.5px solid var(--border)">
            <span>${h(p.username)}</span>
            <span style="font-size:.72rem;color:var(--text3);font-family:monospace">net:${p.binom_network_id}</span>
          </div>`).join('')}
        ${!partners.length ? '<div style="padding:12px;color:var(--text3);font-size:.82rem;text-align:center">Нет партнёров с привязанной сетью</div>' : ''}
      </div>
      <div id="invSelectedPartner" style="display:none;margin-top:6px;padding:6px 10px;background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.3);border-radius:7px;font-size:.82rem;display:flex;align-items:center;justify-content:space-between">
        <span id="invSelectedName" style="color:#a5b4fc;font-weight:500"></span>
        <button onclick="admInvClearPartner()" style="background:none;border:none;color:var(--text3);cursor:pointer;font-size:.9rem">✕</button>
      </div>
    </div>
    <div style="margin-bottom:12px">
      <label style="font-size:.78rem;color:var(--text3);display:block;margin-bottom:3px">Месяц <span style="color:var(--red)">*</span></label>
      <input class="adm-inp" id="invMonth" type="month" value="${_invMonth}">
    </div>
    <input type="hidden" id="invNetId">
    <div style="margin-bottom:12px">
      <label style="font-size:.78rem;color:var(--text3);display:block;margin-bottom:3px">Кошелёк для оплаты <span style="color:var(--red)">*</span></label>
      <div style="display:grid;grid-template-columns:1fr 120px;gap:8px">
        <input class="adm-inp" id="invWalletAddr" placeholder="TMxxxxxxxxxxxxxxxxxxxxxx" type="text">
        <select class="adm-inp" id="invWalletNet">
          <option value="TRC20">TRC20</option>
          <option value="ERC20">ERC20</option>
          <option value="BEP20">BEP20</option>
          <option value="SOL">SOL</option>
          <option value="BTC">BTC</option>
          <option value="Другое">Другое</option>
        </select>
      </div>
    </div>
    <button class="btn" onclick="admInvLoadBinom()" style="width:100%;margin-bottom:12px;font-size:.8rem">⟳ Загрузить данные из Binom</button>
    <div id="invBinomResult" style="display:none;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:12px;font-size:.8rem;max-height:220px;overflow-y:auto"></div>
    <input type="hidden" id="invBinomAmt" value="0">
    <div style="margin-top:4px;display:flex;justify-content:flex-end;gap:8px">
      <button class="btn-secondary" onclick="admModalClose()">Отмена</button>
      <button class="btn" onclick="admInvCreate()">Выставить счёт</button>
    </div>`;
}

function admInvFilterPartners(q) {
  const lq = q.toLowerCase();
  document.querySelectorAll('.inv-partner-opt').forEach(el => {
    const match = el.dataset.name.toLowerCase().includes(lq) || el.dataset.netid.includes(lq);
    el.style.display = match ? '' : 'none';
  });
}

function admInvSelectPartner(netId, name) {
  document.getElementById('invNetId').value = netId;
  const sel = document.getElementById('invSelectedPartner');
  if (sel) { sel.style.display = 'flex'; }
  const nm = document.getElementById('invSelectedName');
  if (nm) nm.textContent = name + '  (net:' + netId + ')';
  document.getElementById('invPartnerList').style.display = 'none';
  document.getElementById('invPartnerSearch').style.display = 'none';
}

function admInvClearPartner() {
  document.getElementById('invNetId').value = '';
  const sel = document.getElementById('invSelectedPartner');
  if (sel) sel.style.display = 'none';
  document.getElementById('invPartnerList').style.display = '';
  document.getElementById('invPartnerSearch').style.display = '';
  document.getElementById('invPartnerSearch').value = '';
  admInvFilterPartners('');
}

let _invBinomOffers = [];

async function admInvLoadBinom() {
  const netId = document.getElementById('invNetId')?.value.trim();
  const month = document.getElementById('invMonth')?.value.trim();
  const resEl = document.getElementById('invBinomResult');
  if (!netId || !month) { alert('Укажите Network ID и месяц'); return; }

  resEl.style.display = 'block';
  resEl.innerHTML = '<div style="color:var(--text3)">Загрузка из Binom...</div>';

  const j = await admApi('GET', `/api/admin/invoices/binom_data?network_id=${netId}&month=${month}`);
  if (!j.ok) { resEl.innerHTML = `<div style="color:var(--red)">Ошибка: ${h(j.error||'')}</div>`; return; }

  _invBinomOffers = j.offers || [];
  const amtInp = document.getElementById('invBinomAmt');
  if (amtInp) amtInp.value = j.total || 0;

  if (!_invBinomOffers.length) {
    resEl.innerHTML = '<div style="color:var(--text3)">Нет данных за этот период</div>';
    return;
  }

  resEl.innerHTML = `
    <div style="font-size:.72rem;color:var(--text3);margin-bottom:6px;font-weight:500;text-transform:uppercase;letter-spacing:.05em">Разбивка по офферам</div>
    <table style="width:100%;border-collapse:collapse">
      <tr style="color:var(--text3);font-size:.72rem">
        <th style="text-align:left;padding:2px 4px">Оффер</th>
        <th style="text-align:right;padding:2px 4px">FD</th>
        <th style="text-align:right;padding:2px 4px">Сумма</th>
      </tr>
      ${_invBinomOffers.map(o => `
        <tr style="border-top:.5px solid var(--border)">
          <td style="padding:3px 4px;color:var(--text2);font-size:.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(o.offer_name)}</td>
          <td style="padding:3px 4px;text-align:right;font-family:monospace;color:var(--text3)">${o.fd}</td>
          <td style="padding:3px 4px;text-align:right;font-family:monospace;font-weight:500">$${(o.amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
        </tr>`).join('')}
      <tr style="border-top:1px solid var(--border)">
        <td style="padding:4px;font-weight:500">Итого</td>
        <td></td>
        <td style="padding:4px;text-align:right;font-family:monospace;font-weight:500">$${(j.total||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      </tr>
    </table>`;
}

async function admInvCreate() {
  const netId  = document.getElementById('invNetId')?.value.trim();
  const month  = document.getElementById('invMonth')?.value.trim();
  const amount = parseFloat(document.getElementById('invBinomAmt')?.value) || 0;
  if (!netId || !month) { alert('Укажите Network ID и месяц'); return; }

  const walletAddr = document.getElementById('invWalletAddr')?.value.trim();
  const walletNet  = document.getElementById('invWalletNet')?.value || 'TRC20';
  if (!walletAddr) { alert('Укажите кошелёк для оплаты'); return; }

  const j = await admApi('POST', '/api/admin/invoices', {
    network_id:      netId,
    month:           month,
    binom_amount:    amount,
    offer_breakdown: _invBinomOffers,
    wallet_address:  walletAddr,
    wallet_network:  walletNet,
  });
  if (!j.ok) { alert('Ошибка: ' + (j.error || '')); return; }
  admModalClose();
  admLoadInvoices();
}

// ── View/review invoice modal ─────────────────────────────
async function admInvOpenModal(invId) {
  const m = document.getElementById('admModal');
  if (!m) return;
  m.style.display = 'flex';
  document.getElementById('admModalTitle').textContent = 'Счёт #' + invId;
  document.getElementById('admModalBody').innerHTML = '<div style="color:var(--text3);padding:20px;text-align:center">Загрузка...</div>';

  const j = await admApi('GET', `/api/admin/invoices/${invId}`);
  if (!j.ok) { document.getElementById('admModalBody').innerHTML = `<div style="color:var(--red)">Ошибка</div>`; return; }

  const inv  = j.invoice;
  const msgs = j.messages || [];
  const breakdown = inv.offer_breakdown || [];
  const txs  = inv.tx_hashes || [];

  const statusLabels = {pending:'⏳ Ожидает',filled:'✏️ Заполнен',review:'🔍 На проверке',confirmed:'✅ Подтверждён',rejected:'❌ Отклонён',questioned:'❓ Вопрос'};

  const diffVal  = ((inv.paid_amount||0) + (inv.hold_amount||0)) - inv.binom_amount;
  const diffPct  = inv.binom_amount ? (diffVal/inv.binom_amount*100).toFixed(1) : 0;
  const diffColor = diffVal >= 0 ? 'var(--green)' : 'var(--red)';

  const offersHtml = breakdown.length ? `
    <div style="background:var(--bg1);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:12px">
      <div style="padding:6px 12px;font-size:.72rem;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)">Данные Binom</div>
      <table style="width:100%;border-collapse:collapse;font-size:.78rem">
        <tr style="color:var(--text3)">
          <th style="padding:5px 10px;text-align:left;font-weight:400">Оффер</th>
          <th style="padding:5px 10px;text-align:right;font-weight:400">FD</th>
          <th style="padding:5px 10px;text-align:right;font-weight:400">Сумма</th>
        </tr>
        ${breakdown.slice(0,8).map(o => `
          <tr style="border-top:.5px solid var(--border)">
            <td style="padding:4px 10px;color:var(--text2);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(o.offer_name||'')}</td>
            <td style="padding:4px 10px;text-align:right;font-family:monospace;color:var(--text3)">${o.fd||0}</td>
            <td style="padding:4px 10px;text-align:right;font-family:monospace">$${(o.amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
          </tr>`).join('')}
        ${breakdown.length > 8 ? `<tr><td colspan="3" style="padding:4px 10px;color:var(--text3);font-size:.72rem">+ ${breakdown.length-8} других</td></tr>` : ''}
      </table>
    </div>` : '';

  const chatHtml = msgs.length ? msgs.map(m =>
    `<div style="margin-bottom:8px">
       <div style="font-size:.7rem;color:var(--text3);margin-bottom:2px">${m.author === 'admin' ? '🔑 Админ' : '👤 Партнёр'} · ${(m.created_at||'').slice(5,16)}</div>
       <div style="background:${m.author==='admin'?'rgba(99,102,241,.1)':'var(--bg2)'};border:1px solid var(--border);border-radius:7px;padding:7px 10px;font-size:.82rem;line-height:1.5">${h(m.text)}</div>
     </div>`).join('') : '<div style="color:var(--text3);font-size:.8rem">Сообщений нет</div>';

  const canAct = inv.status === 'review' || inv.status === 'questioned';

  document.getElementById('admModalBody').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px">
      <div style="background:var(--bg1);border:1px solid var(--border);border-radius:8px;padding:10px">
        <div style="font-size:.7rem;color:var(--text3);margin-bottom:3px">По Binom</div>
        <div style="font-size:1.1rem;font-weight:500;font-family:monospace">$${(inv.binom_amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
      </div>
      <div style="background:var(--bg1);border:1px solid var(--border);border-radius:8px;padding:10px">
        <div style="font-size:.7rem;color:var(--text3);margin-bottom:3px">Оплачено</div>
        <div style="font-size:1.1rem;font-weight:500;font-family:monospace;color:var(--green)">
          ${inv.paid_amount != null ? '$'+inv.paid_amount.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'}
        </div>
        <div style="font-size:.72rem;color:${diffColor};margin-top:2px">${inv.paid_amount!=null?`${diffVal>=0?'+':''}$${Math.abs(diffVal).toFixed(2)} (${diffPct}%)`:'—'}</div>
      </div>
      <div style="background:${(inv.hold_amount||0)>0 ? (inv.hold_paid?'rgba(34,197,94,.1)':'rgba(245,158,11,.1)') : 'var(--bg2)'};border:1px solid ${(inv.hold_amount||0)>0 ? (inv.hold_paid?'rgba(34,197,94,.4)':'rgba(245,158,11,.4)') : 'var(--border)'};border-radius:8px;padding:10px">
        <div style="font-size:.7rem;color:var(--text3);margin-bottom:3px">Холд</div>
        <div style="font-size:1.1rem;font-weight:500;font-family:monospace;color:${(inv.hold_amount||0)>0 ? (inv.hold_paid?'var(--green)':'#f59e0b') : 'var(--text3)'}">
          ${(inv.hold_amount||0)>0 ? '$'+inv.hold_amount.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}) : '$0'}
        </div>
        ${inv.hold_paid
          ? `<div style="font-size:.7rem;color:var(--green);margin-top:2px">✓ Выплачен</div>`
          : (inv.hold_reason ? `<div style="font-size:.7rem;color:#f59e0b;margin-top:2px">${h(inv.hold_reason)}</div>` : '')}
      </div>
    </div>

    ${inv.wallet_address ? `
      <div style="background:var(--bg1);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <div style="font-size:.7rem;color:var(--text3);margin-bottom:3px">Кошелёк для оплаты</div>
          <div style="font-family:monospace;font-size:.82rem;color:var(--text);word-break:break-all">${h(inv.wallet_address)}</div>
        </div>
        <span style="font-size:.72rem;padding:2px 8px;border-radius:4px;background:var(--bg2);color:var(--text3);margin-left:10px;flex-shrink:0">${h(inv.wallet_network||'')}</span>
      </div>` : ''}

    ${offersHtml}

    ${inv.hold_paid ? `
      <div style="background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:.8rem;color:var(--green)">
        ✅ Холд выплачен
      </div>` : (inv.hold_amount > 0 ? `
      <div style="background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:.8rem;color:#f59e0b;display:flex;justify-content:space-between;align-items:center">
        <span>⏳ Холд $${(inv.hold_amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})} — ожидает выплаты</span>
        <button class="btn" onclick="admMarkHoldPaid(${inv.id})" style="padding:3px 10px;font-size:.72rem">Отметить выплаченным</button>
      </div>` : '')}

    ${inv.partner_comment ? `
      <div style="background:var(--bg1);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px">
        <div style="font-size:.7rem;color:var(--text3);margin-bottom:4px">Комментарий партнёра</div>
        <div style="font-size:.82rem;color:var(--text2);line-height:1.5">${h(inv.partner_comment)}</div>
      </div>` : ''}

    ${txs.length ? `
      <div style="margin-bottom:12px">
        <div style="font-size:.7rem;color:var(--text3);margin-bottom:4px">Транзакции:</div>
        ${txs.map(tx => `<div style="font-family:monospace;font-size:.72rem;color:#818cf8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><a href="${h(tx)}" target="_blank" style="color:#818cf8">${h(tx)}</a></div>`).join('')}
      </div>` : ''}

    <div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:12px">
      <div style="font-size:.7rem;color:var(--text3);margin-bottom:8px;font-weight:500">Переписка</div>
      <div id="invChat_${invId}" style="margin-bottom:8px;max-height:180px;overflow-y:auto">${chatHtml}</div>
      <div style="display:flex;gap:6px">
        <input class="adm-inp" id="invMsgInput_${invId}" placeholder="Написать сообщение..." style="flex:1;font-size:.8rem">
        <button class="btn" onclick="admInvSendMsg(${invId})" style="padding:5px 10px;font-size:.78rem">Отправить</button>
      </div>
    </div>

    ${canAct ? `
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn-secondary" onclick="admInvAction(${invId},'reject')" style="color:var(--red)">❌ Отклонить</button>
        <button class="btn-secondary" onclick="admInvAction(${invId},'question')">❓ Задать вопрос</button>
        <button class="btn" onclick="admInvAction(${invId},'confirm')">✅ Подтвердить</button>
      </div>` : `<div style="text-align:right;font-size:.8rem;color:var(--text3)">${statusLabels[inv.status]||inv.status}</div>`}`;
}

async function admInvSendMsg(invId) {
  const inp  = document.getElementById(`invMsgInput_${invId}`);
  const text = inp?.value.trim();
  if (!text) return;
  const j = await admApi('POST', `/api/admin/invoices/${invId}/message`, { text });
  if (!j.ok) { alert('Ошибка'); return; }
  inp.value = '';
  admInvOpenModal(invId);
}

async function admInvAction(invId, action) {
  let comment = '';
  if (action === 'reject' || action === 'question') {
    comment = prompt(action === 'reject' ? 'Причина отклонения:' : 'Ваш вопрос:');
    if (!comment) return;
  }
  const j = await admApi('POST', `/api/admin/invoices/${invId}/action`, { action, comment });
  if (!j.ok) { alert('Ошибка: ' + (j.error||'')); return; }
  admModalClose();
  admLoadInvoices();
}

async function admMarkHoldPaid(invId) {
  if (!confirm('Отметить холд как выплаченный?')) return;
  const j = await admApi('POST', `/api/admin/invoices/${invId}/action`, {
    action: 'mark_hold_paid', comment: 'Холд отмечен выплаченным администратором'
  });
  if (!j.ok) { alert('Ошибка: ' + (j.error||'')); return; }
  admInvOpenModal(invId);
}

async function admLoadHolds() {
  const el = document.getElementById('admHoldsContent');
  if (!el) return;
  el.innerHTML = admInvLoadingHtml();

  const j = await admApi('GET', '/api/admin/invoices/holds');
  if (!j.ok) { el.innerHTML = `<div class="adm-empty">Ошибка: ${h(j.error||'')}</div>`; return; }

  const holds = j.holds || [];
  if (!holds.length) {
    el.innerHTML = '<div class="adm-empty">Нет активных холдов</div>';
    return;
  }

  const total = holds.reduce((s, h) => s + (h.hold_amount||0), 0);
  el.innerHTML = `
    <div style="margin-bottom:14px;padding:12px 16px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:.82rem;color:#f59e0b">Всего в холде</span>
      <span style="font-family:monospace;font-size:1.1rem;font-weight:500;color:#f59e0b">$${total.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
    </div>
    <div style="background:var(--bg1);border:1px solid var(--border);border-radius:10px;overflow:hidden">
      <table style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead>
          <tr style="background:var(--bg2)">
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Партнёр</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Месяц</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Сумма холда</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Причина</th>
            <th style="padding:8px 12px;text-align:left;font-weight:500;color:var(--text3);border-bottom:1px solid var(--border)">Статус счёта</th>
            <th style="padding:8px 12px;border-bottom:1px solid var(--border)"></th>
          </tr>
        </thead>
        <tbody>
          ${holds.map(hold => `
            <tr style="cursor:pointer" onclick="admInvOpenModal(${hold.id})">
              <td style="padding:8px 12px;font-weight:500">${h(hold.partner_name||hold.network_id)}</td>
              <td style="padding:8px 12px;font-family:monospace">${h(hold.month)}</td>
              <td style="padding:8px 12px;font-family:monospace;color:#f59e0b;font-weight:500">$${(hold.hold_amount||0).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
              <td style="padding:8px 12px;color:var(--text3);font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${h(hold.hold_reason||'—')}</td>
              <td style="padding:8px 12px"><span style="font-size:.75rem;padding:2px 8px;border-radius:20px;background:var(--bg2);color:var(--text3)">${h(hold.status)}</span></td>
              <td style="padding:8px 12px">
                <button class="btn" onclick="event.stopPropagation();admMarkHoldPaid(${hold.id})" style="padding:3px 10px;font-size:.72rem">Выплачен</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function admInvLoadingHtml() {
  return '<div class="adm-empty"><div class="spinner"></div> Загрузка…</div>';
}