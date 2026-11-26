import streamlit as st
import pandas as pd
import boto3
import json
import ssl
import tempfile
import threading
import paho.mqtt.client as mqtt

from boto3.dynamodb.conditions import Key
from datetime import datetime

# ==========================================
# 1. CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="Surveillance Environnementale",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

if st.sidebar.button("🔄 Actualiser les données",
                     use_container_width=True):
    st.rerun()

st.sidebar.divider()
st.sidebar.caption("Source : AWS DynamoDB")
st.sidebar.caption("Région : us-east-1")

# ==========================================
# 3. CONTROLE DES CAPTEURS VIA MQTT
# ==========================================

def envoyer_commande(temperature, humidity, smoke):

    topic = "surveillance/environnement/commandes"

    payload = json.dumps({
        "temperature": float(temperature),
        "humidity": float(humidity),
        "smoke": int(smoke)
    })

    client = None

    try:
        with tempfile.TemporaryDirectory() as dossier:

            ca_file = f"{dossier}/AmazonRootCA1.pem"
            cert_file = f"{dossier}/certificate.pem.crt"
            key_file = f"{dossier}/private.pem.key"

            with open(ca_file, "w") as f:
                f.write(st.secrets["AWS_IOT_ROOT_CA"])

            with open(cert_file, "w") as f:
                f.write(st.secrets["AWS_IOT_CERTIFICATE"])

            with open(key_file, "w") as f:
                f.write(st.secrets["AWS_IOT_PRIVATE_KEY"])

            connexion = threading.Event()
            erreur_connexion = []

            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="Streamlit_Surveillance_Commandes"
            )

            client.tls_set(
                ca_certs=ca_file,
                certfile=cert_file,
                keyfile=key_file,
                tls_version=ssl.PROTOCOL_TLS_CLIENT
            )

            def on_connect(client, userdata, flags,
                           reason_code, properties):
                if reason_code == 0:
                    connexion.set()
                else:
                    erreur_connexion.append(str(reason_code))
                    connexion.set()

            client.on_connect = on_connect

            client.connect(
                st.secrets["AWS_IOT_ENDPOINT"],
                8883,
                60
            )

            client.loop_start()

            try:
                if not connexion.wait(timeout=15):
                    raise TimeoutError(
                        "Délai dépassé lors de la connexion MQTT."
                    )

                if erreur_connexion:
                    raise Exception(
                        "Connexion MQTT refusée : "
                        + erreur_connexion[0]
                    )

                resultat = client.publish(
                    topic,
                    payload,
                    qos=1
                )

                if resultat.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise Exception(
                        "Impossible de publier la commande MQTT."
                    )

                resultat.wait_for_publish(timeout=15)

                if not resultat.is_published():
                    raise TimeoutError(
                        "La publication MQTT n'a pas été confirmée."
                    )

                return True, "Commande envoyée avec succès !"

            finally:
                client.loop_stop()
                client.disconnect()

    except Exception as erreur:
        return False, str(erreur)


# ==========================================
# 4. INTERFACE DE CONTROLE
# ==========================================

st.divider()
st.subheader("🎛️ Contrôle à distance de l'ESP32")

st.info(
    "Modifie les valeurs des capteurs simulés "
    "et envoie les commandes directement à ton ESP32 via AWS IoT Core."
)

with st.form("formulaire_commandes"):

    col1, col2, col3 = st.columns(3)

    with col1:
        temperature_commande = st.slider(
            "🌡️ Température (°C)",
            min_value=-10,
            max_value=60,
            value=25
        )

    with col2:
        humidite_commande = st.slider(
            "💧 Humidité (%)",
            min_value=0,
            max_value=100,
            value=60
        )

    with col3:
        fumee_commande = st.slider(
            "💨 Fumée MQ-2 (ADC)",
            min_value=0,
            max_value=4095,
            value=1200
        )

    envoyer = st.form_submit_button(
        "🚀 Envoyer les commandes à l'ESP32",
        use_container_width=True
    )

if envoyer:

    with st.spinner("Envoi des commandes vers AWS IoT Core..."):

        succes, message = envoyer_commande(
            temperature_commande,
            humidite_commande,
            fumee_commande
        )

    if succes:
        st.success(message)
        st.write("Valeurs envoyées :")
        st.json({
            "temperature": temperature_commande,
            "humidity": humidite_commande,
            "smoke": fumee_commande
        })
    else:
        st.error("Erreur lors de l'envoi de la commande.")
        st.code(message)


# ==========================================
# 5. CONNEXION DYNAMODB
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
# 6. RECUPERATION DES DONNEES
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

    unite = (
        "ms"
        if donnees["time"].max() > 100000000000
        else "s"
    )

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
    # 7. INFORMATIONS GENERALES
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
    # 8. MESURES ACTUELLES
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
    # 9. SYSTEME D'ALERTE
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
    # 10. GRAPHIQUES
    # ==========================================

    st.subheader("📈 Analyse des mesures")

    tab1, tab2, tab3 = st.tabs([
        "🌡️ Température",
        "💧 Humidité",
        "💨 Fumée"
    ])

    graphique = donnees.set_index("date")

    with tab1:

        st.caption(
            "Évolution de la température au cours du temps"
        )

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

        st.caption(
            "Évolution de la valeur brute du capteur MQ-2"
        )

        st.line_chart(
            graphique["smoke"],
            color="#E74C3C",
            height=350
        )

    st.divider()

    # ==========================================
    # 11. HISTORIQUE
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
    # 12. PIED DE PAGE
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
