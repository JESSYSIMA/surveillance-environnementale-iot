
import streamlit as st
import pandas as pd
import boto3
import json
import ssl
import tempfile
import threading
import queue
import uuid
import time

import paho.mqtt.client as mqtt

from pathlib import Path
from boto3.dynamodb.conditions import Key


# ==========================================
# 1. CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="Surveillance environnementale",
    page_icon="🌍",
    layout="wide"
)

DEVICE_ID = "ESP32_Surveillance_Environnementale"
TABLE_NAME = "SurveillanceData"

TOPIC_MESURES = "surveillance/environnement/mesures"
TOPIC_COMMANDES = "surveillance/environnement/commandes"

st.title("🌍 Surveillance environnementale")

st.caption(
    "Plateforme IoT bidirectionnelle en temps réel | "
    "ESP32 • Wokwi • AWS • Streamlit"
)


# ==========================================
# 2. BARRE LATERALE
# ==========================================

st.sidebar.title("⚙️ Configuration")

st.sidebar.markdown("### Appareil")

st.sidebar.info(
    "ESP32 - Surveillance environnementale"
)

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

st.sidebar.divider()

st.sidebar.caption("Broker : AWS IoT Core")
st.sidebar.caption("Stockage : AWS DynamoDB")
st.sidebar.caption("Supervision : CloudWatch")
st.sidebar.caption("Région : us-east-1")
st.sidebar.caption("Synchronisation MQTT : 1 seconde")
st.sidebar.caption("Historique : 5 secondes")


# ==========================================
# 3. INITIALISATION DES VARIABLES
# ==========================================

valeurs_initiales = {
    "temperature_commande": 25.0,
    "humidite_commande": 60.0,
    "fumee_commande": 1200,
    "derniere_mesure": None,
    "commande_message": "",
    "commande_succes": False,
    "commandes_attente": {}
}

for cle, valeur in valeurs_initiales.items():

    if cle not in st.session_state:
        st.session_state[cle] = valeur


# ==========================================
# 4. CONNEXION MQTT PERMANENTE
# ==========================================

def initialiser_mqtt():

    if "mqtt_client" in st.session_state:
        return

    messages = queue.Queue(maxsize=100)

    connexion = threading.Event()

    dossier = tempfile.TemporaryDirectory()

    ca_file = Path(dossier.name) / "AmazonRootCA1.pem"

    cert_file = (
        Path(dossier.name) / "certificate.pem.crt"
    )

    key_file = Path(dossier.name) / "private.pem.key"

    # Chargement des certificats AWS
    ca_file.write_text(
        st.secrets["AWS_IOT_ROOT_CA"],
        encoding="utf-8"
    )

    cert_file.write_text(
        st.secrets["AWS_IOT_CERTIFICATE"],
        encoding="utf-8"
    )

    key_file.write_text(
        st.secrets["AWS_IOT_PRIVATE_KEY"],
        encoding="utf-8"
    )

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="Streamlit_" + uuid.uuid4().hex[:12],
        protocol=mqtt.MQTTv311
    )

    client.tls_set(
        ca_certs=str(ca_file),
        certfile=str(cert_file),
        keyfile=str(key_file),
        tls_version=ssl.PROTOCOL_TLS_CLIENT
    )

    client.reconnect_delay_set(
        min_delay=1,
        max_delay=30
    )

    # Connexion au broker
    def on_connect(
        client,
        userdata,
        flags,
        reason_code,
        properties
    ):

        if reason_code == 0:

            print("Connexion AWS IoT Core réussie")

            client.subscribe(
                TOPIC_MESURES,
                qos=1
            )

        else:

            connexion.clear()

            print(
                "Erreur connexion MQTT :",
                reason_code
            )

    # Confirmation de l'abonnement
    def on_subscribe(
        client,
        userdata,
        mid,
        reason_code_list,
        properties
    ):

        if reason_code_list and all(
            not code.is_failure
            for code in reason_code_list
        ):
            connexion.set()
            print("Abonnement MQTT réussi")

        else:
            connexion.clear()
            print("Abonnement MQTT refusé")

    # Déconnexion du broker
    def on_disconnect(
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties
    ):

        connexion.clear()

        print("Connexion MQTT interrompue")

    # Réception des mesures Wokwi
    def on_message(client, userdata, message):

        try:

            data = json.loads(
                message.payload.decode("utf-8")
            )

            mesure = {
                "temperature": float(
                    data["temperature"]
                ),
                "humidity": float(
                    data["humidity"]
                ),
                "smoke": int(
                    data["smoke"]
                ),
                "received_at": time.time()
            }

            # Vérification des valeurs
            if not (
                -40 <= mesure["temperature"] <= 80
                and 0 <= mesure["humidity"] <= 100
                and 0 <= mesure["smoke"] <= 4095
            ):
                return

            # Eviter une accumulation des messages
            if messages.full():

                try:
                    messages.get_nowait()

                except queue.Empty:
                    pass

            messages.put_nowait(mesure)

            print("Mesure MQTT reçue :", mesure)

        except Exception as erreur:

            print("Erreur réception MQTT :", erreur)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Connexion asynchrone
    client.connect_async(
        st.secrets["AWS_IOT_ENDPOINT"],
        8883,
        60
    )

    client.loop_start()

    st.session_state.mqtt_client = client
    st.session_state.mqtt_messages = messages
    st.session_state.mqtt_connexion = connexion
    st.session_state.mqtt_dossier = dossier


try:

    initialiser_mqtt()

except Exception as erreur:

    st.error("Impossible d'initialiser MQTT.")

    st.code(str(erreur))

    st.stop()


# ==========================================
# 5. ENVOI DES COMMANDES VERS WOKWI
# ==========================================

def envoyer_commande(champ, valeur):

    client = st.session_state.mqtt_client

    if not st.session_state.mqtt_connexion.is_set():

        return False, "Connexion MQTT indisponible."

    payload = json.dumps({
        champ: valeur
    })

    try:

        resultat = client.publish(
            TOPIC_COMMANDES,
            payload,
            qos=1,
            retain=False
        )

        if resultat.rc != mqtt.MQTT_ERR_SUCCESS:

            return False, "Erreur de publication MQTT."

        resultat.wait_for_publish(timeout=5)

        if resultat.is_published():

            return True, (
                f"Commande publiée : {champ} = {valeur}"
            )

        return False, "Publication non confirmée."

    except Exception as erreur:

        return False, str(erreur)


# ==========================================
# 6. MODIFICATION AUTOMATIQUE DES CURSEURS
# ==========================================

def commande_automatique(champ, cle):

    valeur = st.session_state[cle]

    succes, message = envoyer_commande(
        champ,
        valeur
    )

    st.session_state.commande_succes = succes

    st.session_state.commande_message = message

    if succes:

        # Attendre la confirmation par les mesures ESP32
        st.session_state.commandes_attente[champ] = {
            "valeur": valeur,
            "expiration": time.time() + 8
        }


# ==========================================
# 7. RECEPTION ET SYNCHRONISATION MQTT
# ==========================================

def synchroniser_mesures():

    messages = st.session_state.mqtt_messages

    derniere = None

    while True:

        try:

            derniere = messages.get_nowait()

        except queue.Empty:

            break

    if derniere is not None:

        st.session_state.derniere_mesure = derniere

    mesure = st.session_state.derniere_mesure

    if mesure is None:
        return

    correspondance = {
        "temperature": "temperature_commande",
        "humidity": "humidite_commande",
        "smoke": "fumee_commande"
    }

    attente = st.session_state.commandes_attente

    for champ, cle in correspondance.items():

        valeur = mesure[champ]

        # Eviter qu'une ancienne mesure MQTT
        # écrase immédiatement une commande récente
        if champ in attente:

            commande = attente[champ]

            confirmation = (
                abs(valeur - commande["valeur"]) < 0.11
                if champ != "smoke"
                else valeur == commande["valeur"]
            )

            expiree = (
                time.time() >= commande["expiration"]
            )

            if confirmation or expiree:

                del attente[champ]

            else:

                continue

        # Mise à jour avant la création des widgets
        if champ == "smoke":

            st.session_state[cle] = int(valeur)

        else:

            st.session_state[cle] = float(
                round(valeur, 1)
            )


# ==========================================
# 8. CONTROLE ET MESURES EN TEMPS REEL
# ==========================================

@st.fragment(run_every="1s")
def afficher_temps_reel():

    synchroniser_mesures()

    mesure = st.session_state.derniere_mesure

    connecte = (
        st.session_state.mqtt_connexion.is_set()
    )

    esp_actif = (
        mesure is not None
        and time.time() - mesure["received_at"] < 15
    )

    # --------------------------------------
    # Etat de connexion
    # --------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        if connecte:

            st.success("🟢 AWS IoT Core connecté")

        else:

            st.warning("🟠 Connexion MQTT en cours...")

    with col2:

        if esp_actif and connecte:

            st.success("🟢 ESP32 Wokwi actif")

        else:

            st.warning("🟠 En attente des mesures ESP32")

    st.divider()

    # --------------------------------------
    # Curseurs synchronisés
    # --------------------------------------

    st.subheader("🎛️ Contrôle à distance de l'ESP32")

    st.info(
        "Modifie les capteurs dans Wokwi ou les curseurs "
        "dans Streamlit. Les valeurs logiques de l'ESP32 "
        "sont automatiquement synchronisées via MQTT."
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.slider(
            "🌡️ Température (°C)",
            min_value=-40.0,
            max_value=80.0,
            step=0.1,
            key="temperature_commande",
            on_change=commande_automatique,
            args=(
                "temperature",
                "temperature_commande"
            ),
            disabled=not (connecte and esp_actif)
        )

    with col2:

        st.slider(
            "💧 Humidité (%)",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            key="humidite_commande",
            on_change=commande_automatique,
            args=(
                "humidity",
                "humidite_commande"
            ),
            disabled=not (connecte and esp_actif)
        )

    with col3:

        st.slider(
            "💨 Fumée MQ-2 (ADC)",
            min_value=0,
            max_value=4095,
            step=1,
            key="fumee_commande",
            on_change=commande_automatique,
            args=(
                "smoke",
                "fumee_commande"
            ),
            disabled=not (connecte and esp_actif)
        )

    if st.session_state.commande_message:

        if st.session_state.commande_succes:

            st.success(
                st.session_state.commande_message
            )

        else:

            st.error(
                st.session_state.commande_message
            )

    if st.session_state.commandes_attente:

        st.caption(
            "⏳ En attente du retour des mesures ESP32..."
        )

    st.divider()

    # --------------------------------------
    # Mesures reçues directement par MQTT
    # --------------------------------------

    st.subheader("📊 Mesures en temps réel")

    if mesure is None:

        st.info(
            "Démarre la simulation Wokwi "
            "pour recevoir les premières mesures."
        )

        return

    if not esp_actif or not connecte:

        st.warning(
            "Les mesures affichées ne sont plus récentes."
        )

    temperature = mesure["temperature"]
    humidite = mesure["humidity"]
    fumee = mesure["smoke"]

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
            value=f"{fumee} ADC"
        )

    date_reception = pd.to_datetime(
        mesure["received_at"],
        unit="s",
        utc=True
    ).tz_convert("Africa/Algiers")

    st.caption(
        "Dernière mesure MQTT : "
        + date_reception.strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    )

    st.divider()

    # --------------------------------------
    # Alertes en temps réel
    # --------------------------------------

    st.subheader("🚨 Surveillance et alertes")

    col1, col2 = st.columns([2, 1])

    with col1:

        if not esp_actif or not connecte:

            st.warning(
                "Etat actuel inconnu : "
                "aucune mesure récente."
            )

        elif fumee >= seuil_fumee:

            st.error(
                f"🚨 ALERTE ! Niveau de fumée élevé : "
                f"{fumee} ADC"
            )

            st.write(
                f"Le seuil de {seuil_fumee} ADC "
                "est atteint ou dépassé."
            )

        else:

            st.success(
                f"✅ Système normal — Fumée : "
                f"{fumee} ADC"
            )

            st.write(
                "Aucun dépassement du seuil de fumée."
            )

    with col2:

        st.metric(
            "Seuil d'alerte",
            f"{seuil_fumee} ADC"
        )

    st.progress(
        min(max(fumee / 4095, 0.0), 1.0),
        text="Niveau du signal MQ-2"
    )

    # Affichage du message JSON
    with st.expander("📡 Dernier message MQTT reçu"):

        st.json({
            "temperature": temperature,
            "humidity": humidite,
            "smoke": fumee
        })


# ==========================================
# 9. CONNEXION A DYNAMODB
# ==========================================

def connexion_dynamodb():

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=st.secrets["AWS_DEFAULT_REGION"],
        aws_access_key_id=st.secrets[
            "AWS_ACCESS_KEY_ID"
        ],
        aws_secret_access_key=st.secrets[
            "AWS_SECRET_ACCESS_KEY"
        ],
        aws_session_token=st.secrets[
            "AWS_SESSION_TOKEN"
        ]
    )

    return dynamodb.Table(TABLE_NAME)


# ==========================================
# 10. HISTORIQUE ET GRAPHIQUES
# ==========================================

@st.fragment(run_every="5s")
def afficher_historique():

    st.divider()

    st.subheader("📈 Analyse des mesures")

    try:

        table = connexion_dynamodb()

        reponse = table.query(
            KeyConditionExpression=Key(
                "deviceId"
            ).eq(DEVICE_ID),
            ScanIndexForward=False,
            Limit=nombre_mesures
        )

        elements = reponse.get("Items", [])

        if not elements:

            st.warning(
                "Aucune mesure disponible dans DynamoDB."
            )

            return

        donnees = pd.DataFrame(elements)

        colonnes = [
            "time",
            "temperature",
            "humidity",
            "smoke"
        ]

        for colonne in colonnes:

            donnees[colonne] = pd.to_numeric(
                donnees[colonne],
                errors="coerce"
            )

        donnees = donnees.dropna(
            subset=colonnes
        )

        if donnees.empty:

            st.warning(
                "Les mesures récupérées sont invalides."
            )

            return

        unite = (
            "ms"
            if donnees["time"].max() > 100000000000
            else "s"
        )

        donnees["date"] = pd.to_datetime(
            donnees["time"],
            unit=unite,
            utc=True
        ).dt.tz_convert("Africa/Algiers")

        donnees = donnees.sort_values("date")

        st.success(
            "🟢 Connexion AWS DynamoDB opérationnelle"
        )

        st.caption(
            f"{len(donnees)} mesures récupérées "
            "depuis DynamoDB."
        )

        # ----------------------------------
        # Statistiques
        # ----------------------------------

        st.subheader("📉 Statistiques")

        col1, col2, col3 = st.columns(3)

        with col1:

            st.metric(
                "Température moyenne",
                f"{donnees['temperature'].mean():.1f} °C"
            )

        with col2:

            st.metric(
                "Humidité moyenne",
                f"{donnees['humidity'].mean():.1f} %"
            )

        with col3:

            st.metric(
                "Fumée maximale",
                f"{donnees['smoke'].max():.0f} ADC"
            )

        # ----------------------------------
        # Graphiques
        # ----------------------------------

        tab1, tab2, tab3 = st.tabs([
            "🌡️ Température",
            "💧 Humidité",
            "💨 Fumée"
        ])

        graphique = donnees.set_index("date")

        with tab1:

            st.caption(
                "Évolution de la température"
            )

            st.line_chart(
                graphique["temperature"],
                color="#F28E2B",
                height=350
            )

        with tab2:

            st.caption(
                "Évolution du taux d'humidité"
            )

            st.area_chart(
                graphique["humidity"],
                color="#3498DB",
                height=350
            )

        with tab3:

            st.caption(
                "Évolution du signal MQ-2 "
                "et seuil d'alerte"
            )

            graphique_fumee = graphique[
                ["smoke"]
            ].copy()

            graphique_fumee["seuil"] = seuil_fumee

            graphique_fumee.columns = [
                "Fumée",
                "Seuil d'alerte"
            ]

            st.line_chart(
                graphique_fumee,
                color=["#E74C3C", "#F39C12"],
                height=350
            )

        st.divider()

        # ----------------------------------
        # Historique
        # ----------------------------------

        st.subheader("📋 Historique des mesures")

        historique = donnees[
            [
                "date",
                "temperature",
                "humidity",
                "smoke"
            ]
        ].sort_values(
            "date",
            ascending=False
        ).copy()

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

        # ----------------------------------
        # Export CSV
        # ----------------------------------

        csv = historique.to_csv(
            index=False
        ).encode("utf-8-sig")

        st.download_button(
            label="📥 Télécharger l'historique CSV",
            data=csv,
            file_name="historique_surveillance.csv",
            mime="text/csv"
        )

    except Exception as erreur:

        st.error(
            "Impossible de récupérer les données DynamoDB."
        )

        st.code(str(erreur))

        st.info(
            "Vérifie les identifiants temporaires AWS "
            "Learner Lab et les autorisations DynamoDB."
        )


# ==========================================
# 11. LANCEMENT DU DASHBOARD
# ==========================================

afficher_temps_reel()

afficher_historique()


# ==========================================
# 12. PIED DE PAGE
# ==========================================

st.divider()

st.caption(
    "Projet IoT — Surveillance environnementale"
)

st.caption(
    "ESP32 | Wokwi | MQTT/TLS | AWS IoT Core | "
    "DynamoDB | CloudWatch | Streamlit"
)
