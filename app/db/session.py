from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings
from app.db.models import (
    Base, Categoria, Cuenta, UsuarioPOS, Mesa,
    InventarioInsumo, ProductoMenu
)

db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _fix_sqlite_bigint_pk_tables():
    if not db_url.startswith("sqlite"):
        return

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='table'")
        ).fetchall()

        broken_tables = [
            name for name, sql_def in rows
            if sql_def and "id BIGINT NOT NULL" in sql_def
        ]

        if not broken_tables:
            return

        # Respaldar filas existentes con id valido antes de recrear con INTEGER PRIMARY KEY
        backed_up = {}
        for tname in broken_tables:
            try:
                res = conn.execute(text(f"SELECT * FROM {tname} WHERE id IS NOT NULL"))
                cols = list(res.keys())
                data = [dict(zip(cols, r)) for r in res.fetchall()]
                backed_up[tname] = data
            except Exception:
                backed_up[tname] = []

        conn.execute(text("PRAGMA foreign_keys = OFF"))
        for tname in broken_tables:
            conn.execute(text(f"DROP TABLE IF EXISTS {tname}"))
        conn.commit()
        conn.execute(text("PRAGMA foreign_keys = ON"))

    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        for tname, records in backed_up.items():
            if not records:
                continue
            cols = list(records[0].keys())
            col_list = ", ".join(cols)
            param_list = ", ".join(f":{c}" for c in cols)
            stmt = text(f"INSERT OR IGNORE INTO {tname} ({col_list}) VALUES ({param_list})")
            for rec in records:
                try:
                    conn.execute(stmt, rec)
                except Exception:
                    pass
        conn.commit()


def _ensure_columns_exist():
    migrations = [
        ("ventas_didan", "metodo_pago", "VARCHAR(20) DEFAULT 'efectivo'"),
        ("ventas_didan", "origen", "VARCHAR(20) DEFAULT 'pos_propio'"),
        ("movimientos", "pregunta_pendiente", "TEXT"),
        ("ordenes_pos", "monto_recibido_centavos", "BIGINT DEFAULT 0"),
        ("ordenes_pos", "cambio_centavos", "BIGINT DEFAULT 0"),
        ("orden_platos", "terminado_cocina", "BOOLEAN DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table_name, col_name, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            except Exception:
                pass


def init_db():
    Base.metadata.create_all(bind=engine)
    _fix_sqlite_bigint_pk_tables()
    _ensure_columns_exist()

    with SessionLocal() as db:
        caja = db.query(Cuenta).filter(Cuenta.id == 1).first()
        if not caja:
            caja = Cuenta(
                id=1,
                nombre="Caja Principal Efectivo",
                tipo="efectivo",
                saldo_actual_centavos=0
            )
            db.add(caja)

        if db.query(Categoria).count() == 0:
            db.add_all([
                Categoria(nombre="Carne e Insumos Principales", tipo="costo_mercancia", requiere_proveedor=True),
                Categoria(nombre="Verduras (Limón, Cilantro, Cebolla)", tipo="costo_mercancia", requiere_proveedor=True),
                Categoria(nombre="Tortillas y Masa", tipo="costo_mercancia", requiere_proveedor=True),
                Categoria(nombre="Bebidas y Refrescos", tipo="costo_mercancia", requiere_proveedor=True),
                Categoria(nombre="Quesos y Lácteos", tipo="costo_mercancia", requiere_proveedor=True),
                Categoria(nombre="Gas y Combustible", tipo="gasto_operativo", requiere_proveedor=True),
                Categoria(nombre="Carbón / Leña", tipo="gasto_operativo", requiere_proveedor=False),
                Categoria(nombre="Desechables y Plásticos", tipo="gasto_operativo", requiere_proveedor=False),
                Categoria(nombre="Limpieza del Local", tipo="gasto_operativo", requiere_proveedor=False),
                Categoria(nombre="Nómina y Pagos a Personal", tipo="nomina", requiere_proveedor=False),
                Categoria(nombre="Servicios (Luz CFE, Agua, Renta)", tipo="servicio", requiere_proveedor=False),
                Categoria(nombre="Retiro de los Propietarios", tipo="retiro_propietario", requiere_proveedor=False),
            ])

        if db.query(UsuarioPOS).count() == 0:
            db.add_all([
                UsuarioPOS(nombre="Administrador", rol="admin", pin="1234"),
                UsuarioPOS(nombre="Auxiliar Turno", rol="auxiliar", pin="1111"),
                UsuarioPOS(nombre="Taquero / Cocina", rol="cocina", pin="2222"),
            ])

        if db.query(Mesa).count() == 0:
            db.add_all([
                Mesa(nombre="Mesa 1", orden=1),
                Mesa(nombre="Mesa 2", orden=2),
                Mesa(nombre="Mesa 3", orden=3),
                Mesa(nombre="Mesa 4", orden=4),
                Mesa(nombre="Mesa 5", orden=5),
                Mesa(nombre="Mesa 6", orden=6),
                Mesa(nombre="Barra", orden=7),
                Mesa(nombre="Para Llevar", orden=8),
            ])

        if db.query(InventarioInsumo).count() == 0:
            ins_cabeza = InventarioInsumo(
                nombre="Cabezas de Res",
                categoria_insumo="cabeza_pieza",
                unidad="pieza",
                stock_actual=3,
                stock_minimo=1,
                costo_unitario_centavos=95000
            )
            ins_carne_cabeza = InventarioInsumo(
                nombre="Carne de Cabeza",
                categoria_insumo="carne",
                unidad="kg",
                stock_actual=15.0,
                stock_minimo=4.0,
                costo_unitario_centavos=17500
            )
            ins_bistec = InventarioInsumo(
                nombre="Carne de Bistec",
                categoria_insumo="carne",
                unidad="kg",
                stock_actual=20.0,
                stock_minimo=5.0,
                costo_unitario_centavos=18500
            )
            ins_normal = InventarioInsumo(
                nombre="Carne Tacos Normales",
                categoria_insumo="carne",
                unidad="kg",
                stock_actual=25.0,
                stock_minimo=6.0,
                costo_unitario_centavos=16000
            )
            ins_especial = InventarioInsumo(
                nombre="Carne Tacos Especiales",
                categoria_insumo="carne",
                unidad="kg",
                stock_actual=15.0,
                stock_minimo=4.0,
                costo_unitario_centavos=21000
            )
            ins_tortilla = InventarioInsumo(
                nombre="Tortilla Taquera",
                categoria_insumo="tortilla",
                unidad="kg",
                stock_actual=30.0,
                stock_minimo=8.0,
                costo_unitario_centavos=2400
            )
            ins_vidrio = InventarioInsumo(
                nombre="Refresco Vidrio",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=48,
                stock_minimo=12,
                costo_unitario_centavos=1300
            )
            ins_chaparrita = InventarioInsumo(
                nombre="Chaparrita",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=36,
                stock_minimo=10,
                costo_unitario_centavos=1100
            )
            ins_coca = InventarioInsumo(
                nombre="COCA 600",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=24,
                stock_minimo=8,
                costo_unitario_centavos=1800
            )
            ins_lata = InventarioInsumo(
                nombre="Refresco Lata",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=24,
                stock_minimo=8,
                costo_unitario_centavos=1600
            )
            ins_agua_nat = InventarioInsumo(
                nombre="Agua Natural",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=20,
                stock_minimo=6,
                costo_unitario_centavos=800
            )
            ins_agua_min = InventarioInsumo(
                nombre="Agua Mineral",
                categoria_insumo="bebida",
                unidad="pieza",
                stock_actual=20,
                stock_minimo=6,
                costo_unitario_centavos=1000
            )

            db.add_all([
                ins_cabeza, ins_carne_cabeza, ins_bistec, ins_normal, ins_especial, ins_tortilla,
                ins_vidrio, ins_chaparrita, ins_coca, ins_lata, ins_agua_nat, ins_agua_min
            ])
            db.flush()

            if db.query(ProductoMenu).count() == 0:
                db.add_all([
                    ProductoMenu(
                        nombre="Cabeza",
                        categoria="tacos",
                        precio_centavos=2600,
                        costo_centavos=1100,
                        es_taco=True,
                        insumo_id=ins_cabeza.id,
                        factor_consumo_insumo=0.02
                    ),
                    ProductoMenu(
                        nombre="Bistec",
                        categoria="tacos",
                        precio_centavos=2600,
                        costo_centavos=1200,
                        es_taco=True,
                        insumo_id=ins_bistec.id,
                        factor_consumo_insumo=0.052
                    ),
                    ProductoMenu(
                        nombre="Normales",
                        categoria="tacos",
                        precio_centavos=2600,
                        costo_centavos=1000,
                        es_taco=True,
                        insumo_id=ins_normal.id,
                        factor_consumo_insumo=0.052
                    ),
                    ProductoMenu(
                        nombre="Especiales",
                        categoria="tacos",
                        precio_centavos=2900,
                        costo_centavos=1300,
                        es_taco=True,
                        insumo_id=ins_especial.id,
                        factor_consumo_insumo=0.055
                    ),
                    ProductoMenu(
                        nombre="Quesadillas",
                        categoria="tacos",
                        precio_centavos=5000,
                        costo_centavos=2200,
                        es_taco=True,
                        insumo_id=ins_especial.id,
                        factor_consumo_insumo=0.06
                    ),
                    ProductoMenu(
                        nombre="Refresco Vidrio",
                        categoria="bebidas",
                        precio_centavos=2500,
                        costo_centavos=1300,
                        es_taco=False,
                        insumo_id=ins_vidrio.id,
                        factor_consumo_insumo=1.0
                    ),
                    ProductoMenu(
                        nombre="Chaparrita",
                        categoria="bebidas",
                        precio_centavos=2000,
                        costo_centavos=1100,
                        es_taco=False,
                        insumo_id=ins_chaparrita.id,
                        factor_consumo_insumo=1.0
                    ),
                    ProductoMenu(
                        nombre="COCA 600",
                        categoria="bebidas",
                        precio_centavos=3000,
                        costo_centavos=1800,
                        es_taco=False,
                        insumo_id=ins_coca.id,
                        factor_consumo_insumo=1.0
                    ),
                    ProductoMenu(
                        nombre="Lata",
                        categoria="bebidas",
                        precio_centavos=3000,
                        costo_centavos=1600,
                        es_taco=False,
                        insumo_id=ins_lata.id,
                        factor_consumo_insumo=1.0
                    ),
                    ProductoMenu(
                        nombre="Agua natural",
                        categoria="bebidas",
                        precio_centavos=1700,
                        costo_centavos=800,
                        es_taco=False,
                        insumo_id=ins_agua_nat.id,
                        factor_consumo_insumo=1.0
                    ),
                    ProductoMenu(
                        nombre="Agua mineral",
                        categoria="bebidas",
                        precio_centavos=2000,
                        costo_centavos=1000,
                        es_taco=False,
                        insumo_id=ins_agua_min.id,
                        factor_consumo_insumo=1.0
                    ),
                ])
        else:
            # Asegurar que tambien exista Carne de Cabeza por kg si la BD ya existia
            existe_carne_cabeza = db.query(InventarioInsumo).filter(
                InventarioInsumo.nombre == "Carne de Cabeza"
            ).first()
            if not existe_carne_cabeza:
                db.add(InventarioInsumo(
                    nombre="Carne de Cabeza",
                    categoria_insumo="carne",
                    unidad="kg",
                    stock_actual=15.0,
                    stock_minimo=4.0,
                    costo_unitario_centavos=17500
                ))

        db.commit()
