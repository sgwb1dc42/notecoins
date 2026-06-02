# NoteCoins

NoteCoins es una demo de marketplace web donde los estudiantes pueden comprar y vender apuntes usando un sistema de monedas interno.

## Funcionalidades

- Búsqueda y filtrado de apuntes por asignatura
- Subida y venta de tus propios apuntes
- Cartera con saldo en NoteCoins
- Historial de pedidos y previsualización de apuntes
- Panel de administración

## Ejecución en local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 backend/app.py
```

Abrir en el navegador:

```
http://127.0.0.1:5000
```

## Ejecución con Docker (VS Code Dev Containers)

Abrir el proyecto en VS Code y seleccionar **Reopen in Container**, luego:

```bash
python3 backend/app.py
```

## Estructura del proyecto

```
backend/      Aplicación Flask y datos locales
frontend/     Plantillas Jinja2 y recursos estáticos
```

## Rutas principales

```
/                         Inicio
/shop/search              Búsqueda de apuntes
/shop/offers              Ofertas actuales
/catalog/products/<id>    Detalle de apunte
/account/login            Acceso
/account/profile          Perfil
/orders/                  Lista de pedidos
/orders/<id>              Detalle de pedido
/admin/import-products    Importación (admin)
```
