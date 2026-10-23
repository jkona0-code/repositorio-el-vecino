# Sistema de Gestión de Ventas e Inventario — Minimarket "El Vecino"

## Prototipo Funcional en Python

Este es el prototipo funcional del sistema web de gestión de ventas e inventario
para el Minimarket "El Vecino", Curicó. Implementa los módulos críticos:

- **Autenticación por roles** (RF-01)
- **Gestión de productos e inventario** (RF-02)
- **Registro de ventas con cálculo de importes** (RF-03)
- **Actualización atómica de stock** (RF-04)
- **Gestión de clientes** (RF-05)

### Controles de Seguridad OWASP Top 10 (2021)

| Categoría | Control implementado |
|-----------|---------------------|
| A01 - Control de acceso | Autorización por rol en cada ruta |
| A02 - Fallas criptográficas | Contraseñas con bcrypt, HTTPS-ready |
| A03 - Inyección | Consultas parametrizadas (SQLite) |
| A04 - Diseño inseguro | Transacciones atómicas, validación de negocio |
| A05 - Config. insegura | Cookies seguras, errores genéricos |
| A06 - Componentes vulnerables | Dependencias mínimas y actualizadas |
| A07 - Fallas de autenticación | Regeneración de sesión, política de contraseñas |
| A08 - Integridad de datos | Tokens CSRF en formularios |
| A09 - Registro y monitoreo | Auditoría de operaciones sensibles |
| A10 - SSRF | No se realizan requests a URLs externas |

### Requisitos

```
pip install flask bcrypt
```

### Ejecución

```
python app.py
```

Luego abrir http://127.0.0.1:5000 en el navegador.

### Usuarios de prueba

| Email | Contraseña | Rol |
|-------|-----------|-----|
| admin@minimarket.cl | Admin123! | administrador |
| cajero@minimarket.cl | Cajero123! | cajero |

### Ejecución de pruebas

```
python tests.py
```
