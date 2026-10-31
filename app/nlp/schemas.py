from typing import Optional, Literal
from pydantic import BaseModel, computed_field


class ExpenseExtraction(BaseModel):
    tipo: Literal["gasto", "retiro", "ingreso", "pago_proveedor", "inventario_entrada", "inventario_salida", "consulta"]
    importe_pesos: float = 0.0
    concepto: str
    categoria_sugerida: str
    proveedor_o_persona: Optional[str] = None
    metodo_pago: Literal["efectivo", "tarjeta", "transferencia"] = "efectivo"
    requiere_confirmacion: bool = False
    pregunta_clarificacion: Optional[str] = None

    # Campos para movimientos de inventario por lenguaje natural ("se fueron 5 kg de cabeza", "entraron 3 cabezas")
    insumo_nombre: Optional[str] = None
    cantidad_insumo: float = 0.0
    unidad_insumo: Optional[str] = None

    @computed_field
    @property
    def importe_centavos(self) -> int:
        return int(round(self.importe_pesos * 100))
