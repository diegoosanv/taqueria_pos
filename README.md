# Sistema POS Taquería

Aplicación web y punto de venta para operación de taquería con interfaz para auxiliar de piso, pantalla de cocina en tiempo real y panel administrativo con control de inventario, conciliación de caja y modelos de pronóstico.

## Características principales

- **Auxiliar (Toma de pedidos y cobro):**
  - Estado de mesas en tiempo real (disponibles y ocupadas con saldo acumulado).
  - Captura de órdenes dividida por platos (`Plato 1`, `Plato 2`, etc.) con notas rápidas de preparación.
  - Envío exclusivo de tacos y alimentos a la cola de cocina; las bebidas se registran directamente en la cuenta de la mesa.
  - Cuentas abiertas que permiten agregar rondas adicionales o quitar productos antes de cerrar.
  - Cobro en efectivo (con cálculo automático de cambio), tarjeta o transferencia, e historial de cuentas del día.

- **Cocina (Pantalla de preparación):**
  - La orden en turno (`#1`) muestra el desglose completo por plato y el conteo total de tacos por especialidad.
  - Las órdenes en espera (`#2`, `#3`, ...) muestran únicamente el resumen total de tacos para preparar insumos sin saturar la pantalla hasta que avancen al turno principal.

- **Administración:**
  - Corte de caja en tiempo real desglosado por método de pago y monitoreo de diferencias acumuladas (CUSUM) para detectar fugas de efectivo.
  - Registro de gastos y movimientos de inventario mediante lenguaje natural (web o webhook de WhatsApp) con memoria de conceptos y proveedores frecuentes.
  - Simulador de demanda y pronóstico a 7 días con estimación de ventas, kilos de carne, kilos de tortilla y piezas de cabeza de res.
  - Control de inventario por pieza y por kilogramo, edición de menú y precios, administración de usuarios por rol e importación de reportes históricos (`.html`, `.json`, `.csv`).

## Instalación y ejecución local

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.server
```

El servidor queda disponible en `http://localhost:8000` (o en la IP local del equipo en el puerto `8000` para conectar teléfonos y tablets en la misma red).

## Pruebas

```bash
PYTHONPATH=. ./venv/bin/pytest
```
