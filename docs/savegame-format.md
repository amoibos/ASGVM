# Spielstand-Format: Laden & Speichern

Dokumentation des Save/Load-Mechanismus von *James Bond 007: Goldfinger*,
basierend auf Analyse der `SAVE1`-Datei und der `GAME.000`-Disassembly.

---

## 1. Übersicht

Das Spiel serialisiert seinen Zustand als **modifizierte Kopie der `TABLES`-Datei**.

| Eigenschaft | Wert |
|---|---|
| Dateiname | `SAVE1` bis `SAVE9` (Slot 1–9) |
| Dateigröße | 4.320 Bytes (identisch mit `TABLES`) |
| Record-Anzahl | 108 |
| Record-Größe | 40 Bytes (`0x28`) |
| Format | Modifizierte `TABLES`-Struktur mit Runtime-State in reservierten Feldern |

Das Spiel hat **keine separate State-Datei** – der gesamte Spielzustand wird
in die ungenutzten/überschreibbaren Bytes der TABLES-Records geschrieben.

---

## 2. Datei- und Code-Referenzen

| Ressource | Pfad / Adresse |
|---|---|
| `SAVE1` (Beispieldatei) | `SAVE1` im Wurzelverzeichnis |
| SAVE-String | `GAME.000` File-Offset `0x0BAE` (Runtime `0x0CC2`) |
| RESTORE-String | `GAME.000` File-Offset `0x2B71` (Runtime `0x2C85`) |
| Save-Prompts | `GAME.000` Offsets `0x07D7`, `0x087C`, `0x08D7` |
| File-Open für SAVE | `GAME.000` ~`0x0CBE`: `push "SAVE"` → `call 0xCA2A` |
| File-Open für RESTORE | `GAME.000` ~`0x02B85` |
| Schreibpuffer | `DS:0x4A80` (derselbe Puffer wie VOCAB) |

**Wichtige Disassembly-Routinen (GAME.000 objdump, AT&T-Syntax)**:

| Adresse | Funktion |
|---|---|
| `0x0AB7` | Datei-Existenz-Prüfung (für RESTORE) |
| `0x0CC1` | SAVE-Datei öffnen: `push "SAVE"` → `call 0xCA2A` → DOS-Open |
| `0x0CD3` | SAVE-Datei als Output öffnen: `mov $0x80, %ax` (rewrite mode) |
| `0x0CEA` | SAVE-Datei schließen: `call 0xCA74` |
| `0x0CD9` | Fehler-Prüfung nach Open: `call 0xB0E6` |

---

## 3. Save-Prozess im Detail

### 3.1 Ablauf

```
1. Spieler tippt "save"
2. Spiel zeigt Meldung (über Message-Renderer):
   "Remove GAME disk from drive and insert STORAGE disk"
   "Press RETURN when ready"
3. Spieler drückt Enter
4. Spiel zeigt: "Saving game #" + Nummer
5. Spiel öffnet/erstellt SAVE<n>:
   - Filename = "SAVE" + ASCII-Ziffer (z.B. "SAVE1")
   - open/create via INT 21h, AH=3Ch
6. Schreibt 4320 Bytes (TABLES mit Runtime-State)
7. Schließt Datei
8. Zeigt: "Remove STORAGE disk from drive and insert GAME disk"
```

### 3.2 Fehlerbehandlung

| Fehlerfall | Meldung |
|---|---|
| Disk schreibgeschützt | `Disk is write-protected. Game NOT saved.` |
| Schreibfehler | `Disk Write Error... Saving was unsuccessful.` |
| Kein Save-Disk | `THIS DISK WAS NOT MADE INTO A SAVE DISK.` |
| Slot bereits belegt | `There is already a game # on this disk. Want to save over it?` |
| Abbruch | `Game was NOT saved. Do you want another chance to save?` |

---

## 4. Restore-Prozess im Detail

### 4.1 Ablauf

```
1. Spiel startet → Frage: "Would you like to resume a saved game?"
2. Spieler antwortet Y/N
3. Bei Y: "Which game would you like to resume (1-9)?"
4. Spieler wählt Slot (1-9)
5. Spiel prüft Existenz von SAVE<n>:
   - DOS Open via INT 21h, AH=3Dh
   - call 0xB0E6 → error check
6. Bei Fehler: "There is no game # on this disk."
7. Bei Erfolg:
   - Liest 4320 Bytes ein
   - Validiert den Spielstand (Prüfsumme/Watermark)
   - Ersetzt TABLES-Daten im Speicher
   - Setzt Room-ID und Spielzustand aus SAVE-Daten
8. Zeigt: "Retrieving game #" + Nummer
```

### 4.2 Validierung

Der Spielstand wird validiert durch:
- Die 11 Bytes bei Record-Offset `+0x1D` in den ersten 8 Records müssen
  das ASCII-Muster `TARTRESTORE` (54 41 52 54 52 45 53 54 4F 52 45) enthalten.
- Bei inkorrekter Validierung: Spielstand wird abgelehnt.

---

## 5. TABLES-Record-Modifikationen (Runtime-State)

Der Vergleich zwischen frischer `TABLES` und `SAVE1` zeigt exakt 420 geänderte
Bytes. Die Änderungen konzentrieren sich auf folgende Record-Offsets:

### 5.1 Record-Typ `0x02` (Room-Records, 65 Stück)

| Offset | Größe | TABLES-Wert | SAVE1-Wert | Interpretation |
|---|---|---|---|---|
| `+0x0D` | 1 | `00` | `01` (erste 4 Records) | Aktivierungs-Flag |
| `+0x12` | 2 | `0F 05` | variiert (z.B. `14 00`) | **MESSAGE-Offset** (Raumbeschreibung) – wird vom Dispatcher auf aktuellen Zustand gesetzt |
| `+0x1D` | 1 | `00` | `54` (= 'T', erste 8 Records) | **Watermark-Byte 1** |
| `+0x1E` | 1 | `00` | `41` (= 'A', erste 7 Records) | Watermark-Byte 2 / State-Flag |
| `+0x1F` | 1 | `00` | `52` (= 'R', erste 7 Records) | Watermark-Byte 3 / State-Flag |
| `+0x20` | 1 | `00` | `54` (= 'T', erste 7 Records) | Watermark-Byte 4 / State-Flag |
| `+0x21` | 1 | `00` | `52` (= 'R', erste 7 Records) | Watermark-Byte 5 / State-Flag |
| `+0x22` | 1 | `00` | `45` (= 'E', erste 7 Records) | Watermark-Byte 6 / **Visited-Flag** |
| `+0x23` | 1 | `00` | `53` (= 'S', erste 7 Records) | Watermark-Byte 7 |
| `+0x24` | 1 | `00` | `54` (= 'T', erste 7 Records) | Watermark-Byte 8 / Entry-Gate |
| `+0x25` | 1 | `00` | `4F` (= 'O', erste 7 Records) | Watermark-Byte 9 |
| `+0x26` | 1 | `00` | `52` (= 'R', erste 7 Records) | Watermark-Byte 10 |
| `+0x27` | 1 | `00` | `45` (= 'E', erste 7 Records) | Watermark-Byte 11 |

**Hinweis**: Die ASCII-Buchstaben sind als **Watermark/Validierung** in
Records 0–7 zu interpretieren, nicht als Klartext. Records 8+ haben andere
Byte-Werte in diesem Bereich (erkennbare Runtime-Zustandsdaten wie
`01`, `00`, Flags).

### 5.2 Record-Typ `0x01` (Object-Records, 26 Stück)

| Offset | TABLES | SAVE1 | Interpretation |
|---|---|---|---|
| `+0x0D` | `00` | `01` (erste Object-Records) | Aktivierungs-Flag |
| `+0x1D`–`+0x27` | `00...00` | variierende Bytes | Objekt-Zustand (genommen/nicht genommen, offen/geschlossen, etc.) |
| vereinzelte Bytes | variiert | variiert | Weitere Objekt-Flags |

### 5.3 Record-Typ `0x07` (Global/Config-Record, 1 Stück)

| Offset | TABLES | SAVE1 | Interpretation |
|---|---|---|---|
| `+0x0D` | `00` | `01` | Spiel-gestartet-Flag |
| `+0x12` | `0F 05` | `14 00` | Aktueller MESSAGE-Pointer |
| `+0x1D`–`+0x27` | `00...00` | `TARTRESTORE` | Watermark |

### 5.4 Weitere geänderte Bytes (isoliert)

Einige Bytes außerhalb der obigen Muster ändern sich in spezifischen Records:

- `Offset 0x852`: `01` → `15` (Room-Record Feld)
- `Offset 0x93D..0x941`: `14 14 14 14 14` → `0F 0F 0F 0F 0F` (Room-Record Block)
- `Offset 0xD52`: `01` → `3D` (Object/Global-Feld)
- `Offset 0xF5A`: `3D` → `01` (Ende-Bereich)
- `Offset 0xF7D..0xF81`: `3C 3C 3C 3C 3C` → `2F 2F 2F 2F 2F` (Ende-Bereich)

---

## 6. TABLES→SAVE Record-Struktur (vollständig)

Jeder 40-Byte-Record:

```
Offset  Size  Feld
────────────────────────────────────────────────────────
+0x00   1     Record-Typ (0x01=Object, 0x02=Room, 0x07=Global, ...)
+0x01   1     Sub-Typ / Flag
+0x02   2     Big-Endian MESSAGE-Offset (Raumbeschreibung)
+0x04   1     Padding (immer 00 in Rooms)
+0x05   6     Direction-Slots N,S,E,W,U,D (1-based Room-IDs)
+0x0B   2     ?
+0x0D   1     Aktivierungs-Flag (00=frisch, 01=aktiv)
+0x0E   4     ?
+0x12   2     Aktueller MESSAGE-Pointer (vom Dispatcher gesetzt)
+0x14   1     State/Category (0x01 = inaktiv/blockiert)
+0x15   1     ?
+0x16   1     ?
+0x17   1     Dispatcher-Gate (< 0x63 = aktiv)
+0x18   1     ?
+0x19   1     ?
+0x1A   1     Room-ID (nur bei Runtime-Records)
+0x1B   1     ?
+0x1C   1     ?
+0x1D   11    *** Runtime-State / Watermark ***
              Records 0-7: "TARTRESTORE" Watermark
              Records 8+:  Per-Record Runtime-Zustand
+0x28   —      (Ende des 40-Byte-Records)
────────────────────────────────────────────────────────
```

---

## 7. Vergleich mit dem Python-Interpreter

### Was bereits existiert

- `gameengine/tables.py` – `TableDecoder` liest und parst die on-disk TABLES
- `gameengine/data.py` – `GameData.load()` lädt alle statischen Dateien
- Keine Save/Load-Logik im Python-Interpreter

### Was für Save/Load benötigt würde

1. **State-Serialisierung**: Die modifizierten TABLES-Felder (`+0x0D`,
   `+0x12`–`+0x13`, `+0x1D`–`+0x27`, isolierte Zustands-Bytes) müssen bei
   Save in ein `SAVEn`-Format geschrieben werden.

2. **Watermark-Generierung**: Records 0–7 erhalten `TARTRESTORE` im
   `+0x1D`–`+0x27`-Bereich.

3. **State-Deserialisierung**: Beim Laden eines `SAVEn`-Files müssen die
   modifizierten Felder in die Runtime-TABLES-Struktur zurückgelesen werden
   (insb. Room-IDs, MESSAGE-Pointer, Objekt-Zustände).

4. **Datei-I/O**: `SAVEn`-Files liegen im selben Verzeichnis wie `TABLES`.

---

## 8. Offene Fragen

- [ ] Exakte Semantik jedes Bytes im `+0x1D`–`+0x27`-Block für Records 8+
- [ ] Welche Records genau die Watermark enthalten müssen (0–7 bestätigt)
- [ ] Bedeutung der isolierten Byte-Änderungen (0x852, 0x93D, 0xD52, etc.)
- [ ] Ob es eine Prüfsumme gibt (in den letzten Records?)
- [ ] Verhalten bei korruptem Spielstand
- [ ] Maximale Anzahl Save-Slots (Strings deuten auf 1–9)
