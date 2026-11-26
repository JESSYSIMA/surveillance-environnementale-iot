
import streamlit as st
import pandas as pd
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime
import json
import ssl
import tempfile
import paho.mqtt.client as mqtt

# ==========================================
# 1. CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="Surveillance Environnementale",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Style général
st.title("🌍 Surveillance environnementale")
st.caption("Plateforme IoT de surveillance en temps réel | ESP32 • AWS")

# ==========================================
# 2. PARAMETRES
# ==========================================

st.sidebar.title("⚙️ Configuration")

st.sidebar.markdown("### Appareil")
st.sidebar.info("ESP32 - Surveillance environnementale")

seuil_fumee = st.sidebar.number_input(
    "Seuil d'alerte MQ-2",
    min_value=500,
    max_value=4095,
    value=3000,
    step=100
)

nombre_mesures = st.sidebar.selectbox(
    "Nombre de mesures à afficher",
    [10, 25, 50, 100],
    index=3
)

if st.sidebar.button("🔄 Actualiser les données", use_container_width=True):
    st.rerun()

st.sidebar.divider()
st.sidebar.caption("Source : AWS DynamoDB")
st.sidebar.caption("Région : us-east-1")

# ==========================================
# 3. CONNEXION AWS
# ==========================================


def connexion_dynamodb():
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=st.secrets["AWS_DEFAULT_REGION"],
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=st.secrets["AWS_SESSION_TOKEN"]
    )

    return dynamodb.Table("SurveillanceData")


# ==========================================
# 4. RECUPERATION DES DONNEES
# ==========================================

try:
    table = connexion_dynamodb()

    reponse = table.query(
        KeyConditionExpression=Key("deviceId").eq(
            "ESP32_Surveillance_Environnementale"
        ),
        ScanIndexForward=False,
        Limit=nombre_mesures
    )

    elements = reponse.get("Items", [])

    if not elements:
        st.warning("Aucune mesure disponible dans DynamoDB.")
        st.stop()

    donnees = pd.DataFrame(elements)

    colonnes = ["time", "temperature", "humidity", "smoke"]

    for colonne in colonnes:
        donnees[colonne] = pd.to_numeric(
            donnees[colonne],
            errors="coerce"
        )

    donnees = donnees.dropna(subset=colonnes)

    if donnees.empty:
        st.warning("Les mesures récupérées ne sont pas valides.")
        st.stop()

    # Conversion du timestamp
    unite = "ms" if donnees["time"].max() > 100000000000 else "s"

    donnees["date"] = pd.to_datetime(
        donnees["time"],
        unit=unite
    )

    donnees = donnees.sort_values("date")

    derniere = donnees.iloc[-1]

    temperature = float(derniere["temperature"])
    humidite = float(derniere["humidity"])
    fumee = float(derniere["smoke"])

    # ==========================================
    # 5. INFORMATIONS GENERALES
    # ==========================================

    col_a, col_b = st.columns([2, 1])

    with col_a:
        st.success("Connexion AWS DynamoDB opérationnelle")

    with col_b:
        st.caption(
            "Dernière mesure : "
            + derniere["date"].strftime("%d/%m/%Y %H:%M:%S")
        )

    st.divider()

    # ==========================================
    # 6. CARTES DES MESURES
    # ==========================================

    st.subheader("📊 Mesures actuelles")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            label="🌡️ Température",
            value=f"{temperature:.1f} °C"
        )

    with col2:
        st.metric(
            label="💧 Humidité",
            value=f"{humidite:.1f} %"
        )

    with col3:
        st.metric(
            label="💨 Fumée MQ-2",
            value=f"{fumee:.0f} ADC"
        )

    st.divider()

    # ==========================================
    # 7. SYSTEME D'ALERTE
    # ==========================================

    st.subheader("🚨 Surveillance et alertes")

    col1, col2 = st.columns([2, 1])

    with col1:
        if fumee >= seuil_fumee:
            st.error(
                f"🚨 ALERTE ! Niveau de fumée élevé : "
                f"{fumee:.0f} ADC"
            )
            st.write(
                f"La mesure a atteint ou dépassé "
                f"le seuil de {seuil_fumee} ADC."
            )
        else:
            st.success(
                f"✅ Système normal — Niveau de fumée : "
                f"{fumee:.0f} ADC"
            )
            st.write("Aucun dépassement du seuil d'alerte.")

    with col2:
        st.metric(
            "Seuil configuré",
            f"{seuil_fumee} ADC"
        )

    st.divider()

    # ==========================================
    # 8. GRAPHIQUES
    # ==========================================

    st.subheader("📈 Analyse des mesures")

    tab1, tab2, tab3 = st.tabs([
        "🌡️ Température",
        "💧 Humidité",
        "💨 Fumée"
    ])

    graphique = donnees.set_index("date")

    with tab1:
        st.caption("Évolution de la température au cours du temps")
        st.line_chart(
            graphique["temperature"],
            color="#F28E2B",
            height=350
        )

    with tab2:
        st.caption("Évolution du taux d'humidité")
        st.area_chart(
            graphique["humidity"],
            color="#3498DB",
            height=350
        )

    with tab3:
        st.caption("Évolution de la valeur brute du capteur MQ-2")
        st.line_chart(
            graphique["smoke"],
            color="#E74C3C",
            height=350
        )

    st.divider()

    # ==========================================
    # 9. HISTORIQUE
    # ==========================================

    st.subheader("📋 Historique des mesures")

    historique = donnees[
        ["date", "temperature", "humidity", "smoke"]
    ].sort_values("date", ascending=False).copy()

    historique.columns = [
        "Date et heure",
        "Température (°C)",
        "Humidité (%)",
        "Fumée (ADC)"
    ]

    st.dataframe(
        historique,
        width="stretch",
        hide_index=True
    )

    # Export CSV
    csv = historique.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        label="📥 Télécharger l'historique CSV",
        data=csv,
        file_name="historique_surveillance.csv",
        mime="text/csv"
    )

    # ==========================================
    # 10. PIED DE PAGE
    # ==========================================

    st.divider()

    st.caption(
        "Projet IoT - Surveillance environnementale"
    )

    st.caption(
        "ESP32 | AWS IoT Core | DynamoDB | CloudWatch | Streamlit"
    )

except Exception as erreur:
    st.error("Impossible de récupérer les données AWS.")
    st.code(str(erreur))
    st.info(
        "Vérifie les identifiants temporaires AWS "
        "et les autorisations DynamoDB."
    )
