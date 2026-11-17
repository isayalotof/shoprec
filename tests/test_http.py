"""Exercise real HTTP handlers and SQLite transactions without a network socket."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from server import Application, Handler
from seed import catalog

TOKEN='test-admin-token-only-for-isolated-unit-tests'

class FakeHandler(Handler):
    def __init__(self,app,path,body=None,admin=False,origin=None):
        self.server=SimpleNamespace(app=app);self.path=path;self.client_address=('127.0.0.1',12345)
        raw=json.dumps(body).encode() if body is not None else b''
        self.rfile=io.BytesIO(raw);self.wfile=io.BytesIO()
        self.headers={'Content-Length':str(len(raw)),'Host':'127.0.0.1:8787','Content-Type':'application/json'}
        if admin:self.headers['Authorization']='Bearer '+TOKEN
        if origin:self.headers['Origin']=origin
        self.status=None;self.response_headers={}
    def send_response(self,status):self.status=status
    def send_header(self,name,value):self.response_headers[name]=value
    def end_headers(self):pass
    def result(self):return json.loads(self.wfile.getvalue())

class HttpTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Application(Path(self.temp.name)/'shoprec.db',TOKEN)
    def tearDown(self):self.temp.cleanup()
    def request(self,path,body=None,admin=False,origin=None):
        h=FakeHandler(self.app,path,body,admin,origin)
        (h.do_GET if body is None else h.do_POST)();return h
    def test_products_stores_and_recommendations(self):
        h=self.request('/api/products');self.assertEqual(h.status,200);self.assertEqual(len(h.result()['products']),30)
        self.assertEqual(len(self.request('/api/stores').result()['stores']),3)
        h=self.request('/api/recommendations?product_id=moka-01&mode=similar');self.assertEqual(len(h.result()['items']),2)
    def test_protected_reads_and_writes_require_token(self):
        self.assertEqual(self.request('/api/analytics').status,401)
        self.assertEqual(self.request('/api/import',{'store_id':'doma','format':'json','data':[]}).status,401)
        self.assertEqual(self.request('/api/settings',{'store_id':'doma','participating':False}).status,401)
        self.assertFalse(self.request('/api/session').result()['authenticated'])
        self.assertTrue(self.request('/api/session',admin=True).result()['authenticated'])
    def test_admin_settings_persist(self):
        h=self.request('/api/settings',{'store_id':'doma','participating':False,'partner_allowlist':[]},True)
        self.assertEqual(h.status,200)
        self.assertEqual(self.request('/api/partners?product_id=moka-01').result()['items'],[])
    def test_unknown_product_bad_mode_and_limit(self):
        for path,code in [('/api/recommendations?product_id=unknown',404),('/api/recommendations?product_id=moka-01&mode=bad',400),('/api/recommendations?product_id=moka-01&limit=abc',400),('/api/recommendations?product_id=moka-01&limit=0',400)]:
            self.assertEqual(self.request(path).status,code)
    def test_invalid_import_is_atomic(self):
        previous=self.app.storage.snapshot()
        h=self.request('/api/import',{'store_id':'doma','format':'json','data':[{'id':'bad'}]},True)
        self.assertEqual(h.status,400);self.assertEqual(self.app.storage.snapshot(),previous)
    def test_import_keeps_other_stores_and_rejects_conflict(self):
        data=[p for p in catalog() if p['store_id']=='doma'][:2]
        h=self.request('/api/import',{'store_id':'doma','format':'json','data':data},True)
        self.assertEqual(h.status,200);self.assertEqual(h.result()['count'],2)
        self.assertEqual(len(self.request('/api/products?store_id=roast').result()['products']),2)
        h=self.request('/api/import',{'store_id':'doma','format':'json','data':[p for p in catalog() if p['store_id']=='roast']},True)
        self.assertEqual(h.status,409)
    def test_csv_import(self):
        csv='id,name,type,category,description,price,in_stock\na,Лампа 1,lamp,Лампы,Свет для чтения,500,true\nb,Лампа 2,lamp,Лампы,Свет для дома,700,false\n'
        h=self.request('/api/import',{'store_id':'doma','format':'csv','data':csv},True)
        self.assertEqual(h.status,200)
        self.assertEqual(self.request('/api/products?store_id=doma').result()['count'],2)
    def test_cross_origin_mutation_rejected(self):
        h=self.request('/api/settings',{'store_id':'doma','participating':False},True,'https://other.example')
        self.assertEqual(h.status,403)
    def test_oversize_body_rejected(self):
        h=FakeHandler(self.app,'/api/import',{},True);h.headers['Content-Length']=str(3*1024*1024);h.do_POST()
        self.assertEqual(h.status,413)
    def test_wrong_content_type_rejected(self):
        h=FakeHandler(self.app,'/api/settings',{'store_id':'doma','participating':False},True);h.headers['Content-Type']='text/plain';h.do_POST()
        self.assertEqual(h.status,400)
    def test_path_escape_rejected(self):
        for path in ['/../server.py','/%2e%2e/server.py','/../../etc/passwd','/data/admin-token','/missing-file']:
            self.assertEqual(self.request(path).status,404)
    def test_public_event_eligible_and_deduplicated(self):
        body={'event_id':str(uuid.uuid4()),'source_product_id':'moka-01','target_product_id':'coffee-01','placement':'partner','is_demo':True}
        self.assertEqual(self.request('/api/events',body).status,201)
        self.assertEqual(self.request('/api/events',body).status,200)
        report=self.request('/api/analytics',admin=True).result()
        self.assertEqual(report['totals']['demo_outbound_clicks'],1);self.assertEqual(report['totals']['outbound_clicks'],0)
    def test_ineligible_event_rejected(self):
        body={'event_id':str(uuid.uuid4()),'source_product_id':'moka-01','target_product_id':'lamp-01','placement':'partner','is_demo':False}
        self.assertEqual(self.request('/api/events',body).status,400)
        self.assertEqual(self.request('/api/analytics',admin=True).result()['totals']['outbound_clicks'],0)

    def test_no_url_events_forced_to_demo_and_external_urls_count_ordinary(self):
        body={'event_id':str(uuid.uuid4()),'source_product_id':'moka-01','target_product_id':'coffee-01','placement':'partner','is_demo':False}
        self.assertEqual(self.request('/api/events',body).status,201)
        self.assertEqual(self.app.storage.analytics()['totals']['outbound_clicks'],0)
        coffee=[p for p in catalog() if p['store_id']=='roast'];coffee[0]['url']='https://coffee.example/product/1'
        self.app.storage.import_products('roast',coffee)
        body['event_id']=str(uuid.uuid4())
        self.assertEqual(self.request('/api/events',body).status,201)
        totals=self.app.storage.analytics()['totals']
        self.assertEqual(totals['outbound_clicks'],1);self.assertEqual(totals['demo_outbound_clicks'],1)
    def test_admin_shell_and_widget_are_public(self):
        for path in ['/','/admin','/embed.js','/widget.html']:
            h=self.request(path);self.assertEqual(h.status,200);self.assertGreater(len(h.wfile.getvalue()),100)
    def test_rate_limit(self):
        self.assertTrue(all(self.app.rate_allowed('test',limit=2) for _ in range(2)))
        self.assertFalse(self.app.rate_allowed('test',limit=2))

if __name__=='__main__':unittest.main()
