const API = window.APP_PREFIX || '';
let TOKEN = localStorage.getItem('partnerToken') || '';
let ME    = null;
let _partnerFd  = {};
let _partnerTrk = {};

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
  const hUser = document.getElementById('hUser');
  if (hUser) hUser.innerHTML = ME.username;
  await Promise.all([loadMyOffers(), loadRequests(), loadBaseOffers()]);
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
  el.innerHTML = '<div class="p-loading"><div class="p-spinner"></div><span>Загрузка...</span></div>';

  if (forceRefresh) {
    await api('POST', '/api/partner/refresh_offers_cache');
  }

  const [j, jfd] = await Promise.all([
    api('GET', '/api/partner/my_offers'),
    api('GET', '/api/partner/tracking_fd'),
  ]);
  if (!j.ok) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${h(j.error || 'Ошибка загрузки')}</div>`;
    return;
  }

  _myOffers  = j.offers || [];
  _partnerFd = jfd.fd || {};
  _partnerTrk = jfd.tracking || {};
  renderMyOffers();
}

function moScrollToGeo(id, el) {
  document.querySelectorAll('.mo-geo-nav-item').forEach(i => i.classList.remove('active'));
  el.classList.add('active');
  const sec = document.getElementById('geo-sec-' + id);
  if (!sec) return;
  // Считаем offset с учётом шапки и filter-bar
  const header     = document.querySelector('.header') || document.querySelector('header');
  const filterBar  = document.querySelector('.filter-bar');
  const offset     = (header?.offsetHeight || 0) + (filterBar?.offsetHeight || 0) + 12;
  const top = sec.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top, behavior: 'smooth' });
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
    const nav2 = document.getElementById('moGeoNav');
    if (nav2) nav2.style.display = 'none';
    return;
  }

  // Группируем по стране
  const byCountry = {};
  for (const o of filtered) {
    const country = o.country || '—';
    if (!byCountry[country]) byCountry[country] = [];
    byCountry[country].push(o);
  }

  const sortedCountries = Object.entries(byCountry).sort(([a],[b]) => a.localeCompare(b));

  el.innerHTML = sortedCountries.map(([country, offs]) => `
    <div class="geo-section" id="geo-sec-${h(country.replace(/[^a-zA-Z0-9]/g,'_'))}">
      <div class="geo-label">${country}</div>
      ${offs.map(o => {
        const payout   = o.payout ? `${o.payout} ${o.currency}` : '';
        const statusCls = o.status === 'active' ? 'active' : 'stopped';
        const statusTxt = o.status === 'active' ? '● Активен' : '● Стоп';
        const dotColor  = o.status === 'active' ? '#22c55e' : '#ef4444';

        // Ищем по ID оффера — ключ в трекинге это Binom offer ID
        const trkId  = String(o.id);
        const fdInfo = _partnerFd[trkId] || {};
        const trkInfo = _partnerTrk[trkId] || {};
        const fd      = fdInfo.fd ?? null;
        const maxCap  = trkInfo.max_cap || o.max_cap;
        const pct      = (fd != null && maxCap) ? Math.min(100, Math.round(fd / maxCap * 100)) : null;
        const barColor = pct >= 90 ? '#ef4444' : pct >= 70 ? '#f59e0b' : '#22c55e';
        const updAt    = fdInfo.updated_at ? fdInfo.updated_at.slice(11,16) : '';

        return `<div class="offer-card">
          <div class="offer-status-dot" style="background:${dotColor}"></div>
          <div class="offer-info">
            <div class="offer-name">${h(o.name)}</div>
            <div class="offer-meta">
              <span class="offer-status-tag ${statusCls}">${statusTxt}</span>
              ${payout ? `<span class="offer-meta-item" style="color:#f59e0b">${h(payout)}</span>` : ''}
            </div>
          </div>
          <div class="offer-right">
            ${fd != null && maxCap ? `
              <div class="offer-cap-wrap">
                <div class="offer-cap-nums">
                  <span class="offer-cap-fd" style="color:${barColor}">${fd}</span>
                  <span style="color:var(--text3)">/</span>
                  <span class="offer-cap-max" onclick="partnerEditCap('${h(String(o.id))}','${h(o.name)}',${maxCap})">${maxCap}</span>
                  ${updAt ? `<span class="offer-cap-upd">${updAt}</span>` : ''}
                </div>
                <div class="offer-cap-bar"><div class="offer-cap-fill" style="width:${pct}%;background:${barColor}"></div></div>
              </div>
            ` : maxCap ? `<span style="font-size:.78rem;color:var(--text3)">Кап: ${maxCap}</span>` : ''}
            <button class="offer-stop-btn" onclick="partnerStopRequest('${h(String(o.id))}','${h(o.name)}')" title="Запрос на стоп">
              <svg width="10" height="10" viewBox="0 0 10 10"><rect width="10" height="10" rx="1.5" fill="currentColor"/></svg>
            </button>
          </div>
        </div>`;
      }).join('')}
    </div>
  `).join('');

  // Build GEO nav
  const nav = document.getElementById('moGeoNav');
  if (nav) {
    const geoFlag = code => {
      const m = (code||'').match(/([A-Z]{2})$/);
      const c = m ? m[1] : (code?.length === 2 ? code.toUpperCase() : '');
      if (!c || c.length !== 2) return '';
      const base = 0x1F1E6;
      return String.fromCodePoint(base + c.charCodeAt(0)-65) + String.fromCodePoint(base + c.charCodeAt(1)-65);
    };
    nav.style.display = 'block';
    nav.innerHTML = `<div class="mo-geo-nav-title">GEO</div>` +
      sortedCountries.map(([country]) => {
        const id  = country.replace(/[^a-zA-Z0-9]/g,'_');
        const m   = country.match(/([A-Z]{2})$/);
        const code = m ? m[1] : country.slice(0,2).toUpperCase();
        const name = country.replace(/\s+[A-Z]{2}$/, '').trim() || country;
        const flag = geoFlag(code);
        return `<div class="mo-geo-nav-item" onclick="moScrollToGeo('${id}',this)">
          <span class="mo-geo-flag">${flag}</span>
          <span class="mo-geo-code">${h(code)}</span>
        </div>`;
      }).join('');
  }

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

async function loadTraffic(dateFrom, dateTo) {
  const el = document.getElementById('trafficContent');
  if (!el) return;
  el.innerHTML = '<div class="p-loading"><div class="p-spinner"></div><span>Загрузка...</span></div>';

  if (!dateFrom || !dateTo) {
    const today = new Date();
    const to    = new Date(today); to.setDate(today.getDate() - 1);
    const from  = new Date(to);   from.setDate(to.getDate() - (_trafficDays - 1));
    dateTo   = to.toISOString().slice(0,10);
    dateFrom = from.toISOString().slice(0,10);
  }

  const j = await api('GET', `/api/partner/traffic?date_from=${dateFrom}&date_to=${dateTo}&min_uniq=1&exclude_1x=false`);
  if (!j.ok) {
    el.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div>${h(j.error || 'Ошибка')}</div>`;
    return;
  }

  const ALLOWED     = ['Crash', 'Casino', 'Betting'];
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
  const geoCodeFn = s => { const m=(s||'').match(/([A-Z]{2})\s*$/); return m?m[1]:(s?.length===2?s.toUpperCase():''); };
  const geoNameFn = s => (s||'').replace(/\s+[A-Z]{2}\s*$/,'').trim()||s;

  const mergedMap = {};
  for (const rot of (j.rotations||[])) {
    const gl = findGroup(rot.rotationName);
    if (!gl || !ALLOWED.includes(gl)) continue;
    if (!mergedMap[gl]) mergedMap[gl] = { name: gl, countries: new Map() };
    for (const c of (rot.countries||[])) {
      mergedMap[gl].countries.set(c.country, (mergedMap[gl].countries.get(c.country)||0) + c.uniq);
    }
  }

  const minUniq = 50;
  const cards = ALLOWED
    .filter(label => mergedMap[label])
    .map(label => ({
      name: mergedMap[label].name,
      geos: Array.from(mergedMap[label].countries.entries())
        .map(([country, uniq]) => ({ country, uniq, code: geoCodeFn(country), name: geoNameFn(country) }))
        .filter(c => c.uniq >= minUniq)
        .sort((a,b) => b.uniq - a.uniq),
    }))
    .filter(r => r.geos.length > 0);

  if (!cards.length) {
    el.innerHTML = `
      ${renderTrafficControls(_trafficDays)}
      <div class="empty" style="margin-top:20px"><div class="empty-icon">📭</div>Нет данных за этот период</div>`;
    return;
  }

  el.innerHTML = `
    ${renderTrafficControls(_trafficDays)}
    <div class="weekly-cards" style="margin-top:16px">
      ${cards.map(card => {
        const topUniq = card.geos[0]?.uniq || 1;
        return `<div class="wcard">
          <div class="wcard-header">
            <div class="wcard-header-left">
              <div class="wcard-title">${h(card.name)}</div>
              <div class="wcard-badge">${card.geos.length} GEO</div>
            </div>
          </div>
          <div class="wcard-rows">
            ${card.geos.map((g, i) => {
              const pct = Math.round(g.uniq / topUniq * 100);
              return `<div class="wrow ${i === 0 ? 'wrow-top' : ''}">
                <div class="wrow-rank">${i+1}</div>
                <div class="wrow-country">
                  <span class="wrow-flag">${geoFlag(g.code)}</span>
                  <span class="wrow-geo-name">${h(g.name || g.code)}</span>
                  ${g.code && g.code !== g.name ? `<span class="wrow-geo-code">${h(g.code)}</span>` : ''}
                </div>
                <div class="wrow-bar-wrap"><div class="wrow-bar" style="width:${pct}%"></div></div>
                <div class="wrow-uniq">${g.uniq.toLocaleString()}</div>
              </div>`;
            }).join('')}
          </div>
        </div>`;
      }).join('')}
    </div>`;
}

function renderTrafficControls(activeDays) {
  // Сколько дней прошло с начала месяца (по Москве)
  const now       = new Date();
  const dayOfMonth = now.getDate(); // сегодня число
  const show14    = dayOfMonth >= 14;
  const show30    = dayOfMonth >= 30;

  return `<div class="trf-controls">
    <div class="trf-presets">
      <button class="trf-preset-btn${activeDays===7?' active':''}" onclick="applyTrafficPreset(7,this)">7 дней</button>
      ${show14 ? `<button class="trf-preset-btn${activeDays===14?' active':''}" onclick="applyTrafficPreset(14,this)">14 дней</button>` : ''}
      ${show30 ? `<button class="trf-preset-btn${activeDays===30?' active':''}" onclick="applyTrafficPreset(30,this)">30 дней</button>` : ''}
    </div>
    <div class="trf-hint">
      <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      ${(() => {
        const today = new Date();
        const to    = new Date(today); to.setDate(today.getDate() - 1);
        const from  = new Date(to);   from.setDate(to.getDate() - (activeDays - 1));
        const fmt   = d => d.toLocaleDateString('ru-RU', {day:'numeric', month:'short'});
        return fmt(from) + ' — ' + fmt(to);
      })()} &nbsp;·&nbsp; Порог ≥50 уников
    </div>
  </div>`;
}



let _trafficDays = 7;

function applyTrafficPreset(days, btn) {
  _trafficDays = days;
  document.querySelectorAll('.trf-preset-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const today = new Date();
  const to    = new Date(today); to.setDate(today.getDate() - 1);
  const from  = new Date(to);   from.setDate(to.getDate() - (days - 1));
  loadTraffic(from.toISOString().slice(0,10), to.toISOString().slice(0,10));
}

// ── Partner offer actions ────────────────────────────

async function partnerEditCap(offerId, offerName, currentCap) {
  const newCap = prompt(`Новый кап для "${offerName}":`, currentCap);
  if (!newCap || isNaN(newCap) || parseInt(newCap) < 1) return;
  const j = await api('POST', `/api/partner/offers/${offerId}/update_cap`, { max_cap: parseInt(newCap) });
  if (j.ok) {
    showToast('Кап обновлён!', true);
    loadMyOffers(true);
  } else {
    showToast(j.error || 'Ошибка', false);
  }
}

function partnerStopRequest(offerId, offerName) {
  // Модал с причиной
  const existing = document.getElementById('partnerStopModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'partnerStopModal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;padding:16px';
  modal.innerHTML = `
    <div style="background:#0f1c2e;border:0.5px solid #1e3a5f;border-radius:12px;padding:24px;width:380px;max-width:100%">
      <div style="font-size:14px;font-weight:500;color:#e2e8f0;margin-bottom:6px">⏹ Запрос на стоп</div>
      <div style="font-size:12px;color:#64748b;margin-bottom:16px">${h(offerName)}</div>
      <div style="margin-bottom:12px">
        <label style="font-size:11px;color:#64748b;display:block;margin-bottom:6px">Причина *</label>
        <select id="stopReqReason" style="width:100%;padding:8px 12px;background:#0a1120;border:0.5px solid #1e3a5f;border-radius:6px;color:#e2e8f0;font-size:13px">
          <option value="">— выберите —</option>
          <option value="Не перформит">Не перформит</option>
          <option value="Плохое качество трафика">Плохое качество трафика</option>
          <option value="Нет конверсий">Нет конверсий</option>
          <option value="Технические проблемы">Технические проблемы</option>
          <option value="Другое">Другое</option>
        </select>
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:11px;color:#64748b;display:block;margin-bottom:6px">Комментарий</label>
        <input id="stopReqComment" type="text" placeholder="Подробности..." style="width:100%;padding:8px 12px;background:#0a1120;border:0.5px solid #1e3a5f;border-radius:6px;color:#e2e8f0;font-size:13px">
      </div>
      <div id="stopReqErr" style="font-size:12px;color:#ef4444;min-height:16px;margin-bottom:8px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button onclick="document.getElementById('partnerStopModal').remove()" style="padding:7px 14px;border-radius:6px;border:0.5px solid #1e3a5f;background:transparent;color:#64748b;cursor:pointer;font-size:13px">Отмена</button>
        <button onclick="partnerSendStopRequest('${h(offerId)}','${h(offerName)}')" style="padding:7px 14px;border-radius:6px;border:none;background:#ef4444;color:#fff;cursor:pointer;font-size:13px">Отправить запрос</button>
      </div>
    </div>`;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
}

async function partnerSendStopRequest(offerId, offerName) {
  const reason  = document.getElementById('stopReqReason').value;
  const comment = document.getElementById('stopReqComment').value.trim();
  const errEl   = document.getElementById('stopReqErr');
  if (!reason) { errEl.textContent = 'Выберите причину'; return; }

  const j = await api('POST', `/api/partner/offers/${offerId}/stop_request`, {
    reason, comment, offer_name: offerName,
  });
  if (j.ok) {
    document.getElementById('partnerStopModal').remove();
    showToast('Запрос отправлен администратору', true);
  } else {
    errEl.textContent = j.error || 'Ошибка';
  }
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