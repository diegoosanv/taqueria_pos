from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Numeric,
    Boolean, DateTime, Date, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# SQLite solo aplica AUTOINCREMENT automatico sobre columnas INTEGER PRIMARY KEY
PKInt = BigInteger().with_variant(Integer, "sqlite")


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(50), nullable=False)
    tipo = Column(String(30), nullable=False)
    categoria_padre_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    requiere_proveedor = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)

    movimientos = relationship("Movimiento", back_populates="categoria")


class Cuenta(Base):
    __tablename__ = "cuentas"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(50), nullable=False)
    tipo = Column(String(20), nullable=False, default="efectivo")
    saldo_actual_centavos = Column(BigInteger, default=0, nullable=False)
    activo = Column(Boolean, default=True)

    movimientos = relationship("Movimiento", back_populates="cuenta")


class MemoriaConcepto(Base):
    __tablename__ = "memoria_conceptos"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    palabra_clave = Column(String(100), unique=True, index=True, nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    tipo = Column(String(20), nullable=False, default="gasto")
    proveedor_o_persona = Column(String(100), nullable=True)
    veces_utilizado = Column(Integer, default=1)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria = relationship("Categoria")


class Movimiento(Base):
    __tablename__ = "movimientos"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    fecha_hora = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas.id"), nullable=False, default=1)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    tipo = Column(String(20), nullable=False, default="gasto")
    importe_centavos = Column(BigInteger, nullable=False)
    concepto_original = Column(Text, nullable=False)
    proveedor_o_persona = Column(String(100), nullable=True)
    metodo_pago = Column(String(20), nullable=False, default="efectivo")
    registrado_por = Column(String(50), nullable=False)
    estado = Column(String(20), nullable=False, default="confirmado")
    necesita_confirmacion = Column(Boolean, default=False)
    pregunta_pendiente = Column(Text, nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    categoria = relationship("Categoria", back_populates="movimientos")
    cuenta = relationship("Cuenta", back_populates="movimientos")


class VentaDidan(Base):
    __tablename__ = "ventas_didan"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    id_venta_didan = Column(String(100), unique=True, index=True, nullable=True)
    fecha = Column(Date, default=date.today, nullable=False, index=True)
    fecha_hora_importacion = Column(DateTime, default=datetime.utcnow)
    total_ventas_centavos = Column(BigInteger, nullable=False)
    total_costo_centavos = Column(BigInteger, default=0)
    total_ganancia_centavos = Column(BigInteger, default=0)
    unidades_vendidas_total = Column(Numeric(10, 2), default=0)
    metodo_pago = Column(String(20), default="efectivo")
    origen = Column(String(20), default="pos_propio")
    raw_payload = Column(JSON, nullable=True)

    detalles = relationship("DetalleVentaDidan", back_populates="venta", cascade="all, delete-orphan")


class DetalleVentaDidan(Base):
    __tablename__ = "detalle_ventas_didan"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    venta_id = Column(PKInt, ForeignKey("ventas_didan.id"), nullable=False)
    categoria = Column(String(50), nullable=False)
    producto = Column(String(100), nullable=False)
    cantidad = Column(Numeric(10, 2), nullable=False)
    precio_unitario_centavos = Column(BigInteger, nullable=False)
    subtotal_centavos = Column(BigInteger, nullable=False)
    costo_centavos = Column(BigInteger, default=0)
    ganancia_centavos = Column(BigInteger, default=0)

    venta = relationship("VentaDidan", back_populates="detalles")


class ConciliacionCaja(Base):
    __tablename__ = "conciliaciones_caja"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    fecha = Column(Date, default=date.today, nullable=False, index=True)
    turno = Column(String(20), nullable=False, default="dia_completo")
    cuenta_id = Column(Integer, ForeignKey("cuentas.id"), nullable=False, default=1)
    fondo_inicial_centavos = Column(BigInteger, nullable=False, default=0)
    ventas_efectivo_centavos = Column(BigInteger, nullable=False, default=0)
    gastos_efectivo_centavos = Column(BigInteger, nullable=False, default=0)
    retiros_efectivo_centavos = Column(BigInteger, nullable=False, default=0)
    saldo_teorico_centavos = Column(BigInteger, nullable=False)
    saldo_real_contado_centavos = Column(BigInteger, nullable=False)
    diferencia_centavos = Column(BigInteger, nullable=False)
    observaciones = Column(Text, nullable=True)
    cerrado_por = Column(String(50), nullable=False)
    fecha_cierre = Column(DateTime, default=datetime.utcnow)


class UsuarioPOS(Base):
    __tablename__ = "usuarios_pos"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(50), nullable=False)
    rol = Column(String(20), nullable=False)  # admin, auxiliar, cocina
    pin = Column(String(10), nullable=False)
    activo = Column(Boolean, default=True)


class Mesa(Base):
    __tablename__ = "mesas"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(50), nullable=False, unique=True)
    orden = Column(Integer, default=1)
    estado = Column(String(20), default="libre")  # libre, ocupada
    activa = Column(Boolean, default=True)

    ordenes = relationship("OrdenPOS", back_populates="mesa")


class InventarioInsumo(Base):
    __tablename__ = "inventario_insumos"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(80), nullable=False, unique=True)
    categoria_insumo = Column(String(40), nullable=False, default="carne")  # cabeza_pieza, carne, tortilla, bebida
    unidad = Column(String(20), nullable=False, default="pieza")  # pieza, kg
    stock_actual = Column(Numeric(10, 3), nullable=False, default=0)
    stock_minimo = Column(Numeric(10, 3), nullable=False, default=0)
    costo_unitario_centavos = Column(BigInteger, default=0)
    activo = Column(Boolean, default=True)

    productos = relationship("ProductoMenu", back_populates="insumo")
    movimientos = relationship("MovimientoInventario", back_populates="insumo", cascade="all, delete-orphan")


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    insumo_id = Column(Integer, ForeignKey("inventario_insumos.id"), nullable=False)
    tipo = Column(String(20), nullable=False)  # entrada, salida, consumo_venta, merma, ajuste
    cantidad = Column(Numeric(10, 3), nullable=False)
    stock_resultante = Column(Numeric(10, 3), nullable=False)
    motivo = Column(String(200), nullable=True)
    fecha_hora = Column(DateTime, default=datetime.utcnow)

    insumo = relationship("InventarioInsumo", back_populates="movimientos")


class ProductoMenu(Base):
    __tablename__ = "productos_menu"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(80), nullable=False)
    categoria = Column(String(40), nullable=False, default="tacos")  # tacos, bebidas
    precio_centavos = Column(BigInteger, nullable=False)
    costo_centavos = Column(BigInteger, default=0)
    es_taco = Column(Boolean, default=True)
    insumo_id = Column(Integer, ForeignKey("inventario_insumos.id"), nullable=True)
    factor_consumo_insumo = Column(Numeric(10, 4), default=1.0)
    activo = Column(Boolean, default=True)

    insumo = relationship("InventarioInsumo", back_populates="productos")


class OrdenPOS(Base):
    __tablename__ = "ordenes_pos"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    mesa_id = Column(Integer, ForeignKey("mesas.id"), nullable=False)
    mesero = Column(String(50), default="Auxiliar")
    estado = Column(String(20), nullable=False, default="abierta")  # abierta, lista, pagada, cancelada
    estado_cocina = Column(String(20), nullable=False, default="en_cola")  # sin_cocina, en_cola, preparando, terminada
    total_centavos = Column(BigInteger, default=0, nullable=False)
    metodo_pago = Column(String(20), nullable=True)  # efectivo, tarjeta, transferencia
    monto_recibido_centavos = Column(BigInteger, default=0)
    cambio_centavos = Column(BigInteger, default=0)
    notas_generales = Column(String(200), nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, index=True)
    fecha_cierre = Column(DateTime, nullable=True)

    mesa = relationship("Mesa", back_populates="ordenes")
    platos = relationship("OrdenPlato", back_populates="orden", cascade="all, delete-orphan", order_by="OrdenPlato.numero_plato")
    items = relationship("OrdenItem", back_populates="orden", cascade="all, delete-orphan")


class OrdenPlato(Base):
    __tablename__ = "orden_platos"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    orden_id = Column(PKInt, ForeignKey("ordenes_pos.id"), nullable=False)
    numero_plato = Column(Integer, nullable=False, default=1)
    notas = Column(String(150), nullable=True)
    terminado_cocina = Column(Boolean, default=False)

    orden = relationship("OrdenPOS", back_populates="platos")
    items = relationship("OrdenItem", back_populates="plato", cascade="all, delete-orphan")


class OrdenItem(Base):
    __tablename__ = "orden_items"

    id = Column(PKInt, primary_key=True, index=True, autoincrement=True)
    orden_id = Column(PKInt, ForeignKey("ordenes_pos.id"), nullable=False)
    plato_id = Column(PKInt, ForeignKey("orden_platos.id"), nullable=True)
    producto_id = Column(Integer, ForeignKey("productos_menu.id"), nullable=True)
    producto_nombre = Column(String(80), nullable=False)
    categoria = Column(String(40), nullable=False, default="tacos")
    es_taco = Column(Boolean, default=True)
    cantidad = Column(Integer, nullable=False, default=1)
    precio_unitario_centavos = Column(BigInteger, nullable=False)
    subtotal_centavos = Column(BigInteger, nullable=False)
    notas = Column(String(150), nullable=True)

    orden = relationship("OrdenPOS", back_populates="items")
    plato = relationship("OrdenPlato", back_populates="items")
