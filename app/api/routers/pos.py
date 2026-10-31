from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import (
    UsuarioPOS, Mesa, InventarioInsumo, MovimientoInventario,
    ProductoMenu, OrdenPOS, OrdenPlato, OrdenItem,
    VentaDidan, DetalleVentaDidan, Movimiento,
    ConciliacionCaja, MemoriaConcepto
)
from app.services.reconciliation import CashReconciliationEngine
from app.services.didan_importer import DidanImporter
from app.analytics.forecast_model import TaqueriaSalesForecaster

router = APIRouter(prefix="/api/pos", tags=["POS & Cocina & Admin"])


class LoginRequest(BaseModel):
    rol: Optional[str] = None
    pin: str


class UsuarioCreate(BaseModel):
    nombre: str
    rol: str  # admin, auxiliar, cocina
    pin: str


class MesaCreate(BaseModel):
    nombre: str
    orden: int = 1


class ProductoCreate(BaseModel):
    nombre: str
    categoria: str = "tacos"
    precio_pesos: float
    costo_pesos: float = 0.0
    es_taco: bool = True
    insumo_id: Optional[int] = None
    factor_consumo_insumo: float = 1.0


class InsumoCreate(BaseModel):
    nombre: str
    categoria_insumo: str = "carne"
    unidad: str = "pieza"
    stock_actual: float = 0.0
    stock_minimo: float = 1.0
    costo_unitario_pesos: float = 0.0


class MovimientoInsumoRequest(BaseModel):
    tipo: str  # entrada, merma, ajuste
    cantidad: float
    motivo: Optional[str] = None


class ItemPedidoInput(BaseModel):
    producto_id: int
    cantidad: int = 1
    notas: Optional[str] = ""


class PlatoPedidoInput(BaseModel):
    numero_plato: int
    notas: Optional[str] = ""
    items: List[ItemPedidoInput]


class CrearOrdenRequest(BaseModel):
    mesa_id: int
    mesero: str = "Mesero"
    notas_generales: Optional[str] = ""
    platos: List[PlatoPedidoInput] = []
    bebidas: List[ItemPedidoInput] = []


class PagarOrdenRequest(BaseModel):
    metodo_pago: str = "efectivo"
    monto_recibido_pesos: Optional[float] = None


class GuardarCorteRequest(BaseModel):
    fondo_inicial_pesos: float = 1000.0
    efectivo_contado_pesos: float
    observaciones: Optional[str] = None


@router.post("/login")
def login_pos(payload: LoginRequest, db: Session = Depends(get_db)):
    query = db.query(UsuarioPOS).filter(
        UsuarioPOS.pin == payload.pin.strip(),
        UsuarioPOS.activo == True
    )
    if payload.rol:
        rol_norm = "auxiliar" if payload.rol == "mesero" else payload.rol
        query = query.filter(UsuarioPOS.rol.in_([rol_norm, "admin"]))

    user = query.first()
    if not user:
        raise HTTPException(status_code=401, detail="PIN incorrecto o usuario no encontrado")

    rol_out = "auxiliar" if user.rol == "mesero" else user.rol
    return {
        "status": "ok",
        "id": user.id,
        "usuario": user.nombre,
        "rol": rol_out
    }


@router.get("/usuarios")
def listar_usuarios(db: Session = Depends(get_db)):
    usuarios = db.query(UsuarioPOS).filter(UsuarioPOS.activo == True).order_by(UsuarioPOS.id.asc()).all()
    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "rol": "auxiliar" if u.rol == "mesero" else u.rol,
            "pin": u.pin
        }
        for u in usuarios
    ]


@router.post("/usuarios")
def crear_usuario(payload: UsuarioCreate, db: Session = Depends(get_db)):
    rol_norm = payload.rol.lower().strip()
    if rol_norm not in ("admin", "auxiliar", "cocina"):
        raise HTTPException(status_code=400, detail="Rol invalido. Usa admin, auxiliar o cocina.")

    nuevo = UsuarioPOS(
        nombre=payload.nombre.strip(),
        rol=rol_norm,
        pin=payload.pin.strip(),
        activo=True
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {
        "id": nuevo.id,
        "nombre": nuevo.nombre,
        "rol": nuevo.rol,
        "pin": nuevo.pin
    }


@router.put("/usuarios/{user_id}")
def actualizar_usuario(user_id: int, payload: UsuarioCreate, db: Session = Depends(get_db)):
    user = db.query(UsuarioPOS).filter(UsuarioPOS.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.nombre = payload.nombre.strip()
    user.rol = payload.rol.lower().strip()
    user.pin = payload.pin.strip()
    db.commit()
    return {"status": "updated", "id": user.id}


@router.delete("/usuarios/{user_id}")
def eliminar_usuario(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UsuarioPOS).filter(UsuarioPOS.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.activo = False
    db.commit()
    return {"status": "deleted"}


@router.get("/mesas")
def listar_mesas(db: Session = Depends(get_db)):
    mesas = db.query(Mesa).filter(Mesa.activa == True).order_by(Mesa.orden.asc(), Mesa.id.asc()).all()
    resultado = []

    for m in mesas:
        orden_activa = db.query(OrdenPOS).filter(
            OrdenPOS.mesa_id == m.id,
            OrdenPOS.estado.in_(["abierta", "lista"])
        ).order_by(OrdenPOS.id.desc()).first()

        resultado.append({
            "id": m.id,
            "nombre": m.nombre,
            "orden": m.orden,
            "estado": "ocupada" if orden_activa else "libre",
            "orden_activa_id": orden_activa.id if orden_activa else None,
            "total_actual_pesos": round(orden_activa.total_centavos / 100.0, 2) if orden_activa else 0.0,
            "estado_cocina": orden_activa.estado_cocina if orden_activa else None
        })

    return resultado


@router.post("/mesas")
def crear_mesa(payload: MesaCreate, db: Session = Depends(get_db)):
    existente = db.query(Mesa).filter(Mesa.nombre.ilike(payload.nombre.strip())).first()
    if existente:
        existente.activa = True
        db.commit()
        return {"id": existente.id, "nombre": existente.nombre}

    nueva = Mesa(nombre=payload.nombre.strip(), orden=payload.orden, estado="libre", activa=True)
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return {"id": nueva.id, "nombre": nueva.nombre}


@router.delete("/mesas/{mesa_id}")
def eliminar_mesa(mesa_id: int, db: Session = Depends(get_db)):
    mesa = db.query(Mesa).filter(Mesa.id == mesa_id).first()
    if not mesa:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")
    mesa.activa = False
    db.commit()
    return {"status": "deleted"}


@router.get("/menu")
def listar_menu(db: Session = Depends(get_db)):
    productos = db.query(ProductoMenu).filter(ProductoMenu.activo == True).order_by(
        ProductoMenu.categoria.asc(), ProductoMenu.id.asc()
    ).all()
    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria,
            "precio_pesos": round(p.precio_centavos / 100.0, 2),
            "precio_centavos": p.precio_centavos,
            "costo_pesos": round(p.costo_centavos / 100.0, 2),
            "es_taco": p.es_taco,
            "insumo_id": p.insumo_id,
            "insumo_nombre": p.insumo.nombre if p.insumo else None,
            "factor_consumo_insumo": float(p.factor_consumo_insumo or 1.0)
        }
        for p in productos
    ]


@router.post("/menu")
def crear_producto_menu(payload: ProductoCreate, db: Session = Depends(get_db)):
    prod = ProductoMenu(
        nombre=payload.nombre.strip(),
        categoria=payload.categoria.lower().strip(),
        precio_centavos=int(round(payload.precio_pesos * 100)),
        costo_centavos=int(round(payload.costo_pesos * 100)),
        es_taco=payload.es_taco,
        insumo_id=payload.insumo_id,
        factor_consumo_insumo=payload.factor_consumo_insumo,
        activo=True
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return {"id": prod.id, "nombre": prod.nombre}


@router.put("/menu/{prod_id}")
def actualizar_producto_menu(prod_id: int, payload: ProductoCreate, db: Session = Depends(get_db)):
    prod = db.query(ProductoMenu).filter(ProductoMenu.id == prod_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    prod.nombre = payload.nombre.strip()
    prod.categoria = payload.categoria.lower().strip()
    prod.precio_centavos = int(round(payload.precio_pesos * 100))
    prod.costo_centavos = int(round(payload.costo_pesos * 100))
    prod.es_taco = payload.es_taco
    prod.insumo_id = payload.insumo_id
    prod.factor_consumo_insumo = payload.factor_consumo_insumo
    db.commit()
    return {"status": "updated", "id": prod.id}


@router.delete("/menu/{prod_id}")
def eliminar_producto_menu(prod_id: int, db: Session = Depends(get_db)):
    prod = db.query(ProductoMenu).filter(ProductoMenu.id == prod_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    prod.activo = False
    db.commit()
    return {"status": "deleted"}


@router.get("/inventario")
def listar_inventario(db: Session = Depends(get_db)):
    insumos = db.query(InventarioInsumo).filter(InventarioInsumo.activo == True).order_by(
        InventarioInsumo.id.asc()
    ).all()
    return [
        {
            "id": i.id,
            "nombre": i.nombre,
            "categoria_insumo": i.categoria_insumo,
            "unidad": i.unidad,
            "stock_actual": round(float(i.stock_actual), 2),
            "stock_minimo": round(float(i.stock_minimo), 2),
            "costo_unitario_pesos": round(i.costo_unitario_centavos / 100.0, 2),
            "bajo_stock": float(i.stock_actual) <= float(i.stock_minimo)
        }
        for i in insumos
    ]


@router.post("/inventario")
def crear_insumo(payload: InsumoCreate, db: Session = Depends(get_db)):
    ins = InventarioInsumo(
        nombre=payload.nombre.strip(),
        categoria_insumo=payload.categoria_insumo,
        unidad=payload.unidad,
        stock_actual=payload.stock_actual,
        stock_minimo=payload.stock_minimo,
        costo_unitario_centavos=int(round(payload.costo_unitario_pesos * 100)),
        activo=True
    )
    db.add(ins)
    db.commit()
    db.refresh(ins)
    return {"id": ins.id, "nombre": ins.nombre}


@router.post("/inventario/{insumo_id}/movimiento")
def registrar_movimiento_inventario(
    insumo_id: int,
    payload: MovimientoInsumoRequest,
    db: Session = Depends(get_db)
):
    ins = db.query(InventarioInsumo).filter(InventarioInsumo.id == insumo_id).first()
    if not ins:
        raise HTTPException(status_code=404, detail="Insumo no encontrado")

    actual = float(ins.stock_actual)
    if payload.tipo == "entrada":
        nuevo_stock = actual + payload.cantidad
    elif payload.tipo in ("merma", "consumo"):
        nuevo_stock = max(0.0, actual - abs(payload.cantidad))
    else:
        nuevo_stock = payload.cantidad

    ins.stock_actual = nuevo_stock
    mov = MovimientoInventario(
        insumo_id=ins.id,
        tipo=payload.tipo,
        cantidad=payload.cantidad,
        stock_resultante=nuevo_stock,
        motivo=payload.motivo or f"Ajuste manual ({payload.tipo})"
    )
    db.add(mov)
    db.commit()
    return {
        "status": "ok",
        "insumo": ins.nombre,
        "stock_actual": round(float(ins.stock_actual), 2),
        "unidad": ins.unidad
    }


def _orden_tiene_tacos_pendientes(orden: OrdenPOS) -> bool:
    for p in orden.platos:
        if not getattr(p, "terminado_cocina", False):
            for it in p.items:
                if it.es_taco and it.cantidad > 0:
                    return True
    return False


def _earliest_pending_plato_id(orden: OrdenPOS) -> int:
    ids = [
        p.id for p in orden.platos
        if not getattr(p, "terminado_cocina", False) and any(it.es_taco for it in p.items)
    ]
    return min(ids) if ids else 999999999


def _sync_kitchen_queue_head(db: Session):
    abiertas = db.query(OrdenPOS).filter(
        OrdenPOS.estado.in_(["abierta", "lista"])
    ).order_by(OrdenPOS.fecha_creacion.asc(), OrdenPOS.id.asc()).all()

    hubo_cambios = False
    for ord_obj in abiertas:
        tiene_pendientes = _orden_tiene_tacos_pendientes(ord_obj)
        if not tiene_pendientes and ord_obj.estado_cocina in ("en_cola", "preparando"):
            ord_obj.estado_cocina = "terminada"
            hubo_cambios = True
        elif tiene_pendientes and ord_obj.estado_cocina == "terminada":
            ord_obj.estado_cocina = "en_cola"
            hubo_cambios = True

    if hubo_cambios:
        db.commit()

    en_prep = db.query(OrdenPOS).filter(
        OrdenPOS.estado.in_(["abierta", "lista"]),
        OrdenPOS.estado_cocina == "preparando"
    ).order_by(OrdenPOS.fecha_creacion.asc(), OrdenPOS.id.asc()).first()

    if not en_prep:
        en_cola_list = db.query(OrdenPOS).filter(
            OrdenPOS.estado.in_(["abierta", "lista"]),
            OrdenPOS.estado_cocina == "en_cola"
        ).all()
        if en_cola_list:
            en_cola_list.sort(key=lambda o: (_earliest_pending_plato_id(o), o.id))
            en_cola_list[0].estado_cocina = "preparando"
            db.commit()


@router.post("/ordenes")
def crear_o_actualizar_orden(payload: CrearOrdenRequest, db: Session = Depends(get_db)):
    mesa = db.query(Mesa).filter(Mesa.id == payload.mesa_id).first()
    if not mesa:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")

    orden = db.query(OrdenPOS).filter(
        OrdenPOS.mesa_id == mesa.id,
        OrdenPOS.estado.in_(["abierta", "lista"])
    ).order_by(OrdenPOS.id.desc()).first()

    es_nueva = False
    if not orden:
        es_nueva = True
        orden = OrdenPOS(
            mesa_id=mesa.id,
            mesero=payload.mesero,
            estado="abierta",
            estado_cocina="terminada",
            total_centavos=0,
            notas_generales=payload.notas_generales
        )
        db.add(orden)
        db.flush()
    else:
        orden.estado = "abierta"

    mesa.estado = "ocupada"

    ultimo_num_plato = 0
    if not es_nueva and orden.platos:
        ultimo_num_plato = max(p.numero_plato for p in orden.platos)

    subtotal_agregado = 0
    tacos_agregados = False

    for idx, p_in in enumerate(payload.platos, start=1):
        items_validos = [it for it in p_in.items if it.cantidad > 0]
        if not items_validos:
            continue

        plato_tacos_list = []
        for item_in in items_validos:
            prod = db.query(ProductoMenu).filter(ProductoMenu.id == item_in.producto_id).first()
            if not prod:
                continue
            if prod.es_taco:
                plato_tacos_list.append((prod, item_in))
            else:
                sub = prod.precio_centavos * item_in.cantidad
                subtotal_agregado += sub
                db.add(OrdenItem(
                    orden_id=orden.id,
                    plato_id=None,
                    producto_id=prod.id,
                    producto_nombre=prod.nombre,
                    categoria=prod.categoria,
                    es_taco=False,
                    cantidad=item_in.cantidad,
                    precio_unitario_centavos=prod.precio_centavos,
                    subtotal_centavos=sub,
                    notas=item_in.notas
                ))

        if plato_tacos_list:
            tacos_agregados = True
            ultimo_num_plato += 1
            num_plato = ultimo_num_plato if not es_nueva else (p_in.numero_plato or ultimo_num_plato)
            plato = OrdenPlato(
                orden_id=orden.id,
                numero_plato=num_plato,
                notas=p_in.notas,
                terminado_cocina=False
            )
            db.add(plato)
            db.flush()

            for prod, item_in in plato_tacos_list:
                sub = prod.precio_centavos * item_in.cantidad
                subtotal_agregado += sub
                db.add(OrdenItem(
                    orden_id=orden.id,
                    plato_id=plato.id,
                    producto_id=prod.id,
                    producto_nombre=prod.nombre,
                    categoria=prod.categoria,
                    es_taco=True,
                    cantidad=item_in.cantidad,
                    precio_unitario_centavos=prod.precio_centavos,
                    subtotal_centavos=sub,
                    notas=item_in.notas
                ))

    for beb_in in payload.bebidas:
        if beb_in.cantidad <= 0:
            continue
        prod = db.query(ProductoMenu).filter(ProductoMenu.id == beb_in.producto_id).first()
        if not prod:
            continue
        sub = prod.precio_centavos * beb_in.cantidad
        subtotal_agregado += sub
        db.add(OrdenItem(
            orden_id=orden.id,
            plato_id=None,
            producto_id=prod.id,
            producto_nombre=prod.nombre,
            categoria=prod.categoria,
            es_taco=False,
            cantidad=beb_in.cantidad,
            precio_unitario_centavos=prod.precio_centavos,
            subtotal_centavos=sub,
            notas=beb_in.notas
        ))

    if tacos_agregados and orden.estado_cocina == "terminada":
        orden.estado_cocina = "en_cola"

    orden.total_centavos = (orden.total_centavos or 0) + subtotal_agregado
    db.commit()
    db.refresh(orden)

    _sync_kitchen_queue_head(db)
    db.refresh(orden)

    return {
        "status": "ok",
        "orden_id": orden.id,
        "mesa": mesa.nombre,
        "estado_cocina": orden.estado_cocina,
        "enviado_a_cocina": tacos_agregados,
        "total_pesos": round(orden.total_centavos / 100.0, 2)
    }


@router.get("/ordenes/{orden_id}")
def detalle_orden(orden_id: int, db: Session = Depends(get_db)):
    orden = db.query(OrdenPOS).filter(OrdenPOS.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    platos_out = []
    for p in orden.platos:
        if not p.items:
            continue
        platos_out.append({
            "id": p.id,
            "numero_plato": p.numero_plato,
            "notas": p.notas,
            "terminado_cocina": bool(getattr(p, "terminado_cocina", False)),
            "items": [
                {
                    "id": it.id,
                    "producto": it.producto_nombre,
                    "cantidad": it.cantidad,
                    "precio_pesos": round(it.precio_unitario_centavos / 100.0, 2),
                    "subtotal_pesos": round(it.subtotal_centavos / 100.0, 2),
                    "notas": it.notas
                }
                for it in p.items
            ]
        })

    bebidas_out = [
        {
            "id": it.id,
            "producto": it.producto_nombre,
            "cantidad": it.cantidad,
            "precio_pesos": round(it.precio_unitario_centavos / 100.0, 2),
            "subtotal_pesos": round(it.subtotal_centavos / 100.0, 2),
            "notas": it.notas
        }
        for it in orden.items if it.plato_id is None or not it.es_taco
    ]

    return {
        "id": orden.id,
        "mesa_id": orden.mesa_id,
        "mesa_nombre": orden.mesa.nombre if orden.mesa else f"Mesa {orden.mesa_id}",
        "mesero": orden.mesero,
        "estado": orden.estado,
        "estado_cocina": orden.estado_cocina,
        "total_pesos": round(orden.total_centavos / 100.0, 2),
        "platos": platos_out,
        "bebidas": bebidas_out
    }


@router.delete("/ordenes/{orden_id}/items/{item_id}")
def eliminar_item_orden_abierta(orden_id: int, item_id: int, db: Session = Depends(get_db)):
    orden = db.query(OrdenPOS).filter(OrdenPOS.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if orden.estado == "pagada":
        raise HTTPException(status_code=400, detail="No se puede modificar una orden ya pagada")

    item = db.query(OrdenItem).filter(
        OrdenItem.id == item_id,
        OrdenItem.orden_id == orden_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado en la orden")

    plato_id = item.plato_id
    db.delete(item)
    db.flush()

    if plato_id:
        plato = db.query(OrdenPlato).filter(OrdenPlato.id == plato_id).first()
        if plato and len(plato.items) == 0:
            db.delete(plato)
            db.flush()

    db.refresh(orden)
    nuevo_total = sum(it.subtotal_centavos for it in orden.items)
    orden.total_centavos = nuevo_total

    if len(orden.items) == 0:
        orden.estado = "cancelada"
        orden.estado_cocina = "terminada"
        if orden.mesa:
            orden.mesa.estado = "libre"

    db.commit()
    _sync_kitchen_queue_head(db)
    return {
        "status": "item_deleted",
        "orden_estado": orden.estado,
        "total_pesos": round(orden.total_centavos / 100.0, 2)
    }


@router.post("/ordenes/{orden_id}/cancelar")
def cancelar_orden_abierta(orden_id: int, db: Session = Depends(get_db)):
    orden = db.query(OrdenPOS).filter(OrdenPOS.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if orden.estado == "pagada":
        raise HTTPException(status_code=400, detail="No se puede cancelar una orden ya pagada")

    orden.estado = "cancelada"
    orden.estado_cocina = "terminada"
    orden.fecha_cierre = datetime.utcnow()
    if orden.mesa:
        orden.mesa.estado = "libre"

    db.commit()
    _sync_kitchen_queue_head(db)
    return {"status": "cancelled", "orden_id": orden.id}


@router.get("/cocina/cola")
def obtener_cola_cocina(db: Session = Depends(get_db)):
    _sync_kitchen_queue_head(db)

    ordenes = db.query(OrdenPOS).filter(
        OrdenPOS.estado.in_(["abierta", "lista"]),
        OrdenPOS.estado_cocina.in_(["preparando", "en_cola"])
    ).all()

    ordenes.sort(key=lambda o: (
        0 if o.estado_cocina == "preparando" else 1,
        _earliest_pending_plato_id(o),
        o.id
    ))

    cola_salida = []

    for ord_obj in ordenes:
        platos_pendientes = [
            p for p in ord_obj.platos
            if not getattr(p, "terminado_cocina", False) and any(it.es_taco for it in p.items)
        ]
        if not platos_pendientes:
            continue

        es_orden_en_turno = (len(cola_salida) == 0)

        total_tacos = 0
        desglose_tacos: Dict[str, int] = {}

        for p in platos_pendientes:
            for it in p.items:
                if it.es_taco:
                    total_tacos += it.cantidad
                    desglose_tacos[it.producto_nombre] = desglose_tacos.get(it.producto_nombre, 0) + it.cantidad

        platos_detalle = []
        if es_orden_en_turno:
            for p in platos_pendientes:
                items_plato = [
                    {
                        "producto": it.producto_nombre,
                        "cantidad": it.cantidad,
                        "notas": it.notas or ""
                    }
                    for it in p.items if it.es_taco
                ]
                if items_plato:
                    platos_detalle.append({
                        "numero_plato": p.numero_plato,
                        "notas": p.notas or "",
                        "resumen_texto": ", ".join(f"{i['cantidad']} de {i['producto']}" for i in items_plato),
                        "items": items_plato
                    })

        cola_salida.append({
            "orden_id": ord_obj.id,
            "posicion_cola": len(cola_salida) + 1,
            "es_orden_en_turno": es_orden_en_turno,
            "modo_vista": "detalle_platos" if es_orden_en_turno else "preview_resumen",
            "mesa": ord_obj.mesa.nombre if ord_obj.mesa else f"Mesa {ord_obj.mesa_id}",
            "mesero": ord_obj.mesero,
            "hora": ord_obj.fecha_creacion.strftime("%H:%M"),
            "cantidad_platos": len(platos_pendientes),
            "platos": platos_detalle,
            "bebidas": {},
            "total_tacos": total_tacos,
            "desglose_tacos": desglose_tacos,
            "resumen_tacos_texto": " | ".join(f"{cant} de {tipo}" for tipo, cant in desglose_tacos.items())
        })

    return {
        "total_ordenes_pendientes": len(cola_salida),
        "orden_en_turno": cola_salida[0] if cola_salida else None,
        "ordenes_en_espera": cola_salida[1:] if len(cola_salida) > 1 else []
    }


@router.post("/cocina/{orden_id}/terminar")
def terminar_orden_cocina(orden_id: int, db: Session = Depends(get_db)):
    orden = db.query(OrdenPOS).filter(OrdenPOS.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    for p in orden.platos:
        p.terminado_cocina = True

    orden.estado_cocina = "terminada"
    orden.estado = "lista"
    db.commit()

    _sync_kitchen_queue_head(db)

    return {"status": "terminada", "orden_id": orden.id}


@router.post("/ordenes/{orden_id}/pagar")
def pagar_y_cerrar_orden(orden_id: int, payload: PagarOrdenRequest, db: Session = Depends(get_db)):
    orden = db.query(OrdenPOS).filter(OrdenPOS.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if orden.estado == "pagada":
        return {"status": "already_paid", "orden_id": orden.id}

    metodo = (payload.metodo_pago or "efectivo").lower().strip()
    if payload.monto_recibido_pesos is not None and payload.monto_recibido_pesos > 0:
        recibido_centavos = int(round(payload.monto_recibido_pesos * 100))
    else:
        recibido_centavos = orden.total_centavos

    if metodo == "efectivo" and recibido_centavos < orden.total_centavos:
        raise HTTPException(
            status_code=400,
            detail=f"El monto recibido (${recibido_centavos/100.0:.2f}) es menor al total (${orden.total_centavos/100.0:.2f})"
        )

    cambio_centavos = max(0, recibido_centavos - orden.total_centavos) if metodo == "efectivo" else 0

    for p in orden.platos:
        p.terminado_cocina = True

    orden.estado = "pagada"
    orden.estado_cocina = "terminada"
    orden.metodo_pago = metodo
    orden.monto_recibido_centavos = recibido_centavos
    orden.cambio_centavos = cambio_centavos
    orden.fecha_cierre = datetime.utcnow()

    if orden.mesa:
        orden.mesa.estado = "libre"

    insumo_tortilla = db.query(InventarioInsumo).filter(
        InventarioInsumo.categoria_insumo == "tortilla"
    ).first()

    total_costo_orden_centavos = 0
    total_unidades = 0

    for item in orden.items:
        total_unidades += item.cantidad
        prod = db.query(ProductoMenu).filter(ProductoMenu.id == item.producto_id).first() if item.producto_id else None
        if prod:
            total_costo_orden_centavos += (prod.costo_centavos or 0) * item.cantidad
            if prod.insumo_id:
                ins = db.query(InventarioInsumo).filter(InventarioInsumo.id == prod.insumo_id).first()
                if ins:
                    consumo = float(item.cantidad) * float(prod.factor_consumo_insumo or 1.0)
                    nuevo_stk = max(0.0, float(ins.stock_actual) - consumo)
                    ins.stock_actual = nuevo_stk
                    db.add(MovimientoInventario(
                        insumo_id=ins.id,
                        tipo="consumo_venta",
                        cantidad=consumo,
                        stock_resultante=nuevo_stk,
                        motivo=f"Orden #{orden.id} ({item.cantidad}x {item.producto_nombre})"
                    ))

        if item.es_taco and insumo_tortilla:
            consumo_tort = round(float(item.cantidad) / 32.0, 3)
            nuevo_stk_t = max(0.0, float(insumo_tortilla.stock_actual) - consumo_tort)
            insumo_tortilla.stock_actual = nuevo_stk_t

    hoy = date.today()
    venta_dia = db.query(VentaDidan).filter(
        VentaDidan.fecha == hoy,
        VentaDidan.origen == "pos_propio"
    ).first()

    ganancia_orden = orden.total_centavos - total_costo_orden_centavos

    if not venta_dia:
        venta_dia = VentaDidan(
            id_venta_didan=f"POS-{hoy.isoformat()}",
            fecha=hoy,
            total_ventas_centavos=orden.total_centavos,
            total_costo_centavos=total_costo_orden_centavos,
            total_ganancia_centavos=ganancia_orden,
            unidades_vendidas_total=total_unidades,
            metodo_pago=metodo,
            origen="pos_propio"
        )
        db.add(venta_dia)
        db.flush()
    else:
        venta_dia.total_ventas_centavos += orden.total_centavos
        venta_dia.total_costo_centavos += total_costo_orden_centavos
        venta_dia.total_ganancia_centavos += ganancia_orden
        venta_dia.unidades_vendidas_total = float(venta_dia.unidades_vendidas_total or 0) + total_unidades

    for item in orden.items:
        det_existente = db.query(DetalleVentaDidan).filter(
            DetalleVentaDidan.venta_id == venta_dia.id,
            DetalleVentaDidan.producto == item.producto_nombre
        ).first()

        if det_existente:
            det_existente.cantidad = float(det_existente.cantidad) + item.cantidad
            det_existente.subtotal_centavos += item.subtotal_centavos
        else:
            db.add(DetalleVentaDidan(
                venta_id=venta_dia.id,
                categoria=item.categoria,
                producto=item.producto_nombre,
                cantidad=item.cantidad,
                precio_unitario_centavos=item.precio_unitario_centavos,
                subtotal_centavos=item.subtotal_centavos,
                costo_centavos=0,
                ganancia_centavos=item.subtotal_centavos
            ))

    db.commit()
    _sync_kitchen_queue_head(db)

    return {
        "status": "paid",
        "orden_id": orden.id,
        "total_pesos": round(orden.total_centavos / 100.0, 2),
        "monto_recibido_pesos": round(recibido_centavos / 100.0, 2),
        "cambio_pesos": round(cambio_centavos / 100.0, 2),
        "metodo_pago": metodo
    }


def _construir_historial_ordenes_dia(db: Session, fecha_target: date) -> List[Dict[str, Any]]:
    ordenes = db.query(OrdenPOS).order_by(OrdenPOS.id.desc()).all()
    salida = []
    for o in ordenes:
        fecha_o = (o.fecha_cierre or o.fecha_creacion).date() if (o.fecha_cierre or o.fecha_creacion) else fecha_target
        if fecha_o != fecha_target:
            continue
        agrupado: Dict[str, int] = {}
        for it in o.items:
            agrupado[it.producto_nombre] = agrupado.get(it.producto_nombre, 0) + it.cantidad
        resumen = ", ".join(f"{c}x {n}" for n, c in agrupado.items())
        salida.append({
            "id": o.id,
            "mesa": o.mesa.nombre if o.mesa else f"Mesa {o.mesa_id}",
            "mesero": o.mesero,
            "estado": o.estado,
            "metodo_pago": o.metodo_pago or "efectivo",
            "total_pesos": round((o.total_centavos or 0) / 100.0, 2),
            "monto_recibido_pesos": round((getattr(o, "monto_recibido_centavos", 0) or o.total_centavos or 0) / 100.0, 2),
            "cambio_pesos": round((getattr(o, "cambio_centavos", 0) or 0) / 100.0, 2),
            "hora": (o.fecha_cierre or o.fecha_creacion).strftime("%H:%M") if (o.fecha_cierre or o.fecha_creacion) else "",
            "resumen_items": resumen
        })
    return salida


@router.get("/ordenes-historial-dia")
def listar_historial_dia(db: Session = Depends(get_db)):
    hoy = date.today()
    return _construir_historial_ordenes_dia(db, hoy)


@router.get("/admin/analytics")
def obtener_estadisticas_admin(
    fondo_inicial_pesos: float = 1000.0,
    efectivo_contado_pesos: Optional[float] = None,
    factor_simulacion: float = 1.0,
    db: Session = Depends(get_db)
):
    hoy = date.today()

    ventas_hoy = db.query(VentaDidan).filter(VentaDidan.fecha == hoy).all()
    ventas_totales_centavos = sum(v.total_ventas_centavos for v in ventas_hoy)
    ventas_totales_pesos = round(ventas_totales_centavos / 100.0, 2)

    ordenes_pagadas_hoy = [
        o for o in db.query(OrdenPOS).filter(OrdenPOS.estado == "pagada").all()
        if ((o.fecha_cierre or o.fecha_creacion).date() if (o.fecha_cierre or o.fecha_creacion) else hoy) == hoy
    ]
    efectivo_pos_centavos = sum(
        o.total_centavos for o in ordenes_pagadas_hoy
        if (o.metodo_pago or "efectivo") == "efectivo"
    )
    tarjeta_pos_centavos = sum(
        o.total_centavos for o in ordenes_pagadas_hoy
        if (o.metodo_pago or "") == "tarjeta"
    )
    transferencia_pos_centavos = sum(
        o.total_centavos for o in ordenes_pagadas_hoy
        if (o.metodo_pago or "") == "transferencia"
    )
    importadas_centavos = sum(
        v.total_ventas_centavos for v in ventas_hoy if v.origen != "pos_propio"
    )
    ventas_efectivo_centavos = efectivo_pos_centavos + importadas_centavos

    movimientos = db.query(Movimiento).filter(Movimiento.estado == "confirmado").all()
    gastos_centavos = sum(
        m.importe_centavos for m in movimientos
        if m.tipo in ("gasto", "costo_mercancia", "nomina", "gasto_operativo")
    )
    retiros_centavos = sum(m.importe_centavos for m in movimientos if m.tipo == "retiro")

    fondo_centavos = int(round(fondo_inicial_pesos * 100))
    teorico_default_centavos = fondo_centavos + ventas_efectivo_centavos - gastos_centavos - retiros_centavos
    real_centavos = int(round(efectivo_contado_pesos * 100)) if efectivo_contado_pesos is not None else teorico_default_centavos

    reconciliacion = CashReconciliationEngine.calculate_shift_reconciliation(
        fondo_inicial_centavos=fondo_centavos,
        ventas_efectivo_centavos=ventas_efectivo_centavos,
        gastos_efectivo_centavos=gastos_centavos,
        retiros_efectivo_centavos=retiros_centavos,
        saldo_real_contado_centavos=real_centavos
    )

    detalles_hoy = []
    for v in ventas_hoy:
        for d in v.detalles:
            detalles_hoy.append({
                "producto": d.producto,
                "categoria": d.categoria,
                "unidades": float(d.cantidad),
                "total_pesos": round(d.subtotal_centavos / 100.0, 2)
            })

    todas_ventas = db.query(VentaDidan).order_by(VentaDidan.fecha.asc()).all()
    agrupado_por_fecha: Dict[date, float] = {}
    for v in todas_ventas:
        agrupado_por_fecha[v.fecha] = agrupado_por_fecha.get(v.fecha, 0.0) + (v.total_ventas_centavos / 100.0)

    if len(agrupado_por_fecha) >= 5:
        df_hist = pd.DataFrame([
            {"fecha": f, "ventas_pesos": monto} for f, monto in agrupado_por_fecha.items()
        ])
    else:
        fechas_base = [hoy - timedelta(days=i) for i in range(30, 0, -1)]
        filas_base = []
        for idx_f, f in enumerate(fechas_base):
            dow = f.weekday()
            base_v = 10500.0 if dow in (4, 5, 6) else 4800.0
            if f.day in (14, 15, 16, 29, 30, 31):
                base_v *= 1.22
            filas_base.append({"fecha": f, "ventas_pesos": base_v + ((idx_f % 5) * 180.0)})
        if ventas_totales_pesos > 0:
            filas_base.append({"fecha": hoy, "ventas_pesos": ventas_totales_pesos})
        df_hist = pd.DataFrame(filas_base)

    forecaster = TaqueriaSalesForecaster()
    pronostico_base = forecaster.predict_next_days(df_hist, days_ahead=7)

    factor = max(0.3, min(2.5, float(factor_simulacion or 1.0)))
    pronostico_7d = []
    for p in pronostico_base:
        venta_sim = round(p["pronostico_pesos_p50"] * factor, 2)
        p10_sim = round(p["escenario_pesimista_p10"] * factor, 2)
        p90_sim = round(p["escenario_optimista_p90"] * factor, 2)
        tacos_sim = int(round(p["tacos_estimados"] * factor))
        carne_sim = round(p["kilos_carne_sugeridos"] * factor, 1)
        tortilla_sim = round(p["kilos_tortillas_sugeridos"] * factor, 1)
        cabezas_sim = round(carne_sim / 4.5, 1)
        pronostico_7d.append({
            **p,
            "pronostico_pesos_p50": venta_sim,
            "escenario_pesimista_p10": p10_sim,
            "escenario_optimista_p90": p90_sim,
            "tacos_estimados": tacos_sim,
            "kilos_carne_sugeridos": carne_sim,
            "kilos_tortillas_sugeridos": tortilla_sim,
            "cabezas_res_sugeridas": cabezas_sim
        })

    venta_7d_pesos = round(sum(p["pronostico_pesos_p50"] for p in pronostico_7d), 2)
    venta_finde_pesos = round(
        sum(p["pronostico_pesos_p50"] for p in pronostico_7d if p.get("es_fin_de_semana")),
        2
    )
    carne_7d_kg = round(sum(p["kilos_carne_sugeridos"] for p in pronostico_7d), 1)
    tortilla_7d_kg = round(sum(p["kilos_tortillas_sugeridos"] for p in pronostico_7d), 1)
    cabezas_7d_piezas = round(carne_7d_kg / 4.5, 1)

    cortes_previos = db.query(ConciliacionCaja).order_by(ConciliacionCaja.id.asc()).all()
    if cortes_previos:
        historial_dif = [c.diferencia_centavos for c in cortes_previos[-10:]]
        if efectivo_contado_pesos is not None:
            historial_dif.append(reconciliacion.diferencia_centavos)
    else:
        historial_dif = [-1200, -1800, 0, -2500, reconciliacion.diferencia_centavos]

    cusum_info = CashReconciliationEngine.calculate_cusum_drift(historial_dif)

    memorias = db.query(MemoriaConcepto).order_by(
        MemoriaConcepto.veces_utilizado.desc(), MemoriaConcepto.id.desc()
    ).limit(20).all()

    return {
        "fecha": hoy.isoformat(),
        "ventas_totales_pesos": ventas_totales_pesos,
        "ventas_efectivo_pesos": round(ventas_efectivo_centavos / 100.0, 2),
        "ventas_tarjeta_pesos": round(tarjeta_pos_centavos / 100.0, 2),
        "ventas_transferencia_pesos": round(transferencia_pos_centavos / 100.0, 2),
        "gastos_pesos": round(gastos_centavos / 100.0, 2),
        "retiros_pesos": round(retiros_centavos / 100.0, 2),
        "reconciliacion": {
            "saldo_teorico_pesos": reconciliacion.saldo_teorico_pesos,
            "saldo_real_pesos": reconciliacion.saldo_real_pesos,
            "diferencia_pesos": reconciliacion.diferencia_pesos,
            "estado_cuadre": reconciliacion.estado_cuadre,
            "alerta_severidad": reconciliacion.alerta_severidad
        },
        "cusum": cusum_info,
        "historial_cortes": [
            {
                "id": c.id,
                "fecha": c.fecha.isoformat(),
                "saldo_teorico_pesos": round(c.saldo_teorico_centavos / 100.0, 2),
                "saldo_real_pesos": round(c.saldo_real_contado_centavos / 100.0, 2),
                "diferencia_pesos": round(c.diferencia_centavos / 100.0, 2),
                "estado": (
                    "exacto" if abs(c.diferencia_centavos) <= 2000
                    else ("faltante" if c.diferencia_centavos < 0 else "sobrante")
                ),
                "observaciones": c.observaciones or ""
            }
            for c in reversed(cortes_previos[-10:])
        ],
        "productos_vendidos_hoy": detalles_hoy,
        "historial_ordenes_hoy": _construir_historial_ordenes_dia(db, hoy),
        "ultimos_gastos_whatsapp": [
            {
                "id": m.id,
                "concepto": m.concepto_original,
                "importe_pesos": round(m.importe_centavos / 100.0, 2),
                "tipo": m.tipo,
                "proveedor": m.proveedor_o_persona or "",
                "fecha": m.fecha_hora.strftime("%Y-%m-%d %H:%M")
            }
            for m in sorted(movimientos, key=lambda x: x.id, reverse=True)[:15]
        ],
        "memoria_aprendida": [
            {
                "id": mem.id,
                "palabra_clave": mem.palabra_clave,
                "tipo_asignado": mem.categoria.nombre if mem.categoria else mem.tipo,
                "proveedor": mem.proveedor_o_persona or "",
                "frecuencia_uso": mem.veces_utilizado
            }
            for mem in memorias
        ],
        "factor_simulacion": factor,
        "resumen_pronostico": {
            "venta_7d_pesos": venta_7d_pesos,
            "venta_finde_pesos": venta_finde_pesos,
            "carne_7d_kg": carne_7d_kg,
            "tortilla_7d_kg": tortilla_7d_kg,
            "cabezas_7d_piezas": cabezas_7d_piezas
        },
        "pronostico_7_dias": pronostico_7d
    }


@router.post("/admin/guardar-corte")
def guardar_corte_caja(payload: GuardarCorteRequest, db: Session = Depends(get_db)):
    hoy = date.today()
    ventas_hoy = db.query(VentaDidan).filter(VentaDidan.fecha == hoy).all()
    ordenes_pagadas_hoy = [
        o for o in db.query(OrdenPOS).filter(OrdenPOS.estado == "pagada").all()
        if ((o.fecha_cierre or o.fecha_creacion).date() if (o.fecha_cierre or o.fecha_creacion) else hoy) == hoy
    ]
    efectivo_pos_centavos = sum(
        o.total_centavos for o in ordenes_pagadas_hoy
        if (o.metodo_pago or "efectivo") == "efectivo"
    )
    importadas_centavos = sum(
        v.total_ventas_centavos for v in ventas_hoy if v.origen != "pos_propio"
    )
    ventas_efectivo_centavos = efectivo_pos_centavos + importadas_centavos

    movimientos = db.query(Movimiento).filter(Movimiento.estado == "confirmado").all()
    gastos_centavos = sum(
        m.importe_centavos for m in movimientos
        if m.tipo in ("gasto", "costo_mercancia", "nomina", "gasto_operativo")
    )
    retiros_centavos = sum(m.importe_centavos for m in movimientos if m.tipo == "retiro")

    fondo_centavos = int(round(payload.fondo_inicial_pesos * 100))
    real_centavos = int(round(payload.efectivo_contado_pesos * 100))

    reconciliacion = CashReconciliationEngine.calculate_shift_reconciliation(
        fondo_inicial_centavos=fondo_centavos,
        ventas_efectivo_centavos=ventas_efectivo_centavos,
        gastos_efectivo_centavos=gastos_centavos,
        retiros_efectivo_centavos=retiros_centavos,
        saldo_real_contado_centavos=real_centavos
    )

    corte = ConciliacionCaja(
        fecha=hoy,
        turno="dia_completo",
        cuenta_id=1,
        fondo_inicial_centavos=fondo_centavos,
        ventas_efectivo_centavos=ventas_efectivo_centavos,
        gastos_efectivo_centavos=gastos_centavos,
        retiros_efectivo_centavos=retiros_centavos,
        saldo_teorico_centavos=reconciliacion.saldo_teorico_centavos,
        saldo_real_contado_centavos=reconciliacion.saldo_real_contado_centavos,
        diferencia_centavos=reconciliacion.diferencia_centavos,
        observaciones=payload.observaciones,
        cerrado_por="Administración"
    )
    db.add(corte)
    db.commit()
    db.refresh(corte)

    return {
        "status": "saved",
        "corte_id": corte.id,
        "diferencia_pesos": reconciliacion.diferencia_pesos,
        "estado_cuadre": reconciliacion.estado_cuadre
    }


@router.post("/admin/import-history")
async def importar_historico_didan(
    file: UploadFile = File(...),
    fecha_reporte: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    contents = await file.read()
    try:
        summary = DidanImporter.parse_any_format(contents, filename=file.filename or "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al procesar archivo ({file.filename}): {e}")

    fecha_obj = date.fromisoformat(fecha_reporte) if fecha_reporte else date.today()

    venta = VentaDidan(
        fecha=fecha_obj,
        total_ventas_centavos=summary.total_sales_centavos,
        total_costo_centavos=summary.total_cost_centavos,
        total_ganancia_centavos=summary.total_profit_centavos,
        unidades_vendidas_total=summary.total_units_sold,
        origen="importacion_didan",
        raw_payload={"filename": file.filename, "items_count": len(summary.items)}
    )
    db.add(venta)
    db.flush()

    for item in summary.items:
        db.add(DetalleVentaDidan(
            venta_id=venta.id,
            categoria=item.category,
            producto=item.product,
            cantidad=item.quantity,
            precio_unitario_centavos=int(round(item.unit_price_pesos * 100)),
            subtotal_centavos=item.amount_centavos,
            costo_centavos=item.cost_centavos,
            ganancia_centavos=item.profit_centavos
        ))

    db.commit()
    return {
        "status": "imported",
        "archivo": file.filename,
        "fecha": fecha_obj.isoformat(),
        "total_ventas_pesos": summary.total_sales_pesos,
        "unidades_totales": summary.total_units_sold,
        "productos_importados": len(summary.items)
    }
