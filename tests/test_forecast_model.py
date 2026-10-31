import pandas as pd
import numpy as np
from datetime import date, timedelta
from app.analytics.forecast_model import TaqueriaSalesForecaster


def test_forecast_training_and_prediction():
    base_date = date.today() - timedelta(days=60)
    records = []

    for i in range(60):
        curr_date = base_date + timedelta(days=i)
        dow = curr_date.weekday()
        ventas = np.random.uniform(9000, 12500) if dow in [4, 5, 6] else np.random.uniform(4000, 6000)
        if curr_date.day in [14, 15, 16, 29, 30, 31]:
            ventas *= 1.25
        records.append({"fecha": curr_date, "ventas_pesos": round(ventas, 2)})

    df_hist = pd.DataFrame(records)

    forecaster = TaqueriaSalesForecaster()
    success = forecaster.fit(df_hist)
    assert success is True

    preds = forecaster.predict_next_days(df_hist, days_ahead=7)
    assert len(preds) == 7

    for p in preds:
        assert p["escenario_pesimista_p10"] <= p["pronostico_pesos_p50"] <= p["escenario_optimista_p90"]
        assert p["tacos_estimados"] > 0
        assert p["kilos_carne_sugeridos"] > 0
        assert p["kilos_tortillas_sugeridos"] > 0


if __name__ == "__main__":
    test_forecast_training_and_prediction()
