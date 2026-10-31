import asyncio
from app.db.session import init_db, SessionLocal
from app.db.models import Movimiento, MemoriaConcepto
from app.api.routers.webhook_wa import process_incoming_chat_message


def test_clarification_and_learning_flow():
    init_db()
    db = SessionLocal()
    test_phone = "5215599999999"

    db.query(Movimiento).filter(Movimiento.registrado_por == test_phone).delete()
    db.query(MemoriaConcepto).filter(MemoriaConcepto.palabra_clave.in_(["estefania", "estefanía"])).delete()
    db.commit()

    # 1. Mensaje ambiguo
    res1 = asyncio.run(process_incoming_chat_message(test_phone, "Gasto 200 de Estefanía", db))
    assert res1["status"] == "needs_confirmation"

    mov_pendiente = db.query(Movimiento).filter(
        Movimiento.registrado_por == test_phone,
        Movimiento.estado == "pendiente"
    ).first()
    assert mov_pendiente is not None
    assert mov_pendiente.importe_centavos == 20000

    # 2. Aclaracion del usuario
    res2 = asyncio.run(process_incoming_chat_message(test_phone, "1", db))
    assert res2["status"] == "resolved_and_learned"

    db.refresh(mov_pendiente)
    assert mov_pendiente.estado == "confirmado"
    assert mov_pendiente.necesita_confirmacion is False

    mem = db.query(MemoriaConcepto).filter(MemoriaConcepto.palabra_clave == "estefania").first()
    assert mem is not None

    # 3. Reconocimiento automatico posterior
    res3 = asyncio.run(process_incoming_chat_message(test_phone, "200 de Estefanía", db))
    assert res3["status"] == "saved_from_memory"

    mov_nuevo = db.query(Movimiento).filter(Movimiento.id == res3["movimiento_id"]).first()
    assert mov_nuevo.estado == "confirmado"
    assert mov_nuevo.importe_centavos == 20000

    db.close()


if __name__ == "__main__":
    test_clarification_and_learning_flow()
