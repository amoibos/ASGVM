# Speicher- und Lademechanismus

Dokumentation des Speicherlayouts und des Lademechanismus von *James Bond 007:
Goldfinger* (1986), basierend auf der IDA-Disassembly von `GAME.COM` und
`GAME.000`.

---

## 1. Architektur-Übersicht

**GAME.COM** ist ein MS-DOS COM-File im **Tiny Model** – Code, Daten und Stack
teilen sich ein einziges 64-KB-Segment.

| Eigenschaft | Wert |
|---|---|
| Format | MS-DOS COM-file |
| Memory Model | tiny (CS=DS=ES=SS) |
| Load-Adresse | `0100h` (nach PSP auf `0000h`) |
| Dateigröße | 25.983 Bytes (`657Fh`) |
| Speicherbereich | `0100h..667Fh` (belegter Code/Data-Bereich) |
| Toolchain | Turbo Pascal 3 (Borland) |
| Stack | `SP = FFFEh` beim Start (wächst abwärts) |

```
┌─────────────────────┐  Segment-Basis (CS=DS=ES=SS)
│ PSP (256 Bytes)     │  0000h..00FFh
├─────────────────────┤  0100h (org 100h)
│ GAME.COM Code       │  0100h..~2CB6h
│  - Start/Init       │  0100h: Entry-Point (JMP 2CB6)
│  - sub_AB7          │  Haupt-Initialisierung
│  - sub_93A          │  DOS-File-I/O-Dispatcher
│  - sub_FB2/F12      │  TP3 Runtime-Thunks
│  - sub_195          │  Timer-Interrupt
│  - Heap-Manager     │  ~0800h
├─────────────────────┤
│ GAME.COM Daten      │  ~0120h..~2CB6h
│  - Globale Variablen│  0120h..0240h
│  - File-Handle-Tab. │  0240h
│  - File-Deskriptoren│  stdin:015Ah, stdout:0166h
│  - MESSAGE-Deskr.   │  1AF9h
│  - Pfad-Puffer      │  0196h
│  - I/O-Puffer       │  diverse
├─────────────────────┤  2CB6h
│ GAME.000 Overlay    │  2CB6h..Ende (69.888 Bytes)
│  - VOCAB-Lader      │  068Bh (relativ zum Overlay)
│  - TABLES-Lader     │  1DF7h (relativ zum Overlay)
│  - Szenen-Aktiv.    │  0D61h (relativ zum Overlay)
│  - Message-Renderer │  CS=0815h (separates Segment!)
├─────────────────────┤  Top des Overlays (variabel)
│ Heap / freier RAM   │  word_18A:word_18C
├─────────────────────┤
│ Stack               │  SS:SP (wächst abwärts)
│  - min. 512 Bytes   │  sub_FB2 prüft stack < heap
│    für Stack frei   │
└─────────────────────┘  Segment-Ende (64 KB)
```

---

## 2. Programmstart und Speicher-Initialisierung (sub_AB7)

### 2.1 Entry-Point

Der DOS-Loader springt den COM-File bei `CS:0100h` an. Der erste Befehl ist
`JMP 2CB6h` (Goldfinger.asm:6338). Von dort wird `sub_AB7` per `CALL`
aufgerufen – dies ist die zentrale Initialisierungsroutine.

### 2.2 Overlay-Descriptor

Direkt nach dem `CALL sub_AB7` liegt im Code ein **Overlay-Descriptor**
(14h Bytes), der die Speicheranforderungen beschreibt:

| Offset | Größe | Feld |
|---|---|---|
| `+00h` | word | Flags (Bit 0 = gesamten Speicher behalten) |
| `+02h` | word | Geladener Code-Segment-Wert |
| `+04h` | word | Geladener Daten-Segment-Wert |
| `+06h` | word | Code-Größe in Paragraphen (16-Byte-Blöcke) |
| `+08h` | word | Daten-Größe in Paragraphen |
| `+0Ah` | word | Stack + BSS Größe in Paragraphen |
| `+0Ch` | word | Minimaler Extra-Speicher |
| `+0Eh` | word | Maximale File-Handles (→ sub_9B3 CX) |
| `+10h` | word | stdin Puffergröße |
| `+12h` | word | stdout Puffergröße |

### 2.3 Initialisierungsablauf (sub_AB7, Goldfinger.asm:1113)

1. **DOS-Version prüfen** (`sub_C08`): `INT 21h, AH=30h` – muss ≥ 2.0 sein
2. **Speicherbedarf berechnen**:
   ```
   benötigt = CS + code_size + data_size + stack_size
   if benötigt > verfügbar → Fehler "not enough memory"
   ```
3. **Segment-Register setzen**:
   - `DS` = CS + code_size (Daten-Segment hinter dem Code)
   - `SS` = DS + data_size (Stack-Segment hinter den Daten)
   - `SP` = berechneter Wert (0xFFFE oder aus descriptor)
4. **Heap initialisieren** (Goldfinger.asm:1155-1159):
   ```
   word_18A = 0          ; Heap Offset = 0
   word_18C = DS-Basis   ; Heap Segment = DS
   [DS:22h] = 0          ; Heap-Start (Far-Pointer)
   [DS:24h] = DS-Basis   ; Heap-Start Segment
   ```
5. **Speicher freigeben** (`INT 21h, AH=4Ah`): Falls Flag Bit 0 nicht gesetzt,
   wird unbenutzter Speicher an DOS zurückgegeben.
6. **File-Handle-Tabelle initialisieren** (`sub_9B3`): Array bei `DS:0240h`,
   Größe aus `descriptor[+0Eh]`, alle Slots auf 0.
7. **stdin/stdout einrichten**: Puffer allozieren, Deskriptoren initialisieren.
8. **Interrupt-Vektoren setzen**:
   - INT 0 (Division-by-Zero) → `loc_1013`
   - INT 24h (Critical Error) → `byte_FD1` (falls word_172 Bit 3 gesetzt)
9. **Video-Modus setzen** (`sub_2AB`): Bildschirm löschen, Cursor positionieren.

---

## 3. Segment-Layout im Detail

### 3.1 Code-Segment (CS) – GAME.COM Resident

Der residente Teil enthält:
- Turbo Pascal 3 Runtime (Stack-Thunks, String-Hilfen, Error-Handler)
- DOS-File-I/O-Wrapper (`sub_93A`)
- Video-Routinen (INT 10h)
- Keyboard-Input (INT 16h)
- Timer-Interrupt (`sub_195`)
- Heap-Manager
- MESSAGE-Paging und -Decoder (6-Bit-Packing, `xtrnip`)

### 3.2 Daten-Segment (DS) – Globale Variablen

**Basis-Adresse**: CS + code_size (nach dem Code-Bereich)

Wichtige DS-Globals (Adressen relativ zu DS=0):

| Adresse | Label | Typ | Bedeutung |
|---|---|---|---|
| `0022h` | — | dword | Heap-Start (Far-Pointer: Offset:Segment) |
| `0138h` | `word_138` | word | Funktionspointer (Keyboard-Input) |
| `013Ah` | `word_13A` | word | Funktionspointer (Screen-Output) |
| `015Ah` | `word_15A` | struct | **stdin File-Deskriptor** |
| `0166h` | `word_166` | struct | **stdout File-Deskriptor** |
| `016Ah` | `word_16A` | word | Bildschirmbreite (Spalten) |
| `0172h` | `word_172` | word | **Globale Flags** (s.u.) |
| `0174h` | `word_174` | word | Gesicherter Stack-Pointer |
| `0176h` | `word_176` | word | Overlay Code-Segment |
| `0178h` | `word_178` | word | Overlay Daten-Segment |
| `017Ah` | `word_17A` | word | **File-Handle-Tabellen-Pointer** |
| `017Ch` | `word_17C` | word | File-Handle-Tabellen-Größe |
| `017Eh` | `word_17E` | word | Error-Handler Far-Pointer |
| `0180h` | `byte_180` | byte | Globaler Error-Code |
| `018Ah` | `word_18A` | word | **Heap-Allokations-Offset** |
| `018Ch` | `word_18C` | word | **Heap-Allokations-Segment** |
| `0196h` | — | buffer | Pfad-Konstruktionspuffer |
| `025Ch` | — | table | **Room-Record Far-Pointer-Tabelle** (4 Bytes/Eintrag) |
| `0438h` | — | table | **Aktions-Record Far-Pointer-Tabelle** (4 Bytes/Eintrag) |
| `04B11h` | `byte_4B11` | byte | Aktuelle Section-Label (für `(`-Selector) |
| `04BE0h` | — | array | **Runtime-Record-Array** (32-Byte Einträge) |
| `0670h` | `byte_670` | byte | Szenen-Flag/ID |
| `06A9h` | `byte_6A9` | byte | **Aktuelle Room-ID** |
| `1AF9h` | `loc_1AF9` | struct | **MESSAGE File-Deskriptor** |
| `1B46h` | `byte_1B46` | byte | Message-End-Flag |
| `1B68h` | — | set | **Template-Control-Set** (`^ | ( + % = $ & * \`) |
| `1BE8h` | `byte_1BE8` | byte | Hard-Break-Zeichen (`0Dh`) |
| `1BEC`h | — | buffer | Line-Buffer (80 Zeichen) |
| `1DE1h` | `word_1DE1` | word | MESSAGE-Cursor (Symbol-Position) |
| `1DE3h` | `word_1DE3` | word | MESSAGE konsumierte Symbole |
| `1DE5h` | `word_1DE5` | word | Aktueller Record-Index |
| `1DE7h` | `word_1DE7` | word | Aktuelle Record-Länge (Base-64 Header) |
| `1DF8h` | — | table | **Symbol→Zeichen Übersetzungstabelle** |
| `4B7Fh` | `word_4B7F` | word | **Dispatcher-Ergebnis** (Text-Referenz) |

#### word_172 – Globale Flags

| Bit | Wert | Bedeutung |
|---|---|---|
| 0 | 1 | Overlay-Modus (überspringe Laden, anderer Exit) |
| 1 | 2 | Char-Device-Prüfung via IOCTL |
| 2 | 4 | Bereits initialisiert (timer setup skip) |
| 3 | 8 | Critical-Error-Handler (INT 24h) installieren |

### 3.3 Stack-Segment (SS)

- `SS` = DS + data_size (hinter dem Datenbereich)
- `SP` = berechnet aus descriptor (typischerweise `0xFFFE`)
- **sub_FB2** (Goldfinger.asm:1912) prüft vor jeder TP-Funktion:
  ```
  if (SP - benötigt < 512) → Stack-Überlauf
  if (SS + (SP-neu/16) >= word_18C) → Kollision mit Heap
  ```

### 3.4 Separates Renderer-Segment (CS=0815h)

Der **Message-Renderer** (der Control-Dispatcher für `% @ | \ $ & ( ) ^ * = +`)
läuft in einem **eigenen Code-Segment** (`CS=0815h`, lineare Basis `0x8150`).
Dieses ist **weder** in den statischen Disassemblies von GAME.COM noch GAME.000
enthalten – es wurde durch Live-DOSBox-X-Memory-Dump (`MEMDUMPBIN 815:0 10000`)
wiederhergestellt.

Der Renderer teilt sich `DS` mit GAME.COM (greift auf `word_1DE1`, `word_1DE5`,
`byte_1B68` etc. zu), hat aber seinen eigenen Code. Die Kommunikation zwischen
Overlay, Renderer und Resident erfolgt über Far-Calls via Pointer-Tabellen.

---

## 4. File-I/O-System

### 4.1 DOS-Call-Wrapper (sub_93A, Goldfinger.asm:835)

`sub_93A` ist die zentrale I/O-Dispatch-Routine. Sie fängt DOS-File-Aufrufe ab
und verwaltet eine File-Handle-Tabelle:

| AH | Operation | Handler |
|---|---|---|
| `3Dh` | File öffnen | `loc_953` – sucht freien Slot in Handle-Tabelle |
| `3Ch` | File erstellen | `loc_953` – wie öffnen |
| `3Eh` | File schließen | `loc_97B` – nullt Handle aus Tabelle |
| `80h` | Alle schließen | `loc_995` – schließt alle offenen Handles |

### 4.2 File-Handle-Tabelle

- **Position**: `word_17A` zeigt darauf (initial `DS:0240h`)
- **Größe**: `word_17C` (gesetzt von `sub_9B3`)
- **Format**: Array von words; `0` = freier Slot, sonst DOS-File-Handle

### 4.3 File-Deskriptor-Struktur

Jeder geöffnete File hat einen 14-Byte Deskriptor:

| Offset | Größe | Feld |
|---|---|---|
| `+0` | word | DOS-File-Handle (`0xFFFF` = nicht offen) |
| `+2` | byte | Flags (0x80=Text, 0x40=Read-Open, Low-Nibble=Device-Typ) |
| `+3` | byte | Letztes gelesenes Zeichen |
| `+4` | word | Datenpuffer-Offset |
| `+6` | word | Puffergröße |
| `+8` | word | Aktuelle Lese-/Schreibposition |
| `+0A` | word | Ende der gültigen Daten im Puffer |
| `+0C` | N bytes | **Dateiname** (Pascal-String: 1 Byte Länge + Zeichen) |

Vordefinierte Deskriptoren:
- **stdin** bei `DS:015Ah` – Tastatur-Eingabe
- **stdout** bei `DS:0166h` – Bildschirm-Ausgabe
- **MESSAGE** bei `DS:1AF9h` – MESSAGE-Datei

---

## 5. Datei-Ladeprozesse

### 5.1 MESSAGE (GAME.COM, Adresse ~5029h)

Wird vom residenten GAME.COM geladen (Goldfinger.asm:11060-11106):

```
1. Initialisierung der MESSAGE-State-Variablen:
   byte_1AF6 = 8       ; Record-Header-Größe
   byte_1BE8 = 0Dh     ; CR
   byte_1BE9 = 0Ah     ; LF
   byte_48F3 = 7Fh     ; DEL (Soft-Break)

2. File öffnen:
   sub_11C6(Deskriptor) → Pascal-String "MESSAGE" → sub_2940 → INT 21h,AH=3Dh

3. Puffer setzen:
   sub_2ACA(Deskriptor, 128) → 128-Byte Lese-Puffer

4. Seek auf Offset 0:
   sub_29F6(Deskriptor, 0)

5. State initialisieren:
   word_1BEA = 0       ; Zustandsvariablen
   word_1AF7 = 0
   byte_1EBE = 3
```

**MESSAGE-Paging**: Die Datei ist in 94 Pages zu je 512 Bytes organisiert
(94 × 512 = 48.128). Jede Page hat:
- 2-Byte Header
- 510 Daten-Bytes (85 Sechs-Byte-Symbolgruppen)

Die Funktion `depage()` (Python: `gameengine/message.py`) entfernt die
2-Byte-Header und konkateniert die 510-Byte-Datenbereiche zu einem
kontinuierlichen Symbol-Stream.

### 5.2 VOCAB (GAME.000, Adresse 068Bh)

Wird vom Overlay geladen (docs/disassembly/GAME.000.asm:570):

```
1. Stack-Frame allozieren: sub SP, 33h (51 Bytes)
2. String "VOCAB" als Dateiname setzen
3. File öffnen: call 0xCA2A (INT 21h, AH=3Dh)
4. Puffer bei DS:0x4A80
5. 26-Byte-Records lesen (mov CX, 1Ah)
6. 236 Records einlesen (6136 / 26 = 236)
7. BST (Binary Search Tree) aufbauen:
   - Header/Node 0: [01, 02, 01, 33, 02, 0A, 01]
   - Nodes bei DS:0x06AF (je 7 Bytes)
   - Node-Layout:
     +0: Typ (01)
     +1: Wortlänge
     +2: Offset im String-Pool
     +3..+6: 4 VOCAB-Metadaten-Bytes (class, group, value_a, value_b)
8. 256-Byte-Buckets bei DS:0x0E6F (10 Stück)
9. 51-Byte Command-Array bei DS:0x19B3
```

### 5.3 TABLES (GAME.000, Adresse 1DF7h)

Wird vom Overlay geladen:

```
1. File-Info-Struct bei CS:0x1E6B (Dateiname, Pufferadresse, Record-Größe)
2. load_file() via INT 21h, AH=3Dh/3Fh/3Eh
3. 40-Byte-Records, 108 Records insgesamt (4320 / 40 = 108)
4. Status-Byte bei DS:0x1DF7
5. Records nach Typ sortiert:
   - Typ 0x01 (26×): Objekt-Records
   - Typ 0x02 (65×): Room-Records → Pointer-Tabelle DS:0x025C
   - Typ 0x03 (4×):  Spezial-Records
   - Typ 0x06 (4×):  Global/Config
   - Sonstige (9×):  Parser/Story-Records
```

### 5.4 GAME.000 Overlay (GAME.COM, loc_2C5D)

Wird vom residenten GAME.COM geladen (Goldfinger.asm:6298-6328):

```
1. Prüfe word_172 Bit 0: falls Overlay-Modus → überspringe Laden
2. File öffnen: INT 21h, AX=3D00h (read-only)
   Dateiname aus Deskriptor+0Ch
3. Seek: INT 21h, AX=4200h, CX=0, DX aus Aufrufer
4. Read: INT 21h, AH=3Fh, CX=FFFFh, DX=2CB6h
   → Lädt Overlay-Daten direkt nach DS:2CB6h
5. File schließen: INT 21h, AH=3Eh
6. Stack wiederherstellen: SP = word_174
7. I/O neu initialisieren: sub_9D9
8. Error-Handler setzen: word_17E = 10B1h
9. Sprung zu loc_2CCD → Overlay-Initialisierung
```

---

## 6. Heap-Management (Bump Allocator)

Der Heap verwendet einen einfachen linearen Allokator (kein `free()`):

| Global | Bedeutung |
|---|---|
| `DS:0022h` (dword) | Heap-Start (Far-Pointer) |
| `word_18A` (word) | Aktueller Allokations-Offset |
| `word_18C` (word) | Aktuelles Allokations-Segment |

**Heap-Manager** (Goldfinger.asm:801-834):
- `loc_801`: Schreibt `word_18A`/`word_18C` als Far-Pointer nach `ES:DI`
- `loc_813`: Liest Far-Pointer aus `ES:DI` und aktualisiert Heap-Globals

Der Heap wächst aufwärts, der Stack abwärts. `sub_FB2` verhindert Kollisionen.

---

## 7. Resident/Overlay-Kommunikation

Die Kommunikation zwischen dem residenten GAME.COM und dem GAME.000-Overlay
erfolgt über zwei Far-Pointer-Tabellen im DS-Segment:

### 7.1 Tabelle DS:0x025C – Room/Dispatcher-Funktionen

66 Referenzen in `goldfinger_overlay.asm`. Zugriff via `sub_B110`:
```
index = [bp+4]
far_ptr = [DS:025C + index*4]   ; 4 Bytes: Offset, Segment
push segment; push offset        ; als Far-Call-Ziel
```

### 7.2 Tabelle DS:0x0438 – Aktions-Funktionen

Zugriff via `sub_B09C`:
```
index = [bp+4]
far_ptr = [DS:0438 + index*4]
push segment; push offset
```

### 7.3 Renderer-Segment (CS=0815h)

Der Message-Renderer läuft in einem **dritten, separaten Code-Segment**
(`CS=0815h`). Er teilt `DS` mit dem Resident und Overlay, wird aber per
Far-Call aus dem Overlay heraus angesprungen. Seine Hauptroutinen:

| Routine | Lineare Adresse | Rolle |
|---|---|---|
| `seek` | `0xCBD9` | Positioniert Cursor auf Record-Index |
| `record-open` | `0xCC08` | Öffnet Record (liest Base-64 Länge) |
| `render-record` | `0x158DC` | Render-Driver mit Control-Dispatch |
| `render-loop` | `0x156FB` | Haupt-Char-Loop (testet Control-Set) |

### 7.4 Overlay-Entry-Points (GAME.000, ab 0x100)

Das Overlay hat mehrere Entry-Points (TP-Funktions-Stubs):

| Offset | Ziel | Funktion |
|---|---|---|
| `0x100` | `0xAD97` | Init/Game-State |
| `0x107` | `0x2BB1` | Main Game Loop |
| `0x10E` | `0x068B` | **VOCAB-Lader** |
| `0x11A` | `0x01C4` | (Parser?) |
| `0x129` | `0x013B` | (weitere Init) |

---

## 8. Runtime Record-Transformation

Die on-disk TABLES-Records (40 Bytes) werden zur Laufzeit in **32-Byte
Runtime-Records** im Array ab `DS:0x4BE0` transformiert. Dabei werden:

- **Message-Pointer reloziert**: Aus Big-Endian-Offset wird ein
  Segment:Offset-Paar
- **Direction-Slots expandiert**: Aus 6×1 Byte (Room-IDs) werden 6 Far-Pointer
  via `DS:0x025C`-Tabelle
- **Felder neu angeordnet**: `+0x14` State-Byte, `+0x1A` Room-ID, `+0x18`
  Active-Marker (`0x63`)

```
┌──────────────────────────────────────────────┐
│ Runtime Record (32 Bytes, DS:0x4BE0)         │
├────────┬─────────────────────────────────────┤
│ +0x00  │ Typ (0x02 = Room)                   │
│ +0x01  │ Message-Pointer (2 Bytes, reloziert) │
│ +0x03  │ Padding (0)                         │
│ +0x04  │ 4 Far-Pointer (aus Direction-Slots) │
│ +0x14  │ State/Category Byte                 │
│ +0x18  │ Active-Marker (0x63)                │
│ +0x1A  │ Room-ID                             │
│ +0x1C  │ Flags                               │
└────────┴─────────────────────────────────────┘
```

---

## 9. Ladereihenfolge (Zusammenfassung)

```
1. DOS lädt GAME.COM bei CS:0100h
2. JMP 2CB6h → CALL sub_AB7 (Memory-Setup)
3. sub_AB7:
   a. DOS-Version prüfen
   b. Segment-Register setzen (DS, SS, SP)
   c. Heap initialisieren
   d. Speicher an DOS freigeben (INT 21h,AH=4Ah)
   e. File-Handle-Tabelle initialisieren
   f. stdin/stdout einrichten
   g. Interrupt-Vektoren setzen
   h. Video-Modus setzen
4. GAME.000 Overlay laden (loc_2C5D)
   → INT 21h: open, seek, read → DS:2CB6h
5. Sprung zu loc_2CCD (Overlay-Init)
6. Overlay lädt VOCAB (0x068B)
   → 236 Records → BST bei DS:0x06AF
7. Overlay lädt TABLES (0x1DF7)
   → 108 Records → Pointer-Tabelle DS:0x025C
8. Overlay initialisiert MESSAGE (GAME.COM resident)
   → File öffnen, Puffer, State
9. Szenen-Aktivierung (0x0D61)
   → Setzt DS:0x06A9 (Room-ID), lädt Szenen-Daten
10. Main Game Loop (0x2BB1)
    → Eingabe, Parser, Dispatcher, Renderer
```

---

## 10. Relevante Quellcode-Referenzen

| Komponente | Python-Modul |
|---|---|
| Daten-Loader | `gameengine/data.py` |
| 6-Bit-Packing | `gameengine/packing.py` |
| Message-Decoder/Paging | `gameengine/message.py` |
| GAME.COM-Engine-Port | `gameengine/gamecom.py` |
| VOCAB-Parser | `gameengine/vocab.py` |
| TABLES-Parser | `gameengine/tables.py` |
| Input-Encoding | `gameengine/input_encoding.py` |
| Disassembly (GAME.COM) | `goldfinger.asm` |
| Disassembly (GAME.000) | `goldfinger_overlay.asm` |
| Reverse-Engineering-Notizen | `docs/reverse-engineering.md` |
| Datenformat-Spezifikation | `docs/data-format.md` |
