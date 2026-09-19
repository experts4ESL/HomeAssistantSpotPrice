# Ökostrom Spot Price

Home-Assistant-Custom-Integration für die öffentlichen 15-Minuten-Day-Ahead-
Preise der österreichischen smartENERGY-API. Die Integration addiert eine
konfigurierbare Abwicklungsgebühr (Standard: **1,80 ct/kWh brutto**) und stellt
die Ergebnisse ausschließlich als Sensoren bereit. Sie steuert keine Batterie
und keine anderen Geräte.

## Funktionen

- ein API-Abruf je Aktualisierung über einen `DataUpdateCoordinator`
- vollständige Einrichtung und Änderung über die Home-Assistant-Oberfläche
- aktueller EPEX- und Tarifpreis sowie Preis der nächsten Viertelstunde
- Tagesminimum, Tagesmaximum und Tagesdurchschnitt
- günstigstes zusammenhängendes 1- und 2-Stunden-Fenster
- relatives Preisniveau von `very_low` bis `very_high`
- Indikator für vollständige Folgetagespreise
- korrekte Intervallauswahl über `start <= now < end`
- Berücksichtigung von Tagen mit 92, 96 oder 100 Viertelstunden
- kompakte Diagnoseinformationen ohne vollständige Preisliste

Die API-Werte und die Abwicklungsgebühr sind inklusive 20 % USt. Netzkosten,
Abgaben und sonstige lokale Gebühren sind nicht enthalten.

## Installation über HACS

Voraussetzung: Home Assistant 2026.7.2 oder neuer.

1. In HACS **Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/experts4ESL/HomeAssistantSpotPrice` eintragen und den
   Typ **Integration** wählen.
3. **Ökostrom Spot Price** installieren.
4. Home Assistant neu starten.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen**
   nach „Ökostrom Spot Price“ suchen.

Alternativ kann `custom_components/oeko_spot` manuell in das
Home-Assistant-Konfigurationsverzeichnis unter `custom_components` kopiert
werden.

## Konfiguration

| Einstellung | Standard |
| --- | --- |
| Tarifbezeichnung | `oeko Spot+` |
| API-Tarifkennung | `EPEXSPOTAT` |
| Abwicklungsgebühr brutto | `1,80 ct/kWh` |
| Abrufintervall | `15 Minuten` |
| Zeitzone | Home-Assistant-Zeitzone |

Die Einrichtung prüft die API-Verbindung und die erwartete Datenstruktur.
Abwicklungsgebühr, Aktualisierungsintervall und Ablaufgrenze lassen sich später
über **Konfigurieren** ändern.

## Entitäten

Home Assistant erzeugt die Entity-IDs aus den übersetzten Namen. Die eindeutigen
Kennungen bleiben unabhängig von Sprache oder Umbenennung stabil.

- aktueller Tarifpreis und reiner EPEX-Preis
- Preis der nächsten Viertelstunde
- Tagesminimum, Tagesmaximum und Tagesdurchschnitt
- Startzeit des günstigsten 1- und 2-Stunden-Fensters; Durchschnitt und Ende
  stehen als Attribute bereit
- Preisniveau
- Binärsensor „Preise für morgen verfügbar“
- nächstes zusammenhängendes niedriges Preisplateau
- nächstes zusammenhängendes hohes Preisplateau
- Binärsensoren für aktuell aktive niedrige und hohe Plateaus
- bestes rein preisbasiertes Lade-/Entlade-Paar und dessen Bruttospanne
- zwei konfigurierbare, ausschließlich zukünftige Speicherprofile für kurze und
  lange Ladefenster
- wirkungsgradbereinigte Nettoersparnis und ein konfigurierbarer
  Wirtschaftlichkeitsindikator je Speicherprofil

Die Plateau-Erkennung lässt sich in den Integrationsoptionen konfigurieren:

| Einstellung | Standard |
| --- | --- |
| Unterer Preisbereich | günstigste 25 % |
| Oberer Preisbereich | teuerste 25 % |
| Mindestdauer eines Plateaus | 60 Minuten |
| Schnelles Ladeprofil | 120 Minuten |
| Langsames Ladeprofil | 300 Minuten |
| Geplantes Entladefenster | 180 Minuten |
| Batterie-Gesamtwirkungsgrad | 85 % |
| Mindest-Nettoersparnis | 3,0 ct/kWh |

Jedes erkannte Plateau enthält Start, Ende, Dauer, Anzahl der Intervalle,
Durchschnitt, Minimum, Maximum, Preisspanne, Standardabweichung, Tagesrang,
Schwellenwert und Abstand zum Tagesdurchschnitt. Der Sensor „Beste Preisspanne“
verknüpft ausschließlich ein zeitlich früheres niedriges Plateau mit einem
späteren hohen Plateau. Er berücksichtigt bewusst noch keine Batteriegröße,
Wirkungsgrade, Verbrauchs- oder PV-Prognosen.

Der Sensor „Preisverlauf“ stellt zusätzlich die Kandidatenlisten
`low_plateaus_today`, `high_plateaus_today`, `low_plateaus_tomorrow` und
`high_plateaus_tomorrow` sowie `best_price_cycle` als maschinenlesbare Attribute
bereit. Ein späterer KI-Controller kann diese Preisinformationen mit Verbrauch,
PV-Prognose und Batteriedaten kombinieren.

## Beratende Batterieplanung

Die Profile „schnell“ und „langsam“ suchen in den noch nicht begonnenen
Viertelstunden von heute und morgen jeweils ein zusammenhängendes Ladefenster
und ein zeitlich späteres Entladefenster. In der hier vorgesehenen Anlage steht
das schnelle Profil für den Wohnungsspeicher und das lange Profil für den auf
800 W begrenzten Kellerspeicher. Die Dauer beider Profile bleibt in den
Integrationsoptionen änderbar und kann später aus nutzbarer Kapazität, aktuellem
SOC und Ladeleistung genauer abgeleitet werden.

Die Nettoersparnis wird pro später abgegebener Kilowattstunde berechnet:

```text
Entladepreis - Ladepreis / Gesamtwirkungsgrad
```

Ein Zyklus gilt nur dann als wirtschaftlich, wenn diese bereinigte Ersparnis
die konfigurierbare Mindest-Nettoersparnis erreicht. Die Berechnung ist bewusst
rein beratend: Sie kennt weder aktuellen SOC noch Hausverbrauch, PV-Prognose,
Leistungsgrenzen oder Blackoutreserve und sendet keine Gerätebefehle.

Beide Profile werden unabhängig berechnet und können sich daher zeitlich
überlappen. Eine ausführende Steuerung muss weiterhin garantieren, dass nur ein
Speicher aktiv ist, vor jedem Wechsel den alten Speicher sicher auf 0 W setzen
(`break before make`) und eine Netzeinspeisung anhand des zentralen Zählers
verhindern.

Neue Entitäten:

- Ladeplan und Nettoersparnis für das schnelle Speicherprofil
- Ladeplan und Nettoersparnis für das langsame Speicherprofil
- Binärsensor „Speicherzyklus wirtschaftlich“ für jedes Profil

Die Ladeplan-Sensoren verwenden den Beginn des empfohlenen Ladefensters als
Zustand. Ladeende, Entladefenster, Durchschnittspreise, Brutto- und
Nettoersparnis sowie Wirkungsgrad stehen als kompakte Attribute bereit.

## Dashboard-Tageskurve

Für eine Kurve mit bereits veröffentlichten zukünftigen Viertelstundenpreisen
wird die über HACS erhältliche **ApexCharts Card** benötigt. Der Sensor
`sensor.oeko_spot_price_chart` stellt dafür je eine kompakte Liste für heute und
morgen bereit.

Nach der Installation der ApexCharts Card kann folgende manuelle Karte in ein
Dashboard eingefügt werden:

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: day
header:
  show: true
  title: Strompreis heute in ct/kWh
  show_states: true
now:
  show: true
  label: Jetzt
yaxis:
  - decimals: 2
series:
  - entity: sensor.oeko_spot_price_chart
    name: Tarifpreis inkl. Abwicklungsgebühr
    type: area
    stroke_width: 2
    opacity: 0.35
    color: "#36a873"
    data_generator: |
      return (entity.attributes.prices_today || []).map((point) => [
        new Date(point.start).getTime(),
        point.tariff_price
      ]);
  - entity: sensor.oeko_spot_price_chart
    name: EPEX-Preis
    type: line
    stroke_width: 2
    color: "#ffffff"
    data_generator: |
      return (entity.attributes.prices_today || []).map((point) => [
        new Date(point.start).getTime(),
        point.epex_price
      ]);
```

Falls Home Assistant beim ersten Anlegen eine abweichende Entity-ID vergibt,
muss `sensor.oeko_spot_price_chart` in der Karte durch die tatsächliche ID des
Sensors „Preisverlauf“ ersetzt werden.

Da dieser Sensor eine vollständige Tagesliste als Attribute enthält, sollte er
von der Recorder-Datenbank ausgeschlossen werden:

```yaml
recorder:
  exclude:
    entities:
      - sensor.oeko_spot_price_chart
```

Nach einer Änderung an `configuration.yaml` muss Home Assistant neu gestartet
werden.

Der normale Sensor „Aktueller Preis“ bleibt davon unberührt. Sein numerischer
Zustand wird vom Home-Assistant-Recorder historisiert und eignet sich deshalb
für langfristige Preisanalysen, ohne die großen Tageslisten des
Preisverlauf-Sensors in der Datenbank abzulegen.

## Fehlerbehebung

- Bei der Einrichtung muss `https://apis.smartenergy.at` vom Home-Assistant-
  System erreichbar sein.
- Bei einem temporären Ausfall bleiben zuletzt erfolgreich geladene Werte bis
  zur konfigurierten Ablaufgrenze verfügbar.
- Nach einem Home-Assistant-Neustart können die zuletzt gespeicherten Werte auch
  ohne API-Verbindung wiederhergestellt werden. Nach Ablauf der konfigurierten
  Grenze werden sie nicht mehr verwendet.
- Strukturänderungen oder unerwartete Einheiten der API werden bewusst als
  Fehler behandelt, damit keine falschen Preise angezeigt werden.
- Vor dem Aktualisieren einer Custom Integration wird ein Home-Assistant-Backup
  empfohlen.

## Entwicklung

```bash
python -m pip install -e ".[test]"
pytest
ruff check .
```

API-Zugriffe werden in Tests nicht gegen den Produktivdienst ausgeführt.

## Datenquelle

Die Daten stammen aus der öffentlichen
[smartENERGY-API](https://www.smartenergy.at/api-schnittstellen). Laut Anbieter
werden die EPEX-SPOT-AT-Werte viertelstündlich, inklusive Umsatzsteuer und ohne
Abwicklungsgebühr bereitgestellt.

## Lizenz

MIT
