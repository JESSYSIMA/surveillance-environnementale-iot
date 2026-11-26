
import streamlit as st
import pandas as pd
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime

st.set_page_config(
    page_title="Surveillance environnementale",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Surveillance environnementale")
st.write("Tableau de bord IoT — ESP32 et AWS")

# Paramètres
st.sidebar.title("⚙️ Paramètres")
seuil_fumee = st.sidebar.slider(
    "Seuil d'alerte fumée (MQ-2)",
    500, 4095, 3000
)

st.sidebar.write("Appareil : ESP32")
st.sidebar.write("Source : AWS DynamoDB")

if st.sidebar.button("🔄 Actualiser les mesures"):
    st.rerun()

# Connexion AWS DynamoDB
@st.cache_resource
def connexion_dynamodb():
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=st.secrets["AWS_DEFAULT_REGION"],
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=st.secrets["AWS_SESSION_TOKEN"]
    )
    return dynamodb.Table("SurveillanceData")

try:
    table = connexion_dynamodb()

    reponse = table.query(
        KeyConditionExpression=Key("deviceId").eq(
            "ESP32_Surveillance_Environnementale"
        ),
        ScanIndexForward=False,
        Limit=100
    )

    elements = reponse.get("Items", [])

    if not elements:
        st.warning("Aucune mesure trouvée pour cet appareil dans DynamoDB.")
        st.stop()

    donnees = pd.DataFrame(elements)

    donnees["time"] = pd.to_numeric(donnees["time"])
    donnees["temperature"] = pd.to_numeric(donnees["temperature"])
    donnees["humidity"] = pd.to_numeric(donnees["humidity"])
    donnees["smoke"] = pd.to_numeric(donnees["smoke"])

    # Conversion des timestamps en dates
    donnees["date"] = donnees["time"].apply(
        lambda x: datetime.fromtimestamp(
            x / 1000 if x > 100000000000 else x
        )
    )

    donnees = donnees.sort_values("date")

    derniere = donnees.iloc[-1]

    st.success("Connexion à DynamoDB réussie !")

    # Mesures actuelles
    st.subheader("📊 Mesures actuelles")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "🌡️ Température",
        f"{derniere['temperature']:.1f} °C"
    )

    col2.metric(
        "💧 Humidité",
        f"{derniere['humidity']:.1f} %"
    )

    col3.metric(
        "💨 Fumée (MQ-2)",
        f"{derniere['smoke']:.0f}"
    )

    # Alertes
    st.subheader("🚨 État du système")

    if derniere["smoke"] > seuil_fumee:
        st.error("ALERTE : seuil de fumée dépassé !")
    else:
        st.success("Système normal — aucun dépassement du seuil.")

    # Graphiques
    st.subheader("📈 Évolution des mesures")

    graphique = donnees.set_index("date")

    st.write("Température")
    st.line_chart(graphique["temperature"])

    st.write("Humidité")
    st.line_chart(graphique["humidity"])

    st.write("Fumée — valeur brute du MQ-2")
    st.line_chart(graphique["smoke"])

    # Historique
    st.subheader("📋 Historique des mesures")

    historique = donnees[
        ["date", "temperature", "humidity", "smoke"]
    ].sort_values("date", ascending=False)

    historique.columns = [
        "Date et heure",
        "Température (°C)",
        "Humidité (%)",
        "Fumée (ADC)"
    ]

    st.dataframe(historique, width="stretch")

    st.caption(
        "ESP32 | AWS IoT Core | DynamoDB | CloudWatch"
    )

except Exception as erreur:
    st.error("Impossible de récupérer les données AWS.")
    st.write("Détail de l'erreur :", str(erreur))
    st.info(
        "Vérifie que le Learner Lab est actif "
        "et que les identifiants AWS temporaires sont encore valides."
    )
