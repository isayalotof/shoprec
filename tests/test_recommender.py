import copy
import math
import unittest
from recommender import Recommender, validate_catalog
from seed import catalog, stores

class RecommendationsTest(unittest.TestCase):
    def setUp(self):
        self.engine = Recommender(catalog())

    def test_similar_never_self_unavailable_or_other_type(self):
        result = self.engine.recommend('moka-01')
        self.assertEqual({p['id'] for p in result}, {'moka-02','moka-03'})
        self.assertTrue(all(p['store_id'] == 'doma' and p['in_stock'] and p['type'] == 'moka' for p in result))

    def test_relevance_prefers_matching_size(self):
        self.assertEqual(self.engine.recommend('moka-01')[0]['id'], 'moka-02')

    def test_complementary_stays_in_own_store(self):
        result = self.engine.recommend('moka-01','complementary')
        self.assertTrue(result)
        self.assertTrue(all(p['store_id'] == 'doma' and p['type']=='cup' for p in result))

    def test_no_irrelevant_fallback(self):
        self.assertEqual(self.engine.recommend('scale-01'), [])

    def test_partner_gap_excludes_all_own_categories(self):
        result = self.engine.partners('moka-01', stores())
        self.assertTrue(result)
        own = {p['category'] for p in self.engine.products if p['store_id']=='doma'}
        self.assertTrue(all(p['category'] not in own and p['store_id']!='doma' for p in result))
        self.assertEqual({p['type'] for p in result}, {'coffee','grinder','scale'})

    def test_own_category_excluded_even_if_out_of_stock(self):
        products = catalog()
        extra = copy.deepcopy(next(p for p in products if p['type']=='coffee'))
        extra.update(id='own-unavailable-coffee',store_id='doma',in_stock=False)
        engine=Recommender(products+[extra])
        self.assertFalse(any(p['type']=='coffee' for p in engine.partners('moka-01',stores(),12)))

    def test_partner_socket_compatibility(self):
        self.assertEqual([p['id'] for p in self.engine.partners('lamp-01',stores())],['bulb-01'])
        self.assertEqual([p['id'] for p in self.engine.partners('lamp-03',stores())],['bulb-02'])

    def test_partner_filter_compatibility(self):
        result=self.engine.partners('dripper-01',stores(),12)
        ids={p['id'] for p in result}
        self.assertIn('filter-01',ids)
        self.assertNotIn('filter-02',ids)

    def test_opt_out_applies_to_both_sides(self):
        ss=stores();ss[0]['participating']=False
        self.assertEqual(self.engine.partners('moka-01',ss),[])
        self.assertFalse(any(p['store_id']=='doma' for p in self.engine.partners('coffee-01',ss,12)))
        ss=stores();ss[2]['participating']=False
        self.assertTrue(all(p['store_id']=='roast' for p in self.engine.partners('moka-01',ss)))

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):validate_catalog(catalog()+[catalog()[0]])

    def test_non_finite_prices_rejected(self):
        for price in (math.inf, math.nan, -1, True):
            raw=catalog();raw[0]['price']=price
            with self.assertRaises(ValueError):validate_catalog(raw)

    def test_invalid_mode_and_product(self):
        with self.assertRaises(ValueError):self.engine.recommend('moka-01','magic')
        with self.assertRaises(KeyError):self.engine.recommend('unknown')

    def test_csv_stock_bool_parsing(self):
        raw=catalog();raw[0]['in_stock']='false';raw[1]['in_stock']='true'
        validated=validate_catalog(raw)
        self.assertFalse(validated[0]['in_stock']);self.assertTrue(validated[1]['in_stock'])

    def test_results_deterministic(self):
        self.assertEqual(self.engine.partners('moka-01',stores()),self.engine.partners('moka-01',stores()))

    def test_product_url_only_http_https_without_credentials(self):
        for url in ('javascript:alert(1)','data:text/html,test','https://user:pass@example.org/p','https://example.org/ bad','https://example.org:bad/p'):
            rows=catalog();rows[0]['url']=url
            with self.assertRaises(ValueError):validate_catalog(rows)
        rows=catalog();rows[0]['url']='https://store.example/product/1?q=coffee'
        self.assertEqual(validate_catalog(rows)[0]['url'],rows[0]['url'])

if __name__=='__main__':unittest.main()
