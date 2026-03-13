const API = window.APP_PREFIX || '';
let TOKEN = localStorage.getItem('partnerToken') || '';
let ME    = null;

// ── API ──────────────────────────────────────────
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' }
  };
  if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
  if (body)  opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  return r.json();
}

// ── AUTH ─────────────────────────────────────────
async function doLogin() {
  const username = document.getElementById('lUser').value.trim();
  const password = document.getElementById('lPass').value.trim();
  const errEl    = document.getElementById('lErr');
  const btn      = document.getElementById('lBtn');
  errEl.textContent = '';
  if (!username || !password) { errEl.textContent = 'Заполните все поля'; return; }
  btn.disabled = true;
  btn.textContent = 'Вхожу...';
  const j = await api('POST', '/api/auth/login', { username, password });
  btn.disabled = false;
  btn.textContent = 'Войти';
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка входа'; return; }
  if (j.role === 'admin') { errEl.textContent = 'Это кабинет партнёра. Используйте /admin'; return; }
  TOKEN = j.token;
  ME    = j;
  localStorage.setItem('partnerToken', TOKEN);
  showApp();
}

function doLogout() {
  TOKEN = '';
  ME    = null;
  localStorage.removeItem('partnerToken');
  document.getElementById('app').classList.remove('visible');
  document.getElementById('loginScreen').style.display = 'flex';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('loginScreen').style.display !== 'none') doLogin();
});

async function checkAuth() {
  if (!TOKEN) return false;
  const j = await api('GET', '/api/auth/me');
  if (!j.ok || j.role === 'admin') { localStorage.removeItem('partnerToken'); TOKEN = ''; return false; }
  ME = j;
  return true;
}

async function showApp() {
  document.getElementById('loginScreen').style.display = 'none';
  document.getElementById('app').classList.add('visible');
  document.getElementById('hUser').textContent = ME.username;
  await Promise.all([loadOffers(), loadRequests()]);
}

// ── TABS ─────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + tab));
  if (tab === 'requests') loadRequests();
}

// ── OFFERS ───────────────────────────────────────
async function loadOffers() {
  const j = await api('GET', '/api/panel');
  const el = document.getElementById('offersList');
  if (!j.ok || !j.data) { el.innerHTML = '<div class="empty"><div class="empty-icon">⚠️</div>Не удалось загрузить офферы</div>'; return; }

  const rotations = (j.data.rotations || []).filter(r => r.geos && r.geos.length);
  if (!rotations.length) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>Офферов пока нет</div>';
    return;
  }

  el.innerHTML = rotations.map(rot => {
    const totalOffers = rot.geos.reduce((s, g) => s + (g.offers || []).length, 0);
    const geoBlocks = rot.geos.map(geo => {
      const offers = (geo.offers || []).filter(o => o.status !== 'stop' && o.status !== 'no_perform');
      if (!offers.length) return '';
      return `<div class="geo-section">
        <div class="geo-label">🌍 ${h(geo.name)}</div>
        ${offers.map(o => {
          const cap = o.cap;
          const filled = o.filled_cap || 0;
          const pct = cap ? Math.min(100, Math.round(filled / cap * 100)) : 0;
          const barClass = pct >= 90 ? 'danger' : pct >= 70 ? 'warn' : '';
          const capText = cap ? `${filled}/${cap}` : '∞';
          const rateText = o.rate ? `$${o.rate}` : '';
          return `<div class="offer-row">
            <div class="offer-name">${h(o.name)}</div>
            ${rateText ? `<div class="offer-rate">${h(rateText)}</div>` : ''}
            ${cap ? `<div class="cap-bar" title="${capText}"><div class="cap-fill ${barClass}" style="width:${pct}%"></div></div>` : ''}
            <div class="offer-cap ${pct >= 100 ? 'full' : ''}">${capText}</div>
          </div>`;
        }).join('')}
      </div>`;
    }).join('');

    return `<div class="rotation-block" id="rot-${h(rot.id)}">
      <div class="rotation-head" onclick="toggleRot('${rot.id}')">
        <div class="rotation-name">${h(rot.name)}</div>
        <div class="rotation-count">${totalOffers} офферов</div>
        <div class="chevron">▼</div>
      </div>
      <div class="geo-list">${geoBlocks}</div>
    </div>`;
  }).join('');
}

function toggleRot(id) {
  const el = document.getElementById('rot-' + id);
  if (el) el.classList.toggle('collapsed');
}

// ── REQUEST FORM ──────────────────────────────────
function selectChip(el) {
  el.closest('.chip-group').querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
}

function getCapValue() {
  const sel = document.getElementById('rCap').value;
  if (sel === 'custom') {
    const num = document.getElementById('rCapCustom').value.trim();
    return num ? `CAP${num}` : '';
  }
  return sel;
}

function updateCapPreview() {
  const cap  = getCapValue();
  const prev = document.getElementById('rCapPreview');
  if (cap) prev.textContent = `Префикс: [${cap}]`;
  else     prev.textContent = '';
}

function onCapChange(sel) {
  const customInp = document.getElementById('rCapCustom');
  if (sel.value === 'custom') {
    customInp.style.display = 'block';
    customInp.focus();
  } else {
    customInp.style.display = 'none';
    customInp.value = '';
  }
  updateCapPreview();
}

function onCapCustomInput(inp) {
  updateCapPreview();
}

async function submitRequest() {
  const name     = document.getElementById('rName').value.trim();
  const geo      = document.getElementById('rGeo').value.trim();
  const rateVal  = document.getElementById('rRate').value.trim();
  const currency = document.getElementById('rCurrency').value;
  const cap      = getCapValue();
  const url      = document.getElementById('rUrl').value.trim();
  const comment  = document.getElementById('rComment').value.trim();
  const errEl    = document.getElementById('rErr');
  const btn      = document.getElementById('rBtn');

  // Approach
  const approachEl = document.querySelector('#rApproachGroup .chip.selected');
  const approach   = approachEl ? approachEl.dataset.val : '';

  errEl.textContent = '';
  if (!approach) { errEl.textContent = 'Выберите подход (Crash / Casino / Betting)'; return; }
  if (!cap)      { errEl.textContent = 'Укажите кап (введите число)'; return; }
  if (!name)     { errEl.textContent = 'Укажите название оффера'; return; }
  if (!geo)      { errEl.textContent = 'Укажите GEO'; return; }

  const rate = rateVal ? `${rateVal} ${currency}` : '';
  // Build full offer name with cap prefix
  const fullName = `[${cap}] ${name}`;
  // Add approach to comment
  const fullComment = `Подход: ${approach}` + (comment ? `
${comment}` : '');

  btn.disabled = true;
  btn.textContent = 'Отправляю...';
  const j = await api('POST', '/api/partner/requests', {
    offer_name: fullName, geo, rate, offer_url: url, comment: fullComment
  });
  btn.disabled = false;
  btn.textContent = 'Отправить заявку';
  if (!j.ok) { errEl.textContent = j.error || 'Ошибка'; return; }
  showToast('Заявка отправлена!', true);
  clearForm();
  switchTab('requests');
  loadRequests();
}

function clearForm() {
  ['rName','rGeo','rRate','rUrl','rComment'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('rCap').value = 'Unlimited';
  document.getElementById('rCapCustom').value = '';
  document.getElementById('rCapCustom').style.display = 'none';
  document.getElementById('rCapPreview').textContent = '';
  document.getElementById('rCurrency').value = 'USD';
  document.querySelectorAll('#rApproachGroup .chip').forEach(c => c.classList.remove('selected'));
  document.getElementById('rErr').textContent = '';
}

// ── MY REQUESTS ───────────────────────────────────
async function loadRequests() {
  const j = await api('GET', '/api/partner/requests');
  const el = document.getElementById('requestsList');
  const badge = document.getElementById('pendingBadge');
  if (!j.ok) { el.innerHTML = '<div class="empty">Ошибка загрузки</div>'; return; }

  const reqs = j.requests || [];
  const pending = reqs.filter(r => r.status === 'pending').length;
  if (pending > 0) {
    badge.textContent = pending;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }

  if (!reqs.length) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">📨</div>Заявок ещё нет.<br>Отправьте первую во вкладке «Новая заявка»</div>';
    return;
  }

  const SL = { pending: '⏳ На рассмотрении', approved: '✅ Одобрена', rejected: '❌ Отклонена' };
  el.innerHTML = '<div class="req-list">' + reqs.map(r => {
    const d = new Date(r.updated_at || r.created_at);
    const dateStr = d.toLocaleDateString('ru') + ' ' + d.toLocaleTimeString('ru', {hour:'2-digit',minute:'2-digit'});
    const adminComment = r.admin_comment ? `<div class="req-comment admin">💬 ${h(r.admin_comment)}</div>` : '';
    const myComment    = r.comment       ? `<div class="req-comment">📝 ${h(r.comment)}</div>` : '';
    const rate = r.rate ? ` · ${h(r.rate)}` : '';
    return `<div class="req-card ${r.status}">
      <div>
        <div class="req-status ${r.status}">${SL[r.status] || r.status}</div>
      </div>
      <div>
        <div class="req-title">${h(r.offer_name)}</div>
        <div class="req-meta">🌍 ${h(r.geo)}${rate}${r.offer_url ? ` · <a href="${h(r.offer_url)}" target="_blank" style="color:var(--blue)">ссылка</a>` : ''}</div>
        ${myComment}${adminComment}
      </div>
      <div class="req-date">${dateStr}</div>
    </div>`;
  }).join('') + '</div>';
}

// ── UTILS ─────────────────────────────────────────
function h(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(msg, ok = true) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (ok ? 'ok' : 'fail');
  t.classList.add('show');
  clearTimeout(t._tm);
  t._tm = setTimeout(() => t.classList.remove('show'), 3000);
}

// ── INIT ──────────────────────────────────────────
(async () => {
  if (TOKEN && await checkAuth()) {
    showApp();
  }
})();