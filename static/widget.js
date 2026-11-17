let id = new URLSearchParams(location.search).get('product_id') || 'moka-01';
let mode = new URLSearchParams(location.search).get('mode') || 'similar', seq = 0;
if (!['similar','complementary','partner'].includes(mode)) mode='similar';
const status = document.getElementById('widget-status');
if (mode==='partner') {
  document.querySelector('.tabs').hidden=true;
  document.querySelector('.rec-heading h2').textContent='Товары партнёров';
  document.querySelector('.mode-description').textContent='Дополнения других магазинов. Размещение после покупки.';
}
for (const tab of document.querySelectorAll('.tab')) {
  tab.classList.toggle('active', tab.dataset.mode === mode);
}

async function render() {
  const n = ++seq, container = document.getElementById('items');
  try {
    const res = await fetch((mode==='partner'?'/api/partners':'/api/recommendations')+'?product_id=' + encodeURIComponent(id) + '&mode=' + mode);
    const data = await res.json();
    if (n !== seq) return;
    if (!res.ok) throw Error(data.error);
    container.replaceChildren();
    if (!data.items.length) {
      const empty = document.createElement('p'); empty.className = 'empty';
      empty.textContent = 'Подходящих товаров в этом каталоге пока нет.'; container.append(empty);
    }
    for (const item of data.items) {
      const card = document.createElement('button'); card.className = 'rec-card';
      const art = document.createElement('div'); art.className = 'rec-image'; art.innerHTML = window.ShopRecArt(item);
      const name = document.createElement('h3'); name.textContent = item.name;
      const price = document.createElement('div'); price.className = 'rec-price';
      price.textContent = new Intl.NumberFormat('ru-RU').format(item.price) + ' ₽';
      const reason = document.createElement('p'); reason.className = 'reason'; reason.textContent = item.reason;
      card.append(art);
      if (mode === 'partner') {
        const seller = document.createElement('p'); seller.className = 'partner-store';
        seller.textContent = item.store_name + ' · партнёр';
        card.append(seller);
      }
      card.append(name, price, reason);
      card.onclick = async () => {
        card.disabled = true;
        // Open synchronously on the actual click to avoid popup blocking after await.
        if (item.url) window.open(item.url,'_blank','noopener,noreferrer');
        const event = {event_id:crypto.randomUUID(),source_product_id:id,target_product_id:item.id,placement:mode,is_demo:!item.url};
        try {
          const response = await fetch('/api/events', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event)});
          if (!response.ok) throw Error('Не удалось записать клик.');
          status.textContent = '';
        } catch(error) { status.textContent = error.message; }
        if (!item.url) { id = item.id; status.textContent = 'Демонстрационный переход: у товара нет внешнего URL.'; await render(); }
        else card.disabled=false;
      };
      container.append(card);
    }
  } catch(error) { if (n === seq) container.textContent = error.message; }
}
for (const button of document.querySelectorAll('.tab')) button.onclick = () => {
  mode = button.dataset.mode;
  for (const tab of document.querySelectorAll('.tab')) tab.classList.toggle('active', tab === button);
  render();
};
render();
