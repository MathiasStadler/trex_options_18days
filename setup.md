# Options Chain Fetcher – Einrichtung & Ausführung

Dieses Dokument enthält die Schritt‑für‑Schritt‑Anleitung, um das Projekt zu klonen, eine Python‑Virtuelle Umgebung (`.venv`) zu erstellen und die Option‑Chain‑Analyse für ein beliebiges Ticker‑Symbol auszuführen.

---

## 1. Projekt klonen

```bash
# Ersetze <dein-username> durch deinen GitHub‑Benutzernamen
git clone https://github.com/<dein-username>/trex_options_18days.git
cd trex_options_18days
```

> **Hinweis:** Das Repository muss bereits auf deinem GitHub‑Konto vorhanden sein. Falls du es noch nicht erstellt hast, lege es zuerst auf GitHub an und füge dann die Remote‑URL hinzu.

---

## 2. Virtuelle Umgebung (`.venv`) anlegen

```bash
# Python 3.11+ wird vorausgesetzt
python3 -m venv .venv
```

Damit wird ein Ordner `.venv` mit allen notwendigen Python‑Paketen und Bibliotheken erstellt.

---

## 3. Umgebung aktivieren

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
```

Sobald die Umgebung aktiv ist, erscheint `( .venv )` am Anfang deiner Shell‑Zeile.

---

## 4. Benötigte Pakete installieren

Das Projekt verwendet das Paket `ib_insync` zum Ansprechen von Interactive Brokers sowie `pandas` (optional für weiterführende Auswertungen).  
Stelle sicher, dass eine `requirements.txt` im Projektstamm existiert (sie sollte bereits angelegt sein):

```text
ib_insync>=0.9.70
pandas>=2.1.0
urllib3>=2.0.0
```

Installiere anschließend alle Abhängigkeiten:

```bash
pip install -r requirements.txt
```

> **Falls du weitere Bibliotheken nutzt**, füge sie zu `requirements.txt` hinzu und führe `pip install` erneut aus.

---

## 5. Skript ausführen – Option‑Chain CSV erzeugen

Das zentrale Skript ist `src/fetch_options_chain.py`. Es nimmt das Ticker‑Symbol als **ersten Kommandozeilen‑Parameter** entgegen und erzeugt eine CSV‑Datei mit Put‑Optionen, die mindestens 18 Tage bis zum Ablaufdatum haben.

```bash
# Aktivierte .venv‑Umgebung vorausgesetzt
python src/fetch_options_chain.py <TICKER>
```

**Beispiele**

```bash
python src/fetch_options_chain.py PLTR   # für Palantir
python src/fetch_options_chain.py MU     # für Micron
python src/fetch_options_chain.py CROX   # für Crocs (ursprüngliches Beispiel)
```

Der Aufruf des Skripts führt folgende Schritte aus:

1. **Marktopen‑Check** – prüft, ob der US‑Aktienmarkt geöffnet ist (ET 09:30‑16:00, Werktage).  
2. **Option‑Contracts abrufen** – holt alle Put‑Contracts des angegebenen Tickers mit ≥ 18 Tagen bis zur expiry.  
3. **Marktdaten‑Abruf** – holt aktuelle Bid/Ask‑Preise, Greeks, Volume, Open‑Interest usw. (Snapshot‑Modus).  
4. **Validierung & Fehlerbehandlung** – überspringt ungültige Daten und loggt Probleme.  
5. **CSV‑Export** – speichert die gesammelten Daten in `<ticker_lower>_options_18days.csv` im Projektstamm.

---

## 6. Ergebnis prüfen

Nach erfolgreicher Ausführung findest du die generierte Datei:

```
<ticker>_options_18days.csv
```

**Beispiel:** Für `PLTR` entsteht die Datei `pltr_options_18days.csv`.

Öffne sie mit Excel, LibreOffice Calc oder einem Text‑Editor, um die Option‑Daten zu analysieren.

---

## 7. Optional: Logs & weitere Ausgaben

- **Console‑Logs** geben detaillierte Informationen über Market‑Open‑Status, Connect‑Versuche, Retry‑Logik und eventuelle Fehlermeldungen.  
- **`CROX_OPTIONS_CHAIN_MAINTENANCE_PLAN.md`** befindet sich ebenfalls im Projektstamm und dokumentiert geplante Erweiterungen (z. B. weitere Back‑Off‑Strategien, zusätzliche Validierungsschritte).

---

## 8. Deinstallation der virtuellen Umgebung (optional)

Falls du die Umgebung komplett entfernen möchtest:

```bash
# Deaktiviere die Umgebung (falls noch aktiv)
deactivate

# Entferne den .venv‑Ordner
rm -rf .venv
```

---

### 🎉 Du bist fertig!

Mit diesen Schritten hast du das Projekt vollständig eingerichtet, die virtuelle Umgebung konfiguriert und die Option‑Chain‑Analyse für ein beliebiges Ticker‑Symbol erfolgreich ausgeführt. Viel Erfolg beim weiteren Erkennen ausgeführt. Viel Erfolg beim weiteren Erkunden! 🚀