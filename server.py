#!/usr/bin/env python3
"""ShopRec single-operator pilot: SQLite, catalog APIs and explicit admin access."""
import argparse
from collections import defaultdict, deque
import csv
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
import time
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
from recommender import Recommender
from storage import Storage, ConflictError

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/'static'
MAX_BYTES=2*1024*1024
VERSION='0.2.0'

class Application:
    def __init__(self, db_path, token):
        if not isinstance(token,str) or len(token)<24:
            raise ValueError('Admin token must contain at least 24 characters.')
        self.storage=Storage(db_path)
        self.token=token
        self.rate_lock=Lock()
        self.rate_buckets=defaultdict(deque)
    def rate_allowed(self,key,limit=120,window=60):
        current=time.monotonic()
        with self.rate_lock:
            bucket=self.rate_buckets[key]
            while bucket and bucket[0]<current-window:bucket.popleft()
            if len(bucket)>=limit:return False
            bucket.append(current)
            if len(self.rate_buckets)>1000:
                self.rate_buckets=defaultdict(deque,{k:v for k,v in self.rate_buckets.items() if v and v[-1]>=current-window})
            return True

class Handler(BaseHTTPRequestHandler):
    server_version='ShopRec/'+VERSION

    @property
    def app(self):return self.server.app

    def authenticated(self):
        header=self.headers.get('Authorization','')
        return header.startswith('Bearer ') and hmac.compare_digest(header[7:],self.app.token)

    def same_origin(self):
        origin=self.headers.get('Origin')
        if not origin:return True
        parsed=urlsplit(origin)
        allowed=os.environ.get('SHOPREC_PUBLIC_ORIGIN','').rstrip('/')
        return origin==allowed or (parsed.scheme in ('http','https') and parsed.netloc==self.headers.get('Host'))

    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')

    def json(self,status,value):
        data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)

    def require_admin(self):
        if not self.authenticated():
            self.json(401,{'error':'Нужен токен администратора.'});return False
        return True

    def read_json(self):
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
            raise ValueError('Нужен Content-Type: application/json.')
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ValueError('Некорректный Content-Length.')
        if not 0<length<=MAX_BYTES:raise OverflowError('Тело запроса должно быть от 1 байта до 2 МБ.')
        payload=json.loads(self.rfile.read(length))
        if not isinstance(payload,dict):raise ValueError('Ожидается JSON-объект.')
        return payload

    def snapshot_engine(self):
        products,stores=self.app.storage.snapshot()
        return Recommender(products),stores

    def do_GET(self):
        try:self.get_route()
        except KeyError as e:self.json(404,{'error':str(e).strip("'")})
        except (ValueError,TypeError) as e:self.json(400,{'error':str(e)})
        except sqlite3.Error:self.json(503,{'error':'Хранилище временно недоступно. Повторите запрос.'})

    def get_route(self):
        url=urlsplit(self.path);path=url.path;params=parse_qs(url.query)
        if path=='/api/health':return self.json(200,{'status':'ok','storage':'sqlite','version':VERSION})
        if path=='/api/session':return self.json(200,{'authenticated':self.authenticated()})
        if path=='/api/stores':return self.json(200,{'stores':self.app.storage.list_stores()})
        if path=='/api/products':
            products,stores=self.app.storage.snapshot()
            sid=params.get('store_id',[None])[0]
            if sid is not None:
                if sid not in {s['id'] for s in stores}:raise KeyError('Магазин не найден.')
                products=[p for p in products if p['store_id']==sid]
            return self.json(200,{'products':products,'stores':stores,'count':len(products),'source':'pilot'})
        if path in ('/api/recommendations','/api/partners'):
            engine,stores=self.snapshot_engine()
            pid=params.get('product_id',[''])[0]
            limit=int(params.get('limit',['3'])[0])
            if not 1<=limit<=12:raise ValueError('limit должен быть от 1 до 12.')
            mode=params.get('mode',['similar'])[0]
            items=engine.partners(pid,stores,limit) if path=='/api/partners' else engine.recommend(pid,mode,limit)
            return self.json(200,{'product_id':pid,'mode':'partner' if path=='/api/partners' else mode,'items':items,
                'placement':'post-purchase' if path=='/api/partners' else 'product-page','behavioral_data':False})
        if path=='/api/analytics':
            if not self.require_admin():return
            return self.json(200,self.app.storage.analytics(params.get('store_id',[None])[0]))
        if path=='/example-catalog.json':
            from seed import catalog
            return self.json(200,[p for p in catalog() if p['store_id']=='doma'])
        if path.startswith('/api/'):raise KeyError('Маршрут не найден.')
        name='index.html' if path in ('/','/admin','/admin/') else unquote(path).lstrip('/')
        target=(STATIC/name).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():raise KeyError('Страница не найдена.')
        data=target.read_bytes()
        self.send_response(200);self.headers_common()
        self.send_header('Content-Type',(mimetypes.guess_type(target)[0] or 'application/octet-stream')+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_POST(self):
        try:self.post_route()
        except ConflictError as e:self.json(409,{'error':str(e)})
        except KeyError as e:self.json(404,{'error':str(e).strip("'")})
        except OverflowError as e:self.json(413,{'error':str(e)})
        except (ValueError,TypeError,UnicodeError,csv.Error) as e:self.json(400,{'error':str(e)})
        except sqlite3.Error:self.json(503,{'error':'Хранилище временно недоступно. Повторите запрос.'})

    def post_route(self):
        path=urlsplit(self.path).path
        if path not in ('/api/import','/api/settings','/api/participation','/api/stores','/api/events'):
            raise KeyError('Маршрут не найден.')
        if not self.same_origin():return self.json(403,{'error':'Запрос с чужого origin запрещён.'})
        if path!='/api/events' and not self.require_admin():return
        if path=='/api/events' and not self.app.rate_allowed(self.client_address[0]):
            return self.json(429,{'error':'Слишком много событий. Повторите позже.'})
        body=self.read_json()
        if path=='/api/stores':
            store=self.app.storage.create_store(body)
            return self.json(201,{'store':store,'stores':self.app.storage.list_stores()})
        if path in ('/api/settings','/api/participation'):
            sid=body.pop('store_id',None)
            if not isinstance(sid,str):raise ValueError('Нужен store_id.')
            store=self.app.storage.update_settings(sid,body)
            return self.json(200,{'store':store,'stores':self.app.storage.list_stores()})
        if path=='/api/import':
            if set(body)-{'store_id','format','data'}:raise ValueError('Неизвестные поля импорта.')
            sid=body.get('store_id')
            if not isinstance(sid,str):raise ValueError('Укажите store_id магазина для импорта.')
            if body.get('format')=='csv':
                if not isinstance(body.get('data'),str):raise ValueError('CSV должен быть строкой.')
                data=list(csv.DictReader(io.StringIO(body['data'].lstrip('\ufeff'))))
            elif body.get('format')=='json':data=body.get('data')
            else:raise ValueError('Поддерживаются CSV и JSON.')
            count=self.app.storage.import_products(sid,data)
            return self.json(200,{'store_id':sid,'count':count})
        if path=='/api/events':
            if set(body)-{'event_id','source_product_id','target_product_id','placement','is_demo'}:
                raise ValueError('Неизвестные поля события.')
            eid=body.get('event_id','')
            try:
                parsed=uuid.UUID(eid)
                if str(parsed)!=eid.lower():raise ValueError()
            except (ValueError,TypeError,AttributeError):raise ValueError('event_id должен быть UUID.')
            placement=body.get('placement')
            if placement not in ('similar','complementary','partner'):raise ValueError('Некорректное размещение события.')
            is_demo=body.get('is_demo',True)
            if not isinstance(is_demo,bool):raise ValueError('is_demo должен быть true или false.')
            source_id=body.get('source_product_id');target_id=body.get('target_product_id')
            if not isinstance(source_id,str) or not isinstance(target_id,str):raise ValueError('Нужны ID исходного и целевого товаров.')
            engine,stores=self.snapshot_engine()
            if source_id not in engine.by_id or target_id not in engine.by_id:raise KeyError('Товар события не найден.')
            eligible=engine.partners(source_id,stores,12) if placement=='partner' else engine.recommend(source_id,placement,12)
            if target_id not in {p['id'] for p in eligible}:raise ValueError('Целевой товар не является доступной рекомендацией для этого размещения.')
            # A seed card without an external destination cannot become ordinary traffic.
            is_demo = is_demo or not bool(engine.by_id[target_id].get('url'))
            event_id,recorded=self.app.storage.record_event(eid,engine.by_id[source_id],engine.by_id[target_id],placement,is_demo)
            return self.json(201 if recorded else 200,{'recorded':recorded,'id':event_id})

    def log_message(self,format,*args):
        path=urlsplit(getattr(self,'path','')).path
        print(f'{self.command} {path}',flush=True)

def load_token(data_dir,host):
    configured=os.environ.get('SHOPREC_ADMIN_TOKEN')
    if configured:
        if len(configured)<24 or configured.lower().startswith(('replace','change','example')):
            raise ValueError('Set SHOPREC_ADMIN_TOKEN to a random secret of at least 24 characters.')
        return configured
    if host not in ('127.0.0.1','localhost','::1'):
        raise ValueError('SHOPREC_ADMIN_TOKEN is required when listening beyond localhost.')
    token_file=data_dir/'admin-token'
    data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    if token_file.exists():
        token=token_file.read_text().strip()
        if len(token)<24:raise ValueError('Invalid admin token file. Set SHOPREC_ADMIN_TOKEN.')
    else:
        token=secrets.token_urlsafe(32)
        fd=os.open(token_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:file.write(token+'\n')
    token_file.chmod(0o600)
    print(f'Admin token file: {token_file} (not printed). Use its value to sign in at /admin.',flush=True)
    return token

def main():
    parser=argparse.ArgumentParser(description='ShopRec single-operator pilot')
    parser.add_argument('--host',default=os.environ.get('SHOPREC_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('SHOPREC_PORT','8787')))
    args=parser.parse_args()
    data_dir=Path(os.environ.get('SHOPREC_DATA_DIR',str(ROOT/'data'))).resolve()
    try:token=load_token(data_dir,args.host)
    except ValueError as error:parser.error(str(error))
    app=Application(data_dir/'shoprec.db',token)
    server=ThreadingHTTPServer((args.host,args.port),Handler);server.app=app
    print(f'ShopRec {VERSION}: http://{args.host}:{args.port} | admin: /admin',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
