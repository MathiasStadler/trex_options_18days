# CROX Options Chain Fetcher Maintenance Plan

## 🎯 **Angeordnete Aufgaben**

### 1️⃣ **Marktopen-Erkennung hinzufügen**
- Füge `is_market_open()` Funktion hinzu, die IBKR API überprüft
- Rufe diese Funktion vor dem Abrufen der Optionen-Kette auf
- Zeige warnende Logs an, wenn der Markt geschlossen ist
- Füge skipping-Logik für End-of-Day Daten hinzu

### 2️⃣ **Exponentielles Retry mit wachsender Verzögerung**
- Ersetze feste 2-Sekunden-Wartezeiten durch exponentielle Backoff:
  - Erster Versuch: 2s
  - Zweiter Versuch: 4s  
  - Dritter Versuch: 8s
  - Maximal 3 Versuche pro Operation
- Fügt `retry_with_backoff()` Helper Funktion hinzu
- Konfiguriere Retry für:
  - Market Data API Anfragen
  - Contract Qualification
  - Datei-IO Operationen

### 3️⃣ **get_stock_price Method reparieren**
- Aktuelle Implementierung:
  ```python
  def get_stock_price(ticker):
      return ticker.marketPrice() or None
  ```
- Neue Implementierung:
  ```python
  def get_stock_price(ticker, max_attempts=3):
      for attempt in range(max_attempts):
          price = ticker.marketPrice()
          if price is not None and price > 0:
              return price
          if attempt < max_attempts - 1:
              ib.sleep(3)  # 3 Sekunden warten
      return None
  ```

### 4️⃣ **Datenvalidierung verbessern**
- Vor dem Anwenden von OptionContract Objekten:
  ```python
  def validate_option_data(row_data):
      required_fields = ['conid', 'symbol', 'right', 'strike', 'expiry', 'bid', 'ask']
      return all(field in row_data and row_data[field] not in [None, ''] for field in required_fields)
  ```

## 📋 **Explizite Aufgabenliste**

### **Aufgabe 1: Marktopen-Erkennung**
- [ ] Implementiere `is_market_open()` Helper Funktion
- [ ] Füge Logik vor Marktdatenabfrage hinzu
- [ ] Füge Benutzeralarm für Marktschließung hinzu
- [ ] Teste verschiedene Börsenzeiten

### **Aufgabe 2: Exponentielles Retry**
- [ ] Erstelle `retry_with_backoff()` Funktion
- [ ] Ersetze alle festen ib.sleep() Aufrufe
- [ ] Teste Retry-Schritte (2s, 4s, 8s)
- [ ] Konfiguriere maximale Versuchsanzahl (3)

### **Aufgabe 3: get_stock_price Methode**
- [ ] Aktualisiere aktuelle `get_stock_price()` Implementierung
- [ ] Füge 3-Sekunden-Wartezeit zwischen Versuchen hinzu
- [ ] Implementiere maximale Versuchsanzahl (3)
- [ ] Validiere dass zurückgegebener Preis gültig ist (> 0)

### **Aufgabe 4: Datenvalidierung**
- [ ] Erstelle `validate_option_data()` Validierungsroutine
- [ ] Füge Validierung vor Contract Erstellung hinzu
- [ ] Weise sicheres Arbeiten mit ungültigen Daten zu
- [ ] Füge sichere Fallback-Werte zu

## 🔧 **Testplan**

### **Test-Szenario A: Einfaches Fallback-Skript**
```bash
python3 crox_options_chain.py
```
- Überprüfe Skript kann ausgeführt werden
- Überprüfe Log-Ausgabe
- Überprüfe CSV Erzeugung

### **Test-Szenario B: Retry Logic**
Simuliere Netzwerkfehler durch:
- Ausschalten von TWS
- Manuelles Unterbrechen der Netzwerkverbindung
- Überprüfe dass Skript Retry loggt und neu versucht

### **Test-Szenario C: Datenvalidierung**
Test mit:
- Teilweise Daten
- Ungültigen Preiswerten
- Fehlenden Contract Details

## 📁 **Dateiänderungen**

### **Hauptskript**: `/home/hermes/crox_options_chain.py`
```diff
# Füge Hilfsfunktionen hinzu
+ def is_market_open():
+     """Überprüfe ob Markt aktuell gehandelt wird (anpassbare Öffnungszeiten)"""
+     # Implementiere Logic mit TradingHours API
+
+ def retry_with_backoff(func, *args, max_attempts=3, base_delay=2):
+     """Führe Funktion mit exponentiellem Backoff-Retry aus"""
+
+ def get_stock_price(ticker, max_attempts=3):
+     """Rufe letzten Preis mit 3-sekündiger Wartezeit ab, falls nötig"""
+
+ def validate_option_data(row_data):
+     """Validiere dass alle erforderlichen Felder vorhanden und gültig sind"""

# In main Funktion:
# - Rufe is_market_open() vor jeder Hauptoperation auf
# - Ersetze alle festen ib.sleep(Anzahl) Aufrufe mit retry_with_backoff
# - Füge Validierung vor Contract Objekten hinzu
# - Passe Logs für Debugging und Status Updates an
```

### **Notizbuch**:
`/home/hermes/qualify_portfolio_fixed.ipynb`
```diff
# Fügt Robustheit hinzu:
- Exponentielles Backoff für Wiederverbindungsversuche
- Marktopen-Erkennung
- Sichere Fallback-Werte für greeks
- Verbesserte Fehlerbehandlung für Lagerreichkeitsfelder
```

## 🔍 **Schritte zur Implementierung**

### **Schritt 1: Hilfsfunktionen hinzufügen**
1. Erstelle Hilfsfunktionen oben im Skript
2. Schreibe gründliche Dokumentation für jede Funktion
3. Füge aufwendige Kommentare für zukünftige Referenz hinzu

### **Schritt 2: Hauptskript aktualisieren**
1. Füge Marktopen-Check vor Abfrage hinzu
2. Ersetze alle festen Wartezeiten mit exponentiellem Backoff
3. Füge Datenvalidierungsschicht hinzu
4. Füge detaillierte Log-Ausgabe für jedes Retry hinzu

### **Schritt 3: Notizbuch aktualisieren**
1. Füge ähnliche Hilfsfunktionen für Robustheit hinzu
2. Implementiere Markup-Fallback-Rigidity
3. Verbessere fehlende Greek-Berechnungsprotokollierung
4. Füge Marktopen-Erkennung für bessere Benutzererfahrung hinzu

### **Schritt 4: Tests durchführen**
1. Starte einfaches Fallback-Skript
2. Validiere Retry-Logik
3. Bestätige Datenvalidierungseffizienz
4. Überprüfe dass CSV korrekt geschrieben wird

## 🚀 **Deployment-Checkliste**

### **Vor dem Deployment:**
- [ ] Überprüfe Git-Repository Status
- [ ] Führe gesamte Aufgabenliste durch
- [ ] Teste in isolierter Umgebung
- [ ] Verifiziere Note zu Sicherheitsrisiken

### **Nach dem Deployment:**
- [ ] Monitor Skripprotokoll (Network-Fehlerbestätigung)
- [ ] Überprüfe erfolgreiche CSV Exporte
- [ ] Validiere Benutzer-Feedback (falls verfügbar)
- [ ] Überprüfe dass Exponential Backoff-Anzahl korrekt ist

## 📊 **Erwartete Ergebnisse**

### **Script-Performance-Metriken:**
- Erste Ausführung: < 5 Sekunden (erfolgreiche Verbindung)
- Netzwerkfehlerfall: 2s → 4s → 8s Backoff-retry (3 Versuche insgesamt)
- Datenverarbeitungsverzögerung: < 10 Sekunden für 30+ Optionenkontrakte
- CSV-Ausgabe: Korrekte Spalten und Zeilen

### **Benutzererfahrung:**
- Benutzerreceivers klare Nachrichten, wenn Markt geschlossen ist
- Erfolgs-/Fehlerszenarien für vollständige Netzwerk-Abdeckung
- Konsistente CSV-Ausgabe mit gefilterten Daten
- Verbessertes Diagnostikprotokoll für Warnseite

## ⚠️ **Risiken & Gegenmaßnahmen**

### **Risiko 1: Übermäßiges Retry**
**Gegenmaßnahme:** Maximal 3 Versuche pro Operation mit Log-Ausgabe und Notfallüberbrückung

### **Risiko 2: Ungültige Datenverarbeitung**
**Gegenmaßnahme:** Robuste Validierungsroutine vor jeder Contract-Erstellung; sichere Fallbacks

### **Risiko 3: Unzureichende Marktopen-Erkennung**
**Gegenmaßnahme:** Mehrschichtige Überprüfung mit TradingHours API und zusätzlichen manuellen Marktschlusszeiten

## 🎯 **Erfolgskriterien**

1. **Skript-Stabilität:** Skript funktioniert kontinuierlich ohne manuelle Intervention
2. **Netzwerk-Robustheit:** Skript kann vorübergehende Netzwerk-Fehler wiederherstellen
3. **Datenvalidierung:** Keine ungültigen Contract Objekte werden erstellt
4. **Ausgabequalität:** CSV mit korrekten Daten und korrekten Spalten
5. **Benutzer-Benachrichtigung:** Benutzerreceivers klare Nachrichten über Status und nicht-menschliche Musterüberbrückungen

## 🔄 **Schrittwiederholung und Überwachungskontrollen**

### **Schrittwiederholungsplan:**
```
Woche 1: Hilfsfunktionen hinzufügen (Step 1)
Woche 2: Hauptskript und Notizbuch aktualisieren (Steps 2-3)
Woche 3: Vollständiger Test Zyklus (Step 4)
Woche 4: Deployment und Überwachung (Deployment-Checkliste)
```

### **Überwachungskontrollen:**
- **Skriptlogs:** Regelmäßige Überprüfung auf Fehler/Zeitüberschreitungen
- **CSV-Größe:** Bestätigung, dass Datei mit erwarteten Daten geschrieben wird
- **Benutzer-Feedback:** Überprüfe Benutzerbeschwerden über Netzwerkkonnektivität
- **Netzwerkstatistik:** Überprüfe Verbindungsprotokolle

## ✅ **Fertigstellungs-Checkliste**

- [ ] Alle Hilfsfunktionen implementiert und getestet
- [ ] Skript aktualisiert mit exponentiellem Backoff-Retry
- [ ] Notizbuch Robustheit verbessert
- [ ] Alle Tests bestanden
- [ ] Bereit für Deployment
- [ ] Dokumentation erstellt