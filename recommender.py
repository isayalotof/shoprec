"""Small, explainable catalog-based recommender; Python standard library only."""
from collections import Counter
import math
import re
from urllib.parse import urlsplit

STOP = {'и', 'для', 'в', 'с', 'на', 'из', 'по', 'до', 'к', 'без', 'это', 'или', 'от'}
PAIRS = {
    'moka': {'coffee', 'grinder', 'cup', 'scale'},
    'dripper': {'filter', 'coffee', 'kettle', 'scale', 'cup', 'grinder'},
    'frenchpress': {'coffee', 'grinder', 'cup', 'kettle'},
    'coffee': {'moka', 'dripper', 'frenchpress', 'grinder', 'cup'},
    'grinder': {'coffee', 'moka', 'dripper', 'frenchpress', 'scale'},
    'kettle': {'dripper', 'frenchpress', 'cup'},
    'cup': {'moka', 'dripper', 'frenchpress', 'coffee'},
    'filter': {'dripper'}, 'scale': {'dripper', 'moka', 'grinder'},
    'lamp': {'bulb', 'tray'}, 'bulb': {'lamp'},
    'vase': {'tray'}, 'tray': {'vase', 'candle'},
    'candle': {'tray'}, 'cushion': {'throw'}, 'throw': {'cushion'},
}
TYPE_LABELS = {
    'moka': 'гейзерные кофеварки', 'dripper': 'воронки', 'frenchpress': 'френч-прессы',
    'coffee': 'кофе', 'grinder': 'кофемолки', 'kettle': 'чайники', 'cup': 'чашки',
    'filter': 'фильтры', 'scale': 'весы', 'lamp': 'лампы', 'bulb': 'лампочки',
    'vase': 'вазы', 'tray': 'подносы', 'candle': 'свечи', 'cushion': 'подушки', 'throw': 'пледы',
}

def tokenize(text):
    return [s for s in re.findall(r'[a-zа-яё0-9]+', text.lower()) if s not in STOP and len(s) > 1]

def validate_catalog(raw, max_products=500):
    if not isinstance(raw, list) or len(raw)<2 or (max_products is not None and len(raw)>max_products):
        raise ValueError('В каталоге должно быть от 2 до 500 товаров.' if max_products else 'В каталоге должно быть не менее 2 товаров.')
    items, seen = [], set()
    for i, source in enumerate(raw, 1):
        if not isinstance(source, dict):
            raise ValueError(f'Строка {i}: ожидается объект товара.')
        p = dict(source)
        for key in ('id', 'name', 'type', 'category', 'description'):
            if not isinstance(p.get(key), str) or not p[key].strip() or len(p[key]) > 2000:
                raise ValueError(f'Строка {i}: нужно текстовое поле {key}.')
            p[key] = p[key].strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', p['id']):
            raise ValueError(f'Строка {i}: id — латинские буквы, цифры, дефис или подчёркивание.')
        if p['id'] in seen:
            raise ValueError(f'Повторяется id: {p["id"]}.')
        seen.add(p['id'])
        if isinstance(p.get('price'), bool):
            raise ValueError(f'Строка {i}: цена должна быть числом.')
        try:
            p['price'] = float(p['price'])
        except (ValueError, TypeError, KeyError):
            raise ValueError(f'Строка {i}: нужна числовая цена.')
        if not math.isfinite(p['price']) or p['price'] < 0:
            raise ValueError(f'Строка {i}: цена не может быть отрицательной или бесконечной.')
        stock = p.get('in_stock', True)
        if isinstance(stock, str):
            if stock.lower() not in ('true', 'false', '1', '0', 'да', 'нет'):
                raise ValueError(f'Строка {i}: in_stock — true или false.')
            stock = stock.lower() in ('true', '1', 'да')
        if not isinstance(stock, bool):
            raise ValueError(f'Строка {i}: in_stock — true или false.')
        p['in_stock'] = stock
        tags = p.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split('|') if t.strip()]
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise ValueError(f'Строка {i}: tags — список строк или строка через |.')
        p['tags'] = tags[:30]
        p['color'] = p.get('color', '#D6CEC0')
        if not isinstance(p['color'], str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', p['color']):
            p['color'] = '#D6CEC0'
        p['compatibility'] = str(p.get('compatibility', ''))[:100]
        p['url'] = p.get('url', '')
        if not isinstance(p['url'], str) or len(p['url'])>2048:
            raise ValueError(f'Строка {i}: url должен быть строкой до 2048 символов.')
        if p['url']:
            try:
                parsed=urlsplit(p['url'])
                _=parsed.port
                valid=(parsed.scheme in ('http','https') and bool(parsed.hostname) and
                       parsed.username is None and parsed.password is None and not any(c.isspace() or ord(c)<32 for c in p['url']))
            except ValueError:valid=False
            if not valid:raise ValueError(f'Строка {i}: url — адрес http/https без логина и пароля.')
        p['store_id'] = p.get('store_id', 'custom')
        if not isinstance(p['store_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', p['store_id']):
            raise ValueError(f'Строка {i}: некорректный store_id.')
        items.append({key: p[key] for key in ('id', 'name', 'type', 'category', 'description', 'price', 'in_stock', 'tags', 'color', 'compatibility', 'store_id', 'url')})
    return items

class Recommender:
    def __init__(self, products):
        self.products = validate_catalog(products, max_products=None)
        self.by_id = {p['id']: p for p in self.products}
        docs = [tokenize(' '.join([p['name']] * 2 + [p['description'], p['category']] + p['tags'] * 2)) for p in self.products]
        df = Counter(t for doc in docs for t in set(doc))
        self.idf = {t: math.log((1 + len(docs)) / (1 + count)) + 1 for t, count in df.items()}
        self.vectors = {}
        for p, tokens in zip(self.products, docs):
            counts = Counter(tokens)
            vector = {t: (1 + math.log(n)) * self.idf[t] for t, n in counts.items()}
            norm = math.sqrt(sum(w*w for w in vector.values())) or 1
            self.vectors[p['id']] = {t: w / norm for t, w in vector.items()}

    def recommend(self, product_id, mode='similar', limit=3):
        if product_id not in self.by_id:
            raise KeyError('Товар не найден.')
        if mode not in ('similar', 'complementary'):
            raise ValueError('Неизвестный режим рекомендаций.')
        base = self.by_id[product_id]
        v = self.vectors[product_id]
        results = []
        for p in self.products:
            if p['id'] == product_id or not p['in_stock'] or p['store_id'] != base['store_id']:
                continue
            cosine = sum(w * self.vectors[p['id']].get(t, 0) for t, w in v.items())
            shared = sorted(set(base['tags']) & set(p['tags']))
            if mode == 'similar':
                if p['type'] != base['type']:
                    continue
                score = cosine
                reason = 'Тот же тип товара'
                if shared:
                    reason += ' · ' + ', '.join(shared[:2])
            else:
                if p['type'] not in PAIRS.get(base['type'], set()):
                    continue
                # Sockets and filter formats must match when both are declared.
                if {base['type'], p['type']} in ({'lamp', 'bulb'}, {'dripper', 'filter'}):
                    if not base['compatibility'] or base['compatibility'] != p['compatibility']:
                        continue
                # Explicit intended use, then textual similarity. Not collaborative filtering.
                score = 0.7 + 0.3 * cosine
                reason = 'Дополняет этот тип товара'
                if {base['type'], p['type']} == {'lamp', 'bulb'}:
                    reason = 'Подходит по цоколю ' + base['compatibility']
                elif {base['type'], p['type']} == {'dripper', 'filter'}:
                    reason = 'Совместимый размер ' + base['compatibility']
                elif shared:
                    reason += ' · ' + shared[0]
            results.append({**p, 'score': round(score, 6), 'reason': reason})
        results.sort(key=lambda p: (-p['score'], p['id']))
        if mode == 'complementary':
            # Prefer different useful types before a second item of the same type.
            unique, remaining, types = [], [], set()
            for p in results:
                if p['type'] in types:
                    remaining.append(p)
                else:
                    unique.append(p)
                    types.add(p['type'])
            results = unique + remaining
        return results[:max(1, min(int(limit), 12))]

    def partners(self, product_id, stores, limit=3):
        if product_id not in self.by_id:
            raise KeyError('Товар не найден.')
        base = self.by_id[product_id]
        eligible = {s['id']: s for s in stores if s.get('participating')}
        if base['store_id'] not in eligible:
            return []
        source_store = eligible[base['store_id']]
        own = [p for p in self.products if p['store_id'] == base['store_id']]
        # Protect the whole assortment, including temporarily unavailable items.
        own_types = {p['type'].casefold() for p in own}
        own_categories = {p['category'].casefold() for p in own}
        v = self.vectors[product_id]
        results = []
        for p in self.products:
            if p['store_id'] == base['store_id'] or p['store_id'] not in eligible or not p['in_stock']:
                continue
            target_store = eligible[p['store_id']]
            source_allow = source_store.get('partner_allowlist')
            target_allow = target_store.get('partner_allowlist')
            category_allow = source_store.get('category_allowlist')
            if source_allow is not None and p['store_id'] not in source_allow:
                continue
            if target_allow is not None and base['store_id'] not in target_allow:
                continue
            if category_allow is not None and p['category'] not in category_allow:
                continue
            if p['type'].casefold() in own_types or p['category'].casefold() in own_categories:
                continue
            if p['type'] not in PAIRS.get(base['type'], set()):
                continue
            if {base['type'], p['type']} in ({'lamp', 'bulb'}, {'dripper', 'filter'}):
                if not base['compatibility'] or p['compatibility'] != base['compatibility']:
                    continue
            cosine = sum(w * self.vectors[p['id']].get(t, 0) for t, w in v.items())
            reason = 'Дополнение вне ассортимента вашего магазина'
            if p['compatibility']:
                reason += ' · ' + p['compatibility']
            results.append({**p, 'score': round(cosine, 6), 'reason': reason, 'store_name': eligible[p['store_id']]['name']})
        results.sort(key=lambda p: (-p['score'], p['id']))
        unique, rest, types = [], [], set()
        for p in results:
            (rest if p['type'] in types else unique).append(p)
            types.add(p['type'])
        return (unique + rest)[:max(1, min(int(limit), 12))]
