from app.services.didan_importer import DidanImporter
from app.schemas.didan import DidanDailyReportSummary


def test_parse_didan_real_sample():
    sample_path = "/home/diego/taqueria/sample_data/didan_sales_sample.json"
    with open(sample_path, "r", encoding="utf-8") as f:
        raw_json = f.read()

    summary: DidanDailyReportSummary = DidanImporter.parse_json_data(raw_json)

    assert summary.total_sales_pesos == 5185.0
    assert summary.total_sales_centavos == 518500
    assert summary.total_units_sold == 196.0

    top_product = summary.top_products_by_revenue[0]
    assert top_product["producto"] == "Normales"
    assert top_product["venta_pesos"] == 3146.0
    assert top_product["unidades"] == 121.0

    wa_msg = DidanImporter.generate_whatsapp_summary(summary)
    assert "Resumen de Ventas" in wa_msg
    assert "$5,185.00" in wa_msg
    assert "169 piezas" in wa_msg


if __name__ == "__main__":
    test_parse_didan_real_sample()
