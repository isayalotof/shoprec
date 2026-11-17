/* Runs the application state and API flows in a minimal DOM; no browser required.
   This checks behavior and request contracts, not pixel rendering. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
const elements = [];
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = {}; this.attributes = {}; this.dataset = {};
    this.hidden = false; this.checked = false; this.disabled = false; this.value = ''; this.textContent = '';
    const classes = new Set(); this.classList = {add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,on)=>{on ? classes.add(x) : classes.delete(x);}};
    elements.push(this);
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key,value) { this.attributes[key] = value; }
  toggleAttribute(key,value) { if (value) this.attributes[key] = ''; else delete this.attributes[key]; }
  addEventListener(type,fn) { this.listeners[type] = fn; }
  scrollIntoView() {}
  click() { return this.listeners.click?.({target:this,preventDefault(){}}); }
}
const ids = new Map();
for (const match of html.matchAll(/<([a-z]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
  assert(!ids.has(match[2]), 'duplicate DOM ID');
  const element = new Element(match[1]); element.id = match[2]; element.hidden = /\bhidden\b/.test(match[0]);
  const mode = /data-mode="([^"]+)"/.exec(match[0]); if (mode) element.dataset.mode = mode[1];
  ids.set(element.id, element);
}
const queryAll = selector => {
  if (selector === '.tab') return [ids.get('similar-tab'),ids.get('complementary-tab')];
  const named = /^input\[name="([^"]+)"\](:checked)?$/.exec(selector);
  if (named) return elements.filter(el => el.name === named[1] && (!named[2] || el.checked));
  throw Error('Unsupported selector: '+selector);
};
const document = {querySelector: selector => {const item=ids.get(selector.replace(/^#/,''));assert(item,'missing selector '+selector);return item;},querySelectorAll:queryAll,createElement:tag=>new Element(tag)};
let stores = [{id:'doma',name:'Дома',description:'Дом',participating:true,partner_allowlist:null,category_allowlist:null},{id:'coffee',name:'Кофе',description:'Кофе',participating:true,partner_allowlist:null,category_allowlist:null}];
const products = [{id:'cup-1',store_id:'doma',name:'Чашка',description:'Чашка',category:'Посуда',type:'cup',price:500,in_stock:true},{id:'cup-2',store_id:'doma',name:'Другая чашка',description:'Чашка',category:'Посуда',type:'cup',price:600,in_stock:true},{id:'coffee-1',store_id:'coffee',name:'Кофе',description:'Кофе',category:'Кофе',type:'coffee',price:700,in_stock:true}];
const requests = [], memory = new Map(), downloads = [], openCalls = [], activity = [];
async function fetch(url, options = {}) {
  if (url === '/api/events') activity.push('event');
  const body = options.body ? JSON.parse(options.body) : null; requests.push({url,options,body});
  let data;
  if (url === '/api/products') data = {products,stores};
  else if (url === '/api/session') data = {authenticated:options.headers.Authorization === 'Bearer test-admin-key'};
  else if (url.startsWith('/api/analytics')) data = {totals:{internal_clicks:0,inbound_clicks:0,outbound_clicks:0,demo_internal_clicks:2,demo_inbound_clicks:1,demo_outbound_clicks:3},stores:[{id:'doma',name:'Дома'}],recent:[]};
  else if (url === '/api/settings') { stores = stores.map(s=>s.id===body.store_id?{...s,...body}:s); data={stores,store:stores.find(s=>s.id===body.store_id)}; }
  else if (url === '/api/import') data = {store_id:body.store_id,count:body.data.length};
  else if (url === '/api/events') data = {recorded:true,id:1};
  else if (url.startsWith('/api/recommendations')) data={items:[products[1]]};
  else throw Error('Unexpected endpoint '+url);
  return {ok:true,status:200,json:async()=>data};
}
class TestURL extends URL { static createObjectURL(blob) {downloads.push(blob);return 'blob:test';} static revokeObjectURL(){} }
const context=vm.createContext({document,location:{pathname:'/admin',origin:'http://localhost:8787',search:''},sessionStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},window:{ShopRecArt:()=>'<svg></svg>',open:(...args)=>{activity.push('open');openCalls.push(args);return null;}},fetch,crypto:webcrypto,URL:TestURL,URLSearchParams,Blob,Intl,Date,Set,Error,SyntaxError,console,setTimeout:fn=>fn(),matchMedia:()=>({matches:true})});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const run=code=>vm.runInContext(code,context);
const submit=id=>ids.get(id).listeners.submit({preventDefault(){}});
(async()=>{
  vm.runInContext(source,context); await flush();
  assert.equal(ids.get('storefront-view').hidden,true);
  assert.equal(ids.get('admin-workspace').hidden,true);
  assert.equal(requests.filter(r=>r.url==='/api/events').length,0,'loading must not emit clicks');
  ids.get('admin-token').value='test-admin-key'; await submit('login-form'); await flush();
  assert.equal(ids.get('admin-workspace').hidden,false);
  assert.equal(ids.get('admin-token').value,'');
  assert.equal(ids.get('metric-demo').textContent,'6');
  ids.get('all-partners').checked=false; queryAll('input[name="partner"]').forEach(input=>input.checked=false);
  ids.get('all-categories').checked=false; queryAll('input[name="category"]').forEach(input=>input.checked=false);
  await submit('settings-form');
  const settings=requests.findLast(r=>r.url==='/api/settings');
  assert.deepEqual(settings.body.partner_allowlist,[]); assert.deepEqual(settings.body.category_allowlist,[]);
  assert.equal(settings.body.store_id,'doma'); assert.equal(settings.options.headers.Authorization,'Bearer test-admin-key');
  run("downloadTemplate('json')"); const example=JSON.parse(await downloads.at(-1).text());
  assert.equal(example.length,2); assert.notEqual(example[0].id,example[1].id); assert.equal(typeof example[0].compatibility,'string'); assert.equal(new URL(example[0].url).hostname,'example.com');
  const file={name:'catalog.json',size:900,text:async()=>JSON.stringify(example)};
  ids.get('catalog-file').listeners.change({target:{files:[file]}});
  await submit('import-form'); await flush();
  const imported=requests.findLast(r=>r.url==='/api/import'); assert.equal(imported.body.store_id,'doma'); assert.equal(imported.body.data.length,2); assert.equal(imported.options.headers.Authorization,'Bearer test-admin-key');
  await run("recordClick('cup-1','cup-2','similar')"); const event=requests.findLast(r=>r.url==='/api/events'); assert.equal(event.body.is_demo,true); assert.equal(event.body.placement,'similar'); assert(!event.options.headers.Authorization);
  assert.equal(run("productUrl({url:'javascript:alert(1)'})"),null);
  assert.equal(run("productUrl({url:'https://user:pass@example.com/'})"),null);
  context.externalItem={...products[1],url:'https://example.com/product/cup-350'}; context.externalButton=new Element('button');
  const selectedBefore=run('selected'); activity.length=0;
  const opening=run("openRecommendation(externalButton,'cup-1',externalItem,'similar')");
  assert.equal(openCalls.length,1,'window must open synchronously within user gesture');
  assert.deepEqual(activity.slice(0,2),['open','event']);
  await opening;
  assert.deepEqual(openCalls[0],['https://example.com/product/cup-350','_blank','noopener,noreferrer']);
  const outbound=requests.findLast(r=>r.url==='/api/events'); assert.equal(outbound.body.is_demo,false); assert.equal(outbound.body.source_product_id,'cup-1'); assert.equal(outbound.body.target_product_id,'cup-2'); assert.equal(run('selected'),selectedBefore); assert.equal(context.externalButton.disabled,false);
  ids.get('logout-button').click(); assert.equal(memory.has('shoprec-admin'),false); assert.equal(ids.get('admin-workspace').hidden,true);
  console.log('PASS: frontend auth, scoped settings/import, allowlists, valid sample URLs, no render events, demo/real click separation, safe synchronous external opening.');
})().catch(error=>{console.error(error);process.exitCode=1;});
