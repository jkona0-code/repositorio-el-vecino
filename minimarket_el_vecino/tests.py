import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
"""
=============================================================================
 Minimarket "El Vecino" — Suite de Pruebas Ejecutables
 Pruebas unitarias, de integración y de seguridad
=============================================================================

 Criterio 3.1.5: Testing, ISO y corrección
 - PU-01: Cálculo correcto del total de venta
 - PU-02: Rechazo de ventas vacías y cantidades inválidas
 - PI-01: Venta exitosa descuenta stock correctamente
 - PI-02: Venta rechazada cuando stock es insuficiente
 - PS-01: Inyección SQL no altera la consulta
 - PS-02: Control de acceso por rol

 Mapeo ISO/IEC 27002:2022:
 - A.8.28 — Codificación segura → PS-01
 - A.5.15 — Control de acceso → PS-02
 - A.8.5  — Autenticación segura → PS-03
 - A.8.26 — Requisitos de seguridad → PI-01, PI-02
=============================================================================
"""

import unittest
import sqlite3
import os
import sys
import tempfile
import json

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, init_db, DATABASE


class BaseTestCase(unittest.TestCase):
    """Clase base con configuración común para todas las pruebas."""

    def setUp(self):
        """
        Prepara un entorno de pruebas aislado con base de datos temporal.
        Se utiliza un entorno separado para no afectar datos reales.
        """
        # Usar base de datos temporal para pruebas
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')

        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        # Sobrescribir DATABASE temporalmente
        import app as app_module
        self.original_db = app_module.DATABASE
        app_module.DATABASE = self.db_path

        # Inicializar base de datos de pruebas
        init_db_test(self.db_path)

        self.app = app
        self.client = app.test_client()

    def tearDown(self):
        """Limpia el entorno de pruebas."""
        import app as app_module
        app_module.DATABASE = self.original_db
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def login(self, email, password):
        """Helper: inicia sesión con credenciales."""
        # Primero obtener el CSRF token
        response = self.client.get('/login')
        # Extraer csrf_token de la respuesta
        csrf_token = self._extract_csrf(response.data.decode())

        return self.client.post('/login', data={
            'email': email,
            'password': password,
            'csrf_token': csrf_token
        }, follow_redirects=True)

    def login_admin(self):
        """Helper: inicia sesión como administrador."""
        return self.login('admin@minimarket.cl', 'Admin123!')

    def login_cajero(self):
        """Helper: inicia sesión como cajero."""
        return self.login('cajero@minimarket.cl', 'Cajero123!')

    def _extract_csrf(self, html):
        """Extrae el token CSRF del HTML."""
        import re
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if match:
            return match.group(1)
        return ''


def init_db_test(db_path):
    """Inicializa la base de datos de pruebas con datos controlados."""
    import bcrypt
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    db.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL,
            rol TEXT NOT NULL CHECK(rol IN ('administrador', 'cajero')),
            activo INTEGER NOT NULL DEFAULT 1,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            precio INTEGER NOT NULL CHECK(precio > 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
            categoria TEXT DEFAULT 'General',
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            rut TEXT UNIQUE,
            telefono TEXT,
            email TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            cliente_id INTEGER,
            total INTEGER NOT NULL DEFAULT 0,
            metodo_pago TEXT NOT NULL DEFAULT 'efectivo'
                CHECK(metodo_pago IN ('efectivo', 'tarjeta')),
            fecha TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS detalle_venta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL CHECK(cantidad > 0),
            precio_unitario INTEGER NOT NULL CHECK(precio_unitario > 0),
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id),
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        );

        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            accion TEXT NOT NULL,
            detalle TEXT,
            ip TEXT,
            fecha TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Usuarios de prueba
    usuarios = [
        ('Admin Sistema', 'admin@minimarket.cl', 'Admin123!', 'administrador'),
        ('María González', 'cajero@minimarket.cl', 'Cajero123!', 'cajero'),
    ]
    for nombre, email, password, rol in usuarios:
        hash_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        db.execute(
            "INSERT INTO usuarios (nombre, email, hash, rol) VALUES (?, ?, ?, ?)",
            (nombre, email, hash_pw, rol)
        )

    # Productos de prueba con stock conocido para las pruebas
    productos = [
        ('T001', 'Producto A', 1500, 20, 'General'),   # id=1
        ('T002', 'Producto B', 2000, 10, 'General'),   # id=2
        ('T003', 'Producto C', 3000, 2, 'General'),    # id=3, stock bajo
        ('T004', 'Producto D', 500, 0, 'General'),     # id=4, sin stock
    ]
    for codigo, nombre, precio, stock, cat in productos:
        db.execute(
            "INSERT INTO productos (codigo, nombre, precio, stock, categoria) VALUES (?, ?, ?, ?, ?)",
            (codigo, nombre, precio, stock, cat)
        )

    db.commit()
    db.close()


# =========================================================================
# PRUEBAS UNITARIAS (PU)
# =========================================================================

class TestPU01_CalculoTotal(BaseTestCase):
    """
    PU-01 · Unitaria
    Ejecutar cálculo con 2 productos a $1.500 y 1 producto a $2.000.
    Resultado esperado: Subtotal $5.000 y total $5.000.

    ISO/IEC 27002: A.8.26 — Requisitos de seguridad de las aplicaciones.
    """

    def test_calculo_total_dos_productos(self):
        """
        PROCEDIMIENTO:
        - Login como cajero
        - Registrar venta con 2 unidades de Producto A ($1.500) y
          1 unidad de Producto B ($2.000)
        - Verificar que el total sea $5.000

        DATOS: Producto A (id=1, $1.500) x 2 + Producto B (id=2, $2.000) x 1
        ESPERADO: Total = (1500 * 2) + (2000 * 1) = $5.000
        """
        self.login_cajero()

        # Obtener CSRF token del formulario de venta
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        # Registrar venta: 2x Producto A + 1x Producto B
        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': ['1', '2'],
            'cantidad[]': ['2', '1'],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        # Verificar en la base de datos
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        db.row_factory = sqlite3.Row

        venta = db.execute("SELECT * FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(venta, "Debe existir una venta registrada")
        self.assertEqual(venta['total'], 5000,
                         f"Total esperado $5.000, obtenido ${venta['total']}")

        # Verificar detalles
        detalles = db.execute(
            "SELECT * FROM detalle_venta WHERE venta_id = ? ORDER BY producto_id",
            (venta['id'],)
        ).fetchall()

        self.assertEqual(len(detalles), 2, "Deben haber 2 líneas de detalle")

        # Detalle 1: Producto A, 2 uds, $1.500 c/u, subtotal $3.000
        self.assertEqual(detalles[0]['cantidad'], 2)
        self.assertEqual(detalles[0]['precio_unitario'], 1500)
        self.assertEqual(detalles[0]['subtotal'], 3000)

        # Detalle 2: Producto B, 1 ud, $2.000 c/u, subtotal $2.000
        self.assertEqual(detalles[1]['cantidad'], 1)
        self.assertEqual(detalles[1]['precio_unitario'], 2000)
        self.assertEqual(detalles[1]['subtotal'], 2000)

        db.close()
        print("  [OK] PU-01: Total calculado correctamente = $5.000")


class TestPU02_VentasInvalidas(BaseTestCase):
    """
    PU-02 · Unitaria
    Probar una venta sin productos y luego una cantidad negativa.
    Resultado esperado: No se confirma venta vacía; cantidades inválidas rechazadas.

    ISO/IEC 27002: A.8.26 — Requisitos de seguridad de las aplicaciones.
    """

    def test_venta_sin_productos(self):
        """
        PROCEDIMIENTO: Intentar registrar venta sin seleccionar productos.
        ESPERADO: Venta rechazada con mensaje de error.
        """
        self.login_cajero()
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': [],
            'cantidad[]': [],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        # Verificar que no se creó ninguna venta
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        count = db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        self.assertEqual(count, 0, "No debe crearse una venta vacía")
        db.close()
        print("  [OK] PU-02a: Venta sin productos rechazada correctamente")

    def test_cantidad_negativa(self):
        """
        PROCEDIMIENTO: Intentar registrar venta con cantidad negativa.
        ESPERADO: Venta rechazada; no se modifica stock ni ventas.
        """
        self.login_cajero()
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': ['1'],
            'cantidad[]': ['-5'],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        # Verificar que no se creó venta
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        count = db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        self.assertEqual(count, 0, "No debe crearse una venta con cantidad negativa")

        # Verificar que el stock no cambió
        stock = db.execute("SELECT stock FROM productos WHERE id = 1").fetchone()[0]
        self.assertEqual(stock, 20, "El stock no debe modificarse")
        db.close()
        print("  [OK] PU-02b: Cantidad negativa rechazada correctamente")


# =========================================================================
# PRUEBAS DE INTEGRACIÓN (PI)
# =========================================================================

class TestPI01_VentaExitosa(BaseTestCase):
    """
    PI-01 · Integración
    Con stock inicial de 20 unidades, vender 3 unidades; consultar stock.
    Resultado esperado: Se guarda la venta y el stock queda en 17 unidades.

    Regla crítica del informe (sección 2.2):
    Si un producto tiene 20 unidades y se venden 3, el resultado debe ser 17.

    ISO/IEC 27002: A.8.26 — Requisitos de seguridad de las aplicaciones.
                   A.8.29 — Pruebas de seguridad.
    """

    def test_venta_descuenta_stock(self):
        """
        PROCEDIMIENTO:
        1. Verificar stock inicial de Producto A = 20
        2. Registrar venta de 3 unidades
        3. Verificar que stock = 17
        4. Verificar que la venta fue registrada con total correcto

        DATOS: Producto A (id=1, precio=$1.500, stock=20)
        ESPERADO: Stock final = 17, Total venta = $4.500
        """
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)

        # 1. Verificar stock inicial
        stock_antes = db.execute("SELECT stock FROM productos WHERE id = 1").fetchone()[0]
        self.assertEqual(stock_antes, 20, "Stock inicial debe ser 20")
        db.close()

        # 2. Login y registrar venta
        self.login_cajero()
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': ['1'],
            'cantidad[]': ['3'],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        # 3. Verificar stock después
        db = sqlite3.connect(app_module.DATABASE)
        stock_despues = db.execute("SELECT stock FROM productos WHERE id = 1").fetchone()[0]
        self.assertEqual(stock_despues, 17,
                         f"Stock esperado 17, obtenido {stock_despues}")

        # 4. Verificar venta registrada
        venta = db.execute("SELECT * FROM ventas ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(venta)
        # Total: 3 x $1.500 = $4.500
        self.assertEqual(venta[3], 4500,  # columna total
                         f"Total esperado $4.500, obtenido ${venta[3]}")
        db.close()
        print("  [OK] PI-01: Venta exitosa → stock 20 - 3 = 17 [OK] | Total $4.500 [OK]")


class TestPI02_StockInsuficiente(BaseTestCase):
    """
    PI-02 · Integración
    Intentar vender 5 unidades cuando solo hay 2 disponibles.
    Resultado esperado: Operación rechazada; venta y stock sin cambios.

    ISO/IEC 27002: A.8.26 — Requisitos de seguridad de las aplicaciones.
    """

    def test_venta_rechazada_stock_insuficiente(self):
        """
        PROCEDIMIENTO:
        1. Verificar stock de Producto C = 2
        2. Intentar vender 5 unidades
        3. Verificar que no se creó venta
        4. Verificar que stock sigue en 2

        DATOS: Producto C (id=3, precio=$3.000, stock=2)
        ESPERADO: Venta rechazada, stock = 2 (sin cambios)
        """
        import app as app_module

        self.login_cajero()
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': ['3'],
            'cantidad[]': ['5'],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        # Verificar que la venta fue rechazada
        html = response.data.decode()
        self.assertIn('rechazada', html.lower(),
                      "Debe mostrarse mensaje de rechazo")

        # Verificar en BD
        db = sqlite3.connect(app_module.DATABASE)
        ventas = db.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        self.assertEqual(ventas, 0, "No debe existir ninguna venta")

        stock = db.execute("SELECT stock FROM productos WHERE id = 3").fetchone()[0]
        self.assertEqual(stock, 2,
                         f"Stock debe permanecer en 2, obtenido {stock}")
        db.close()
        print("  [OK] PI-02: Venta con stock insuficiente rechazada [OK] | Stock sin cambios [OK]")


# =========================================================================
# PRUEBAS DE SEGURIDAD (PS)
# =========================================================================

class TestPS01_InyeccionSQL(BaseTestCase):
    """
    PS-01 · Seguridad
    Ingresar una cadena SQL maliciosa en el login.
    Resultado esperado: Acceso denegado; la consulta no interpreta la entrada como SQL.

    OWASP: A03:2021 — Inyección
    ISO/IEC 27002: A.8.28 — Codificación segura.

    ANTES (código vulnerable):
        $query = "SELECT * FROM usuarios WHERE email = '" . $email . "'";

    DESPUÉS (código corregido — implementado en el prototipo):
        stmt = db.execute("SELECT ... WHERE email = ?", (email,))
    """

    def test_sqli_en_login(self):
        """
        PROCEDIMIENTO:
        1. Intentar login con payload SQL injection clásico
        2. Verificar que el acceso es denegado
        3. Verificar que no se inició sesión

        DATOS: email = "' OR '1'='1" , password = "' OR '1'='1"
        ESPERADO: Acceso denegado, sin sesión activa
        """
        resp = self.client.get('/login')
        csrf = self._extract_csrf(resp.data.decode())

        # Intento de SQL Injection clásico
        response = self.client.post('/login', data={
            'email': "' OR '1'='1",
            'password': "' OR '1'='1",
            'csrf_token': csrf
        }, follow_redirects=True)

        html = response.data.decode()
        # No debe haber acceso al dashboard
        self.assertNotIn('Panel de Control', html,
                         "SQL Injection no debe dar acceso al sistema")
        self.assertIn('inválidas', html.lower(),
                      "Debe mostrar mensaje de credenciales inválidas")
        print("  [OK] PS-01a: SQL Injection en login bloqueado [OK]")

    def test_sqli_union_attack(self):
        """
        PROCEDIMIENTO: Intentar UNION-based SQL injection.
        DATOS: email = "admin@minimarket.cl' UNION SELECT 1,2,3,4,5,6,7--"
        ESPERADO: Acceso denegado
        """
        resp = self.client.get('/login')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/login', data={
            'email': "admin@minimarket.cl' UNION SELECT 1,2,3,4,5,6,7--",
            'password': "cualquiera",
            'csrf_token': csrf
        }, follow_redirects=True)

        html = response.data.decode()
        self.assertNotIn('Panel de Control', html)
        print("  [OK] PS-01b: UNION-based SQL Injection bloqueado [OK]")

    def test_sqli_en_producto(self):
        """
        PROCEDIMIENTO: Intentar inyección en parámetro de producto.
        DATOS: producto_id = "1; DROP TABLE productos;--"
        ESPERADO: Datos de producto inválidos; tabla productos intacta.
        """
        self.login_cajero()
        resp = self.client.get('/ventas/nueva')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/ventas/nueva', data={
            'csrf_token': csrf,
            'producto_id[]': ['1; DROP TABLE productos;--'],
            'cantidad[]': ['1'],
            'metodo_pago': 'efectivo',
            'cliente_id': ''
        }, follow_redirects=True)

        # Verificar que la tabla productos sigue existiendo
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        try:
            count = db.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
            self.assertGreater(count, 0, "La tabla productos debe seguir intacta")
            print("  [OK] PS-01c: SQL Injection en parámetro producto bloqueado [OK]")
        finally:
            db.close()


class TestPS02_ControlAccesoPorRol(BaseTestCase):
    """
    PS-02 · Seguridad
    Intentar acceder a una ruta administrativa con una sesión de cajero.
    Resultado esperado: Respuesta HTTP 403 (acceso denegado).

    OWASP: A01:2021 — Pérdida de control de acceso
    ISO/IEC 27002: A.5.15 — Control de acceso.
                   A.8.3  — Restricción de acceso a la información.
    """

    def test_cajero_no_accede_a_admin(self):
        """
        PROCEDIMIENTO:
        1. Login como cajero
        2. Intentar acceder a /productos/nuevo (solo administrador)
        3. Verificar respuesta 403

        DATOS: Sesión de cajero
        ESPERADO: HTTP 403 — Acceso denegado
        """
        self.login_cajero()
        response = self.client.get('/productos/nuevo')
        self.assertEqual(response.status_code, 403,
                         f"Esperado 403, obtenido {response.status_code}")
        print("  [OK] PS-02a: Cajero bloqueado de ruta /productos/nuevo [OK]")

    def test_cajero_no_edita_producto(self):
        """
        PROCEDIMIENTO: Cajero intenta editar un producto.
        ESPERADO: HTTP 403
        """
        self.login_cajero()
        response = self.client.get('/productos/editar/1')
        self.assertEqual(response.status_code, 403)
        print("  [OK] PS-02b: Cajero bloqueado de editar productos [OK]")

    def test_cajero_no_ve_auditoria(self):
        """
        PROCEDIMIENTO: Cajero intenta ver el registro de auditoría.
        ESPERADO: HTTP 403
        """
        self.login_cajero()
        response = self.client.get('/auditoria')
        self.assertEqual(response.status_code, 403)
        print("  [OK] PS-02c: Cajero bloqueado de auditoría [OK]")

    def test_admin_accede_a_todo(self):
        """
        PROCEDIMIENTO: Admin accede a rutas privilegiadas.
        ESPERADO: HTTP 200
        """
        self.login_admin()
        for ruta in ['/productos/nuevo', '/auditoria']:
            response = self.client.get(ruta)
            self.assertEqual(response.status_code, 200,
                             f"Admin debe acceder a {ruta}")
        print("  [OK] PS-02d: Administrador accede a rutas privilegiadas [OK]")

    def test_usuario_no_autenticado(self):
        """
        PROCEDIMIENTO: Acceder a rutas protegidas sin sesión.
        ESPERADO: Redirección a login (HTTP 302)
        """
        for ruta in ['/dashboard', '/productos', '/ventas/nueva', '/ventas']:
            response = self.client.get(ruta)
            self.assertEqual(response.status_code, 302,
                             f"Sin sesión, {ruta} debe redirigir a login")
        print("  [OK] PS-02e: Rutas protegidas redirigen a login sin sesión [OK]")


class TestPS03_Autenticacion(BaseTestCase):
    """
    PS-03 · Seguridad
    Verificar política de contraseñas y almacenamiento seguro.

    OWASP: A07:2021 — Fallas de identificación y autenticación
    ISO/IEC 27002: A.8.5 — Autenticación segura.
                   A.8.24 — Uso de criptografía.
    """

    def test_password_no_almacenado_en_texto_plano(self):
        """
        PROCEDIMIENTO: Verificar que las contraseñas están hasheadas con bcrypt.
        ESPERADO: El campo hash NO contiene la contraseña en texto plano.
        """
        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        users = db.execute("SELECT email, hash FROM usuarios").fetchall()

        for email, hash_val in users:
            # bcrypt hashes empiezan con $2b$ o $2a$
            self.assertTrue(
                hash_val.startswith('$2b$') or hash_val.startswith('$2a$'),
                f"Hash de {email} debe ser bcrypt, no texto plano"
            )
            # La contraseña original NO debe aparecer en el hash
            self.assertNotIn('Admin123!', hash_val)
            self.assertNotIn('Cajero123!', hash_val)
        db.close()
        print("  [OK] PS-03a: Contraseñas almacenadas con bcrypt [OK]")

    def test_login_credenciales_incorrectas(self):
        """
        PROCEDIMIENTO: Login con contraseña incorrecta.
        ESPERADO: Mensaje genérico (no revela si el email existe).
        """
        resp = self.client.get('/login')
        csrf = self._extract_csrf(resp.data.decode())

        response = self.client.post('/login', data={
            'email': 'admin@minimarket.cl',
            'password': 'contraseña_incorrecta',
            'csrf_token': csrf
        }, follow_redirects=True)

        html = response.data.decode()
        self.assertIn('inválidas', html.lower())
        # No debe revelar si el email existe
        self.assertNotIn('email no encontrado', html.lower())
        self.assertNotIn('usuario no existe', html.lower())
        print("  [OK] PS-03b: Mensaje genérico en login fallido [OK]")

    def test_login_exitoso(self):
        """
        PROCEDIMIENTO: Login con credenciales correctas.
        ESPERADO: Acceso al dashboard.
        """
        response = self.login_admin()
        html = response.data.decode()
        self.assertIn('Panel de Control', html,
                      "Login exitoso debe mostrar el dashboard")
        print("  [OK] PS-03c: Login exitoso con credenciales correctas [OK]")


class TestPS04_CSRF(BaseTestCase):
    """
    PS-04 · Seguridad
    Verificar protección CSRF en formularios.

    OWASP: A08:2021 — Fallas en la integridad del software y los datos
    """

    def test_formulario_sin_csrf_rechazado(self):
        """
        PROCEDIMIENTO: Enviar formulario de login sin token CSRF.
        ESPERADO: HTTP 403 — Solicitud no válida.
        """
        response = self.client.post('/login', data={
            'email': 'admin@minimarket.cl',
            'password': 'Admin123!',
            'csrf_token': 'token_invalido'
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 403,
                         "Formulario sin CSRF válido debe ser rechazado")
        print("  [OK] PS-04: Protección CSRF activa [OK]")


class TestPS05_Auditoria(BaseTestCase):
    """
    PS-05 · Seguridad
    Verificar que las operaciones sensibles quedan registradas.

    OWASP: A09:2021 — Fallas en el registro y monitoreo de seguridad
    ISO/IEC 27002: A.8.15 — Registro de eventos.
    """

    def test_login_fallido_registrado(self):
        """
        PROCEDIMIENTO: Intentar login fallido y verificar auditoría.
        ESPERADO: Registro en tabla auditoria con acción LOGIN_FALLIDO.
        """
        resp = self.client.get('/login')
        csrf = self._extract_csrf(resp.data.decode())

        self.client.post('/login', data={
            'email': 'hacker@evil.com',
            'password': 'intento_malicioso',
            'csrf_token': csrf
        })

        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        registro = db.execute(
            "SELECT * FROM auditoria WHERE accion = 'LOGIN_FALLIDO' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        self.assertIsNotNone(registro, "Login fallido debe quedar en auditoría")
        db.close()
        print("  [OK] PS-05a: Login fallido registrado en auditoría [OK]")

    def test_login_exitoso_registrado(self):
        """
        PROCEDIMIENTO: Login exitoso y verificar auditoría.
        ESPERADO: Registro con acción LOGIN_EXITOSO.
        """
        self.login_admin()

        import app as app_module
        db = sqlite3.connect(app_module.DATABASE)
        registro = db.execute(
            "SELECT * FROM auditoria WHERE accion = 'LOGIN_EXITOSO' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        self.assertIsNotNone(registro, "Login exitoso debe quedar en auditoría")
        db.close()
        print("  [OK] PS-05b: Login exitoso registrado en auditoría [OK]")


# =========================================================================
# Ejecución
# =========================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("  Minimarket 'El Vecino' — Suite de Pruebas")
    print("  Criterio 3.1.5: Testing, ISO 27001/27002 y corrección")
    print("=" * 70)
    print()
    print("  Ejecutando pruebas unitarias, de integración y de seguridad...")
    print()

    # Ejecutar con verbosidad
    unittest.main(verbosity=2, exit=True)
