# MySkoda PublicAPI — Home Assistant Integration

Home-Assistant-Integration für die **offizielle MyŠkoda Public API**
([Doku](https://public.api.connect.skoda-auto.cz/docs) ·
[API-Referenz](https://public.api.connect.skoda-auto.cz/docs/swagger-ui/index.html)).

Die Integration nutzt ausschließlich den dokumentierten, öffentlichen Endpunkt mit einem
**API-Key aus der MyŠkoda-App** — keine Zugangsdaten, keine internen Endpunkte, keine
externen Python-Abhängigkeiten.

> **Status: Lesepfade gegen ein echtes Fahrzeug verifiziert, Fernbefehle noch nicht.**
> Die API ist in der Beta (`1.0.0-beta.6`). Mit einem echten API-Key geprüft wurden: der
> vollständige Fahrzeug-Abruf, der Teilabruf `?include=info`, das Verhalten bei einer nicht
> abgedeckten FIN, die `RateLimit-*`- und Ablauf-Header sowie das Fehlen eines
> Fahrzeuglisten-Endpunkts. Die Antwort eines echten Enyaq liegt anonymisiert als
> Test-Fixture bei. **Nicht** erprobt sind die acht `POST`-Befehle — die würden das Fahrzeug
> tatsächlich bedienen.

---

## Abgrenzung zu `homeassistant-myskoda`

| | [skodaconnect/homeassistant-myskoda](https://github.com/skodaconnect/homeassistant-myskoda) | **MySkoda PublicAPI** |
|---|---|---|
| Zugang | inoffizielle App-API, E-Mail + Passwort | offizielle Public API, API-Key |
| Push | MQTT-Events, nahezu Echtzeit | nein, reines Polling |
| Rate-Limit | praktisch keins | **20 Anfragen/Stunde pro Key** |
| Umfang | sehr groß (Fahrten, Wartung, Score …) | auf den Public-API-Umfang begrenzt |
| Abhängigkeit | `myskoda` PyPI-Paket | keine |

Beide Integrationen lassen sich parallel betreiben — sie nutzen unterschiedliche Domains
(`myskoda` vs. `myskoda_publicapi`).

---

## Voraussetzungen

* Home Assistant **2025.3.0** oder neuer
* Ein verbundenes Škoda-Fahrzeug
* Ein API-Key aus der MyŠkoda-App: **[go.skoda.eu/api-keys](https://go.skoda.eu/api-keys)**
  (Link auf dem Handy öffnen, die App verwaltet die Keys)

Ein Key ist **an die Fahrzeuge gebunden, die bei seiner Erstellung ausgewählt wurden**, und
**läuft ab**. Die Integration liest das Ablaufdatum aus jeder Antwort mit und meldet sich
rechtzeitig (Sensor *API-Schlüssel läuft ab am*, Problem-Sensor *API-Schlüssel läuft bald ab*).
Ist der Key abgelaufen, startet Home Assistant automatisch den Reauth-Dialog.

## Installation

**HACS (empfohlen)** — HACS → ⋮ → *Benutzerdefinierte Repositorys* → dieses Repository als
Kategorie *Integration* hinzufügen → *MySkoda PublicAPI* installieren → Home Assistant neu starten.

**Manuell** — `custom_components/myskoda_publicapi` nach `<config>/custom_components/` kopieren und
Home Assistant neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → **MySkoda PublicAPI***

1. **API-Key** — der einzige Pflichtwert.
2. **Fahrzeuge (FIN)** — dieser Schritt erscheint nur, weil die Public API **keinen Endpunkt
   zum Auflisten der Fahrzeuge** eines Keys anbietet; es gibt ausschließlich
   `GET /api/v1/vehicles/{vin}`. Mit einem gültigen Key geprüft: `GET /api/v1/vehicles`
   antwortet mit `404 No static resource`. Die Integration probiert das bei jeder
   Einrichtung trotzdem zuerst — liefert Škoda dort irgendwann eine Liste, entfällt der
   Schritt automatisch und die Einrichtung fragt tatsächlich nur noch den API-Key ab.

Jede eingegebene FIN wird sofort gegen die API geprüft, Tippfehler und nicht abgedeckte
Fahrzeuge fallen also direkt im Dialog auf.

## Optionen

*Geräte & Dienste → MySkoda PublicAPI → **Konfigurieren***

| Option | Standard | Bedeutung |
|---|---|---|
| Abfrageintervall | 30 min | 5–1440 Minuten. Der Dialog zeigt an, wie viele Anfragen/Stunde die aktuelle Einstellung verbraucht. Auch als Entität aus Automationen änderbar — siehe unten. |
| S-PIN | leer | Nur für die **Standheizung** nötig — die API verlangt sie im Start-Aufruf. Ohne S-PIN funktioniert alles andere. |
| Nach Befehl aktualisieren | an | Fragt ~30 s nach einem Fernbefehl einmal nach, damit der neue Zustand zeitnah ankommt. Wird übersprungen, wenn weniger als 3 Anfragen im Kontingent übrig sind. |

## Abfrageintervall aus Automationen steuern

Das Intervall ist zusätzlich eine Entität — `number.<api-gerät>_abfrageintervall` auf dem
Dienst-Gerät *MySkoda PublicAPI*. Damit lässt es sich per `number.set_value` aus einer
Automation ändern, etwa um während des Ladens öfter abzufragen und danach wieder
zurückzugehen. Der Wert landet in denselben Optionen wie über den Dialog und übersteht
deshalb einen Neustart.

```yaml
automation:
  - alias: MyŠkoda schneller abfragen während des Ladens
    triggers:
      - trigger: state
        entity_id: binary_sensor.my_enyaq_charging
        to: "on"
    actions:
      - action: number.set_value
        target:
          entity_id: number.myskoda_publicapi_abfrageintervall
        data:
          value: 5

  - alias: MyŠkoda zurück auf Normalintervall
    triggers:
      - trigger: state
        entity_id: binary_sensor.my_enyaq_charging
        to: "off"
        for: "00:10:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.myskoda_publicapi_abfrageintervall
        data:
          value: 30
```

Ein **verkürztes** Intervall kostet eine Anfrage, weil Home Assistant den Timer sonst erst
nach dem bereits eingeplanten Poll neu stellt. Ein **verlängertes** ist gratis — der nächste,
noch im kurzen Takt fällige Poll stellt den Timer selbst um. Ist das Kontingent fast leer,
wird auch das Verkürzen nicht sofort scharf gestellt, sondern beim nächsten Poll.

Ein Haken bleibt: Wird der Ladebeginn aus einer MyŠkoda-Entität getriggert, erfährst du
davon frühestens beim nächsten Poll — bei 30 Minuten also bis zu 30 Minuten zu spät. Wenn du
eine Quelle außerhalb der Integration hast, die den Ladebeginn sofort kennt — Wallbox,
Energiezähler oder eine eigene Ladeüberwachung — nimm die als Auslöser. Dann greift das
kurze Intervall ab der ersten Minute.

## Rate-Limit — bitte lesen

Škoda erlaubt **20 Anfragen pro Stunde pro API-Key**, geteilt über *alle* Fahrzeuge und
*alle* Fernbefehle. Die Integration ist darauf ausgelegt:

* **ein** Koordinator pro Konfigurationseintrag, der alle Fahrzeuge nacheinander abfragt
* Auswertung der `RateLimit-*`-Header nach jeder Antwort
* automatisches Zurückstellen des Pollings bei `429`, gesteuert über `Retry-After`
* Diagnose-Entitäten für Kontingent, Reset-Zeitpunkt und Key-Ablauf

Faustregel: `60 / Intervall × Anzahl Fahrzeuge` Anfragen pro Stunde fürs Polling — der Rest
bleibt für Fernbefehle. Bei zwei Fahrzeugen und 30 Minuten sind das 4 von 20.

Fehlerantworten mit `401`/`403` verbrauchen kein Kontingent, alle anderen — auch `5xx` — schon.

## Entitäten

Jedes Fahrzeug wird ein eigenes Gerät; dazu kommt ein Dienst-Gerät *MySkoda PublicAPI* für
Kontingent und Key-Status. Entitäten werden nur angelegt, wenn das Fahrzeug den zugehörigen
Datenbereich überhaupt liefert — ein Diesel bekommt keine Lade-Entitäten, ein BEV keine
Tank-Entitäten.

**An jeder Entität hängt der komplette Rohdaten-Abschnitt als Attribut.** Alles, wofür es
keine eigene Entität gibt — und alles, was Škoda in der Beta noch nachreicht — ist damit ohne
Codeänderung in Home Assistant verfügbar.

<details>
<summary><b>Sensoren</b> (bis zu 70)</summary>

* **Fahrzeug** — Kennzeichen, FIN, Kilometerstand, Zeitpunkt der letzten Abfrage, Anzahl Datenfehler
* **Tank** (`fuelStatus`) — Fahrzeugtyp, Gesamtreichweite, AdBlue-Reichweite sowie Antriebsart,
  Reichweite, Tankfüllstand und Ladestand für primären und sekundären Antrieb
* **Laden** (`charging`) — Ladezustand, Ladeart, Ladeleistung, Ladegeschwindigkeit,
  Restladezeit, Zeitpunkt „voll“, Batterieladestand, elektrische Reichweite, Ziel-Ladestand,
  Batterieschonung, Steckerentriegelung, max. Ladestrom (Stufe und Ampere)
* **Klima** (`airConditioning`) — Status, Zieltemperatur, erwartete Zielerreichung,
  Front-/Heckscheibenheizung
* **Standheizung** (`auxiliaryHeating`) — Status, Startmodus, Laufzeit, Zieltemperatur
* **Aktivlüftung** (`activeVentilation`) — Status, Laufzeit
* **Fahrzeugstatus** (`status`) — Verriegelung, Türen, Fenster, Licht, zuverlässiger
  Verriegelungsstatus, Schiebedach, Kofferraum, Motorhaube
* **Parken** (`parkingPosition`) — Parkstatus, Adresse
* **Ladeprofile** (`chargingProfiles`) — Anzahl Profile (Details als Attribut), aktuelles
  Profil, dessen Ziel-Ladestand und nächste Ladezeit
* **API** — verbleibende Anfragen, Limit, Reset-Zeitpunkt, Ablauf des API-Keys
* je Datenbereich zusätzlich der `carCapturedTimestamp` (standardmäßig deaktiviert)

</details>

<details>
<summary><b>Binärsensoren</b> (bis zu 21)</summary>

Türen verriegelt · Türen · Fenster · Licht · Schiebedach · Kofferraum · Motorhaube · lädt ·
Ladekabel angeschlossen · an gespeichertem Ort · Klimatisierung läuft · Scheibenheizung
aktiviert · Front-/Heckscheibenheizung · Klimatisierung ohne externe Stromversorgung ·
Klimatisierung beim Entriegeln · Standheizung läuft · Aktivlüftung läuft · in Bewegung ·
API-Schlüssel läuft bald ab · Anfragelimit erreicht

</details>

<details>
<summary><b>Steuerung</b></summary>

| Plattform | Entitäten |
|---|---|
| `switch` | Laden, Klimatisierung, Standheizung, Aktivlüftung, „Klimatisierung ohne externe Stromversorgung erlauben“ |
| `climate` | Klimatisierung (Zieltemperatur, An/Aus), Standheizung (Zieltemperatur, Preset Heizen/Lüften) |
| `number` | Zieltemperatur, Laufzeit Standheizung |
| `select` | Startmodus Standheizung |
| `button` | Aktualisieren + je ein Start/Stopp-Knopf pro Funktion (standardmäßig deaktiviert) |
| `device_tracker` | Parkposition (GPS, Adresse als Attribut) |
| `image` | Fahrzeug-Render aus `renderUrl` |

`number`, `select` und der Schalter „ohne externe Stromversorgung“ schreiben **nichts** ans
Fahrzeug — die API kennt keine Endpunkte zum Ändern von Einstellungen. Sie halten die Werte,
die Home Assistant beim **nächsten Startbefehl** mitschickt, und werden über Neustarts hinweg
wiederhergestellt.

</details>

## Aktionen (Services)

`myskoda_publicapi.refresh` · `start_charging` · `stop_charging` · `start_air_conditioning` ·
`stop_air_conditioning` · `start_auxiliary_heating` · `stop_auxiliary_heating` ·
`start_active_ventilation` · `stop_active_ventilation`

Ziel wahlweise über das Feld `device_id` oder `vin`. Ohne Ziel gilt die Aktion für alle
konfigurierten Fahrzeuge.

```yaml
action: myskoda_publicapi.start_air_conditioning
data:
  device_id: <Fahrzeug>
  temperature: 22
  without_external_power: true
```

```yaml
action: myskoda_publicapi.start_auxiliary_heating
data:
  vin: TMBJB9NY5RF999999
  temperature: 21.5
  duration: 20
  start_mode: heating
  spin: "1234"   # optional, sonst aus den Optionen
```

## Grenzen der API

Nicht möglich, weil die Public API es (noch) nicht anbietet:

* **Ver-/Entriegeln**, Hupen, Lichthupe — nur Statusabfrage, kein `lock`-Endpunkt
* **Einstellungen schreiben** — Ziel-Ladestand, Ladestrom, Ladeprofile und Timer sind
  ausschließlich lesbar
* **Fahrten, Wartung, Fahrzeug-Score, Software-Version, Außentemperatur** — nicht Teil der
  Public API
* **Fahrzeugliste zum API-Key** — deshalb der FIN-Schritt bei der Einrichtung
* **Push/Echtzeit** — die API bietet kein MQTT und keine Webhooks

Antworten mit Status `200` können unvollständig sein: nicht unterstützte oder gerade nicht
abrufbare Bereiche fehlen und werden in der Liste `errors` beschrieben. Diese Liste hängt am
Sensor *Datenfehler*.

## Fehlerbilder

| Symptom | Ursache | Lösung |
|---|---|---|
| Reauth-Dialog erscheint | Key abgelaufen oder widerrufen (`401`) | Neuen Key in der MyŠkoda-App erzeugen |
| „Der API-Schlüssel gilt nicht für dieses Fahrzeug“ | Key deckt die FIN nicht ab (`403`) | Key mit dem Fahrzeug neu erstellen |
| Entitäten werden `unavailable` | Kontingent erschöpft (`429`) | Intervall erhöhen; die Integration wartet automatisch ab |
| Befehl schlägt mit „nicht möglich“ fehl | `422` — Funktion fehlt oder ist deaktiviert | Wiederholen hilft nicht; Ausstattung bzw. Freischaltung prüfen |
| Standheizung nicht schaltbar | S-PIN fehlt | S-PIN in den Optionen hinterlegen |

Debug-Logging:

```yaml
logger:
  logs:
    custom_components.myskoda_publicapi: debug
```

Für Fehlerberichte: *Geräte & Dienste → MySkoda PublicAPI → ⋮ → Diagnose herunterladen*. FIN,
Kennzeichen, Adresse und GPS-Position werden dabei automatisch entfernt.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

Kein offizielles Produkt von Škoda Auto. Škoda und MyŠkoda sind Marken der Škoda Auto a.s.

## Tests

Die Integration läuft in den Tests gegen ein echtes Home Assistant. 76 Tests decken
Config-Flow, Reauth, Optionen, Entitätserzeugung für BEV und Verbrenner, alle Fernbefehle,
Rate-Limit-Backoff, Fehlerbilder (401/403/422/429), Wiederherstellung nach Neustart, die
Diagnose-Redaktion sowie die Regeln, die `hassfest` und HACS prüfen.

Ein Teil davon läuft gegen die **anonymisierte Antwort eines echten Enyaq**
(`tests/fixture_real_enyaq.json`): welche Bereiche das Fahrzeug meldet, welche Felder es
weglässt, die tatsächlichen Enum-Werte und die gemischten Zeitstempel-Formate sind
unverändert übernommen.

```bash
pip install -r requirements-test.txt && pytest -q
```

Was damit **nicht** abgedeckt ist: die acht `POST`-Befehle gegen ein echtes Fahrzeug, das
Verhalten bei erschöpftem Kontingent (`429`) und der Reauth mit einem tatsächlich
abgelaufenen Schlüssel.
