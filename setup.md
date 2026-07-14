# CROX Options Chain Fetcher – Einrichtung & Ausführung

Dieses Dokument enthält die Schritt‑für‑Schritt‑Anleitung, um das Projekt zu klonen, eine Python‑Virtuelle Umgebung (`.venv`) zu erstellen und die Option‑Chain‑Analyse auszuführen. 

---

## 1. Projekt klonen

```bash
# Ersetze <dein‑username> durch deinen GitHub‑Benutzernamen
git clone https://github.com/<dein-username>/trex_options_18days.git
cd trex_options_18days
```

> **Hinweis:** Das Repository muss already on your GitHub account verbunden sein. Wenn du es noch nicht erstellt hast, erstelle es zuerst auf GitHub und füge dann die Remote‑URL ein.

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

Das Projekt verwendet das Paket `ib_insync` zum Ansprechen von Interactive Brokers.  
Erstelle (oder ergänze) eine `requirements.txt`‑Datei im Projektstamm mit:

```text
ib_insync>=0.99
pandas>=2.0
```

Installiere anschließend alle Abhängigkeiten:

```bash
pip install -r requirements.txt
```

> **Falls du weitere Bibliotheken nutzt**, füge sie zu `requirements.txt` hinzu und führe `pip install` erneut aus.

---

## 5. Skript ausführen – Option‑Chain CSV erzeugen

```bash
# Aktivierte .venv‑Umgebung vorausgesetzt
python src/crox_options_chain.py
```

Der Aufruf des Skripts führt folgende Schritte aus:

1. **Marktopen‑Check** – prüft, ob der US‑Aktienmarkt geöffnet ist.  
2. **Option‑Contracts abrufen** – holt alle CROX‑Put‑Contracts mit ≥ 18 Tagen bis zur expiry.  
3. **Marktdaten‑Abruf** – holt aktuelle Bid/Ask‑Preise, Greeks, Volume, Open‑Interest usw.  
4. **Validierung & Fehlerbehandlung** – überspringt ungültige Daten und loggt Probleme.  
5. **CSV‑Export** – speichert die gesammelten Daten in `crox_options_18days.csv` im Projektstamm.

---

## 6. Ergebnis prüfen

Nach erfolgreicher Ausführung findest du die generierte Datei:

```
crox_options_18days.csv
```

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

Mit diesen Schritten hast du das Projekt vollständig eingerichtet, die virtuelle Umgebung konfiguriert und die Option‑Chain‑Analyse erfolgreich ausgeführt. Viel Erfolg beim further Exploring! 🚀