from app.db.session import init_db, SessionLocal
from app.db.models import OrdenPOS, OrdenPlato, OrdenItem, ProductoMenu, InventarioInsumo
from app.services.didan_importer import DidanImporter
from app.nlp.parser import TaqueriaNLPParser
from app.api.routers.pos import (
    CrearOrdenRequest, PlatoPedidoInput, ItemPedidoInput,
    PagarOrdenRequest, crear_o_actualizar_orden,
    obtener_cola_cocina, terminar_orden_cocina,
    pagar_y_cerrar_orden, obtener_estadisticas_admin,
    listar_historial_dia
)


def test_html_historical_import():
    html_path = "/home/diego/taqueria/sample_data/didan_sales_sample.html"
    with open(html_path, "r", encoding="utf-8") as f:
        html_raw = f.read()

    summary = DidanImporter.parse_any_format(html_raw, filename="didan_sales_sample.html")
    assert summary.total_sales_pesos == 7539.0
    assert summary.total_units_sold == 283.0


def test_nlp_inventory_movements():
    salida = TaqueriaNLPParser.parse("se fueron 5 kg de cabeza")
    assert salida.tipo == "inventario_salida"
    assert salida.cantidad_insumo == 5.0
    assert salida.unidad_insumo == "kg"
    assert "Cabeza" in (salida.insumo_nombre or "")
    assert salida.requiere_confirmacion is False

    entrada = TaqueriaNLPParser.parse("entraron 3 cabezas")
    assert entrada.tipo == "inventario_entrada"
    assert entrada.cantidad_insumo == 3.0
    assert entrada.unidad_insumo == "pieza"
    assert "Cabeza" in (entrada.insumo_nombre or "")
    assert entrada.requiere_confirmacion is False


def test_pos_orders_kitchen_queue_and_inventory():
    init_db()
    db = SessionLocal()

    db.query(OrdenItem).delete()
    db.query(OrdenPlato).delete()
    db.query(OrdenPOS).delete()
    db.commit()

    prod_cabeza = db.query(ProductoMenu).filter(ProductoMenu.nombre == "Cabeza").first()
    prod_bistec = db.query(ProductoMenu).filter(ProductoMenu.nombre == "Bistec").first()
    prod_normal = db.query(ProductoMenu).filter(ProductoMenu.nombre == "Normales").first()
    prod_coca = db.query(ProductoMenu).filter(ProductoMenu.nombre == "COCA 600").first()

    ins_cabeza = db.query(InventarioInsumo).filter(InventarioInsumo.nombre == "Cabezas de Res").first()
    stock_inicial_cabeza = float(ins_cabeza.stock_actual)

    # 0. Orden solo de refrescos en Mesa 3 -> NO debe enviarse a Cocina
    req_bebidas = CrearOrdenRequest(
        mesa_id=3,
        mesero="Auxiliar",
        platos=[],
        bebidas=[ItemPedidoInput(producto_id=prod_coca.id, cantidad=2)]
    )
    res_beb = crear_o_actualizar_orden(req_bebidas, db)
    assert res_beb["enviado_a_cocina"] is False
    assert res_beb["estado_cocina"] == "terminada"
    cola_vacia = obtener_cola_cocina(db)
    assert cola_vacia["total_ordenes_pendientes"] == 0

    # 1. Crear Orden #1 en Mesa 1 (Plato 1: 2 Cabeza, 2 Bistec | Plato 2: 3 Normales + 1 Coca)
    req1 = CrearOrdenRequest(
        mesa_id=1,
        mesero="Auxiliar",
        platos=[
            PlatoPedidoInput(
                numero_plato=1,
                notas="Con todo",
                items=[
                    ItemPedidoInput(producto_id=prod_cabeza.id, cantidad=2),
                    ItemPedidoInput(producto_id=prod_bistec.id, cantidad=2),
                ]
            ),
            PlatoPedidoInput(
                numero_plato=2,
                notas="Sin cebolla",
                items=[
                    ItemPedidoInput(producto_id=prod_normal.id, cantidad=3),
                ]
            )
        ],
        bebidas=[
            ItemPedidoInput(producto_id=prod_coca.id, cantidad=1)
        ]
    )
    res_ord1 = crear_o_actualizar_orden(req1, db)
    ord1_id = res_ord1["orden_id"]

    # 2. Crear Orden #2 en Mesa 2 (Plato 1: 4 Cabeza, 1 Bistec)
    req2 = CrearOrdenRequest(
        mesa_id=2,
        mesero="Auxiliar",
        platos=[
            PlatoPedidoInput(
                numero_plato=1,
                notas="Dorados",
                items=[
                    ItemPedidoInput(producto_id=prod_cabeza.id, cantidad=4),
                    ItemPedidoInput(producto_id=prod_bistec.id, cantidad=1),
                ]
            )
        ],
        bebidas=[]
    )
    res_ord2 = crear_o_actualizar_orden(req2, db)
    ord2_id = res_ord2["orden_id"]

    # 3. Verificar Cola de Cocina (los refrescos no aparecen en cocina)
    cola = obtener_cola_cocina(db)
    assert cola["total_ordenes_pendientes"] == 2

    en_turno = cola["orden_en_turno"]
    assert en_turno["orden_id"] == ord1_id
    assert en_turno["modo_vista"] == "detalle_platos"
    assert len(en_turno["platos"]) == 2
    assert en_turno["bebidas"] == {}
    assert en_turno["total_tacos"] == 7
    assert en_turno["desglose_tacos"] == {"Cabeza": 2, "Bistec": 2, "Normales": 3}

    en_espera = cola["ordenes_en_espera"][0]
    assert en_espera["orden_id"] == ord2_id
    assert en_espera["modo_vista"] == "preview_resumen"
    assert en_espera["platos"] == []
    assert en_espera["total_tacos"] == 5
    assert en_espera["desglose_tacos"] == {"Cabeza": 4, "Bistec": 1}

    # 4. Terminar Orden #1 en Cocina -> Orden #2 pasa automaticamente a EN TURNO
    terminar_orden_cocina(ord1_id, db)
    cola_actualizada = obtener_cola_cocina(db)
    assert cola_actualizada["total_ordenes_pendientes"] == 1
    nuevo_turno = cola_actualizada["orden_en_turno"]
    assert nuevo_turno["orden_id"] == ord2_id
    assert nuevo_turno["modo_vista"] == "detalle_platos"
    assert len(nuevo_turno["platos"]) == 1
    assert nuevo_turno["platos"][0]["resumen_texto"] == "4 de Cabeza, 1 de Bistec"

    # 5. Agregar otro plato a la Mesa 1 mientras sigue abierta -> solo el nuevo Plato 3 entra a Cocina
    req1_extra = CrearOrdenRequest(
        mesa_id=1,
        mesero="Auxiliar",
        platos=[
            PlatoPedidoInput(
                numero_plato=1,
                notas="Extra",
                items=[ItemPedidoInput(producto_id=prod_cabeza.id, cantidad=2)]
            )
        ],
        bebidas=[]
    )
    crear_o_actualizar_orden(req1_extra, db)
    cola_con_extra = obtener_cola_cocina(db)
    assert cola_con_extra["total_ordenes_pendientes"] == 2
    assert cola_con_extra["ordenes_en_espera"][0]["orden_id"] == ord1_id
    assert cola_con_extra["ordenes_en_espera"][0]["total_tacos"] == 2

    # 6. Cobrar Orden #1 con billete de $500 y verificar cálculo de cambio e historial del día
    pago_res = pagar_y_cerrar_orden(
        ord1_id,
        PagarOrdenRequest(metodo_pago="efectivo", monto_recibido_pesos=500.0),
        db
    )
    assert pago_res["cambio_pesos"] == round(500.0 - pago_res["total_pesos"], 2)

    db.refresh(ins_cabeza)
    assert float(ins_cabeza.stock_actual) < stock_inicial_cabeza

    historial = listar_historial_dia(db)
    assert len(historial) >= 1

    stats = obtener_estadisticas_admin(fondo_inicial_pesos=1000.0, db=db)
    assert stats["ventas_totales_pesos"] > 0
    assert len(stats["historial_ordenes_hoy"]) >= 1

    db.close()


def test_http_endpoints_end_to_end():
    from fastapi.testclient import TestClient
    from app.server import app

    with TestClient(app) as client:
        r_home = client.get("/")
        assert r_home.status_code == 200
        assert "Sistema POS Taquería" in r_home.text

        r_mesas = client.get("/api/pos/mesas")
        assert r_mesas.status_code == 200
        mesas = r_mesas.json()
        assert len(mesas) >= 1

        r_menu = client.get("/api/pos/menu")
        assert r_menu.status_code == 200
        menu = r_menu.json()
        taco_id = next(m["id"] for m in menu if m["es_taco"])
        bebida_id = next(m["id"] for m in menu if not m["es_taco"])

        r_ord = client.post("/api/pos/ordenes", json={
            "mesa_id": 4,
            "mesero": "Auxiliar",
            "platos": [
                {
                    "numero_plato": 1,
                    "notas": "Con todo",
                    "items": [{"producto_id": taco_id, "cantidad": 3, "notas": ""}]
                }
            ],
            "bebidas": [
                {"producto_id": bebida_id, "cantidad": 2, "notas": ""}
            ]
        })
        assert r_ord.status_code == 200, r_ord.text
        ord_data = r_ord.json()
        assert ord_data["status"] == "ok"
        assert ord_data["enviado_a_cocina"] is True
        oid = ord_data["orden_id"]

        r_pay = client.post(f"/api/pos/ordenes/{oid}/pagar", json={
            "metodo_pago": "efectivo",
            "monto_recibido_pesos": 500.0
        })
        assert r_pay.status_code == 200, r_pay.text
        pay_data = r_pay.json()
        assert pay_data["status"] == "paid"
        assert pay_data["cambio_pesos"] == round(500.0 - pay_data["total_pesos"], 2)

        r_inv1 = client.post("/webhook/simulate-message", json={
            "phone": "admin_panel",
            "message": "se fueron 5 kg de cabeza"
        })
        assert r_inv1.status_code == 200
        assert r_inv1.json()["status"] == "inventory_updated"
        assert "reply" in r_inv1.json()

        r_inv2 = client.post("/webhook/simulate-message", json={
            "phone": "admin_panel",
            "message": "entraron 2 cabezas"
        })
        assert r_inv2.status_code == 200
        assert r_inv2.json()["status"] == "inventory_updated"

        r_stats_base = client.get("/api/pos/admin/analytics?factor_simulacion=1.0")
        assert r_stats_base.status_code == 200
        stats_base = r_stats_base.json()
        assert "resumen_pronostico" in stats_base
        assert len(stats_base["pronostico_7_dias"]) == 7

        r_stats_sim = client.get("/api/pos/admin/analytics?factor_simulacion=1.3")
        assert r_stats_sim.status_code == 200
        stats_sim = r_stats_sim.json()
        assert stats_sim["resumen_pronostico"]["venta_7d_pesos"] > stats_base["resumen_pronostico"]["venta_7d_pesos"]

        r_corte = client.post("/api/pos/admin/guardar-corte", json={
            "fondo_inicial_pesos": 1000.0,
            "efectivo_contado_pesos": 1100.0,
            "observaciones": "Corte de prueba"
        })
        assert r_corte.status_code == 200
        assert r_corte.json()["status"] == "saved"


if __name__ == "__main__":
    test_html_historical_import()
    test_nlp_inventory_movements()
    test_pos_orders_kitchen_queue_and_inventory()
    test_http_endpoints_end_to_end()
