"""Small paho-mqtt helper shared by the controller, simulator and tag learner."""
import paho.mqtt.client as mqtt


def client(client_id: str, will: tuple[str, str] | None = None) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
    if will:
        c.will_set(will[0], will[1], qos=1, retain=True)
    return c
