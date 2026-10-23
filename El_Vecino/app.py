"""Prototipo académico local. Python 3.10+, sin dependencias externas."""
import hashlib, hmac, html, json, os, secrets, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('VECINO_DB', str(ROOT / 'vecino.sqlite3')))
SESSIONS = {}
ATTEMPTS = {}

class Rejected(Exception):
    pass

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()

def connect():
    c = sqlite3.connect(DB, timeout=10, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt + ':' + digest

def password_ok(password, stored):
    salt, digest = stored.split(':')
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return hmac.compare_digest(candidate, digest)

def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('administrador','cajero')));
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>0), stock INTEGER NOT NULL CHECK(stock>=0));
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100));
        CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), total INTEGER NOT NULL CHECK(total>=0), created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS details(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>0), price INTEGER NOT NULL CHECK(price>0));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        if not c.execute('SELECT 1 FROM users').fetchone():
            for name, role, pwd in [('admin','administrador','AdminDemo!2026'), ('cajero','cajero','CajaDemo!2026')]:
                c.execute('INSERT INTO users(name,hash,role) VALUES(?,?,?)',(name,password_hash(pwd),role))
            c.executemany('INSERT INTO products(name,price,stock) VALUES(?,?,?)', [('Bebida 1,5 L',1500,24),('Pan de molde',2000,10),('Arroz 1 kg',1200,2)])

def login(name, password):
    now = time.monotonic()
    # Límite global adicional a la clave de cuenta, para este servidor de demostración.
    for key in ('global', 'account:' + name[:100]):
        ATTEMPTS[key] = [t for t in ATTEMPTS.get(key,[]) if now-t < 60]
        if len(ATTEMPTS[key]) >= (30 if key=='global' else 5):
            raise Rejected('Demasiados intentos. Espere un minuto.')
    with connect() as c:
        row = c.execute('SELECT * FROM users WHERE name=?',(name,)).fetchone()
        if not row or not password_ok(password, row['hash']):
            for key in ('global', 'account:' + name[:100]): ATTEMPTS[key].append(now)
            c.execute('INSERT INTO audit(action) VALUES(?)',('LOGIN_FAILED',))
            raise Rejected('Credenciales inválidas')
        c.execute('INSERT INTO audit(user_id,action) VALUES(?,?)',(row['id'],'LOGIN_OK'))
        ATTEMPTS.pop('account:' + name[:100],None)
        return {'id':row['id'],'name':row['name'],'role':row['role']}

def require_admin(user):
    if user['role'] != 'administrador': raise Rejected('Acceso denegado: se requiere administrador')

def total(items):
    if not items: raise Rejected('La venta debe contener productos')
    if any(type(q) is not int or type(p) is not int or q<=0 or p<=0 for p,q in items):
        raise Rejected('Precio o cantidad inválida')
    return sum(p*q for p,q in items)

def register_sale(user, items):
    if not items: raise Rejected('La venta debe contener productos')
    if user['role'] not in ('cajero','administrador'): raise Rejected('Acceso denegado')
    c = connect()
    try:
        c.execute('BEGIN IMMEDIATE')
        sale = c.execute('INSERT INTO sales(user_id,total) VALUES(?,0)',(user['id'],)).lastrowid
        amount = 0
        for pid, qty in items:
            if type(pid) is not int or type(qty) is not int or pid<=0 or qty<=0 or qty>100000:
                raise Rejected('Producto o cantidad inválida')
            row = c.execute('SELECT price FROM products WHERE id=?',(pid,)).fetchone()
            if not row: raise Rejected('Producto inexistente')
            changed = c.execute('UPDATE products SET stock=stock-? WHERE id=? AND stock>=?',(qty,pid,qty))
            if changed.rowcount!=1: raise Rejected('Stock insuficiente: venta rechazada sin modificar existencias')
            amount += total([(row['price'],qty)])
            c.execute('INSERT INTO details(sale_id,product_id,quantity,price) VALUES(?,?,?,?)',(sale,pid,qty,row['price']))
        c.execute('UPDATE sales SET total=? WHERE id=?',(amount,sale))
        c.execute('INSERT INTO audit(user_id,action) VALUES(?,?)',(user['id'],'SALE_CREATED'))
        c.commit()
        return sale, amount
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def e(value): return html.escape(str(value),quote=True)
def money(value): return '$' + format(value,',').replace(',','.')

CSS = '''*{box-sizing:border-box}body{margin:0;background:#f1f4f8;color:#182c3a;font:16px Segoe UI,Arial}header{background:#163b42;color:white;padding:24px 7%}header h1{margin:0 0 5px;font-size:25px}main{max-width:1080px;margin:30px auto;padding:0 22px}nav{display:flex;gap:20px;margin:20px 0}a{color:#126c60}header a{color:white}section{background:white;border:1px solid #d9e1e5;border-radius:10px;padding:25px;margin:20px 0}h2{font-size:23px;margin-top:0}table{width:100%;border-collapse:collapse}th,td{padding:14px;text-align:left;border-bottom:1px solid #e0e6eb}th{background:#edf3f5}input{padding:11px;border:1px solid #a7b7c2;border-radius:5px;font:inherit;max-width:100%}input[type=number]{width:95px}button{background:#176f5d;color:white;border:0;border-radius:5px;padding:12px 20px;font:inherit;cursor:pointer}label{display:block;margin:15px 0}label input{display:block;margin-top:6px}.notice{padding:16px;background:#e3f4ec;border-left:5px solid #178761;margin:18px 0}.error{background:#fff0ee;border-color:#c44333}.muted{color:#566875;font-size:14px}.summary{font-size:23px;font-weight:600;text-align:right;margin:20px 0}.login{max-width:480px;margin:45px auto}.login input{width:100%}footer{font-size:13px;color:#566875;margin:28px 0}@media(max-width:650px){td,th{padding:8px;font-size:14px}main{padding:0 10px}}'''

CSS += '@media(max-width:650px){section{padding:12px}td,th{padding:7px 4px;font-size:12px}input[type=number]{width:52px;padding:7px 3px}nav{gap:12px;font-size:14px}}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def session(self):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: return None
        sid=cookie.get('sid')
        s=SESSIONS.get(sid.value) if sid else None
        if s and time.monotonic()-s['last']<900:
            s['last']=time.monotonic()
            return s
        if sid: SESSIONS.pop(sid.value,None)
        return None
    def page(self, content, user=None, status=200, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers()
        who=f"Sesión: {e(user['name'])} · {e(user['role'])}" if user else 'Acceso al sistema'
        nav='<nav><a href="/">Ventas e inventario</a><a href="/clients">Clientes</a><a href="/admin">Administración</a></nav>' if user else ''
        s=self.session() if user else None
        logout=f'<form action="/logout" method="post">{self.csrf(s)}<button>Cerrar sesión</button></form>' if s else ''
        body=f'<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>El Vecino | Ventas e inventario</title><style>{CSS}</style><header><h1>Minimarket El Vecino</h1>{who}</header><main>{nav}{content}{logout}<footer>Prototipo académico local · Datos ficticios · Ventas en pesos chilenos</footer></main></html>'
        self.wfile.write(body.encode())
    def csrf(self,s):return f'<input type="hidden" name="csrf" value="{s["csrf"]}">' if s else ''
    def login_page(self,msg=''):
        self.page(f'<section class="login"><h2>Iniciar sesión</h2><p>Gestión de ventas e inventario</p>{msg}<form method="post" action="/login"><label>Usuario<input name="name" required autocomplete="username" maxlength="100"></label><label>Contraseña<input name="password" type="password" required autocomplete="current-password" maxlength="200"></label><button>Entrar</button></form></section>')
    def dashboard(self,s,msg='',error=False,status=200):
        with connect() as c:
            products=c.execute('SELECT * FROM products ORDER BY id').fetchall()
            sales=c.execute('SELECT id,total,created FROM sales ORDER BY id DESC LIMIT 5').fetchall()
        rows=''.join(f'<tr><td>{e(p["name"])}</td><td>{money(p["price"])}</td><td>{p["stock"]}</td><td><input aria-label="Cantidad {e(p["name"])}" name="qty_{p["id"]}" type="number" value="0" min="0" max="100000"></td></tr>' for p in products)
        history=''.join(f'<tr><td>#{p["id"]}</td><td>{money(p["total"])}</td><td>{e(p["created"])}</td></tr>' for p in sales)
        notice=f'<div role="status" class="notice {"error" if error else ""}">{e(msg)}</div>' if msg else ''
        self.page(f'{notice}<section><h2>Nueva venta en efectivo</h2><p class="muted">El servidor calcula los precios y confirma venta y stock en una sola transacción.</p><form action="/sale" method="post">{self.csrf(s)}<table><tr><th>Producto</th><th>Precio</th><th>Stock</th><th>Cantidad</th></tr>{rows}</table><p><button>Confirmar venta</button></p></form></section><section><h2>Últimas ventas</h2><table><tr><th>Venta</th><th>Total</th><th>Fecha UTC</th></tr>{history}</table></section>',s['user'],status)
    def do_GET(self):
        s=self.session()
        if not s:return self.login_page()
        if self.path=='/':return self.dashboard(s)
        if self.path=='/clients':
            with connect() as c: clients=c.execute('SELECT name FROM clients ORDER BY id').fetchall()
            rows=''.join(f'<li>{e(r[0])}</li>' for r in clients)
            return self.page(f'<section><h2>Clientes</h2><p>Registro mínimo: solo nombre comercial. Use datos ficticios.</p><ul>{rows}</ul><form method="post" action="/clients">{self.csrf(s)}<label>Nombre<input name="name" required maxlength="100"></label><button>Registrar cliente</button></form></section>',s['user'])
        if self.path=='/admin':
            try:require_admin(s['user'])
            except Rejected as ex:return self.page(f'<section><h2>Acceso denegado</h2><p>{e(ex)}</p></section>',s['user'],403)
            with connect() as c:rows=c.execute('SELECT id,name,price,stock FROM products').fetchall()
            forms=''.join(f'<form method="post" action="/price">{self.csrf(s)}<input type="hidden" name="id" value="{p["id"]}"><label>{e(p["name"])} · Stock {p["stock"]}<input aria-label="Precio {e(p["name"])}" name="price" value="{p["price"]}" type="number" min="1" required></label><button>Actualizar precio</button></form>' for p in rows)
            return self.page(f'<section><h2>Administrar precios</h2>{forms}</section>',s['user'])
        self.page('<section>Recurso no encontrado</section>',s['user'],404)
    def do_POST(self):
        from urllib.parse import parse_qs
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>16384:raise Rejected('Solicitud inválida')
            data={k:v[0] for k,v in parse_qs(self.rfile.read(length).decode(),keep_blank_values=True).items()}
            if self.path=='/login':
                user=login(data.get('name','')[:100],data.get('password','')[:200])
                sid=secrets.token_urlsafe(32)
                SESSIONS[sid]={'user':user,'csrf':secrets.token_urlsafe(32),'last':time.monotonic()}
                self.send_response(303);self.send_header('Location','/');self.send_header('Set-Cookie',f'sid={sid}; HttpOnly; SameSite=Strict; Path=/');self.end_headers();return
            s=self.session()
            if not s:return self.page('<section>Sesión requerida</section>',status=401)
            if not data.get('csrf') or not hmac.compare_digest(data['csrf'],s['csrf']):return self.page('<section>Solicitud no válida: token CSRF ausente o incorrecto</section>',s['user'],403)
            if self.path=='/logout':
                for sid,value in list(SESSIONS.items()):
                    if value is s:SESSIONS.pop(sid,None)
                return self.page('<section>Sesión cerrada. <a href="/">Volver</a></section>',cookie='sid=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict')
            if self.path=='/sale':
                items=[(int(k[4:]),int(v)) for k,v in data.items() if k.startswith('qty_') and v not in ('','0')]
                sid,amount=register_sale(s['user'],items)
                return self.dashboard(s,f'Venta #{sid} confirmada por {money(amount)}. Stock actualizado.')
            if self.path=='/price':
                require_admin(s['user'])
                price=int(data.get('price','0'));pid=int(data.get('id','0'))
                if price<=0 or price>100000000:raise Rejected('Precio inválido')
                with connect() as c:
                    r=c.execute('UPDATE products SET price=? WHERE id=?',(price,pid))
                    if r.rowcount!=1:raise Rejected('Producto inexistente')
                    c.execute('INSERT INTO audit(user_id,action) VALUES(?,?)',(s['user']['id'],'PRICE_UPDATED'))
                return self.dashboard(s,'Precio actualizado')
            if self.path=='/clients':
                name=data.get('name','').strip()
                if not name or len(name)>100:raise Rejected('Nombre inválido')
                with connect() as c:c.execute('INSERT INTO clients(name) VALUES(?)',(name,))
                return self.dashboard(s,'Cliente registrado')
            self.page('<section>Recurso no encontrado</section>',s['user'],404)
        except (Rejected,ValueError) as ex:
            s=self.session()
            if s:return self.dashboard(s,str(ex),True,400)
            return self.login_page(f'<div class="notice error">{e(ex)}</div>')
        except Exception:
            self.page('<section>Error interno. No se confirmó la operación.</section>',status=500)

if __name__=='__main__':
    init_db()
    print('El Vecino: http://127.0.0.1:8765',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
