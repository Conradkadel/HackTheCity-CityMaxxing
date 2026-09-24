import duckdb
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import lightgbm as lgb
import pickle

print("🚀 A carregar dados corrigidos para treino (sem Data Leakage)...")
con = duckdb.connect("hackthecity.db")

# Query corrigida: usa o histórico do veículo e da paragem anterior
df_features = con.execute("""
    WITH gps_ord AS (
        SELECT 
            _id,
            agency_id,
            vehicle_id,
            trip_id,
            stop_id,
            latitude,
            longitude,
            timestamp_criado,
            COALESCE(route_short_name, route_id, 'Unknown') AS linha,
            EXTRACT(HOUR FROM timestamp_criado) AS hora_dia,
            EXTRACT(DOW FROM timestamp_criado) AS dia_semana,
            
            -- Headway na paragem atual (Target)
            LAG(timestamp_criado) OVER (
                PARTITION BY stop_id, COALESCE(route_short_name, route_id) 
                ORDER BY timestamp_criado
            ) AS ts_anterior_paragem,
            
            -- Posição/Tempo anterior do MESMO veículo (para calcular velocidade/deslocamento)
            LAG(timestamp_criado) OVER (
                PARTITION BY vehicle_id 
                ORDER BY timestamp_criado
            ) AS ts_veiculo_prev,
            
            LAG(latitude) OVER (
                PARTITION BY vehicle_id 
                ORDER BY timestamp_criado
            ) AS lat_prev,
            
            LAG(longitude) OVER (
                PARTITION BY vehicle_id 
                ORDER BY timestamp_criado
            ) AS lon_prev
            
        FROM tb_gps_filtrado
        WHERE stop_id IS NOT NULL AND stop_id != ''
    ),
    features_calc AS (
        SELECT 
            latitude,
            longitude,
            hora_dia,
            dia_semana,
            linha,
            agency_id,
            -- Target
            date_diff('second', ts_anterior_paragem, timestamp_criado) AS headway_segundos,
            -- Feature: Tempo decorrido desde a última transmissão de GPS do veículo
            COALESCE(date_diff('second', ts_veiculo_prev, timestamp_criado), 30) AS delta_tempo_veiculo,
            -- Feature: Deslocamento aproximado
            COALESCE(ABS(latitude - lat_prev) + ABS(longitude - lon_prev), 0.0) AS deslocamento_espacial
        FROM gps_ord
        WHERE ts_anterior_paragem IS NOT NULL
    )
    SELECT 
        latitude,
        longitude,
        hora_dia,
        dia_semana,
        delta_tempo_veiculo,
        deslocamento_espacial,
        linha,
        agency_id,
        CASE WHEN headway_segundos <= 120 THEN 1 ELSE 0 END AS target_bunching
    FROM features_calc
    WHERE headway_segundos <= 3600
    USING SAMPLE 300000;
""").df()

con.close()

print(f"✅ Dados extraídos: {len(df_features):,} linhas para treino.")

# Tratamento de Tipos
df_features['linha'] = df_features['linha'].astype('category')
df_features['agency_id'] = df_features['agency_id'].astype('category')

X = df_features[['latitude', 'longitude', 'hora_dia', 'dia_semana', 'delta_tempo_veiculo', 'deslocamento_espacial', 'linha', 'agency_id']]
y = df_features['target_bunching']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

print("🧠 A treinar o modelo preditivo corrigido...")
model = lgb.LGBMClassifier(
    n_estimators=120,
    learning_rate=0.03,
    max_depth=5,
    class_weight='balanced',
    verbosity=-1,
    random_state=42
)

model.fit(X_train, y_train)

# Avaliação
y_pred_proba = model.predict_proba(X_test)[:, 1]
y_pred = (y_pred_proba >= 0.5).astype(int)

print("\n--- Relatório do Modelo Corrigido ---")
print(classification_report(y_test, y_pred))
print(f"ROC-AUC Score: {roc_auc_score(y_test, y_pred_proba):.4f}")

# Guardar Modelo
with open("modelo_bunching.pkl", "wb") as f:
    pickle.dump(model, f)

print("\n💾 Novo modelo guardado como 'modelo_bunching.pkl' com sucesso!")