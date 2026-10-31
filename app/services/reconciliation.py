from typing import Dict, Any, List
from pydantic import BaseModel


class CashReconciliationResult(BaseModel):
    fondo_inicial_centavos: int
    ventas_efectivo_centavos: int
    gastos_efectivo_centavos: int
    retiros_efectivo_centavos: int
    saldo_teorico_centavos: int
    saldo_real_contado_centavos: int
    diferencia_centavos: int
    estado_cuadre: str  # exacto, faltante, sobrante
    alerta_severidad: str  # ok, advertencia, critica

    @property
    def saldo_teorico_pesos(self) -> float:
        return round(self.saldo_teorico_centavos / 100.0, 2)

    @property
    def saldo_real_pesos(self) -> float:
        return round(self.saldo_real_contado_centavos / 100.0, 2)

    @property
    def diferencia_pesos(self) -> float:
        return round(self.diferencia_centavos / 100.0, 2)


class CashReconciliationEngine:

    @staticmethod
    def calculate_shift_reconciliation(
        fondo_inicial_centavos: int,
        ventas_efectivo_centavos: int,
        gastos_efectivo_centavos: int,
        retiros_efectivo_centavos: int,
        saldo_real_contado_centavos: int,
        umbral_tolerancia_centavos: int = 2000
    ) -> CashReconciliationResult:
        saldo_teorico = (
            fondo_inicial_centavos
            + ventas_efectivo_centavos
            - gastos_efectivo_centavos
            - retiros_efectivo_centavos
        )

        diferencia = saldo_real_contado_centavos - saldo_teorico

        if abs(diferencia) <= umbral_tolerancia_centavos:
            estado = "exacto"
            severidad = "ok"
        elif diferencia < 0:
            estado = "faltante"
            severidad = "critica" if abs(diferencia) > 10000 else "advertencia"
        else:
            estado = "sobrante"
            severidad = "advertencia"

        return CashReconciliationResult(
            fondo_inicial_centavos=fondo_inicial_centavos,
            ventas_efectivo_centavos=ventas_efectivo_centavos,
            gastos_efectivo_centavos=gastos_efectivo_centavos,
            retiros_efectivo_centavos=retiros_efectivo_centavos,
            saldo_teorico_centavos=saldo_teorico,
            saldo_real_contado_centavos=saldo_real_contado_centavos,
            diferencia_centavos=diferencia,
            estado_cuadre=estado,
            alerta_severidad=severidad
        )

    @staticmethod
    def format_whatsapp_reconciliation(result: CashReconciliationResult) -> str:
        if result.estado_cuadre == "exacto":
            veredicto = "Caja Cuadrada Exacta"
        elif result.estado_cuadre == "faltante":
            veredicto = f"Faltante de Caja: -${abs(result.diferencia_pesos):,.2f} MXN"
        else:
            veredicto = f"Sobrante de Caja: +${result.diferencia_pesos:,.2f} MXN"

        lines = [
            f"{veredicto}",
            "-------------------",
            f"Fondo inicial: ${result.fondo_inicial_centavos / 100:,.2f}",
            f"Ventas en efectivo: +${result.ventas_efectivo_centavos / 100:,.2f}",
            f"Gastos en efectivo: -${result.gastos_efectivo_centavos / 100:,.2f}",
            f"Retiros personales: -${result.retiros_efectivo_centavos / 100:,.2f}",
            "-------------------",
            f"Efectivo esperado: ${result.saldo_teorico_pesos:,.2f}",
            f"Efectivo contado: ${result.saldo_real_pesos:,.2f}",
            f"Diferencia: ${result.diferencia_pesos:,.2f} MXN"
        ]

        if result.estado_cuadre == "faltante" and result.alerta_severidad == "critica":
            lines.append("\nRevisa compras o retiros no reportados.")

        return "\n".join(lines)

    @staticmethod
    def calculate_cusum_drift(
        historical_differences_centavos: List[int],
        k_ref_centavos: int = 1500,
        h_threshold_centavos: int = 10000
    ) -> Dict[str, Any]:
        s_negative = 0
        alarm_triggered = False
        alarm_index = -1

        for idx, diff in enumerate(historical_differences_centavos):
            if diff < 0:
                loss = abs(diff)
                s_negative = max(0, s_negative + (loss - k_ref_centavos))
            else:
                s_negative = max(0, s_negative - k_ref_centavos)

            if s_negative > h_threshold_centavos and not alarm_triggered:
                alarm_triggered = True
                alarm_index = idx

        return {
            "cusum_score_centavos": s_negative,
            "cusum_score_pesos": round(s_negative / 100.0, 2),
            "alarm_triggered": alarm_triggered,
            "alarm_turn_index": alarm_index,
            "threshold_pesos": round(h_threshold_centavos / 100.0, 2)
        }
