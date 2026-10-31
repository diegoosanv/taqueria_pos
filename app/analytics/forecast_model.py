from datetime import date, timedelta
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor


class TaqueriaSalesForecaster:
    PRECIO_PROMEDIO_TACO = 27.50
    TACOS_POR_KG_CARNE = 19.0
    TACOS_POR_KG_TORTILLAS = 32.0

    def __init__(self):
        self.model_p10 = GradientBoostingRegressor(loss='quantile', alpha=0.10, n_estimators=60, random_state=42)
        self.model_p50 = GradientBoostingRegressor(loss='quantile', alpha=0.50, n_estimators=60, random_state=42)
        self.model_p90 = GradientBoostingRegressor(loss='quantile', alpha=0.90, n_estimators=60, random_state=42)
        self.is_fitted = False
        self.day_of_week_means: Dict[int, float] = {}
        self.global_mean: float = 6500.0

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df['fecha']):
            df['fecha'] = pd.to_datetime(df['fecha'])

        df = df.sort_values('fecha').reset_index(drop=True)
        df['day_of_week'] = df['fecha'].dt.day_of_week
        df['is_weekend'] = df['day_of_week'].isin([4, 5, 6]).astype(int)
        df['day_of_month'] = df['fecha'].dt.day
        df['is_quincena'] = df['day_of_month'].isin([14, 15, 16, 29, 30, 31]).astype(int)

        df['lag_1'] = df['ventas_pesos'].shift(1)
        df['lag_7'] = df['ventas_pesos'].shift(7)
        df['rolling_mean_7'] = df['ventas_pesos'].rolling(window=7, min_periods=1).mean()

        mean_val = df['ventas_pesos'].mean()
        df['lag_1'] = df['lag_1'].fillna(mean_val)
        df['lag_7'] = df['lag_7'].fillna(mean_val)
        return df

    def fit(self, df_history: pd.DataFrame) -> bool:
        if len(df_history) < 7:
            self.global_mean = float(df_history['ventas_pesos'].mean()) if len(df_history) > 0 else 6500.0
            return False

        df_feat = self.extract_features(df_history)
        X = df_feat[['day_of_week', 'is_weekend', 'day_of_month', 'is_quincena', 'lag_1', 'lag_7', 'rolling_mean_7']]
        y = df_feat['ventas_pesos']

        self.model_p10.fit(X, y)
        self.model_p50.fit(X, y)
        self.model_p90.fit(X, y)
        self.is_fitted = True

        df_history['dow'] = pd.to_datetime(df_history['fecha']).dt.day_of_week
        self.day_of_week_means = df_history.groupby('dow')['ventas_pesos'].mean().to_dict()
        self.global_mean = float(df_history['ventas_pesos'].mean())
        return True

    def predict_next_days(self, df_history: pd.DataFrame, days_ahead: int = 7) -> List[Dict[str, Any]]:
        if not self.is_fitted:
            self.fit(df_history)

        predictions = []
        last_date = pd.to_datetime(df_history['fecha'].max()) if len(df_history) > 0 else pd.to_datetime(date.today())
        recent_sales = list(df_history.sort_values('fecha')['ventas_pesos'].tail(14)) if len(df_history) > 0 else [6500.0] * 14

        for step in range(1, days_ahead + 1):
            target_date = last_date + timedelta(days=step)
            dow = target_date.day_of_week
            is_we = 1 if dow in [4, 5, 6] else 0
            dom = target_date.day
            is_quin = 1 if dom in [14, 15, 16, 29, 30, 31] else 0

            lag1 = recent_sales[-1]
            lag7 = recent_sales[-7] if len(recent_sales) >= 7 else np.mean(recent_sales)
            roll_mean = np.mean(recent_sales[-7:])

            if self.is_fitted:
                x_input = pd.DataFrame(
                    [[dow, is_we, dom, is_quin, lag1, lag7, roll_mean]],
                    columns=['day_of_week', 'is_weekend', 'day_of_month', 'is_quincena', 'lag_1', 'lag_7', 'rolling_mean_7']
                )
                p10 = float(self.model_p10.predict(x_input)[0])
                p50 = float(self.model_p50.predict(x_input)[0])
                p90 = float(self.model_p90.predict(x_input)[0])
            else:
                base_val = self.day_of_week_means.get(dow, self.global_mean)
                if is_quin:
                    base_val *= 1.25
                p50 = base_val
                p10 = base_val * 0.85
                p90 = base_val * 1.20

            p10 = max(1000.0, p10)
            p50 = max(p10, p50)
            p90 = max(p50, p90)

            tacos_estimados = p50 / self.PRECIO_PROMEDIO_TACO
            kilos_carne = tacos_estimados / self.TACOS_POR_KG_CARNE
            kilos_tortilla = tacos_estimados / self.TACOS_POR_KG_TORTILLAS

            predictions.append({
                "fecha": target_date.strftime("%Y-%m-%d"),
                "dia_semana": ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"][dow],
                "es_fin_de_semana": bool(is_we),
                "es_quincena": bool(is_quin),
                "pronostico_pesos_p50": round(p50, 2),
                "escenario_pesimista_p10": round(p10, 2),
                "escenario_optimista_p90": round(p90, 2),
                "tacos_estimados": int(round(tacos_estimados)),
                "kilos_carne_sugeridos": round(kilos_carne, 1),
                "kilos_tortillas_sugeridos": round(kilos_tortilla, 1)
            })
            recent_sales.append(p50)

        return predictions
