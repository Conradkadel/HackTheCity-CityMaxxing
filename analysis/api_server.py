from fastapi import FastAPI, Query
import duckdb
import pickle
import pandas as pd
import numpy as np

app = FastAPI(title="Hack the City - API de Previsão de Bus Bunching")

# 1. Carregar o modelo treinado
with open("modelo_bunching.pkl", "rb") as f:
    model = pickle.load(f)

@app.get("/api/v1/buses/live")
def get_live_buses(linha: str = Query(..., description="Exemplo: 750, 1715, M22")):
    con = duckdb.connect("hackthecity.db", read_only=True)
    
    # Busca as últimas posições conhecidas dos autocarros da linha
    query = """
        WITH ultimos_pings AS (
            SELECT 
                vehicle_id,
                latitude,
                longitude,
                timestamp_criado,
                stop_id,
                agency_id,
                COALESCE(route_short_name, route_id) AS linha,
                ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY timestamp_criado DESC) as rn
            FROM tb_gps_filtrado
            WHERE COALESCE(route_short_name, route_id) = ?
        )
        SELECT vehicle_id, latitude, longitude, timestamp_criado, stop_id, agency_id, linha
        FROM ultimos_pings
        WHERE rn = 1;
    """
    
    df_live = con.execute(query, [linha]).df()
    con.close()
    
    if df_live.empty:
        return {"status": "success", "count": 0, "data": [], "message": "Nenhum autocarro ativo encontrado para esta linha."}
    
    # 2. Construir as features esperadas pelo modelo
    df_live['timestamp_criado'] = pd.to_datetime(df_live['timestamp_criado'])
    df_live['hora_dia'] = df_live['timestamp_criado'].dt.hour
    df_live['dia_semana'] = df_live['timestamp_criado'].dt.dayofweek
    df_live['delta_tempo_veiculo'] = 30  # Assumindo intervalo de atualização de 30s
    df_live['deslocamento_espacial'] = 0.002 # Média de deslocamento
    
    df_live['linha'] = df_live['linha'].astype('category')
    df_live['agency_id'] = df_live['agency_id'].astype('category')

    features = df_live[['latitude', 'longitude', 'hora_dia', 'dia_semana', 'delta_tempo_veiculo', 'deslocamento_espacial', 'linha', 'agency_id']]
    
    # 3. Fazer a inferência com o modelo
    probas = model.predict_proba(features)[:, 1]

    # 4. Formatar a resposta para o Front-End
    results = []
    for idx, row in df_live.iterrows():
        prob = float(probas[idx])
        
        if prob >= 0.65:
            risk_category = "high_probability"
            are_we_close = "YES"
        elif prob >= 0.40:
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