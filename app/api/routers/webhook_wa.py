import logging
from datetime import date
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Response, Query, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db.models import (
    Movimiento, Categoria, VentaDidan, DetalleVentaDidan,
    MemoriaConcepto, InventarioInsumo, MovimientoInventario
)
from app.nlp.parser import HybridExpenseParser
from app.services.didan_importer import DidanImporter
from app.whatsapp.client import WhatsAppClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["WhatsApp Webhook"])


@router.get("")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token invalido")


@router.post("")
async def receive_whatsapp_message(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored"}

    entry = body.get("entry", [])
    if not entry:
        return {"status": "ok"}

    for e in entry:
        for c in e.get("changes", []):
            value = c.get("value", {})
            for msg in value.get("messages", []):
                from_phone = msg.get("from")
                msg_type = msg.get("type")

                if settings.authorized_phone_list and from_phone not in settings.authorized_phone_list:
                    await WhatsAppClient.send_text_message(
                        from_phone,
                        "Numero no autorizado para registrar movimientos."
                    )
                    continue

                if msg_type == "text":
                    text_body = msg.get("text", {}).get("body", "")
                    await process_incoming_chat_message(from_phone, text_body, db)

                elif msg_type == "document":
                    doc = msg.get("document", {})
                    filename = doc.get("filename", "")
                    await WhatsAppClient.send_text_message(
                        from_phone,
                        f"Archivo {filename} recibido. Procesando..."
                    )

    return {"status": "processed"}


async def process_incoming_chat_message(phone: str, text: str, db: Session) -> Dict[str, Any]:
    text_clean = text.strip()

    # 1. Comprobar confirmacion pendiente
    pending_mov = db.query(Movimiento).filter(
        Movimiento.registrado_por == phone,
        Movimiento.estado == "pendiente",
        Movimiento.necesita_confirmacion == True
    ).order_by(Movimiento.id.desc()).first()

    if pending_mov:
        return await resolve_pending_classification(phone, text_clean, pending_mov, db)

    # 2. Parsear texto con IA / Reglas primero para detectar si es movimiento de inventario
    parsed = HybridExpenseParser.parse_message(text_clean)

    if parsed.tipo in ("inventario_entrada", "inventario_salida") and parsed.cantidad_insumo > 0:
        nombre_buscado = parsed.insumo_nombre or "Cabezas de Res"
        insumo = db.query(InventarioInsumo).filter(
            InventarioInsumo.nombre.ilike(nombre_buscado)
        ).first()

        if not insumo and parsed.unidad_insumo:
            insumo = db.query(InventarioInsumo).filter(
                InventarioInsumo.nombre.ilike(f"%{nombre_buscado.split()[-1]}%"),
                InventarioInsumo.unidad == parsed.unidad_insumo
            ).first()

        if not insumo:
            insumo = db.query(InventarioInsumo).filter(
                InventarioInsumo.nombre.ilike(f"%{nombre_buscado.split()[0]}%")
            ).first()

        if not insumo:
            insumo = InventarioInsumo(
                nombre=nombre_buscado,
                categoria_insumo="carne",
                unidad=parsed.unidad_insumo or "kg",
                stock_actual=0,
                stock_minimo=1
            )
            db.add(insumo)
            db.flush()

        stock_previo = float(insumo.stock_actual)
        if parsed.tipo == "inventario_entrada":
            nuevo_stock = stock_previo + float(parsed.cantidad_insumo)
            tipo_mov_inv = "entrada"
            accion_txt = "Entrada de inventario registrada"
        else:
            nuevo_stock = max(0.0, stock_previo - float(parsed.cantidad_insumo))
            tipo_mov_inv = "salida"
            accion_txt = "Salida de inventario registrada"

        insumo.stock_actual = nuevo_stock
        db.add(MovimientoInventario(
            insumo_id=insumo.id,
            tipo=tipo_mov_inv,
            cantidad=parsed.cantidad_insumo,
            stock_resultante=nuevo_stock,
            motivo=text_clean
        ))
        db.commit()

        msg_inv = (
            f"{accion_txt}: {parsed.cantidad_insumo} {insumo.unidad} de {insumo.nombre} "
            f"(Existencia actual: {round(nuevo_stock, 2)} {insumo.unidad})"
        )
        await WhatsAppClient.send_text_message(phone, msg_inv)
        return {
            "status": "inventory_updated",
            "reply": msg_inv,
            "insumo": insumo.nombre,
            "tipo": tipo_mov_inv,
            "cantidad": parsed.cantidad_insumo,
            "stock_actual": round(nuevo_stock, 2)
        }

    # 3. Consultar memoria de clasificaciones previas
    memoria_match = check_concept_memory(text_clean, db)
    if memoria_match:
        cat = db.query(Categoria).filter(Categoria.id == memoria_match.categoria_id).first()
        cat_nombre = cat.nombre if cat else "Gasto Operativo"

        importe_centavos = parsed.importe_centavos if parsed.importe_centavos > 0 else 0

        mov = Movimiento(
            cuenta_id=1,
            categoria_id=memoria_match.categoria_id,
            tipo=memoria_match.tipo,
            importe_centavos=importe_centavos,
            concepto_original=text_clean,
            proveedor_o_persona=memoria_match.proveedor_o_persona,
            metodo_pago="efectivo",
            registrado_por=phone,
            estado="confirmado"
        )
        db.add(mov)
        memoria_match.veces_utilizado += 1
        db.commit()
        db.refresh(mov)

        msg_resp = (
            f"Gasto registrado automaticamente: ${mov.importe_centavos / 100:,.2f} MXN "
            f"en {cat_nombre} ({memoria_match.proveedor_o_persona}) - Folio #{mov.id}"
        )
        await WhatsAppClient.send_text_message(phone, msg_resp)
        return {"status": "saved_from_memory", "reply": msg_resp, "movimiento_id": mov.id}

    # 4. Si requiere confirmacion
    if parsed.requiere_confirmacion:
        sujeto = parsed.proveedor_o_persona or "este concepto"
        pregunta = (
            f"Registre un gasto de ${parsed.importe_pesos:,.2f} relacionado con {sujeto}. Que tipo de gasto es? "
            f"(1. Nomina, 2. Carne/Verdura, 3. Proveedor/Gas, 4. Retiro personal)"
        )

        mov = Movimiento(
            cuenta_id=1,
            categoria_id=None,
            tipo=parsed.tipo,
            importe_centavos=parsed.importe_centavos,
            concepto_original=parsed.concepto,
            proveedor_o_persona=parsed.proveedor_o_persona,
            metodo_pago=parsed.metodo_pago,
            registrado_por=phone,
            estado="pendiente",
            necesita_confirmacion=True,
            pregunta_pendiente=pregunta
        )
        db.add(mov)
        db.commit()
        db.refresh(mov)

        await WhatsAppClient.send_text_message(phone, pregunta)
        return {"status": "needs_confirmation", "reply": pregunta, "movimiento_id": mov.id, "pregunta": pregunta}

    # 5. Guardar movimiento confirmado
    cat = db.query(Categoria).filter(Categoria.nombre.ilike(f"%{parsed.categoria_sugerida}%")).first()
    cat_id = cat.id if cat else None

    mov = Movimiento(
        cuenta_id=1,
        categoria_id=cat_id,
        tipo=parsed.tipo,
        importe_centavos=parsed.importe_centavos,
        concepto_original=parsed.concepto,
        proveedor_o_persona=parsed.proveedor_o_persona,
        metodo_pago=parsed.metodo_pago,
        registrado_por=phone,
        estado="confirmado"
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)

    if parsed.proveedor_o_persona and cat_id:
        learn_concept(parsed.proveedor_o_persona, cat_id, parsed.tipo, parsed.proveedor_o_persona, db)

    prov_str = f" ({parsed.proveedor_o_persona})" if parsed.proveedor_o_persona else ""
    tipo_label = "Gasto" if parsed.tipo == "gasto" else "Retiro"

    msg_resp = (
        f"{tipo_label} registrado: ${parsed.importe_pesos:,.2f} MXN | "
        f"Categoria: {parsed.categoria_sugerida}{prov_str} | Folio #{mov.id}"
    )
    await WhatsAppClient.send_text_message(phone, msg_resp)
    return {"status": "saved", "reply": msg_resp, "movimiento_id": mov.id, "parsed": parsed.model_dump()}


async def resolve_pending_classification(phone: str, user_answer: str, mov: Movimiento, db: Session) -> Dict[str, Any]:
    answer_lower = user_answer.lower().strip()

    categoria_nombre = "Gastos Generales"
    tipo = "gasto"

    if answer_lower in ["1", "nomina", "nómina", "sueldo", "mesero", "auxiliar", "taquero", "empleado"]:
        categoria_nombre = "Nómina y Pagos a Personal"
        tipo = "nomina"
    elif answer_lower in ["2", "carne", "verdura", "mercancia", "mercancía", "insumo"]:
        categoria_nombre = "Carne e Insumos Principales"
        tipo = "costo_mercancia"
    elif answer_lower in ["3", "proveedor", "gas", "limpieza", "cocina"]:
        categoria_nombre = "Gas y Combustible"
        tipo = "gasto_operativo"
    elif answer_lower in ["4", "retiro", "dueño", "dueña", "casa", "personal"]:
        categoria_nombre = "Retiro de los Propietarios"
        tipo = "retiro"
    else:
        cat_match = db.query(Categoria).filter(Categoria.nombre.ilike(f"%{answer_lower}%")).first()
        if cat_match:
            categoria_nombre = cat_match.nombre
            tipo = cat_match.tipo

    cat = db.query(Categoria).filter(Categoria.nombre.ilike(f"%{categoria_nombre}%")).first()
    cat_id = cat.id if cat else None

    mov.categoria_id = cat_id
    mov.tipo = tipo
    mov.estado = "confirmado"
    mov.necesita_confirmacion = False
    db.commit()
    db.refresh(mov)

    sujeto = mov.proveedor_o_persona or mov.concepto_original
    if sujeto and cat_id:
        learn_concept(sujeto, cat_id, tipo, mov.proveedor_o_persona, db)

    msg_resp = (
        f"Clasificado: ${mov.importe_centavos / 100:,.2f} MXN en {categoria_nombre} - Folio #{mov.id}"
    )
    await WhatsAppClient.send_text_message(phone, msg_resp)
    return {"status": "resolved_and_learned", "reply": msg_resp, "movimiento_id": mov.id, "categoria": categoria_nombre}


import unicodedata


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def check_concept_memory(text: str, db: Session) -> Optional[MemoriaConcepto]:
    text_norm = _strip_accents(text.lower())
    for mem in db.query(MemoriaConcepto).all():
        if _strip_accents(mem.palabra_clave.lower()) in text_norm:
            return mem
    return None


def learn_concept(clave: str, categoria_id: int, tipo: str, persona: Optional[str], db: Session):
    clave_clean = _strip_accents(clave.lower().strip())
    clave_clean = clave_clean.replace("gasto ", "").replace("de ", "").replace("a ", "").strip()
    if not clave_clean or len(clave_clean) < 3:
        return

    mem = db.query(MemoriaConcepto).filter(MemoriaConcepto.palabra_clave == clave_clean).first()
    if not mem:
        mem = MemoriaConcepto(
            palabra_clave=clave_clean,
            categoria_id=categoria_id,
            tipo=tipo,
            proveedor_o_persona=persona or clave.title(),
            veces_utilizado=1
        )
        db.add(mem)
    else:
        mem.categoria_id = categoria_id
        mem.tipo = tipo
        mem.veces_utilizado += 1
    db.commit()


class SimulateMessageRequest(BaseModel):
    phone: str = "5215512345678"
    message: str = "Gasto 200 de Estefanía"


@router.post("/simulate-message", tags=["Simulación"])
async def simulate_message_endpoint(payload: SimulateMessageRequest, db: Session = Depends(get_db)):
    return await process_incoming_chat_message(payload.phone, payload.message, db)


@router.post("/simulate-didan-upload", tags=["Simulación"])
async def simulate_didan_upload_endpoint(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    summary = DidanImporter.parse_any_format(contents, filename=file.filename or "")

    venta = VentaDidan(
        fecha=date.today(),
        total_ventas_centavos=summary.total_sales_centavos,
        total_costo_centavos=summary.total_cost_centavos,
        total_ganancia_centavos=summary.total_profit_centavos,
        unidades_vendidas_total=summary.total_units_sold,
        raw_payload={"items_count": len(summary.items)}
    )
    db.add(venta)
    db.flush()

    for item in summary.items:
        det = DetalleVentaDidan(
            venta_id=venta.id,
            categoria=item.category,
            producto=item.product,
            cantidad=item.quantity,
            precio_unitario_centavos=int(round(item.unit_price_pesos * 100)),
            subtotal_centavos=item.amount_centavos,
            costo_centavos=item.cost_centavos,
            ganancia_centavos=item.profit_centavos
        )
        db.add(det)

    db.commit()
    db.refresh(venta)

    wa_summary_text = DidanImporter.generate_whatsapp_summary(
        summary,
        dashboard_url="http://localhost:8000"
    )

    return {
        "status": "success",
        "venta_id": venta.id,
        "summary": summary.model_dump(exclude={"items"}),
        "whatsapp_preview": wa_summary_text
    }
