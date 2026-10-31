import csv
import io
import json
import re
from html.parser import HTMLParser
from typing import List, Union, Dict, Any, Optional
from app.schemas.didan import DidanProductItem, DidanDailyReportSummary


class _HTMLTableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.current_cell: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs):
        tag_l = tag.lower()
        if tag_l == "tr":
            self.current_row = []
        elif tag_l in ("td", "th"):
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag: str):
        tag_l = tag.lower()
        if tag_l in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).strip())
        elif tag_l == "tr" and self.current_row:
            self.rows.append(self.current_row)

    def handle_data(self, data: str):
        if self.in_cell:
            self.current_cell.append(data)


class DidanImporter:

    @staticmethod
    def _clean_number(val: Any) -> float:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        s = re.sub(r"[^\d.,-]", "", s)
        if not s:
            return 0.0
        if "," in s and "." in s:
            s = s.replace(",", "")
        elif "," in s:
            parts = s.split(",")
            if len(parts[-1]) == 2:
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return 0.0

    @classmethod
    def _normalize_row_dict(cls, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        norm = {str(k).lower().strip(): v for k, v in row.items() if k is not None}

        cat = (
            norm.get("category")
            or norm.get("categoria")
            or norm.get("categoría")
            or norm.get("grupo")
            or "tacos"
        )
        prod = (
            norm.get("product")
            or norm.get("producto")
            or norm.get("articulo")
            or norm.get("artículo")
            or norm.get("nombre")
            or norm.get("item")
        )
        if not prod:
            return None

        prod_str = str(prod).strip()
        if prod_str.lower() in ("total", "totales", "subtotal", "suma", ""):
            return None

        qty = cls._clean_number(
            norm.get("quantity")
            or norm.get("cantidad")
            or norm.get("cant")
            or norm.get("unidades")
            or norm.get("piezas")
            or 1
        )
        amount = cls._clean_number(
            norm.get("amount")
            or norm.get("importe")
            or norm.get("monto")
            or norm.get("total")
            or norm.get("venta")
            or norm.get("ventas")
            or 0
        )
        cost = cls._clean_number(norm.get("cost") or norm.get("costo") or 0)
        tax = cls._clean_number(norm.get("tax") or norm.get("impuesto") or norm.get("iva") or 0)
        profit = cls._clean_number(
            norm.get("profit")
            or norm.get("ganancia")
            or norm.get("utilidad")
            or (amount - cost)
        )

        if qty <= 0 and amount <= 0:
            return None

        return {
            "category": str(cat).strip() or "general",
            "product": prod_str,
            "amount": amount,
            "tax": tax,
            "cost": cost,
            "profit": profit,
            "quantity": qty if qty > 0 else 1.0,
        }

    @classmethod
    def parse_html_data(cls, html_content: Union[str, bytes]) -> DidanDailyReportSummary:
        text = html_content.decode("utf-8", errors="ignore") if isinstance(html_content, bytes) else html_content
        parser = _HTMLTableExtractor()
        parser.feed(text)

        if not parser.rows:
            raise ValueError("No se encontraron tablas en el archivo HTML.")

        header_idx = -1
        headers: List[str] = []
        for idx, row in enumerate(parser.rows):
            row_lower = [c.lower() for c in row]
            if any(k in " ".join(row_lower) for k in ("product", "producto", "artículo", "articulo", "amount", "importe", "cantidad")):
                header_idx = idx
                headers = row_lower
                break

        items_list: List[Dict[str, Any]] = []
        if header_idx >= 0:
            for row in parser.rows[header_idx + 1:]:
                if len(row) < 2:
                    continue
                row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                normalized = cls._normalize_row_dict(row_dict)
                if normalized:
                    items_list.append(normalized)
        else:
            # Fallback posicional: [Categoria, Producto, Cantidad, Importe] o [Producto, Cantidad, Importe]
            for row in parser.rows:
                if len(row) >= 3:
                    if len(row) >= 4 and not re.match(r"^[\d$,.\s-]+$", row[1]):
                        candidate = {"category": row[0], "product": row[1], "quantity": row[2], "amount": row[3]}
                    else:
                        candidate = {"category": "tacos", "product": row[0], "quantity": row[1], "amount": row[2]}
                    normalized = cls._normalize_row_dict(candidate)
                    if normalized:
                        items_list.append(normalized)

        if not items_list:
            raise ValueError("No se pudieron extraer productos validos del HTML.")

        return cls.parse_json_data(items_list)

    @classmethod
    def parse_csv_data(cls, csv_content: Union[str, bytes]) -> DidanDailyReportSummary:
        text = csv_content.decode("utf-8", errors="ignore") if isinstance(csv_content, bytes) else csv_content
        reader = csv.DictReader(io.StringIO(text))
        items_list = []
        for row in reader:
            normalized = cls._normalize_row_dict(row)
            if normalized:
                items_list.append(normalized)
        if not items_list:
            raise ValueError("No se pudieron extraer productos del CSV.")
        return cls.parse_json_data(items_list)

    @classmethod
    def parse_any_format(cls, content: Union[str, bytes], filename: str = "") -> DidanDailyReportSummary:
        fname = filename.lower().strip()
        text = content.decode("utf-8", errors="ignore").strip() if isinstance(content, bytes) else content.strip()

        if fname.endswith(".html") or fname.endswith(".htm") or text.startswith("<") or "<table" in text.lower():
            return cls.parse_html_data(text)
        if fname.endswith(".csv"):
            return cls.parse_csv_data(text)
        if text.startswith("[") or text.startswith("{"):
            return cls.parse_json_data(text)
        return cls.parse_csv_data(text)

    @staticmethod
    def parse_json_data(data: Union[str, bytes, List[Dict[str, Any]]]) -> DidanDailyReportSummary:
        if isinstance(data, (str, bytes)):
            items_raw = json.loads(data)
        else:
            items_raw = data

        if not isinstance(items_raw, list):
            raise ValueError("El reporte de Didan POS debe ser una lista de articulos.")

        items: List[DidanProductItem] = [DidanProductItem(**item) for item in items_raw]

        total_sales_centavos = sum(item.amount_centavos for item in items)
        total_cost_centavos = sum(item.cost_centavos for item in items)
        total_profit_centavos = sum(item.profit_centavos for item in items)
        total_units = sum(item.quantity for item in items)

        categories_breakdown: Dict[str, int] = {}
        for item in items:
            cat = item.category.lower().strip()
            categories_breakdown[cat] = categories_breakdown.get(cat, 0) + item.amount_centavos

        sorted_by_revenue = sorted(items, key=lambda x: x.amount_centavos, reverse=True)
        top_revenue = [
            {
                "producto": item.product,
                "categoria": item.category,
                "venta_pesos": item.amount,
                "unidades": item.quantity,
                "precio_promedio": item.unit_price_pesos
            }
            for item in sorted_by_revenue[:5]
        ]

        sorted_by_quantity = sorted(items, key=lambda x: x.quantity, reverse=True)
        top_quantity = [
            {
                "producto": item.product,
                "categoria": item.category,
                "unidades": item.quantity,
                "venta_pesos": item.amount
            }
            for item in sorted_by_quantity[:5]
        ]

        return DidanDailyReportSummary(
            total_sales_centavos=total_sales_centavos,
            total_cost_centavos=total_cost_centavos,
            total_profit_centavos=total_profit_centavos,
            total_units_sold=total_units,
            categories_breakdown_centavos=categories_breakdown,
            top_products_by_revenue=top_revenue,
            top_products_by_quantity=top_quantity,
            items=items
        )

    @staticmethod
    def generate_whatsapp_summary(summary: DidanDailyReportSummary, dashboard_url: Optional[str] = None) -> str:
        tacos_units = sum(
            item.quantity for item in summary.items if "taco" in item.category.lower()
        )
        bebidas_units = sum(
            item.quantity for item in summary.items if "bebida" in item.category.lower() or "refresco" in item.category.lower()
        )

        lines = [
            "Resumen de Ventas (Didan POS)",
            "-------------------",
            f"Venta Total: ${summary.total_sales_pesos:,.2f} MXN",
            f"Tacos vendidos: {int(tacos_units)} piezas",
            f"Bebidas vendidas: {int(bebidas_units)} piezas",
            f"Total de articulos: {int(summary.total_units_sold)} unidades",
            "",
            "Productos principales:",
        ]

        for idx, prod in enumerate(summary.top_products_by_revenue[:3], 1):
            lines.append(f" {idx}. {prod['producto']}: ${prod['venta_pesos']:,.2f} ({int(prod['unidades'])} pzs)")

        if dashboard_url:
            lines.extend([
                "",
                "Panel de administracion:",
                f"{dashboard_url}"
            ])

        return "\n".join(lines)
