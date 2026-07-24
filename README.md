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
