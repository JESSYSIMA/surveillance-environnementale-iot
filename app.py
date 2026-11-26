
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# Configuration de la page
st.set_page_config(
    page_title="Surveillance environnementale",
    page_icon="🌍",
    layout="wide"
)

# Titre
st.title("🌍 Surveillance environnementale")
st.write("Tableau de bord IoT — ESP32 et AWS")

st.info("Mode démonstration : les valeurs affichées sont fictives. La connexion aux données AWS sera ajoutée ensuite.")

# Paramètres
st.sidebar.title("⚙️ Paramètres")
seuil_fumee = st.sidebar.slider(
    "Seuil d'alerte fumée (valeur brute MQ-2)",
    min_value=500,
    max_value=4095,
    value=3000
)

st.sidebar.write("Appareil : ESP32")
st.sidebar.write("Statut : Simulation")

# Données de démonstration
donnees = pd.DataFrame({
    "Heure": [datetime.now() - timedelta(minutes=5*i) for i in range(11, -1, -1)],
    "Température (°C)": [22, 22.5, 23, 23.5, 24, 24.5, 25, 25.2, 25.5, 26, 25.8, 25.5],
    "Humidité (%)": [55, 54, 53, 52, 50, 49, 48, 47, 46, 45, 46, 47],
    "Fumée (ADC)": [900, 950, 1000, 1100, 1200, 1300, 1500, 1600, 1800, 1900, 2000, 2100]
})

# Dernières mesures
temperature = donnees["Température (°C)"].iloc[-1]
humidite = donnees["Humidité (%)"].iloc[-1]
fumee = donnees["Fumée (ADC)"].iloc[-1]

st.subheader("📊 Mesures actuelles")

col1, col2, col3 = st.columns(3)

col1.metric("🌡️ Température", f"{temperature} °C")
col2.metric("💧 Humidité", f"{humidite} %")
col3.metric("💨 Fumée (MQ-2)", f"{fumee}")

# État du système
st.subheader("🚨 État du système")

if fumee > seuil_fumee:
    st.error("ALERTE : seuil de fumée dépassé !")
else:
    st.success("Système normal — aucun dépassement du seuil.")

# Graphiques
st.subheader("📈 Évolution des mesures")

st.write("Température")
st.line_chart(donnees.set_index("Heure")["Température (°C)"])

st.write("Humidité")
st.line_chart(donnees.set_index("Heure")["Humidité (%)"])

st.write("Fumée — valeur brute du capteur MQ-2")
st.line_chart(donnees.set_index("Heure")["Fumée (ADC)"])

# Historique
st.subheader("📋 Historique des mesures")
st.dataframe(donnees.sort_values("Heure", ascending=False), use_container_width=True)

st.caption("Projet IoT — ESP32 | AWS IoT Core | DynamoDB | CloudWatch")
