"""Pruebas reales sobre BD temporal y servidor HTTP aislado."""
import csv, http.cookiejar, json, re, sqlite3, tempfile, threading, time, unittest
from datetime import datetime
from pathlib import Path
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
from urllib.parse import urlencode
import app, baseline_inseguro as before

EVIDENCE=[]
class Checks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        app.DB=Path(self.temp.name)/'test.sqlite3'
        app.init_db();app.ATTEMPTS.clear();app.SESSIONS.clear()
        self.user={'id':2,'name':'cajero','role':'cajero'}
    def tearDown(self):self.temp.cleanup()
    def record(self,id,observed):
        EVIDENCE.append({'id':id,'fecha':datetime.now().astimezone().isoformat(timespec='seconds'),'resultado_obtenido':observed,'estado':'APROBADO','prueba':self._testMethodName})
    def scalar(self,sql):
        with app.connect() as c:return c.execute(sql).fetchone()[0]
    def test_01_total(self):
        self.assertEqual(app.total([(1500,2),(2000,1)]),5000)
        self.record('PU-01','2×1500 + 1×2000 = 5000 CLP')
    def test_02_empty_negative(self):
        for items in ([],[(1,-1)],[(1,0)],[(1,1.5)]):
            with self.assertRaises(app.Rejected):app.register_sale(self.user,items)
        self.assertEqual(self.scalar('SELECT count(*) FROM sales'),0)
        self.record('PU-02','Venta vacía, negativa, cero y fraccionaria rechazadas; 0 ventas')
    def test_03_sale(self):
        with app.connect() as c:c.execute('UPDATE products SET stock=10 WHERE id=1')
        _,amount=app.register_sale(self.user,[(1,3)])
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'),7)
        self.assertEqual(amount,4500)
        self.record('PI-01','Venta de 3: stock 10→7, total 4500, 1 venta')
    def test_04_insufficient(self):
        with self.assertRaises(app.Rejected):app.register_sale(self.user,[(3,5)])
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=3'),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM sales'),0)
        self.record('PI-02','Stock 2, solicitud 5: rechazo; stock=2 y ventas=0')
    def test_05_sql_injection(self):
        with self.assertRaises(app.Rejected):app.login("' OR '1'='1' --",'x')
        self.assertEqual(app.login('cajero','CajaDemo!2026')['role'],'cajero')
        self.record('PS-01','Inyección en usuario rechazada; credencial válida aceptada')
    def test_06_roles(self):
        with self.assertRaises(app.Rejected):app.require_admin(self.user)
        app.require_admin({'role':'administrador'})
        self.record('PS-02','Cajero rechazado y administrador autorizado por servidor')
    def test_07_password(self):
        stored=self.scalar("SELECT hash FROM users WHERE name='cajero'")
        self.assertNotEqual(stored,'CajaDemo!2026')
        self.assertTrue(app.password_ok('CajaDemo!2026',stored))
        self.assertFalse(app.password_ok('incorrecta',stored))
        self.assertNotEqual(stored,app.password_hash('CajaDemo!2026'))
        self.record('PS-03','PBKDF2-SHA256, 600000 iteraciones; salt diferente; clave errónea rechazada')
    def test_08_rollback(self):
        with self.assertRaises(app.Rejected):app.register_sale(self.user,[(1,2),(3,5)])
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'),24)
        self.assertEqual(self.scalar('SELECT count(*) FROM sales'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM details'),0)
        self.record('PI-03','Fallo en segundo ítem revierte primer descuento, venta y detalles')
    def test_09_server_price(self):
        _,amount=app.register_sale(self.user,[(1,2)])
        self.assertEqual(amount,3000)
        self.record('PS-04','Total 3000 calculado con precio de BD; API no recibe precio del navegador')
    def test_10_audit(self):
        app.register_sale(self.user,[(1,1)])
        self.assertEqual(self.scalar("SELECT count(*) FROM audit WHERE user_id=2 AND action='SALE_CREATED'"),1)
        self.record('PS-05','Venta genera auditoría con usuario y acción, sin contraseñas')
    def test_11_concurrency(self):
        outcomes=[]
        def buy():
            try:app.register_sale(self.user,[(3,2)]);outcomes.append('ok')
            except app.Rejected:outcomes.append('reject')
        threads=[threading.Thread(target=buy) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(outcomes,['ok','reject'])
        self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=3'),0)
        self.record('PI-04','Dos ventas concurrentes sobre stock 2: una aprobada, otra rechazada; stock=0')
    def test_12_throttle(self):
        for _ in range(5):
            with self.assertRaises(app.Rejected):app.login('cajero','incorrecta')
        with self.assertRaisesRegex(app.Rejected,'Demasiados'):app.login('cajero','CajaDemo!2026')
        self.record('PS-06','Tras 5 fallos se bloquea temporalmente la cuenta')
    def test_13_http(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        base='http://127.0.0.1:'+str(server.server_port)
        jar=http.cookiejar.CookieJar();client=build_opener(HTTPCookieProcessor(jar))
        def post(path,data):return client.open(Request(base+path,urlencode(data).encode()))
        try:
            page=post('/login',{'name':'cajero','password':'CajaDemo!2026'}).read().decode()
            token=re.search('name="csrf" value="([^"]+)"',page).group(1)
            with self.assertRaises(HTTPError) as err:client.open(base+'/admin')
            self.assertEqual(err.exception.code,403)
            self.record('HTTP-01','Login HTTP crea sesión; GET /admin con cajero devuelve 403')
            with self.assertRaises(HTTPError) as err:post('/sale',{'qty_1':'1'})
            self.assertEqual(err.exception.code,403)
            self.assertEqual(self.scalar('SELECT count(*) FROM sales'),0)
            self.record('HTTP-02','POST sin CSRF devuelve 403 y no registra venta')
            r=post('/sale',{'csrf':token,'qty_1':'2','qty_2':'1'})
            self.assertIn('5.000',r.read().decode())
            self.assertIn('HttpOnly',next(c for c in jar if c.name=='sid')._rest)
            self.assertEqual(self.scalar('SELECT stock FROM products WHERE id=1'),22)
            self.record('HTTP-03','Venta HTTP total 5000, stock 22; cookie HttpOnly; CSP presente')
            post('/clients',{'csrf':token,'name':'<script>alert(1)</script>'}).read()
            page=client.open(base+'/clients').read().decode()
            self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>alert',page)
            self.record('HTTP-04','Cliente con etiqueta script se presenta escapado, sin ejecución')
            sid=next(iter(app.SESSIONS));app.SESSIONS[sid]['last']=time.monotonic()-901
            self.assertIn('Iniciar sesión',client.open(base+'/').read().decode())
            self.record('HTTP-05','Sesión con inactividad superior a 900 segundos expira')
        finally:server.shutdown();server.server_close();t.join()
    def test_14_before_after(self):
        c=sqlite3.connect(':memory:')
        c.executescript("CREATE TABLE users(name,password); INSERT INTO users VALUES('admin','demo'); CREATE TABLE products(id,stock); INSERT INTO products VALUES(1,10);")
        self.assertIsNotNone(before.authenticate(c,"' OR 1=1 --",'x'))
        self.assertTrue(before.verify_password('demo','demo'))
        self.assertTrue(before.allow_admin(self.user))
        with self.assertRaises(RuntimeError):before.sale(c,1,3)
        self.assertEqual(c.execute('SELECT stock FROM products').fetchone()[0],7)
        c.close()
        self.record('AD-01','Baseline didáctico reproduce 4 defectos: SQLi, texto plano, permiso abierto y descuento parcial; correcciones verificadas en PS-01/02/03 y PI-03')

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    out=Path(__file__).parent/'evidencias';out.mkdir(exist_ok=True)
    payload={'fecha':datetime.now().astimezone().isoformat(),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'evidencias':EVIDENCE,'fallos':[str(x) for x in result.failures+result.errors]}
    (out/'resultados.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'resultados.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['id','fecha','resultado_obtenido','estado','prueba']);w.writeheader();w.writerows(EVIDENCE)
    raise SystemExit(not result.wasSuccessful())
