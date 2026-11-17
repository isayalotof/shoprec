"""SQLite persistence for the single-operator ShopRec pilot."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from recommender import validate_catalog
from seed import catalog, stores as seed_stores

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

class ConflictError(ValueError):
    pass

class Storage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connection() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS stores (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
              participating INTEGER NOT NULL DEFAULT 0 CHECK(participating IN (0,1)),
              partner_allowlist TEXT, category_allowlist TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
              id TEXT PRIMARY KEY, store_id TEXT NOT NULL REFERENCES stores(id),
              name TEXT NOT NULL, type TEXT NOT NULL, category TEXT NOT NULL,
              description TEXT NOT NULL, price REAL NOT NULL CHECK(price>=0),
              in_stock INTEGER NOT NULL CHECK(in_stock IN (0,1)), tags TEXT NOT NULL,
              color TEXT NOT NULL, compatibility TEXT NOT NULL, url TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS products_store ON products(store_id);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
              source_store_id TEXT NOT NULL REFERENCES stores(id),
              target_store_id TEXT NOT NULL REFERENCES stores(id),
              source_product_id TEXT NOT NULL, target_product_id TEXT NOT NULL,
              source_product_name TEXT NOT NULL, target_product_name TEXT NOT NULL,
              placement TEXT NOT NULL CHECK(placement IN ('similar','complementary','partner')),
              is_demo INTEGER NOT NULL DEFAULT 1 CHECK(is_demo IN (0,1)),
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_source ON events(source_store_id);
            CREATE INDEX IF NOT EXISTS events_target ON events(target_store_id);
            ''')
            if 'is_demo' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
                db.execute('ALTER TABLE events ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 1')
            if 'url' not in {r[1] for r in db.execute('PRAGMA table_info(products)')}:
                db.execute("ALTER TABLE products ADD COLUMN url TEXT NOT NULL DEFAULT ''")
            if db.execute('SELECT COUNT(*) FROM stores').fetchone()[0] == 0:
                timestamp = now()
                for s in seed_stores():
                    db.execute('INSERT INTO stores VALUES(?,?,?,?,?,?,?,?)',
                        (s['id'],s['name'],s['description'],int(s['participating']),None,None,timestamp,timestamp))
                self._insert_products(db, validate_catalog(catalog()))
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path, timeout=10)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _store(row):
        s=dict(row)
        s['participating']=bool(s['participating'])
        for key in ('partner_allowlist','category_allowlist'):
            s[key]=json.loads(s[key]) if s[key] is not None else None
        return s

    @staticmethod
    def _product(row):
        p=dict(row);p['in_stock']=bool(p['in_stock']);p['tags']=json.loads(p['tags']);return p

    @staticmethod
    def _insert_products(db, products):
        db.executemany('INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', [
            (p['id'],p['store_id'],p['name'],p['type'],p['category'],p['description'],p['price'],
             int(p['in_stock']),json.dumps(p['tags'],ensure_ascii=False),p['color'],p['compatibility'],p['url']) for p in products])

    def snapshot(self):
        with self.connection() as db:
            db.execute('BEGIN')
            stores=[self._store(r) for r in db.execute('SELECT * FROM stores ORDER BY created_at,id')]
            products=[self._product(r) for r in db.execute('SELECT * FROM products ORDER BY rowid')]
            return products,stores

    def list_stores(self):
        with self.connection() as db:
            return [self._store(r) for r in db.execute('SELECT * FROM stores ORDER BY created_at,id')]

    def create_store(self, payload):
        allowed={'id','name','description','participating'}
        if set(payload)-allowed:raise ValueError('Неизвестные поля магазина.')
        sid=payload.get('id','')
        if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',sid):
            raise ValueError('ID магазина: латинские буквы, цифры, дефис или подчёркивание, до 64 символов.')
        name=payload.get('name','');description=payload.get('description','')
        if not isinstance(name,str) or not name.strip() or len(name)>100:
            raise ValueError('Название магазина: от 1 до 100 символов.')
        if not isinstance(description,str) or len(description)>500:raise ValueError('Описание: до 500 символов.')
        participating=payload.get('participating',False)
        if not isinstance(participating,bool):raise ValueError('participating должен быть true или false.')
        with self.connection() as db:
            if db.execute('SELECT 1 FROM stores WHERE id=?',(sid,)).fetchone():raise ConflictError('Такой ID магазина уже существует.')
            timestamp=now()
            db.execute('INSERT INTO stores VALUES(?,?,?,?,?,?,?,?)',(sid,name.strip(),description.strip(),int(participating),None,None,timestamp,timestamp))
            return self._store(db.execute('SELECT * FROM stores WHERE id=?',(sid,)).fetchone())

    def update_settings(self, sid, changes):
        allowed={'participating','partner_allowlist','category_allowlist'}
        if not changes or set(changes)-allowed:raise ValueError('Нужны корректные поля настроек магазина.')
        with self.connection() as db:
            row=db.execute('SELECT * FROM stores WHERE id=?',(sid,)).fetchone()
            if not row:raise KeyError('Магазин не найден.')
            current=self._store(row)
            known_stores={r[0] for r in db.execute('SELECT id FROM stores')}
            known_categories={r[0] for r in db.execute('SELECT DISTINCT category FROM products')}
            for key,value in changes.items():
                if key=='participating':
                    if not isinstance(value,bool):raise ValueError('participating должен быть true или false.')
                elif value is not None:
                    if not isinstance(value,list) or len(value)>500 or any(not isinstance(v,str) for v in value):
                        raise ValueError(f'{key}: нужен список строк или null.')
                    if len(value)!=len(set(value)):raise ValueError(f'{key}: значения не должны повторяться.')
                    if key=='partner_allowlist' and (set(value)-known_stores or sid in value):
                        raise ValueError('Выберите существующие магазины-партнёры, кроме своего.')
                    if key=='category_allowlist' and set(value)-known_categories:
                        raise ValueError('Категории должны существовать в каталоге сети.')
                current[key]=value
            db.execute('UPDATE stores SET participating=?,partner_allowlist=?,category_allowlist=?,updated_at=? WHERE id=?',
                (int(current['participating']),json.dumps(current['partner_allowlist']) if current['partner_allowlist'] is not None else None,
                 json.dumps(current['category_allowlist'],ensure_ascii=False) if current['category_allowlist'] is not None else None,now(),sid))
            return self._store(db.execute('SELECT * FROM stores WHERE id=?',(sid,)).fetchone())

    def import_products(self, sid, raw):
        if not isinstance(raw,list):raise ValueError('Каталог должен быть массивом товаров.')
        products=validate_catalog([{**p,'store_id':sid} if isinstance(p,dict) else p for p in raw])
        with self.connection() as db:
            if not db.execute('SELECT 1 FROM stores WHERE id=?',(sid,)).fetchone():raise KeyError('Магазин не найден.')
            foreign={r[0] for r in db.execute('SELECT id FROM products WHERE store_id<>?',(sid,))}
            collision=foreign & {p['id'] for p in products}
            if collision:raise ConflictError('ID заняты другим магазином: '+', '.join(sorted(collision)[:5])+'. Используйте уникальный префикс.')
            db.execute('DELETE FROM products WHERE store_id=?',(sid,))
            self._insert_products(db,products)
            db.execute('UPDATE stores SET updated_at=? WHERE id=?',(now(),sid))
        return len(products)

    def record_event(self, event_id, source, target, placement, is_demo=True):
        values=(source['store_id'],target['store_id'],source['id'],target['id'],placement,int(is_demo))
        with self.connection() as db:
            previous=db.execute('SELECT * FROM events WHERE event_id=?',(event_id,)).fetchone()
            if previous:
                old=tuple(previous[key] for key in ('source_store_id','target_store_id','source_product_id','target_product_id','placement','is_demo'))
                if old!=values:raise ConflictError('event_id уже использован для другого события.')
                return previous['id'],False
            cursor=db.execute('INSERT INTO events(event_id,source_store_id,target_store_id,source_product_id,target_product_id,source_product_name,target_product_name,placement,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (event_id,*values[:4],source['name'],target['name'],placement,int(is_demo),now()))
            return cursor.lastrowid,True

    def analytics(self, sid=None):
        with self.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT id,name FROM stores ORDER BY name')]
            if sid is not None and sid not in {r['id'] for r in rows}:raise KeyError('Магазин не найден.')
            keys=('internal_clicks','inbound_clicks','outbound_clicks','demo_internal_clicks','demo_inbound_clicks','demo_outbound_clicks')
            counts={r['id']:{**r,**dict.fromkeys(keys,0)} for r in rows}
            for event in db.execute('SELECT source_store_id,target_store_id,placement,is_demo,COUNT(*) AS n FROM events GROUP BY source_store_id,target_store_id,placement,is_demo'):
                prefix='demo_' if event['is_demo'] else ''
                if event['placement']=='partner':
                    counts[event['source_store_id']][prefix+'outbound_clicks']+=event['n']
                    counts[event['target_store_id']][prefix+'inbound_clicks']+=event['n']
                else:counts[event['source_store_id']][prefix+'internal_clicks']+=event['n']
            result=[v for key,v in counts.items() if sid is None or key==sid]
            totals={key:sum(r[key] for r in result) for key in keys}
            where='WHERE source_store_id=? OR target_store_id=?' if sid else ''
            recent=[dict(r) for r in db.execute('SELECT * FROM events '+where+' ORDER BY id DESC LIMIT 50',(sid,sid) if sid else ())]
            for event in recent:event['is_demo']=bool(event['is_demo'])
            return {'totals':totals,'stores':result,'recent':recent,'note':'Записанные клики, не подтверждённые продажи. Тестовые клики оператора тоже учитываются.'}
