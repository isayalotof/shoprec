'use strict';
const $ = selector => document.querySelector(selector);
const money = value => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value) + ' ₽';
const count = value => new Intl.NumberFormat('ru-RU').format(Number(value) || 0);
const storage = {
  get(key) { try { return sessionStorage.getItem(key); } catch (_) { return null; } },
  set(key, value) { try { sessionStorage.setItem(key, value); } catch (_) { /* In-memory session remains usable. */ } },
  remove(key) { try { sessionStorage.removeItem(key); } catch (_) { /* Nothing to clear. */ } }
};
let products = [], stores = [], storeId = storage.get('shoprec-store') || 'doma', selected = '';
let mode = 'similar', requestNumber = 0, partnerRequest = 0, reportRequest = 0;
let authToken = storage.get('shoprec-admin') || '', authenticated = false, importedFile = null;
const isAdminView = location.pathname.replace(/\/$/, '') === '/admin';
function text(selector, value) { $(selector).textContent = value; }
function message(selector, value, error = false) {
  text(selector, value); $(selector).classList.toggle('error', error);
}
function status(value, error = false) { message('#status', value, error); }
function currentStore() { return stores.find(store => store.id === storeId); }
function ownProducts() { return products.filter(product => product.store_id === storeId); }
function setAuthenticated(value) {
  authenticated = value;
  $('#login-panel').hidden = value; $('#admin-workspace').hidden = !value;
  if (!value) { authToken = ''; storage.remove('shoprec-admin'); }
}
async function api(url, options = {}, admin = false) {
  const headers = { ...(options.headers || {}) };
  if (admin && authToken) headers.Authorization = 'Bearer ' + authToken;
  let response;
  try { response = await fetch(url, { ...options, headers, cache: 'no-store' }); }
  catch (_) { throw Error('Сервер недоступен. Проверьте подключение и повторите попытку.'); }
  let data;
  try { data = await response.json(); }
  catch (_) { throw Error('Сервер вернул неожиданный ответ. Обновите страницу.'); }
  if (admin && response.status === 401) {
    setAuthenticated(false);
    message('#login-status', 'Сессия недействительна. Введите ключ доступа снова.', true);
  }
  if (!response.ok) throw Error(data.error || 'Не удалось выполнить запрос.');
  return data;
}
function post(url, payload, admin = false) {
  return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, admin);
}
function option(value, label) {
  const node = document.createElement('option'); node.value = value; node.textContent = label; return node;
}
function empty(container, value) {
  container.replaceChildren(); const node = document.createElement('p'); node.className = 'empty'; node.textContent = value; container.append(node);
}
function uuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
async function recordClick(sourceProductId, targetProductId, placement, isDemo = true) {
  return post('/api/events', { event_id: uuid(), source_product_id: sourceProductId, target_product_id: targetProductId, placement, is_demo: isDemo });
}
function productUrl(product) {
  if (!product.url) return null;
  try {
    const url = new URL(product.url);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch (_) { return null; }
}
async function loadData() {
  const data = await api('/api/products'); products = data.products || []; stores = data.stores || [];
  if (!stores.some(store => store.id === storeId)) storeId = stores[0]?.id || '';
  for (const selector of ['#store-select', '#admin-store-select']) {
    const node = $(selector); node.replaceChildren();
    stores.forEach(store => node.append(option(store.id, store.name))); node.value = storeId;
  }
  fillProducts();
  text('#data-note', 'Начальные магазины и товары вымышлены. Карточки без ссылки работают в демо-режиме; товары с URL открывают сайт магазина. Клики учитываются отдельно.');
  if (isAdminView && authenticated) renderAdmin();
  else if (!isAdminView) await render();
}
function fillProducts() {
  const own = ownProducts(), store = currentStore(), select = $('#product-select'); select.replaceChildren();
  own.forEach(product => select.append(option(product.id, product.name)));
  if (!own.some(product => product.id === selected)) selected = own[0]?.id || '';
  select.value = selected;
  text('#product-count', count(own.length));
  text('#store-description', store?.description || 'Каталог магазина');
  text('#admin-store-description', store?.description || 'Управление каталогом');
  $('#catalog-empty').hidden = own.length > 0;
  $('#store-grid').hidden = !own.length; $('#network-entry').hidden = !own.length;
  $('#show-partners').disabled = !own.length;
  text('#embed-code', selected ? `<script src="${location.origin}/embed.js" data-product="${selected}"></script>` : 'Сначала загрузите каталог магазина.');
}
async function chooseStore(id) {
  storeId = id; storage.set('shoprec-store', id); selected = ''; ++requestNumber; ++partnerRequest;
  $('#store-select').value = id; $('#admin-store-select').value = id;
  $('#partner-panel').hidden = true; clearImport(); status(''); fillProducts();
  if (isAdminView && authenticated) renderAdmin(); else await render();
}
function art(product, className) {
  const node = document.createElement('div'); node.className = className; node.innerHTML = window.ShopRecArt(product); return node;
}
async function openRecommendation(button, sourceId, item, placement) {
  if (button.disabled) return; button.disabled = true;
  const targetId = item.id, externalUrl = productUrl(item);
  try {
    // Open during the original user gesture, before awaiting telemetry.
    if (externalUrl) window.open(externalUrl, '_blank', 'noopener,noreferrer');
    await recordClick(sourceId, targetId, placement, !externalUrl);
    if (externalUrl) { status('Клик по ссылке магазина записан. Посещение сайта и покупка не подтверждены.'); return; }
    if (placement === 'partner') {
      storeId = item.store_id; storage.set('shoprec-store', storeId);
      $('#store-select').value = storeId; $('#admin-store-select').value = storeId;
    }
    selected = item.id; $('#partner-panel').hidden = true; ++partnerRequest; fillProducts(); await render();
    status(placement === 'partner' ? `Открыта карточка магазина «${item.store_name}». Демо-клик записан; заказ не создавался.` : 'Товар открыт. Демо-клик записан отдельно от рабочих событий.');
  } catch (error) { status(error.message, true); }
  finally { button.disabled = false; }
}
function recommendationCard(item, sourceId, placement) {
  const button = document.createElement('button'); button.type = 'button'; button.className = placement === 'partner' ? 'partner-card' : 'rec-card';
  const externalUrl = productUrl(item);
  button.setAttribute('aria-label', `Открыть ${item.name}, ${money(item.price)}${placement === 'partner' ? ', магазин ' + item.store_name : ''}${externalUrl ? ', на сайте магазина в новой вкладке' : ', демо-карточка'}`);
  const image = art(item, 'rec-image'), body = document.createElement('div'); body.className = 'rec-card-body';
  if (placement === 'partner') { const store = document.createElement('span'); store.className = 'partner-store'; store.textContent = item.store_name + ' · ПАРТНЁР'; body.append(store); }
  const name = document.createElement('h3'); name.textContent = item.name;
  const price = document.createElement('div'); price.className = 'rec-price'; price.textContent = money(item.price);
  const reason = document.createElement('p'); reason.className = 'reason'; reason.textContent = item.reason;
  body.append(name, price, reason);
  if (externalUrl) { const caption = document.createElement('span'); caption.className = 'external-caption'; caption.textContent = 'На сайт магазина ↗'; body.append(caption); }
  button.append(image, body);
  button.addEventListener('click', () => openRecommendation(button, sourceId, item, placement));
  return button;
}
async function render() {
  const number = ++requestNumber, product = products.find(item => item.id === selected), activeMode = mode;
  if (!product) return;
  $('#hero-art').replaceChildren(art(product, 'hero-illustration'));
  text('#product-category', product.category); text('#product-name', product.name); text('#product-description', product.description);
  text('#product-price', money(product.price)); text('#stock-status', product.in_stock ? 'В наличии' : 'Нет в наличии');
  text('#embed-code', `<script src="${location.origin}/embed.js" data-product="${product.id}"></script>`);
  text('#mode-description', activeMode === 'similar' ? 'Альтернативы того же типа из этого магазина.' : 'Товары из этого магазина, которые дополняют выбранный.');
  text('#method-description', activeMode === 'similar' ? 'Сопоставляем названия, описания и атрибуты. История покупок не нужна.' : 'Подбираем по назначению и проверяем доступные атрибуты совместимости.');
  const container = $('#recommendations'); container.classList.add('loading'); container.setAttribute('aria-busy', 'true');
  empty(container, 'Подбираем товары…');
  try {
    const data = await api(`/api/recommendations?product_id=${encodeURIComponent(product.id)}&mode=${activeMode}&limit=3`);
    if (number !== requestNumber) return;
    container.replaceChildren();
    if (!data.items.length) empty(container, activeMode === 'similar' ? 'Сейчас нет доступных альтернатив этого типа. Подбор появится, когда в каталоге будут подходящие товары.' : 'Подходящих дополнений сейчас нет. Случайные товары не подставляем.');
    data.items.forEach(item => container.append(recommendationCard(item, product.id, activeMode)));
  } catch (error) { if (number === requestNumber) { empty(container, 'Не удалось загрузить рекомендации. Выберите товар повторно.'); status(error.message, true); } }
  finally { if (number === requestNumber) { container.classList.remove('loading'); container.setAttribute('aria-busy', 'false'); } }
}
async function renderPartners() {
  const number = ++partnerRequest, product = products.find(item => item.id === selected), store = currentStore();
  if (!product || !store) return;
  text('#partner-context', `Представим, что «${product.name}» уже куплен в магазине «${store.name}». Здесь доступны согласованные дополнения от других участников.`);
  const container = $('#partner-items'); empty(container, 'Проверяем партнёрские предложения…'); container.setAttribute('aria-busy', 'true');
  try {
    const data = await api(`/api/partners?product_id=${encodeURIComponent(product.id)}&limit=3`);
    if (number !== partnerRequest) return;
    container.replaceChildren();
    if (!data.items.length) empty(container, store.participating ? 'Подходящих предложений сейчас нет. Нужны взаимное разрешение магазинов, разрешённая категория и совместимый товар в наличии.' : 'У этого магазина отключён обмен. Его можно включить в кабинете, выбрав партнёров и категории.');
    data.items.forEach(item => container.append(recommendationCard(item, product.id, 'partner')));
  } catch (error) { if (number === partnerRequest) { empty(container, 'Не удалось загрузить предложения партнёров.'); status(error.message, true); } }
  finally { if (number === partnerRequest) container.setAttribute('aria-busy', 'false'); }
}
function choice(name, value, label, checked) {
  const node = document.createElement('label'); node.className = 'choice';
  const input = document.createElement('input'); input.type = 'checkbox'; input.name = name; input.value = value; input.checked = checked;
  const span = document.createElement('span'); span.textContent = label; node.append(input, span); return node;
}
function updateChoices() {
  const participating = $('#participating').checked;
  $('#partners-fieldset').disabled = !participating; $('#categories-fieldset').disabled = !participating;
  for (const input of document.querySelectorAll('input[name="partner"]')) input.disabled = !participating || $('#all-partners').checked;
  for (const input of document.querySelectorAll('input[name="category"]')) input.disabled = !participating || $('#all-categories').checked;
}
function renderSettings() {
  const store = currentStore(); if (!store) return;
  $('#participating').checked = Boolean(store.participating);
  $('#all-partners').checked = store.partner_allowlist == null;
  $('#all-categories').checked = store.category_allowlist == null;
  const partners = $('#partner-options'); partners.replaceChildren();
  stores.filter(item => item.id !== storeId).forEach(item => partners.append(choice('partner', item.id, item.name, store.partner_allowlist == null || store.partner_allowlist.includes(item.id))));
  const ownCategories = new Set(ownProducts().map(product => product.category));
  const categories = [...new Set([...products.filter(product => product.store_id !== storeId && !ownCategories.has(product.category)).map(product => product.category), ...(store.category_allowlist || [])])].sort((a,b) => a.localeCompare(b, 'ru'));
  const holder = $('#category-options'); holder.replaceChildren();
  categories.forEach(category => holder.append(choice('category', category, category, store.category_allowlist == null || store.category_allowlist.includes(category))));
  if (!categories.length) { const note = document.createElement('p'); note.className = 'field-help'; note.textContent = 'У партнёров пока нет категорий вне вашего каталога.'; holder.append(note); }
  updateChoices(); message('#settings-status', '');
}
function renderAdmin() {
  if (!currentStore()) return;
  text('#metric-products', count(ownProducts().length)); text('#catalog-source', 'Каталог и правила сохраняются');
  renderSettings(); loadReport();
}
async function loadReport() {
  const number = ++reportRequest, id = storeId;
  message('#report-status', 'Обновляем события…'); $('#refresh-report').disabled = true;
  $('#traffic-rows').replaceChildren(); $('#recent-events').replaceChildren();
  text('#report-period', `Все сохранённые события магазина «${currentStore()?.name || id}».`);
  for (const selector of ['#metric-incoming', '#metric-outgoing', '#metric-demo']) text(selector, '—');
  try {
    const data = await api(`/api/analytics?store_id=${encodeURIComponent(id)}`, {}, true);
    if (number !== reportRequest || id !== storeId) return;
    const total = data.totals || {};
    text('#metric-incoming', count(total.inbound_clicks)); text('#metric-outgoing', count(total.outbound_clicks));
    text('#metric-demo', count((total.demo_internal_clicks || 0) + (total.demo_inbound_clicks || 0) + (total.demo_outbound_clicks || 0)));
    const rows = $('#traffic-rows'); rows.replaceChildren();
    for (const row of data.stores || []) {
      const tr = document.createElement('tr');
      [row.name, count(row.inbound_clicks), count(row.outbound_clicks), count(row.demo_inbound_clicks), count(row.demo_outbound_clicks)].forEach((value,index) => { const cell = document.createElement(index ? 'td' : 'th'); if (!index) cell.scope = 'row'; cell.textContent = value; tr.append(cell); });
      rows.append(tr);
    }
    if (!rows.children.length) { const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 5; td.className = 'table-empty'; td.textContent = 'Событий пока нет. Нажатия из витрины появятся отдельно в демо-столбцах.'; tr.append(td); rows.append(tr); }
    const events = $('#recent-events');
    for (const entry of (data.recent || []).slice(0,12)) {
      const li = document.createElement('li'), details = document.createElement('div'), title = document.createElement('strong'), note = document.createElement('span'), time = document.createElement('time'), badge = document.createElement('span');
      title.textContent = `${entry.source_product_name || entry.source_product_id} → ${entry.target_product_name || entry.target_product_id}`;
      const sourceStore = stores.find(store => store.id === entry.source_store_id)?.name || entry.source_store_id;
      const targetStore = stores.find(store => store.id === entry.target_store_id)?.name || entry.target_store_id;
      note.textContent = entry.placement === 'partner' ? `${sourceStore} → ${targetStore} · партнёрская карточка` : `${sourceStore} · ${entry.placement === 'similar' ? 'похожий товар' : 'дополнение'}`;
      details.append(title, note); badge.className = 'event-badge' + (entry.is_demo ? ' is-demo' : ''); badge.textContent = entry.is_demo ? 'Демо-клик' : 'Клик виджета';
      const date = new Date(entry.created_at); time.dateTime = entry.created_at;
      time.textContent = Number.isNaN(date.getTime()) ? entry.created_at : new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date);
      if (!entry.is_demo) badge.textContent = 'Клик по ссылке';
      li.append(details,badge,time); events.append(li);
    }
    if (!events.children.length) { const li = document.createElement('li'); li.className = 'activity-empty'; li.textContent = 'Кликов пока нет. Откройте рекомендацию в витрине, затем обновите отчёт.'; events.append(li); }
    message('#report-status', 'Обновлено ' + new Intl.DateTimeFormat('ru-RU', {hour:'2-digit',minute:'2-digit'}).format(new Date()));
    text('#report-period', `Все сохранённые события магазина «${currentStore().name}». Внутренние клики: ${count(total.internal_clicks)}; демо-внутренние: ${count(total.demo_internal_clicks)}.`);
  } catch (error) { if (number === reportRequest) message('#report-status', error.message, true); }
  finally { if (number === reportRequest) $('#refresh-report').disabled = false; }
}
function clearImport() {
  importedFile = null; $('#catalog-file').value = ''; $('#import-button').disabled = true;
  text('#file-name', 'Выберите JSON или CSV'); text('#file-detail', 'Файл до 1,9 МБ'); message('#import-status', '');
}
function setMutationBusy(busy, button) { $('#admin-store-select').disabled = busy; button.disabled = busy; }
function downloadTemplate(format) {
  const example = [
    {id:`${storeId}-example-01`,name:'Керамическая чашка',description:'Пример товара: замените описание и URL данными магазина. Чашка для кофе, 250 мл.',category:'Посуда',type:'cup',price:890,in_stock:true,color:'#D6CEC0',tags:['кофе','керамика'],compatibility:'',url:'https://example.com/product/cup-250'},
    {id:`${storeId}-example-02`,name:'Большая керамическая чашка',description:'Пример товара: замените описание и URL данными магазина. Чашка для кофе, 350 мл.',category:'Посуда',type:'cup',price:1190,in_stock:true,color:'#A8B39A',tags:['кофе','керамика'],compatibility:'',url:'https://example.com/product/cup-350'}
  ];
  let content, mime;
  if (format === 'json') { content = JSON.stringify(example, null, 2); mime = 'application/json;charset=utf-8'; }
  else { const keys = ['id','name','description','category','type','price','in_stock','color','url']; const csvCell = value => '"' + String(value).replaceAll('"','""') + '"'; content = '\uFEFF' + keys.join(',') + '\r\n' + example.map(row => keys.map(key => csvCell(row[key])).join(',')).join('\r\n'); mime = 'text/csv;charset=utf-8'; }
  const url = URL.createObjectURL(new Blob([content], {type:mime})), link = document.createElement('a'); link.href = url; link.download = `shoprec-${storeId}-example.${format}`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#store-select').addEventListener('change', event => chooseStore(event.target.value));
$('#admin-store-select').addEventListener('change', event => chooseStore(event.target.value));
$('#product-select').addEventListener('change', event => { selected = event.target.value; ++partnerRequest; $('#partner-panel').hidden = true; status(''); render(); });
$('#show-partners').addEventListener('click', () => { $('#partner-panel').hidden = false; renderPartners(); $('#partner-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',block:'start'}); });
$('#close-partners').addEventListener('click', () => { ++partnerRequest; $('#partner-panel').hidden = true; });
for (const tab of document.querySelectorAll('.tab')) tab.addEventListener('click', () => {
  mode = tab.dataset.mode;
  for (const other of document.querySelectorAll('.tab')) { other.classList.toggle('active', other === tab); other.setAttribute('aria-selected', String(other === tab)); }
  $('#recommendations').setAttribute('aria-labelledby', tab.id); render();
});
for (const id of ['#participating','#all-partners','#all-categories']) $(id).addEventListener('change', updateChoices);
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const token = $('#admin-token').value.trim(); if (!token) return;
  $('#login-button').disabled = true; authToken = token; message('#login-status', 'Проверяем доступ…');
  try {
    const result = await api('/api/session', {}, true);
    if (!result.authenticated) throw Error('Ключ не подходит. Проверьте его и попробуйте снова.');
    storage.set('shoprec-admin', token); setAuthenticated(true); $('#admin-token').value = ''; message('#login-status', '');
    await loadData();
  } catch (error) { setAuthenticated(false); message('#login-status', error.message, true); }
  finally { $('#login-button').disabled = false; }
});
$('#logout-button').addEventListener('click', () => { ++reportRequest; setAuthenticated(false); $('#admin-token').value = ''; message('#login-status', 'Вы вышли из кабинета.'); });
$('#settings-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#settings-save'), id = storeId;
  const checked = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(input => input.value);
  const payload = {store_id:id,participating:$('#participating').checked,partner_allowlist:$('#all-partners').checked ? null : checked('partner'),category_allowlist:$('#all-categories').checked ? null : checked('category')};
  setMutationBusy(true, button); message('#settings-status', 'Сохраняем…');
  try { const result = await post('/api/settings', payload, true); stores = result.stores || stores.map(store => store.id === id ? result.store : store); renderSettings(); message('#settings-status', 'Правила сохранены.'); }
  catch (error) { message('#settings-status', error.message, true); }
  finally { setMutationBusy(false, button); }
});
$('#catalog-file').addEventListener('change', event => {
  const file = event.target.files[0]; clearImport(); if (!file) return;
  if (!/\.(json|csv)$/i.test(file.name)) { message('#import-status', 'Выберите файл JSON или CSV.', true); return; }
  if (file.size > 1900000) { message('#import-status', 'Файл должен быть меньше 1,9 МБ.', true); return; }
  importedFile = file; text('#file-name', file.name); text('#file-detail', `${count(Math.ceil(file.size / 1024))} КБ · заменит каталог «${currentStore()?.name || ''}»`); $('#import-button').disabled = false;
});
$('#import-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!importedFile) return;
  const file = importedFile, id = storeId, name = currentStore()?.name || id, button = $('#import-button');
  setMutationBusy(true, button); $('#catalog-file').disabled = true; message('#import-status', 'Проверяем и загружаем каталог…');
  try {
    const content = await file.text(), format = file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'json';
    const data = format === 'json' ? JSON.parse(content.replace(/^\uFEFF/, '')) : content;
    const result = await post('/api/import', {store_id:id,format,data}, true);
    clearImport(); await loadData(); message('#import-status', `Каталог «${name}» сохранён: ${count(result.count)} товаров. Другие магазины не изменены.`);
  } catch (error) { message('#import-status', error instanceof SyntaxError ? 'JSON не удалось прочитать. Исправьте файл или скачайте пример. Каталог не изменён.' : error.message, true); }
  finally { $('#admin-store-select').disabled = false; $('#catalog-file').disabled = false; button.disabled = !importedFile; }
});
$('#download-json').addEventListener('click', () => downloadTemplate('json'));
$('#download-csv').addEventListener('click', () => downloadTemplate('csv'));
$('#refresh-report').addEventListener('click', loadReport);
(async function start() {
  $('#storefront-view').hidden = isAdminView; $('#admin-view').hidden = !isAdminView;
  $('#storefront-nav').toggleAttribute('aria-current', !isAdminView); $('#admin-nav').toggleAttribute('aria-current', isAdminView);
  if (isAdminView) $('#admin-nav').setAttribute('aria-current','page'); else $('#storefront-nav').setAttribute('aria-current','page');
  try {
    await loadData();
    if (isAdminView && authToken) {
      const session = await api('/api/session', {}, true); setAuthenticated(Boolean(session.authenticated)); if (authenticated) renderAdmin();
    }
    const requestedProduct = new URLSearchParams(location.search).get('product');
    const product = products.find(item => item.id === requestedProduct);
    if (!isAdminView && product) { storeId = product.store_id; selected = product.id; $('#store-select').value = storeId; fillProducts(); await render(); }
  } catch (error) { status(error.message, true); }
})();
