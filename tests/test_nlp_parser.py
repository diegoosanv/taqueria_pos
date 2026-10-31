from app.nlp.parser import HybridExpenseParser


def test_nlp_expenses_parsing():
    res1 = HybridExpenseParser.parse_message("Gasto 350 carne con Don Beto")
    assert res1.tipo == "gasto"
    assert res1.importe_pesos == 350.0
    assert res1.importe_centavos == 35000
    assert "Carne" in res1.categoria_sugerida
    assert res1.proveedor_o_persona == "Don Beto"
    assert not res1.requiere_confirmacion

    res2 = HybridExpenseParser.parse_message("200 cilantro y limones")
    assert res2.tipo == "gasto"
    assert res2.importe_pesos == 200.0
    assert "Verdura" in res2.categoria_sugerida

    res3 = HybridExpenseParser.parse_message("Retiro 500 pesos para la casa")
    assert res3.tipo == "retiro"
    assert res3.importe_pesos == 500.0
    assert "Retiro" in res3.categoria_sugerida

    res4 = HybridExpenseParser.parse_message("Pagué 1200 de luz CFE")
    assert res4.tipo == "gasto"
    assert res4.importe_pesos == 1200.0
    assert "Servicio" in res4.categoria_sugerida

    res5 = HybridExpenseParser.parse_message("200 de Estefanía")
    assert res5.importe_pesos == 200.0
    assert res5.proveedor_o_persona == "Estefanía"
    assert res5.requiere_confirmacion is True


if __name__ == "__main__":
    test_nlp_expenses_parsing()
