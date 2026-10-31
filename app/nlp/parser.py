import re
import logging
from app.core.config import settings
from app.nlp.schemas import ExpenseExtraction

logger = logging.getLogger(__name__)


class HybridExpenseParser:

    SYSTEM_PROMPT = """Eres el asistente de administracion e inventario de una taqueria.
Extrae datos financieros o movimientos de inventario del mensaje.
Reglas:
1. Si el mensaje indica movimiento de inventario sin dinero (ej. "se fueron 5 kg de cabeza", "entraron 3 cabezas", "salieron 4 kg de bistec", "llegaron 20 kg de tortillas"):
   - Usa tipo='inventario_entrada' (entraron, llegaron, metimos) o tipo='inventario_salida' (se fueron, salieron, se usaron, merma).
   - Asigna cantidad_insumo con el numero, unidad_insumo ('kg' o 'pieza') e insumo_nombre ('Cabezas de Res', 'Carne de Bistec', 'Carne Tacos Normales', 'Carne Tacos Especiales', 'Tortilla Taquera', 'Refresco Vidrio', 'Chaparrita', 'COCA 600', 'Refresco Lata', 'Agua Natural', 'Agua Mineral').
2. Si es un gasto o movimiento de dinero:
   - Usa tipo='gasto' o 'retiro'.
   - Categorias:
     Carne e Insumos Principales (pastor, suadero, bistec, cabeza, tripa, carne)
     Verduras (Limón, Cilantro, Cebolla) (cilantro, cebolla, limon, aguacate, jitomate, pina)
     Tortillas y Masa (tortillas, masa)
     Bebidas y Refrescos (refresco, coca, agua, hielo)
     Gas y Combustible (gas, tanque)
     Carbón / Leña (carbon, lena)
     Nómina y Pagos a Personal (sueldo, nomina, taquero, auxiliar, mesero)
     Servicios (Luz CFE, Agua, Renta) (luz, cfe, agua, renta)
     Desechables y Plásticos (bolsas, servilletas, platos, jabon, cloro)
     Retiro de los Propietarios (retiro personal, saque para la casa) -> tipo 'retiro'
"""

    @classmethod
    def parse_message(cls, text: str) -> ExpenseExtraction:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Mensaje vacio.")

        if settings.GEMINI_API_KEY:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=cleaned,
                    config=types.GenerateContentConfig(
                        system_instruction=cls.SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=ExpenseExtraction,
                        temperature=0.1
                    )
                )
                if response.text:
                    return ExpenseExtraction.model_validate_json(response.text)
            except Exception as e:
                logger.warning(f"Fallo llamada a Gemini API ({e}). Usando fallback.")

        return cls._rule_based_fallback(cleaned)

    @classmethod
    def parse(cls, text: str) -> ExpenseExtraction:
        return cls.parse_message(text)

    @classmethod
    def _detect_insumo_name_and_unit(cls, text_lower: str) -> tuple[str, str]:
        es_kg = any(u in text_lower for u in ["kg", "kilo", "kilos"])
        unidad = "kg" if es_kg else "pieza"
        if "cabeza" in text_lower:
            if es_kg:
                return "Carne de Cabeza", "kg"
            return "Cabezas de Res", "pieza"
        if "bistec" in text_lower:
            return "Carne de Bistec", "kg"
        if "especial" in text_lower:
            return "Carne Tacos Especiales", "kg"
        if "normal" in text_lower or "pastor" in text_lower or "carne" in text_lower:
            return "Carne Tacos Normales", "kg"
        if "tortilla" in text_lower or "masa" in text_lower:
            return "Tortilla Taquera", "kg"
        if "coca" in text_lower:
            return "COCA 600", "pieza"
        if "chaparrita" in text_lower:
            return "Chaparrita", "pieza"
        if "lata" in text_lower:
            return "Refresco Lata", "pieza"
        if "mineral" in text_lower:
            return "Agua Mineral", "pieza"
        if "agua" in text_lower:
            return "Agua Natural", "pieza"
        if "refresco" in text_lower or "vidrio" in text_lower:
            return "Refresco Vidrio", "pieza"
        return "Carne Tacos Normales", unidad

    @staticmethod
    def _has_any_word(text_lower: str, words: list[str]) -> bool:
        for w in words:
            if " " in w:
                if w in text_lower:
                    return True
            elif re.search(rf"\b{re.escape(w)}\b", text_lower):
                return True
        return False

    @classmethod
    def _rule_based_fallback(cls, text: str) -> ExpenseExtraction:
        text_lower = text.lower()

        # 1. Detectar si es movimiento de inventario ("se fueron X kg de cabeza", "entraron X cabezas", etc.)
        es_salida_inv = cls._has_any_word(text_lower, [
            "se fueron", "se fue", "salieron", "salio", "salió",
            "se usaron", "se uso", "se acabó", "se acabo", "merma"
        ])
        es_entrada_inv = cls._has_any_word(text_lower, [
            "entraron", "entro", "entró", "llegaron", "llego", "llegó",
            "metimos", "ingreso inventario", "agregamos"
        ])

        match_num = re.search(r"(\d+(?:[.,]\d{1,3})?)", text_lower)
        if (es_salida_inv or es_entrada_inv) and match_num and "pesos" not in text_lower and "$" not in text_lower:
            cant = float(match_num.group(1).replace(",", "."))
            insumo_nom, unidad = cls._detect_insumo_name_and_unit(text_lower)
            tipo_inv = "inventario_salida" if es_salida_inv else "inventario_entrada"
            return ExpenseExtraction(
                tipo=tipo_inv,
                importe_pesos=0.0,
                concepto=text,
                categoria_sugerida="Inventario",
                requiere_confirmacion=False,
                insumo_nombre=insumo_nom,
                cantidad_insumo=cant,
                unidad_insumo=unidad
            )

        # 2. Movimiento financiero / Gasto
        match_amount = re.search(r"\$?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:pesos|mxn|\$)?", text_lower)
        if not match_amount:
            return ExpenseExtraction(
                tipo="consulta",
                importe_pesos=0.0,
                concepto=text,
                categoria_sugerida="No clasificado",
                requiere_confirmacion=True,
                pregunta_clarificacion="No se detecto un importe o cantidad. Indica el monto o cantidad."
            )

        amount_str = match_amount.group(1).replace(",", ".")
        importe = float(amount_str)

        if cls._has_any_word(text_lower, ["retiro", "agarre", "agarré", "saque", "saqué", "para mi", "para mí", "dueño", "dueña"]):
            return ExpenseExtraction(
                tipo="retiro",
                importe_pesos=importe,
                concepto=text,
                categoria_sugerida="Retiro de los Propietarios",
                requiere_confirmacion=False
            )

        categoria = "Gastos Generales"
        tipo = "gasto"
        proveedor = None

        if cls._has_any_word(text_lower, ["carne", "carnes", "pastor", "suadero", "bistec", "cabeza", "cabezas", "tripa", "chuleta", "longaniza", "pollo"]):
            categoria = "Carne e Insumos Principales"
        elif cls._has_any_word(text_lower, ["cilantro", "cebolla", "cebollas", "limon", "limones", "limón", "aguacate", "aguacates", "jitomate", "tomate", "verdura", "verduras", "pina", "piña"]):
            categoria = "Verduras (Limón, Cilantro, Cebolla)"
        elif cls._has_any_word(text_lower, ["tortilla", "tortillas", "masa", "taquera"]):
            categoria = "Tortillas y Masa"
        elif cls._has_any_word(text_lower, ["refresco", "refrescos", "coca", "bebida", "bebidas", "chaparrita", "hielo", "cerveza"]):
            categoria = "Bebidas y Refrescos"
        elif cls._has_any_word(text_lower, ["gas", "tanque", "pipa"]):
            categoria = "Gas y Combustible"
        elif cls._has_any_word(text_lower, ["carbon", "carbón", "lena", "leña"]):
            categoria = "Carbón / Leña"
        elif cls._has_any_word(text_lower, ["sueldo", "nomina", "nómina", "taquero", "mesero", "auxiliar", "lavalozas", "propina"]):
            categoria = "Nómina y Pagos a Personal"
        elif cls._has_any_word(text_lower, ["luz", "cfe", "agua", "renta"]):
            categoria = "Servicios (Luz CFE, Agua, Renta)"
        elif cls._has_any_word(text_lower, ["jabon", "jabón", "cloro", "bolsas", "desechables", "platos", "servilletas"]):
            categoria = "Desechables y Plásticos"

        match_prov = re.search(r"(?:a|de|con|para)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?)", text)
        if match_prov:
            proveedor = match_prov.group(1).strip()

        requiere_conf = (categoria == "Gastos Generales") and (proveedor is not None or len(text.split()) <= 3)

        return ExpenseExtraction(
            tipo=tipo,
            importe_pesos=importe,
            concepto=text,
            categoria_sugerida=categoria,
            proveedor_o_persona=proveedor,
            metodo_pago="efectivo",
            requiere_confirmacion=requiere_conf,
            pregunta_clarificacion=f"Registre ${importe:,.2f} MXN. Que tipo de gasto es? (1. Nomina, 2. Insumos/Carne, 3. Proveedor, 4. Retiro)" if requiere_conf else None
        )


TaqueriaNLPParser = HybridExpenseParser
