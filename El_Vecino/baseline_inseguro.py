"""Ejemplos deliberadamente inseguros, aislados de la aplicación.
Se usan exclusivamente para demostrar defectos y compararlos con app.py.
No corresponden a una versión histórica del equipo.
"""
def authenticate(conn, name, password):
    return conn.execute("SELECT * FROM users WHERE name='" + name + "' AND password='" + password + "'").fetchone()

def verify_password(password, stored):
    return password == stored

def allow_admin(user):
    return True

def sale(conn, pid, qty):
    conn.execute('UPDATE products SET stock=stock-? WHERE id=?',(qty,pid))
    conn.commit()
    raise RuntimeError('Fallo después de descontar stock')
