import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, timedelta
from app.db.session import SessionLocal
from app.db.models import Movimiento, VentaDidan, DetalleVentaDidan
from app.services.reconciliation import CashReconciliationEngine
from app.services.didan_importer import DidanImporter
from app.analytics.forecast_model import TaqueriaSalesForecaster

st.set_page_config(
    page_title="Taquería - Control Financiero",
    layout="wide"
)

st.title("Control Financiero y Pronósticos")

db = SessionLocal()

st.sidebar.header("Filtros")
fecha_seleccionada = st.sidebar.date_input("Fecha de analisis", date.today())

st.sidebar.markdown("---")
st.sidebar.header("Importar Didan POS")
uploaded_files = st.sidebar.file_uploader(
    "Archivos JSON o CSV",
    type=["json", "csv"],
    accept_multiple_files=True
)

if uploaded_files:
    for up_file in uploaded_files:
        try:
            content = up_file.read()
            summary = DidanImporter.parse_json_data(content)
            fecha_archivo = fecha_seleccionada
            v_existente = db.query(VentaDidan).filter(VentaDidan.fecha == fecha_archivo).first()
            if not v_existente:
                nueva_v = VentaDidan(
                    fecha=fecha_archivo,
                    total_ventas_centavos=summary.total_sales_centavos,
                    total_costo_centavos=summary.total_cost_centavos,
                    total_ganancia_centavos=summary.total_profit_centavos,
                    unidades_vendidas_total=summary.total_units_sold,
                    raw_payload={"filename": up_file.name}
                )
                db.add(nueva_v)
                db.flush()
                for item in summary.items:
                    det = DetalleVentaDidan(
                        venta_id=nueva_v.id,
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
                st.sidebar.success(f"Cargado: {up_file.name} (${summary.total_sales_pesos:,.2f})")
        except Exception as e:
            st.sidebar.error(f"Error {up_file.name}: {e}")

movimientos = db.query(Movimiento).all()
ventas_dia = db.query(VentaDidan).filter(VentaDidan.fecha == fecha_seleccionada).first()
todas_ventas = db.query(VentaDidan).order_by(VentaDidan.fecha.asc()).all()

detalles_dia = []
if ventas_dia:
    detalles_dia = db.query(DetalleVentaDidan).filter(DetalleVentaDidan.venta_id == ventas_dia.id).all()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Conciliacion de Caja",
    "Pronostico de Ventas",
    "Ventas Didan POS",
    "Gastos WhatsApp",
    "Deteccion de Fugas"
])

with tab1:
    st.subheader(f"Corte de Caja - {fecha_seleccionada.strftime('%d/%m/%Y')}")

    ventas_totales_pesos = (ventas_dia.total_ventas_centavos / 100.0) if ventas_dia else 0.0
    gastos_totales_pesos = sum(m.importe_centavos for m in movimientos if m.tipo == "gasto") / 100.0
    retiros_totales_pesos = sum(m.importe_centavos for m in movimientos if m.tipo == "retiro") / 100.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ventas Registradas", f"${ventas_totales_pesos:,.2f}")
    col2.metric("Gastos en Efectivo", f"${gastos_totales_pesos:,.2f}")
    col3.metric("Retiros Personales", f"${retiros_totales_pesos:,.2f}")

    c_fondo, c_real = st.columns(2)
    fondo_inicial = c_fondo.number_input("Fondo Inicial", value=1000.0, step=50.0)
    efectivo_contado = c_real.number_input(
        "Efectivo Fisico Contado",
        value=max(0.0, ventas_totales_pesos - gastos_totales_pesos + fondo_inicial - retiros_totales_pesos),
        step=50.0
    )

    res = CashReconciliationEngine.calculate_shift_reconciliation(
        fondo_inicial_centavos=int(round(fondo_inicial * 100)),
        ventas_efectivo_centavos=int(round(ventas_totales_pesos * 100)),
        gastos_efectivo_centavos=int(round(gastos_totales_pesos * 100)),
        retiros_efectivo_centavos=int(round(retiros_totales_pesos * 100)),
        saldo_real_contado_centavos=int(round(efectivo_contado * 100))
    )

    col4.metric(
        "Diferencia",
        f"${res.diferencia_pesos:,.2f}",
        delta=f"{res.diferencia_pesos:,.2f} MXN",
        delta_color="normal" if res.diferencia_pesos >= 0 else "inverse"
    )

    if res.estado_cuadre == "exacto":
        st.success("Caja cuadrada.")
    elif res.estado_cuadre == "faltante":
        st.error(f"Faltante: -${abs(res.diferencia_pesos):,.2f} MXN.")
    else:
        st.warning(f"Sobrante: +${res.diferencia_pesos:,.2f} MXN.")

with tab2:
    st.subheader("Pronostico a 7 Dias (Cuantiles P10, P50, P90)")

    if len(todas_ventas) >= 5:
        df_hist = pd.DataFrame([
            {"fecha": v.fecha, "ventas_pesos": v.total_ventas_centavos / 100.0}
            for v in todas_ventas
        ])
    else:
        fechas_demo = [date.today() - timedelta(days=i) for i in range(45, 0, -1)]
        records_demo = []
        for f in fechas_demo:
            dow = f.weekday()
            v_base = np.random.uniform(9000, 13000) if dow in [4, 5, 6] else np.random.uniform(4200, 6200)
            if f.day in [14, 15, 16, 29, 30, 31]:
                v_base *= 1.25
            records_demo.append({"fecha": f, "ventas_pesos": round(v_base, 2)})
        if ventas_dia:
            records_demo.append({"fecha": ventas_dia.fecha, "ventas_pesos": ventas_dia.total_ventas_centavos / 100.0})
        df_hist = pd.DataFrame(records_demo)

    forecaster = TaqueriaSalesForecaster()
    predicciones = forecaster.predict_next_days(df_hist, days_ahead=7)
    df_pred = pd.DataFrame(predicciones)

    ventas_finde = df_pred[df_pred["es_fin_de_semana"]]["pronostico_pesos_p50"].sum()
    carne_total = df_pred["kilos_carne_sugeridos"].sum()
    tortillas_total = df_pred["kilos_tortillas_sugeridos"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("Venta Esperada Fin de Semana", f"${ventas_finde:,.2f} MXN")
    m2.metric("Carne Estimada (Semana)", f"{carne_total:.1f} kg")
    m3.metric("Tortillas Estimadas (Semana)", f"{tortillas_total:.1f} kg")

    chart_data = df_pred.set_index("fecha")[["escenario_pesimista_p10", "pronostico_pesos_p50", "escenario_optimista_p90"]]
    chart_data.columns = ["Pesimista (P10)", "Esperado (P50)", "Optimista (P90)"]
    st.line_chart(chart_data)

    st.dataframe(
        df_pred[[
            "fecha", "dia_semana", "pronostico_pesos_p50",
            "tacos_estimados", "kilos_carne_sugeridos", "kilos_tortillas_sugeridos"
        ]].rename(columns={
            "fecha": "Fecha",
            "dia_semana": "Dia",
            "pronostico_pesos_p50": "Venta Estimada ($)",
            "tacos_estimados": "Tacos Estimados",
            "kilos_carne_sugeridos": "Carne (kg)",
            "kilos_tortillas_sugeridos": "Tortillas (kg)"
        }),
        use_container_width=True
    )

with tab3:
    st.subheader("Desglose Didan POS")
    if detalles_dia:
        df_det = pd.DataFrame([
            {
                "Categoria": d.categoria.title(),
                "Producto": d.producto,
                "Unidades": float(d.cantidad),
                "Precio Promedio": round(d.precio_unitario_centavos / 100.0, 2),
                "Total ($)": round(d.subtotal_centavos / 100.0, 2)
            }
            for d in detalles_dia
        ])
        st.dataframe(df_det, use_container_width=True)

        col_bar, col_pie = st.columns(2)
        with col_bar:
            st.bar_chart(df_det.set_index("Producto")["Unidades"])
        with col_pie:
            st.bar_chart(df_det.groupby("Categoria")["Total ($)"].sum())
    else:
        st.info("Sin registros para la fecha.")

with tab4:
    st.subheader("Bitacora de Gastos WhatsApp")
    if movimientos:
        df_mov = pd.DataFrame([
            {
                "Fecha": m.fecha_hora.strftime("%Y-%m-%d %H:%M"),
                "Tipo": m.tipo.upper(),
                "Importe ($)": round(m.importe_centavos / 100.0, 2),
                "Concepto": m.concepto_original,
                "Proveedor": m.proveedor_o_persona or "N/A",
                "Metodo": m.metodo_pago,
                "Registrado Por": m.registrado_por
            }
            for m in movimientos
        ])
        st.dataframe(df_mov, use_container_width=True)
    else:
        st.info("Sin movimientos registrados.")

with tab5:
    st.subheader("Monitoreo CUSUM")
    diferencias_demo = [-1500, -2500, 0, -3000, -4500, -1000, -5000, -6000]
    cusum_demo = CashReconciliationEngine.calculate_cusum_drift(diferencias_demo)

    col_c1, col_c2 = st.columns(2)
    col_c1.metric("Perdida Acumulada", f"${cusum_demo['cusum_score_pesos']:,.2f} MXN")
    col_c2.metric("Umbral", f"${cusum_demo['threshold_pesos']:,.2f} MXN")

    if cusum_demo["alarm_triggered"]:
        st.error("Alerta CUSUM: Desviacion sistematica negativa detectada.")

db.close()
