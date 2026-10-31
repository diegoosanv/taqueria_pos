from app.services.reconciliation import CashReconciliationEngine


def test_reconciliation_exact():
    res = CashReconciliationEngine.calculate_shift_reconciliation(
        fondo_inicial_centavos=100000,
        ventas_efectivo_centavos=500000,
        gastos_efectivo_centavos=150000,
        retiros_efectivo_centavos=50000,
        saldo_real_contado_centavos=400000
    )
    assert res.estado_cuadre == "exacto"
    assert res.diferencia_centavos == 0
    assert res.saldo_teorico_pesos == 4000.0


def test_reconciliation_faltante():
    res = CashReconciliationEngine.calculate_shift_reconciliation(
        fondo_inicial_centavos=100000,
        ventas_efectivo_centavos=500000,
        gastos_efectivo_centavos=150000,
        retiros_efectivo_centavos=50000,
        saldo_real_contado_centavos=370000
    )
    assert res.estado_cuadre == "faltante"
    assert res.diferencia_pesos == -300.0
    assert res.alerta_severidad == "critica"


def test_cusum_leak_detection():
    daily_differences = [-5000] * 10
    cusum = CashReconciliationEngine.calculate_cusum_drift(
        historical_differences_centavos=daily_differences,
        k_ref_centavos=1000,
        h_threshold_centavos=20000
    )
    assert cusum["alarm_triggered"] is True
    assert cusum["cusum_score_pesos"] > 200.0


if __name__ == "__main__":
    test_reconciliation_exact()
    test_reconciliation_faltante()
    test_cusum_leak_detection()
