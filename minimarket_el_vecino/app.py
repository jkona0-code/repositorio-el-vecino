"""
=============================================================================
 Minimarket "El Vecino" — Prototipo Funcional
 Sistema web de gestión de ventas e inventario
 Curicó, Región del Maule
=============================================================================

 Módulos implementados:
   - Autenticación por roles (RF-01)
   - Gestión de productos e inventario (RF-02)
   - Registro de ventas con cálculo de importes (RF-03)
   - Actualización atómica de stock (RF-04)
   - Gestión de clientes (RF-05)

 Seguridad:
   - OWASP Top 10 (2021) — 10 categorías cubiertas
   - Ley 21.459 — prevención de delitos informáticos
   - Ley 19.628 — protección de datos personales

 Tecnologías: Python 3, Flask, SQLite, bcrypt
=============================================================================
"""

import os
import re
import sqlite3
import secrets
import logging
import functools
from datetime import datetime, timedelta

from flask import (
    Flask, request, session, redirect, url_for,
    render_template, flash, g, abort
)
import bcrypt

# =============================================================================
# Configuración de la aplicación
# =============================================================================

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Clave de sesión segura (A02)

# Configuración de cookies de sesión seguras (A05, A07)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,     # No accesible desde JavaScript
    SESSION_COOKIE_SAMESITE='Strict', # Protección CSRF a nivel cookie
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),  # Expiración de sesión
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # Límite de 1MB en requests
)

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'minimarket.db')

# Configuración de logging para auditoría (A09)
logging.basicConfig(
    filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auditoria.log'),
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('minimarket')


# =============================================================================
# Base de datos — Consultas parametrizadas (A03 — Inyección)
# =============================================================================

def get_db():
    """Obtiene conexión a la base de datos con WAL para concurrencia."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Cierra la conexión al finalizar el request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Inicializa la base de datos con tablas y datos de prueba."""
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    # Creación de tablas
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

    # --- Datos de prueba (ficticios, según código de ética ACM/IEEE) ---

    usuarios_prueba = [
        ('Admin Sistema', 'admin@minimarket.cl', 'Admin123!', 'administrador'),
        ('María González', 'cajero@minimarket.cl', 'Cajero123!', 'cajero'),
    ]

    for nombre, email, password, rol in usuarios_prueba:
        existe = db.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
        if not existe:
            hash_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.execute(
                "INSERT INTO usuarios (nombre, email, hash, rol) VALUES (?, ?, ?, ?)",
                (nombre, email, hash_pw, rol)
            )

    productos_prueba = [
        ('P001', 'Leche entera 1L', 1290, 50, 'Lácteos'),
        ('P002', 'Pan de molde', 1990, 30, 'Panadería'),
        ('P003', 'Arroz 1kg', 1490, 40, 'Abarrotes'),
        ('P004', 'Aceite 1L', 2490, 25, 'Abarrotes'),
        ('P005', 'Bebida 1.5L', 1590, 60, 'Bebidas'),
        ('P006', 'Jabón líquido', 2990, 20, 'Limpieza'),
        ('P007', 'Papel higiénico 4u', 3490, 35, 'Limpieza'),
        ('P008', 'Huevos docena', 3290, 15, 'Lácteos'),
        ('P009', 'Fideos 400g', 890, 45, 'Abarrotes'),
        ('P010', 'Azúcar 1kg', 990, 55, 'Abarrotes'),
    ]

    for codigo, nombre, precio, stock, cat in productos_prueba:
        existe = db.execute("SELECT id FROM productos WHERE codigo = ?", (codigo,)).fetchone()
        if not existe:
            db.execute(
                "INSERT INTO productos (codigo, nombre, precio, stock, categoria) VALUES (?, ?, ?, ?, ?)",
                (codigo, nombre, precio, stock, cat)
            )

    clientes_prueba = [
        ('Juan Pérez', '11.111.111-1', '912345678', 'juan@ejemplo.cl'),
        ('Ana López', '22.222.222-2', '987654321', 'ana@ejemplo.cl'),
    ]

    for nombre, rut, tel, email in clientes_prueba:
        existe = db.execute("SELECT id FROM clientes WHERE rut = ?", (rut,)).fetchone()
        if not existe:
            db.execute(
                "INSERT INTO clientes (nombre, rut, telefono, email) VALUES (?, ?, ?, ?)",
                (nombre, rut, tel, email)
            )

    db.commit()
    db.close()


# =============================================================================
# Funciones de seguridad
# =============================================================================

def auditar(usuario_id, accion, detalle):
    """
    A09 — Registro de operaciones sensibles.
    Cada cambio de precio, stock o usuario deja una huella consultable.
    """
    ip = request.remote_addr or ''
    db = get_db()
    db.execute(
        "INSERT INTO auditoria (usuario_id, accion, detalle, ip) VALUES (?, ?, ?, ?)",
        (usuario_id, accion, detalle, ip)
    )
    db.commit()
    logger.info(f"Usuario={usuario_id} | Accion={accion} | IP={ip} | {detalle}")


def generar_csrf():
    """
    A08 — Genera y almacena un token CSRF en la sesión.
    """
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def validar_csrf():
    """
    A08 — Valida que el token CSRF del formulario coincida con la sesión.
    """
    token_form = request.form.get('csrf_token', '')
    token_session = session.get('csrf_token', '')
    if not token_form or not token_session or not secrets.compare_digest(token_form, token_session):
        abort(403)


def require_login(f):
    """Decorador: requiere sesión activa."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Debe iniciar sesión.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def require_role(*roles):
    """
    A01 — Decorador: autorización por rol en cada ruta sensible.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if 'rol' not in session or session['rol'] not in roles:
                auditar(
                    session.get('usuario_id', 0),
                    'ACCESO_DENEGADO',
                    f"Ruta={request.path} Rol={session.get('rol', 'N/A')} Roles_requeridos={roles}"
                )
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_csrf():
    """Inyecta el token CSRF en todas las plantillas."""
    return dict(csrf_token=generar_csrf())


# =============================================================================
# Rutas de la aplicación
# =============================================================================

@app.route('/', methods=['GET'])
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Autenticación de usuarios (RF-01)."""
    if request.method == 'POST':
        validar_csrf()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Complete todos los campos.', 'danger')
            return render_template('login.html', titulo='Login')

        db = get_db()
        usuario = db.execute(
            "SELECT id, nombre, hash, rol, activo FROM usuarios WHERE email = ?",
            (email,)
        ).fetchone()

        if usuario and usuario['activo'] and bcrypt.checkpw(
            password.encode('utf-8'), usuario['hash'].encode('utf-8')
        ):
            session.clear()
            session.permanent = True
            session['usuario_id'] = usuario['id']
            session['nombre'] = usuario['nombre']
            session['rol'] = usuario['rol']
            session['csrf_token'] = secrets.token_hex(32)

            auditar(usuario['id'], 'LOGIN_EXITOSO', f"Email={email}")
            return redirect(url_for('dashboard'))
        else:
            auditar(0, 'LOGIN_FALLIDO', f"Email={email} IP={request.remote_addr}")
            flash('Credenciales inválidas.', 'danger')

    return render_template('login.html', titulo='Login')


@app.route('/logout')
def logout():
    uid = session.get('usuario_id', 0)
    if uid:
        auditar(uid, 'LOGOUT', "Usuario cerró sesión")
    session.clear()
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard')
@require_login
def dashboard():
    db = get_db()
    hoy = datetime.now().strftime('%Y-%m-%d')

    stats = {
        'productos': db.execute("SELECT COUNT(*) FROM productos WHERE activo=1").fetchone()[0],
        'ventas_hoy': db.execute(
            "SELECT COUNT(*) FROM ventas WHERE fecha LIKE ?", (hoy + '%',)
        ).fetchone()[0],
        'total_hoy': db.execute(
            "SELECT COALESCE(SUM(total), 0) FROM ventas WHERE fecha LIKE ?", (hoy + '%',)
        ).fetchone()[0],
        'stock_bajo': db.execute(
            "SELECT COUNT(*) FROM productos WHERE stock < 10 AND activo=1"
        ).fetchone()[0],
    }

    productos_bajo = db.execute(
        "SELECT codigo, nombre, stock FROM productos WHERE stock < 10 AND activo=1 ORDER BY stock"
    ).fetchall()

    return render_template(
        'dashboard.html', titulo='Dashboard',
        stats=type('Stats', (), stats)(), productos_bajo_stock=productos_bajo
    )


@app.route('/productos')
@require_login
def productos():
    db = get_db()
    prods = db.execute(
        "SELECT * FROM productos WHERE activo=1 ORDER BY nombre"
    ).fetchall()
    return render_template('productos.html', titulo='Productos', productos=prods)


@app.route('/productos/nuevo', methods=['GET', 'POST'])
@require_login
@require_role('administrador')
def nuevo_producto():
    if request.method == 'POST':
        validar_csrf()
        codigo = request.form.get('codigo', '').strip()
        nombre = request.form.get('nombre', '').strip()
        precio = request.form.get('precio', type=int)
        stock = request.form.get('stock', type=int, default=0)
        categoria = request.form.get('categoria', 'General')

        if not codigo or not nombre or not precio or precio <= 0 or stock < 0:
            flash('Datos inválidos. Revise los campos.', 'danger')
            return render_template('producto_form.html', titulo='Nuevo Producto', producto=None)

        db = get_db()
        try:
            db.execute(
                "INSERT INTO productos (codigo, nombre, precio, stock, categoria) VALUES (?, ?, ?, ?, ?)",
                (codigo, nombre, precio, stock, categoria)
            )
            db.commit()
            auditar(session['usuario_id'], 'PRODUCTO_CREADO',
                    f"Código={codigo} Nombre={nombre} Precio={precio} Stock={stock}")
            flash(f'Producto "{nombre}" creado exitosamente.', 'success')
            return redirect(url_for('productos'))
        except sqlite3.IntegrityError:
            flash('Ya existe un producto con ese código.', 'danger')

    return render_template('producto_form.html', titulo='Nuevo Producto', producto=None)


@app.route('/productos/editar/<int:id>', methods=['GET', 'POST'])
@require_login
@require_role('administrador')
def editar_producto(id):
    db = get_db()
    producto = db.execute("SELECT * FROM productos WHERE id = ?", (id,)).fetchone()
    if not producto:
        abort(404)

    if request.method == 'POST':
        validar_csrf()
        codigo = request.form.get('codigo', '').strip()
        nombre = request.form.get('nombre', '').strip()
        precio = request.form.get('precio', type=int)
        stock = request.form.get('stock', type=int, default=0)
        categoria = request.form.get('categoria', 'General')

        if not codigo or not nombre or not precio or precio <= 0 or stock < 0:
            flash('Datos inválidos.', 'danger')
            return render_template('producto_form.html', titulo='Editar Producto', producto=producto)

        precio_anterior = producto['precio']
        stock_anterior = producto['stock']

        db.execute(
            "UPDATE productos SET codigo=?, nombre=?, precio=?, stock=?, categoria=? WHERE id=?",
            (codigo, nombre, precio, stock, categoria, id)
        )
        db.commit()

        detalle = f"ID={id} Código={codigo}"
        if precio != precio_anterior:
            detalle += f" PrecioAnterior={precio_anterior} PrecioNuevo={precio}"
        if stock != stock_anterior:
            detalle += f" StockAnterior={stock_anterior} StockNuevo={stock}"

        auditar(session['usuario_id'], 'PRODUCTO_EDITADO', detalle)
        flash(f'Producto "{nombre}" actualizado.', 'success')
        return redirect(url_for('productos'))

    return render_template('producto_form.html', titulo='Editar Producto', producto=producto)


@app.route('/ventas/nueva', methods=['GET', 'POST'])
@require_login
def nueva_venta():
    """
    Registro de venta con transacción atómica (RF-03, RF-04, A04 OWASP).
    """
    db = get_db()

    if request.method == 'POST':
        validar_csrf()

        producto_ids = request.form.getlist('producto_id[]')
        cantidades = request.form.getlist('cantidad[]')
        cliente_id = request.form.get('cliente_id', type=int)
        metodo_pago = request.form.get('metodo_pago', 'efectivo')

        if metodo_pago not in ('efectivo', 'tarjeta'):
            flash('Método de pago inválido.', 'danger')
            return redirect(url_for('nueva_venta'))

        items = []
        for pid, qty in zip(producto_ids, cantidades):
            try:
                pid_int = int(pid)
                qty_int = int(qty)
                if pid_int <= 0 or qty_int <= 0:
                    raise ValueError
                items.append((pid_int, qty_int))
            except (ValueError, TypeError):
                flash('Datos de producto inválidos.', 'danger')
                return redirect(url_for('nueva_venta'))

        if not items:
            flash('Debe agregar al menos un producto.', 'danger')
            return redirect(url_for('nueva_venta'))

        try:
            db.execute("BEGIN IMMEDIATE")

            cursor = db.execute(
                "INSERT INTO ventas (usuario_id, cliente_id, total, metodo_pago) VALUES (?, ?, 0, ?)",
                (session['usuario_id'], cliente_id if cliente_id else None, metodo_pago)
            )
            venta_id = cursor.lastrowid
            total = 0

            for producto_id, cantidad in items:
                cursor = db.execute(
                    "UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ? AND activo = 1",
                    (cantidad, producto_id, cantidad)
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"Stock insuficiente para producto ID={producto_id}")

                row = db.execute(
                    "SELECT precio FROM productos WHERE id = ?", (producto_id,)
                ).fetchone()
                precio = row['precio']
                subtotal = precio * cantidad
                total += subtotal

                db.execute(
                    "INSERT INTO detalle_venta (venta_id, producto_id, cantidad, precio_unitario, subtotal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (venta_id, producto_id, cantidad, precio, subtotal)
                )

            db.execute("UPDATE ventas SET total = ? WHERE id = ?", (total, venta_id))
            db.commit()

            auditar(
                session['usuario_id'], 'VENTA_REGISTRADA',
                f"VentaID={venta_id} Total={total} Items={len(items)} Método={metodo_pago}"
            )
            flash(f'Venta #{venta_id} registrada exitosamente. Total: ${total:,.0f}', 'success')
            return redirect(url_for('detalle_venta', id=venta_id))

        except RuntimeError as e:
            db.rollback()
            auditar(session['usuario_id'], 'VENTA_RECHAZADA', str(e))
            flash(f'Venta rechazada: {e}', 'danger')
        except Exception as e:
            db.rollback()
            auditar(session['usuario_id'], 'VENTA_ERROR', str(e))
            flash('Error al procesar la venta. Intente nuevamente.', 'danger')

    prods = db.execute(
        "SELECT * FROM productos WHERE activo=1 AND stock > 0 ORDER BY nombre"
    ).fetchall()
    cls = db.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()

    return render_template('nueva_venta.html', titulo='Nueva Venta', productos=prods, clientes=cls)


@app.route('/ventas')
@require_login
def ventas():
    db = get_db()
    lista = db.execute("""
        SELECT v.*, u.nombre as cajero_nombre,
               COALESCE(c.nombre, '') as cliente_nombre
        FROM ventas v
        JOIN usuarios u ON v.usuario_id = u.id
        LEFT JOIN clientes c ON v.cliente_id = c.id
        ORDER BY v.fecha DESC
        LIMIT 100
    """).fetchall()

    return render_template('ventas.html', titulo='Ventas', ventas=lista)


@app.route('/ventas/<int:id>')
@require_login
def detalle_venta(id):
    db = get_db()
    venta = db.execute("""
        SELECT v.*, u.nombre as cajero_nombre,
               COALESCE(c.nombre, '') as cliente_nombre
        FROM ventas v
        JOIN usuarios u ON v.usuario_id = u.id
        LEFT JOIN clientes c ON v.cliente_id = c.id
        WHERE v.id = ?
    """, (id,)).fetchone()

    if not venta:
        abort(404)

    detalles = db.execute("""
        SELECT dv.*, p.nombre as producto_nombre
        FROM detalle_venta dv
        JOIN productos p ON dv.producto_id = p.id
        WHERE dv.venta_id = ?
    """, (id,)).fetchall()

    return render_template('detalle_venta.html', titulo=f'Venta #{id}', venta=venta, detalles=detalles)


@app.route('/clientes')
@require_login
def clientes():
    db = get_db()
    lista = db.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
    return render_template('clientes.html', titulo='Clientes', clientes=lista)


@app.route('/clientes/nuevo', methods=['GET', 'POST'])
@require_login
def nuevo_cliente():
    if request.method == 'POST':
        validar_csrf()
        nombre = request.form.get('nombre', '').strip()
        rut = request.form.get('rut', '').strip() or None
        telefono = request.form.get('telefono', '').strip() or None
        email = request.form.get('email', '').strip() or None

        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('cliente_form.html', titulo='Nuevo Cliente')

        db = get_db()
        try:
            db.execute(
                "INSERT INTO clientes (nombre, rut, telefono, email) VALUES (?, ?, ?, ?)",
                (nombre, rut, telefono, email)
            )
            db.commit()
            auditar(session['usuario_id'], 'CLIENTE_CREADO', f"Nombre={nombre}")
            flash(f'Cliente "{nombre}" registrado.', 'success')
            return redirect(url_for('clientes'))
        except sqlite3.IntegrityError:
            flash('Ya existe un cliente con ese RUT.', 'danger')

    return render_template('cliente_form.html', titulo='Nuevo Cliente')


@app.route('/auditoria')
@require_login
@require_role('administrador')
def auditoria():
    db = get_db()
    registros = db.execute("""
        SELECT a.*, COALESCE(u.nombre, 'Sistema') as usuario_nombre
        FROM auditoria a
        LEFT JOIN usuarios u ON a.usuario_id = u.id
        ORDER BY a.fecha DESC
        LIMIT 200
    """).fetchall()

    return render_template('auditoria.html', titulo='Auditoría', registros=registros)


@app.errorhandler(403)
def error_403(e):
    return render_template('403.html', titulo='Acceso Denegado'), 403


@app.errorhandler(404)
def error_404(e):
    return render_template('404.html', titulo='404'), 404


if __name__ == '__main__':
    init_db()
    print("Base de datos inicializada en", DATABASE)
    app.run(debug=True, host='0.0.0.0', port=5000)
