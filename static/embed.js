/* One-tag ShopRec widget. Uses an iframe to isolate the shop's CSS. */
(() => {
  const script = document.currentScript;
  if (!script) return;
  const base = new URL(script.src), url = new URL('widget.html', base);
  url.searchParams.set('product_id', script.dataset.product || 'moka-01');
  if (['partner','complementary'].includes(script.dataset.mode)) url.searchParams.set('mode',script.dataset.mode);
  const frame = document.createElement('iframe');
  frame.src = url.href; frame.title = 'Рекомендации ShopRec';
  frame.style.cssText = 'width:100%;height:450px;border:0;display:block;border-radius:16px;';
  frame.loading = 'lazy';
  script.insertAdjacentElement('afterend', frame);
})();
