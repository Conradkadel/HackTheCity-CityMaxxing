from fastapi import FastAPI, Query
import duckdb
import pickle
import pandas as pd
import numpy as np

app = FastAPI(title="Hack the City - API de Previsão de Bus Bunching")

# 1. Carregar o modelo treinado
with open("modelo_bunching.pkl", "rb") as f:
    model = pickle.load(f)

# Obter as categorias oficiais do modelo
model_features = model.feature_name_

@app.get("/api/v1/buses/live")
def get_live_buses(linha: str = Query(..., description="Exemplo: 1715, 3508, 1709, 3512")):
    con = duckdb.connect("hackthecity.db", read_only=True)
    
    # Busca os pings recentes calculando o deslocamento espacial e delta de tempo REAL entre pings do mesmo autocarro
    query = """
        WITH pings_ord AS (
            SELECT 
                vehicle_id,
                latitude,
                longitude,
                timestamp_criado,
                stop_id,
                agency_id,
                COALESCE(route_short_name, route_id, 'Sem_Linha') AS linha_id,
                LAG(timestamp_criado) OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado) AS ts_prev,
                LAG(latitude) OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado) AS lat_prev,
                LAG(longitude) OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado) AS lon_prev,
                ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado DESC) as rn
            FROM tb_gps_filtrado
            WHERE UPPER(route_short_name) = UPPER(?) 
               OR UPPER(route_id) = UPPER(?)
        )
        SELECT 
            vehicle_id, 
            latitude, 
            longitude, 
            timestamp_criado, 
            stop_id, 
            agency_id, 
            linha_id AS linha,
            COALESCE(date_diff('second', ts_prev, timestamp_criado), 30) AS delta_tempo_veiculo,
            COALESCE(ABS(latitude - lat_prev) + ABS(longitude - lon_prev), 0.001) AS deslocamento_espacial
        FROM pings_ord
        WHERE rn = 1
        LIMIT 50;
    """
    
    search_param = str(linha).strip()
    df_live = con.execute(query, [search_param, search_param]).df()
    con.close()
    
    if df_live.empty:
        return {
            "status": "success", 
            "count": 0, 
            "data": [], 
            "message": f"Nenhum registo encontrado para a linha '{linha}'."
        }
    
    # 2. Construir as features DINÂMICAS esperadas pelo modelo
    df_live['timestamp_criado'] = pd.to_datetime(df_live['timestamp_criado'])
    df_live['hora_dia'] = df_live['timestamp_criado'].dt.hour
    df_live['dia_semana'] = df_live['timestamp_criado'].dt.dayofweek
    
    # Trata categorias garantindo a compatibilidade com o LightGBM
    df_live['linha'] = df_live['linha'].astype('category')
    df_live['agency_id'] = df_live['agency_id'].astype('category')

    features = df_live[['latitude', 'longitude', 'hora_dia', 'dia_semana', 'delta_tempo_veiculo', 'deslocamento_espacial', 'linha', 'agency_id']]
    
    # 3. Inferência com variação real
    probas = model.predict_proba(features)[:, 1]

    # 4. Formatar a resposta para o Front-End
    results = []
    for idx, row in df_live.iterrows():
        prob = float(probas[idx])
        
        if prob >= 0.60:
            risk_category = "high_probability"
            are_we_close = "YES"
        elif prob >= 0.35:
            risk_category = "medium_probability"
            are_we_close = "MODERATE"
        else:
            risk_category = "no_probability"
            are_we_close = "NO"

        results.append({
            "vehicle_id": str(row["vehicle_id"]),
            "linha": str(row["linha"]),
            "agency_id": str(row["agency_id"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "last_ping": row["timestamp_criado"].strftime("%Y-%m-%d %H:%M:%S"),
            "prediction": {
                "are_we_close_to_bunching": are_we_close,
                "risk_level": risk_category,
                "bunching_probability": round(prob, 2)
            }
        })

    return {"status": "success", "count": len(results), "data": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)