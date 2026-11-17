from pathlib import Path
import tempfile
import unittest
import uuid
from recommender import Recommender
from seed import catalog
from storage import Storage, ConflictError

class StorageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'shoprec.db';self.db=Storage(self.path)
    def tearDown(self):self.temp.cleanup()
    def test_seed_is_once_and_settings_persist(self):
        self.db.update_settings('doma',{'participating':False,'partner_allowlist':['tools'],'category_allowlist':['Кофемолки']})
        reopened=Storage(self.path);products,stores=reopened.snapshot()
        self.assertEqual(len(products),30)
        s=next(s for s in stores if s['id']=='doma')
        self.assertFalse(s['participating']);self.assertEqual(s['partner_allowlist'],['tools']);self.assertEqual(s['category_allowlist'],['Кофемолки'])
    def test_import_replaces_only_selected_store_and_persists(self):
        before,_=self.db.snapshot();other=[p for p in before if p['store_id']!='doma']
        self.db.import_products('doma',[p for p in catalog() if p['store_id']=='doma'][:2])
        after,_=Storage(self.path).snapshot()
        self.assertEqual([p for p in after if p['store_id']!='doma'],other)
        self.assertEqual(len([p for p in after if p['store_id']=='doma']),2)
    def test_conflict_and_invalid_import_do_not_mutate(self):
        before=self.db.snapshot()
        with self.assertRaises(ConflictError):self.db.import_products('doma',[p for p in catalog() if p['store_id']=='roast'])
        with self.assertRaises(ValueError):self.db.import_products('doma',[{'bad':'data'}])
        self.assertEqual(self.db.snapshot(),before)
    def test_aggregate_larger_than_single_store_limit(self):
        for sid in ('doma','roast','tools'):
            rows=[{**catalog()[0],'id':sid+'-'+str(i),'store_id':sid} for i in range(200)]
            self.db.import_products(sid,rows)
        products,stores=self.db.snapshot();engine=Recommender(products)
        self.assertEqual(len(engine.products),600)
        self.assertEqual(len(engine.recommend('doma-0')),3)
    def test_partner_and_category_allowlists(self):
        self.db.update_settings('doma',{'partner_allowlist':['roast'],'category_allowlist':['Кофе']})
        products,stores=self.db.snapshot()
        result=Recommender(products).partners('moka-01',stores)
        self.assertTrue(result);self.assertTrue(all(p['store_id']=='roast' for p in result))
        self.db.update_settings('roast',{'partner_allowlist':[]})
        products,stores=self.db.snapshot()
        self.assertEqual(Recommender(products).partners('moka-01',stores),[])
    def test_settings_validate_ids_categories_and_booleans(self):
        for changes in ({'partner_allowlist':['missing']},{'partner_allowlist':['doma']},{'category_allowlist':['missing']},{'participating':'yes'},{'typo':1}):
            with self.assertRaises(ValueError):self.db.update_settings('doma',changes)
    def test_clicks_persist_and_demo_metrics_are_separate(self):
        products,_=self.db.snapshot();by_id={p['id']:p for p in products}
        self.db.record_event(str(uuid.uuid4()),by_id['moka-01'],by_id['coffee-01'],'partner',True)
        eid=str(uuid.uuid4())
        self.assertTrue(self.db.record_event(eid,by_id['moka-01'],by_id['grinder-01'],'partner',False)[1])
        self.assertFalse(self.db.record_event(eid,by_id['moka-01'],by_id['grinder-01'],'partner',False)[1])
        self.db.record_event(str(uuid.uuid4()),by_id['moka-01'],by_id['moka-02'],'similar',False)
        report=Storage(self.path).analytics()
        self.assertEqual(report['totals'],dict(internal_clicks=1,inbound_clicks=1,outbound_clicks=1,demo_internal_clicks=0,demo_inbound_clicks=1,demo_outbound_clicks=1))
        self.assertEqual(len(report['recent']),3)
        self.assertEqual(self.db.analytics('doma')['totals']['outbound_clicks'],1)
    def test_event_id_conflict_rejected(self):
        products,_=self.db.snapshot();p={p['id']:p for p in products};eid=str(uuid.uuid4())
        self.db.record_event(eid,p['moka-01'],p['moka-02'],'similar')
        with self.assertRaises(ConflictError):self.db.record_event(eid,p['moka-01'],p['moka-03'],'similar')
    def test_new_store_starts_empty_and_not_participating(self):
        new=self.db.create_store({'id':'new','name':'Новый','description':'Пилот'})
        self.assertFalse(new['participating'])
        with self.assertRaises(ConflictError):self.db.create_store({'id':'new','name':'Дубликат'})
        self.assertEqual(len(self.db.list_stores()),4)

    def test_product_url_persists(self):
        rows=[p for p in catalog() if p['store_id']=='doma'][:2]
        rows[0]['url']='https://store.example/products/1'
        self.db.import_products('doma',rows)
        products,_=Storage(self.path).snapshot()
        self.assertEqual(next(p for p in products if p['id']==rows[0]['id'])['url'],rows[0]['url'])

if __name__=='__main__':unittest.main()
