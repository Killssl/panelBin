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

const _PREFIX = (window.APP_PREFIX || '').replace(/\/$/, '');

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
    const r = await fetch(_PREFIX + path, opts);
    return r.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

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
    const r = await fetch(_PREFIX + '/api/auth/session_token');
    if (r.ok) {
      const j = await r.json();
      if (j.ok && j.token) {
        ADM.token = j.token;
              }
    }
  } catch(e) {}
})();


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
  admLoadNetworks();
  admLoadPendingCount();
}

['admLoginUser', 'admLoginPass'].forEach(id => {
  document.getElementById(id)?.addEventListener('keydown', e => {
    if (e.key === 'Enter') admDoLogin();
  });
});

// ─── Navigation ───────────────────────────────────────────────────────────────

const ADM_TITLES = { networks: 'Сети', requests: 'Заявки', users: 'Пользователи' };

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
}

// ─── Networks (from Binom) ────────────────────────────────────────────────────

async function admLoadNetworks() {
  const tbody = document.getElementById('admNetworksTbody');
  tbody.innerHTML = `<tr><td colspan="6" class="adm-empty">Загрузка из Binom…</td></tr>`;

  const j = await admApi('GET', '/api/admin/networks');

  if (!j.ok) {
    tbody.innerHTML = `<tr><td colspan="6" class="adm-empty" style="color:#ef4444">
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
    bodyEl.innerHTML = `<div class="adm-empty" style="color:#ef4444">Ошибка: ${h(j.error)}</div>`;
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
          <label>${h(f.label)}${f.required ? ' <span style="color:#ef4444">*</span>' : ''}</label>`;

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
          <b style="color:#e2e8f0">${h(acc.username || '—')}</b>
        </div>
        <div class="adm-partner-acc-row">
          <span class="adm-net-info-key">UID входа</span>
          <span class="adm-uid-pill" onclick="admCopyText('${h(acc.uid||'')}')" title="Нажмите скопировать">${h(acc.uid||'—')}</span>
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
        <button class="adm-btn sm" onclick="admRegenUID('${h(String(netId))}')">🎲 Новый UID</button>
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
          <label>Пароль <span style="color:#475569">(авто)</span></label>
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
  document.getElementById('admApproveCurrency').value     = 'USD';
  document.getElementById('admApprovePriority').value     = 'offers_in_path_alternative';
  document.getElementById('admApproveBindomErr').textContent = '';
  document.getElementById('admApproveAltOffer').innerHTML = '<option value="">— нет —</option>';
  const geoSel = document.getElementById('admApproveGeo');
  geoSel.innerHTML = '<option value="">— загрузите ротацию —</option>';
  geoSel.disabled  = true;

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
      `<b style="color:#e2e8f0;font-size:1.05em">${h(req.offer_name)}</b>`,
      `GEO: <b style="color:#60a5fa">${h(req.geo)}</b>`,
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
      document.getElementById('admApproveResetSec').value  = '86400';
      document.getElementById('admApproveResetFrom').value = '';
    }

    // Auto-select affiliate network by partner's binom_network_id
    admAutoSelectAffNet();
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
    drop.innerHTML = `<div style="padding:8px 12px;color:#475569;font-size:.8em">Не найдено — введите код вручную</div>`;
    return;
  }
  drop.innerHTML = list.map(c =>
    `<div onclick="admSelectCountry('${h(c.code)}','${h(c.name)}')"
          style="padding:7px 12px;cursor:pointer;font-size:.82em;display:flex;gap:10px;align-items:center;border-bottom:1px solid #1e2d45"
          onmouseover="this.style.background='#1e2d45'" onmouseout="this.style.background=''">
       <span style="color:#60a5fa;font-weight:600;min-width:28px">${h(c.code)}</span>
       <span style="color:#94a3b8">${h(c.name)}</span>
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

async function admLoadGeos() {
  const rotId = document.getElementById('admApproveRotId').value.trim();
  if (!rotId) return;
  const btn = document.getElementById('admLoadGeosBtn');
  btn.textContent = '⏳';
  btn.disabled = true;
  const j = await admApi('GET', `/api/rotation/${rotId}/active_offers_grouped`);
  btn.textContent = 'GEO ↓';
  btn.disabled = false;
  const errEl = document.getElementById('admApproveBindomErr');
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка загрузки ротации'; return; }
  errEl.textContent = '';
  const geoSel = document.getElementById('admApproveGeo');
  const geos = (j.groups || []).map(g => g.geoTitle);
  if (!geos.length) { errEl.textContent = 'Нет GEO в этой ротации'; return; }
  geoSel.innerHTML = '<option value="">— выберите GEO —</option>' +
    geos.map(g => `<option value="${h(g)}">${h(g)}</option>`).join('');
  geoSel.disabled = false;
  const reqGeo = (ADM.pendingReqData?.geo || '').toUpperCase().slice(0,2);
  if (reqGeo) {
    for (const opt of geoSel.options) {
      if (opt.value.toUpperCase().includes(reqGeo)) { opt.selected = true; break; }
    }
  }
}

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
  const rotId      = document.getElementById('admApproveRotId').value.trim();
  const geo        = document.getElementById('admApproveGeo').value.trim();
  const weight     = parseInt(document.getElementById('admApproveWeight').value) || 50;
  const comment    = document.getElementById('admApproveComment').value.trim();

  if (!name) { errEl.textContent = 'Укажите название оффера'; return; }
  if (!url)  { errEl.textContent = 'Укажите URL оффера'; return; }
  if (rotId && !geo) { errEl.textContent = 'Выберите GEO для ротации'; return; }

  errEl.style.color   = '#94a3b8';
  errEl.textContent   = '⏳ Создаю оффер в Binom...';

  const payload = {
    name, url,
    postback_url:          postback    || undefined,
    affiliate_network_id:  affNet      || undefined,
    country:               country     || undefined,
    payout:                payout      || undefined,
    currency,
    auto_payout:           autoPay,
    conversion_cap:        convCap,
    max_cap:               convCap && maxCap ? maxCap : undefined,
    reset_cap_seconds:     convCap && resetSec ? resetSec : undefined,
    reset_cap_from:        convCap && resetFrom ? resetFrom : undefined,
    alternative_offer_id:  altOffer    || undefined,
    // priority не передаём в offer body
    rotation_id:           rotId       || undefined,
    geo:                   geo         || undefined,
    weight,
  };

  const j = await admApi('POST', '/api/binom/offers', payload);
  if (!j.ok) {
    errEl.style.color   = '#e05050';
    errEl.textContent   = '❌ ' + (j.error || 'Ошибка создания оффера');
    return;
  }

  const offerIdMsg = j.binom_offer_id ? ` (ID: ${j.binom_offer_id})` : '';
  const rotMsg = j.rotation_added === true  ? ' + добавлен в ротацию ✓'
               : j.rotation_error           ? ` ⚠️ ${j.rotation_error}` : '';
  errEl.style.color   = '#3ecf8e';
  errEl.textContent   = `✅ Оффер создан${offerIdMsg}${rotMsg}`;

  await admApi('POST', `/api/admin/requests/${ADM.pendingReqId}/approve`, {
    comment: comment || `Оффер создан в Binom${offerIdMsg}`,
    rotation_id: rotId || undefined,
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

// ─── Google Sheets Sync Panel ─────────────────────────────────────────────────


function openSheetsSyncPanel() {
  document.getElementById("sheetsSyncPanel")?.remove();

  const panel = document.createElement("div");
  panel.id = "sheetsSyncPanel";
  panel.style.cssText = `
    position:fixed;top:0;right:0;width:420px;height:100vh;
    background:#0d1b2e;border-left:1px solid #1e3a5f;
    display:flex;flex-direction:column;z-index:3000;
    font-family:inherit;font-size:14px;color:#e2e8f0;
  `;
  panel.innerHTML = `
    <div style="padding:16px 20px;border-bottom:1px solid #1e3a5f;display:flex;justify-content:space-between;align-items:center">
      <b style="font-size:16px">📊 Google Sheets Sync</b>
      <button onclick="document.getElementById('sheetsSyncPanel').remove()" style="background:none;border:none;color:#94a3b8;font-size:20px;cursor:pointer">✕</button>
    </div>
    <div style="padding:20px;flex:1;overflow-y:auto">

      <!-- Статус автосинка -->
      <div id="ssSyncStatus" style="background:#0f1724;border:1px solid #1e3a5f;border-radius:8px;padding:12px;margin-bottom:16px">
        <div style="color:#94a3b8;margin-bottom:8px">Авто-синк Filled Cap</div>
        <div id="ssStatusText" style="color:#60a5fa">Загрузка...</div>
      </div>

      <!-- Управление авто-синком -->
      <div style="margin-bottom:16px">
        <div style="color:#94a3b8;font-size:12px;margin-bottom:6px">Интервал (минуты)</div>
        <input id="ssInterval" type="number" value="5" min="1" max="60"
          style="width:80px;background:#0f1724;border:1px solid #1e3a5f;border-radius:6px;padding:6px 10px;color:#e2e8f0;margin-right:8px">
        <button class="btn primary" onclick="ssToggle(true)" style="margin-right:6px">▶ Включить</button>
        <button class="btn" onclick="ssToggle(false)">⏹ Выключить</button>
      </div>

      <!-- Ручной запуск -->
      <div style="border-top:1px solid #1e3a5f;padding-top:16px;margin-bottom:16px">
        <div style="color:#94a3b8;font-size:12px;margin-bottom:8px">Ручной запуск</div>
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <button class="btn primary" onclick="ssRunNow(false)" style="flex:1">⟳ Синк сейчас</button>
          <button class="btn" onclick="ssRunNow(true)" style="flex:1">👁 Dry run</button>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn" onclick="ssFillIds(true)" style="flex:1">🔍 Fill IDs (preview)</button>
          <button class="btn primary" onclick="ssFillIds(false)" style="flex:1">✏️ Fill IDs</button>
        </div>
      </div>

      <!-- Лог последнего запуска -->
      <div id="ssSyncLog" style="background:#0f1724;border:1px solid #1e3a5f;border-radius:8px;padding:12px;font-size:12px;font-family:monospace;min-height:100px;white-space:pre-wrap;color:#94a3b8">
        Нажми "Синк сейчас" или "Dry run"...
      </div>
    </div>
  `;
  document.body.appendChild(panel);
  ssLoadStatus();
}

async function ssEnsureToken() {
  if (ADM.token) return true;
  try {
    const r = await fetch(_PREFIX + '/api/auth/session_token');
    if (r.ok) {
      const j = await r.json();
      if (j.ok && j.token) {
        ADM.token = j.token;
        return true;
      }
    }
  } catch(e) {}
  return false;
}

async function ssLoadStatus() {
  const ok = await ssEnsureToken();
  if (!ok) {
    const el = document.getElementById('ssStatusText');
    if (el) { el.style.color = '#f87171'; el.textContent = '🔒 Нужно войти в панель'; }
    return;
  }
  try {
    const j = await admApi('POST', '/api/sheets/schedule', {});
    const s = j.schedule || {};
    const el = document.getElementById('ssStatusText');
    if (!el) return;
    if (s.enabled) {
      el.style.color = '#3ecf8e';
      el.textContent = `✅ Включён — каждые ${s.interval_minutes || 5} мин`;
    } else {
      el.style.color = '#f87171';
      el.textContent = '⛔ Выключен';
    }
    if (s.interval_minutes) {
      const inp = document.getElementById('ssInterval');
      if (inp) inp.value = s.interval_minutes;
    }
  } catch(e) {}
}

async function ssToggle(enable) {
  if (!await ssEnsureToken()) { ssLog('🔒 Нужно войти в панель'); return; }
  const interval = parseInt(document.getElementById('ssInterval')?.value || 5);
  const j = await admApi('POST', '/api/sheets/schedule', {
    enabled: enable, interval_minutes: interval, sheet_name: 'all'
  });
  ssLog(enable ? `▶ Авто-синк включён (каждые ${interval} мин)` : '⏹ Авто-синк выключен');
  ssLoadStatus();
}

async function ssRunNow(dryRun) {
  if (!await ssEnsureToken()) { ssLog('🔒 Нужно войти в панель'); return; }
  ssLog('⟳ Запуск...');
  const j = await admApi('POST', '/api/sheets/sync_caps', {sheet_name: 'all', dry_run: dryRun});
  if (j.sheets) {
    let out = dryRun ? '👁 DRY RUN\n' : '✅ Готово\n';
    for (const [sheet, res] of Object.entries(j.sheets)) {
      const u = (res.updated || []).length;
      const nf = (res.not_found || []).length;
      out += `\n📋 ${sheet}: обновлено=${u} не найдено=${nf}`;
      if (res.error) out += ` ❌ ${res.error}`;
      for (const r of (res.updated || [])) {
        out += `\n  • ${r.sheet_name}: ${r.base}+${r.fd_today}=${r.filled_cap}`;
      }
    }
    ssLog(out);
  } else {
    ssLog(JSON.stringify(j, null, 2));
  }
}

async function ssFillIds(dryRun) {
  if (!await ssEnsureToken()) { ssLog('🔒 Нужно войти в панель'); return; }
  ssLog('🔍 Ищу Binom ID...');
  const j = await admApi('POST', '/api/sheets/fill_ids', {sheet_name: 'all', dry_run: dryRun});
  if (j.sheets) {
    let out = dryRun ? '👁 DRY RUN — IDs не записаны\n' : '✅ IDs записаны\n';
    for (const [sheet, res] of Object.entries(j.sheets)) {
      const f = (res.filled || []).length;
      const nf = (res.not_found || []).length;
      out += `\n📋 ${sheet}: найдено=${f} пропущено=${res.skipped||0} не найдено=${nf}`;
    }
    ssLog(out);
  } else {
    ssLog(JSON.stringify(j, null, 2));
  }
}

function ssLog(text) {
  const el = document.getElementById('ssSyncLog');
  if (el) el.textContent = text;
}