# Minimarket El Vecino

Prototipo académico local con Python 3.10 o superior y SQLite. No requiere paquetes adicionales. La arquitectura PHP/MySQL del informe original se conserva como alternativa de despliegue; esta entrega implementa Python/SQLite para una demostración reproducible.

## Iniciar

1. Extraer completamente el ZIP.
2. Abrir INICIAR.bat (o ejecutar `python app.py`). Mantener la ventana abierta.
3. Abrir http://127.0.0.1:8765 en el navegador.
4. Cajero: usuario `cajero`, contraseña `CajaDemo!2026`.
5. Administrador: usuario `admin`, contraseña `AdminDemo!2026`.

Si Python no está disponible en PATH, ejecutar con la ruta absoluta a python.exe. En el equipo donde se preparó esta entrega se usó `C:\Users\jorda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.

## Demostración en cinco minutos

- Entrar como cajero y vender 2 bebidas y 1 pan: total $5.000, stocks 22 y 9.
- Intentar vender 5 unidades de arroz cuando hay 2: operación rechazada sin cambios.
- Entrar a Administración como cajero: acceso denegado.
- Cerrar sesión y entrar como admin: actualizar un precio.
- Registrar un cliente ficticio y consultar su nombre.

## Pruebas y evidencias

Ejecutar PROBAR.bat o `python test_app.py`. La suite utiliza bases temporales: no modifica la base de la demostración. Los resultados se guardan en evidencias/resultados.json y resultados.csv. El archivo baseline_inseguro.py contiene ejemplos inseguros aislados para comparar antes/después, no una versión histórica del equipo. No se importa desde app.py.

## Alcance

Ventas en efectivo, catálogo precargado, consulta de stock, cambio de precios por administrador, clientes con nombre mínimo y auditoría. No incluye pago bancario, cuenta corriente, alta/baja de productos ni administración de usuarios desde interfaz. Las credenciales son exclusivas de demostración.

Escucha solo en 127.0.0.1. HTTP local: no se afirma cifrado HTTPS ni cookie Secure. Antes de cualquier uso real requiere servidor de producción, HTTPS, secretos propios, gestión de usuarios, respaldo y restauración verificados, monitoreo y revisión de seguridad. Sesiones y bloqueo de intentos están en memoria y se pierden al reiniciar. No es una certificación ISO ni una auditoría legal.

Para reiniciar datos de demostración, detener la aplicación y renombrar vecino.sqlite3; al iniciar se genera otra base. Conservar una copia si se necesita el historial.
