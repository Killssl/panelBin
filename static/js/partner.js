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
  await Promise.all([loadMyOffers(), loadRequests(), loadBaseOffers()]);
  loadTraffic();
}

// ── TABS ─────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + tab));
  if (tab === 'requests')  loadRequests();
  if (tab === 'my_offers') loadMyOffers();
  if (tab === 'traffic')   loadTraffic();
}

// ── МОИ ОФФЕРЫ ────────────────────────────────────
let _myOffers = [];
let _myOffersFilter = 'active';

async function loadMyOffers(forceRefresh = false) {
  const el = document.getElementById('myOffersList');
  if (!el) return;
  el.innerHTML = '<div class="empty"><div class="empty-icon">⏳</div>Загрузка...</div>';

  if (forceRefresh) {
    await api('POST', '/api/partner/refresh_offers_cache');
  }

  const j = await api('GET', '/api/partner/my_offers');
  if (!j.ok) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${h(j.error || 'Ошибка загрузки')}</div>`;
    return;
  }

  _myOffers = j.offers || [];
  renderMyOffers();
}

function setMyOffersFilter(f, btn) {
  _myOffersFilter = f;
  document.querySelectorAll('.mo-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderMyOffers();
}

function renderMyOffers() {
  const el = document.getElementById('myOffersList');
  if (!el) return;

  const filtered = _myOffers.filter(o =>
    _myOffersFilter === 'all'     ? true :
    _myOffersFilter === 'active'  ? o.status === 'active' :
    _myOffersFilter === 'stopped' ? o.status === 'stopped' : true
  );

  if (!filtered.length) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>Нет офферов в этой категории</div>';
    return;
  }

  // Группируем по стране
  const byCountry = {};
  for (const o of filtered) {
    const country = o.country || '—';
    if (!byCountry[country]) byCountry[country] = [];
    byCountry[country].push(o);
  }

  el.innerHTML = Object.entries(byCountry).sort(([a],[b]) => a.localeCompare(b)).map(([country, offs]) => `
    <div class="geo-section">
      <div class="geo-label">🌍 ${h(country)}</div>
      ${offs.map(o => {
        const cap    = o.max_cap;
        const payout = o.payout ? `${o.payout} ${o.currency}` : '';
        const capTxt = cap ? `Кап: ${cap}` : '';
        const statusDot = o.status === 'active'  ? '<span style="color:#10b981;font-size:.75em">● Активен</span>'
                        : o.status === 'stopped' ? '<span style="color:#ef4444;font-size:.75em">● Стоп</span>'
                        : '';
        return `<div class="offer-row">
          <div class="offer-name">${h(o.name)}</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            ${statusDot}
            ${payout ? `<div class="offer-rate">${h(payout)}</div>` : ''}
            ${capTxt  ? `<div class="offer-cap">${h(capTxt)}</div>` : ''}
            ${o.url   ? `<a href="${h(o.url)}" target="_blank" style="font-size:.75em;color:var(--blue)">🔗 ссылка</a>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>
  `).join('');
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
function toggleChip(el) {
  el.classList.toggle('selected');
}

// Base offer list from Binom
let _baseOffers = [];
let _networkPostback = '';

async function loadBaseOffers() {
  const j = await api('GET', '/api/partner/my_offers');
  if (!j.ok) return;
  _baseOffers = (j.offers || []).filter(o => o.status === 'active' || o.status === 'unknown');
  _networkPostback = j.network_postback || '';
  renderBaseOffers(_baseOffers);
  // Подставляем постбек в форму если поле пустое
  const pbInp = document.getElementById('rPostback');
  if (pbInp && !pbInp.value && _networkPostback) {
    pbInp.value = _networkPostback;
  }
}

function renderBaseOffers(list) {
  const sel = document.getElementById('rBaseOffer');
  if (!sel) return;
  sel.innerHTML = '<option value="">— не выбрано —</option>' +
    list.map(o => `<option value="${h(String(o.id))}" data-url="${h(o.url||'')}" data-country="${h(o.country||'')}">${h(o.name)}</option>`).join('');
}

function filterBaseOffers(q) {
  if (!q) { renderBaseOffers(_baseOffers); return; }
  const ql = q.toLowerCase();
  renderBaseOffers(_baseOffers.filter(o => (o.name||'').toLowerCase().includes(ql)));
}

function onBaseOfferSelect(sel) {
  const opt = sel.options[sel.selectedIndex];
  if (!opt || !opt.value) return;
  // Pre-fill URL if empty
  const urlInp = document.getElementById('rUrl');
  if (urlInp && !urlInp.value) {
    urlInp.value = opt.dataset.url || '';
  }
  // Pre-fill GEO if empty
  const geoInp = document.getElementById('rGeo');
  if (geoInp && !geoInp.value) {
    geoInp.value = opt.dataset.country || '';
  }
  // Pre-fill postback from network
  const pbInp = document.getElementById('rPostback');
  if (pbInp && !pbInp.value && _networkPostback) {
    pbInp.value = _networkPostback;
  }
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
  const postback = document.getElementById('rPostback')?.value.trim() || '';
  const comment  = document.getElementById('rComment').value.trim();
  const errEl    = document.getElementById('rErr');
  const btn      = document.getElementById('rBtn');

  // Approach (multi-select)
  const approachEls = document.querySelectorAll('#rApproachGroup .chip.selected');
  const approaches  = [...approachEls].map(el => el.dataset.val);
  const approach    = approaches.join(', ');

  errEl.textContent = '';
  if (!approach) { errEl.textContent = 'Выберите хотя бы один подход'; return; }
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
    offer_name: fullName, geo, rate, offer_url: url,
    postback_url: postback || undefined, comment: fullComment
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
  document.getElementById('rBaseOffer').value = '';
  const pbEl = document.getElementById('rPostback'); if (pbEl) pbEl.value = _networkPostback || '';
  document.getElementById('rBaseOfferSearch').value = '';
  renderBaseOffers(_baseOffers);
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

// ── TRAFFIC ──────────────────────────────────────

// Country codes → flag emoji
function geoFlag(code) {
  if (!code || code.length !== 2) return '';
  return String.fromCodePoint(...[...code.toUpperCase()].map(c => 0x1F1E6 + c.charCodeAt(0) - 65));
}

// Country code → name
const GEO_NAMES = {
  BR:'Brazil',TR:'Turkey',FR:'France',IN:'India',PL:'Poland',
  DE:'Germany',ES:'Spain',IT:'Italy',NL:'Netherlands',GB:'United Kingdom',
  AR:'Argentina',MX:'Mexico',CL:'Chile',CO:'Colombia',PE:'Peru',
  UA:'Ukraine',KZ:'Kazakhstan',RU:'Russia',AE:'UAE',SA:'Saudi Arabia',
  GH:'Ghana',NG:'Nigeria',ZA:'South Africa',MZ:'Mozambique',
  PT:'Portugal',BE:'Belgium',CH:'Switzerland',AT:'Austria',CZ:'Czech Republic',
  RO:'Romania',HU:'Hungary',LV:'Latvia',LT:'Lithuania',EE:'Estonia',
  MY:'Malaysia',TH:'Thailand',PH:'Philippines',ID:'Indonesia',SG:'Singapore',
  AU:'Australia',NZ:'New Zealand',CA:'Canada',US:'United States',
};

async function loadTraffic() {
  const el = document.getElementById('trafficContent');
  if (!el) return;
  el.innerHTML = '<div class="empty"><div class="empty-icon">⏳</div>Загрузка трафика...</div>';

  const j = await api('GET', '/api/partner/traffic');
  if (!j.ok) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${h(j.error || 'Ошибка загрузки')}</div>`;
    return;
  }

  const cards = j.cards || [];
  if (!cards.length) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>Нет данных за неделю</div>';
    return;
  }

  const totalUniq = cards.reduce((s, c) => s + c.total_uniq, 0);

  el.innerHTML = `
    <div class="wk-meta">
      <span>${h(j.date_from)} — ${h(j.date_to)}</span>
      <span class="wmeta-sep">·</span>
      <b>${totalUniq.toLocaleString()}</b> уников
      <span class="wmeta-sep">·</span>
      ${cards.length} офферов
    </div>
    <div class="weekly-cards">
      ${cards.map(card => {
        const maxUniq = card.geos[0]?.uniq || 1;
        return `<div class="wcard">
          <div class="wcard-header">
            <div class="wcard-header-left">
              <div class="wcard-title">${h(card.name)}</div>
              <div class="wcard-badge">${card.total_uniq.toLocaleString()} uniq</div>
            </div>
          </div>
          <div class="wcard-rows">
            ${card.geos.map((g, i) => {
              const pct  = Math.round(g.uniq / maxUniq * 100);
              const flag = geoFlag(g.code);
              const name = GEO_NAMES[g.code] || g.code;
              const isTop = i === 0;
              return `<div class="wrow${isTop ? ' wrow-top' : ''}">
                <div class="wrow-rank">${i+1}</div>
                <div class="wrow-country">
                  <span class="wrow-flag">${flag}</span>
                  <span class="wrow-geo-name">${h(name)}</span>
                  <span class="wrow-geo-code">${h(g.code)}</span>
                </div>
                <div class="wrow-bar-wrap"><div class="wrow-bar" style="width:${pct}%"></div></div>
                <div class="wrow-uniq">${g.uniq.toLocaleString()}</div>
                ${g.fd > 0 ? `<span class="wk-fd-badge">${g.fd} FD</span>` : '<span></span>'}
              </div>`;
            }).join('')}
          </div>
        </div>`;
      }).join('')}
    </div>`;
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