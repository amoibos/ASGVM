# VM-Migrations-Audit: Logik in die Engine, Daten in `games/<titel>/`

## State-Variant-Binding auf Code-/Feld-Ebene lokalisiert (2026-07-06, statisch)

Der Dispatcher-/Prädikat-Kern ist bereits portiert und die Composite-Records
rendern messbar sauber (OPEN/PRESS/READ nicht mehr garbled). Der verbleibende
Gap ist die **State-Variant-Selektion** — präzise seziert am kanonischen Fall
`examine armrest`:

- **Record & Struktur.** Der EXAMINE-Ref (`object.le_word(+0x9)`) ist **6273**;
  Control-Struktur: `…is [&]g‹op›|…open [$]…exposing…buttons [^]…closed`. Der
  offen/geschlossen-Zustand wird über `&g` (open-Zweig) + `$`/`^` (closed-Zweig)
  selektiert.
- **Symptom.** Beide Zweige rendern (`"is open … several buttons closed"`,
  widersprüchlich) — identisch in beiden Zuständen.
- **Ursache 1 — Evaluator wird nicht erreicht.** Probe: `_evaluate_fgi_entry`
  wird während `examine armrest` **nie aufgerufen** (`fgi calls: []`). Der
  EXAMINE-Pfad `examine_object` → `render_with_conditional_spans` →
  `_evaluate_conditional_span` parst nur `$`/`^` als ConditionalSpan, **nicht
  `&`** (0x2C). Der `&g|…open`-Zweig wird daher nie gegated → „open" rendert
  immer.
- **Ursache 2 — fg-Kontext nie gesetzt.** Selbst für die `$`/`^`-Spans liefert
  `_evaluate_fgi_entry` `None`, weil `fg_context_type`/`condition_records` im
  EXAMINE-Pfad nicht aufgebaut werden (Guard Zeile 716). `None` ⇒ Default-Keep ⇒
  „closed" rendert ebenfalls.
- **Ursache 3 — Zustand erreicht das Record nie.** `OPEN armrest` schreibt nur
  das Python-`state.opened`-Set; das native Objekt-State-Byte, das `g`
  (`condition_record[+0x1B]`, Guard `[+0x18]!=0`) liest, bleibt unverändert
  (Armlehnen-Record `[0x14:0x20]` ist geschlossen wie offen identisch,
  `[0x1b]=00`). Der generische OPEN-Pfad in `game.py` führt das native
  Action-Programm (das via `write_native_field`/Opcode 0x5A ein State-Feld
  schreiben würde) nicht aus.

**Konkreter Fix-Pfad (drei Teile, in Reihenfolge):**
1. **Upstream zuerst (assembly-zu-bestätigen):** welches Objekt-Feld schreibt
   das native OPEN? → OPEN im generischen Pfad das native Action-Programm
   ausführen lassen (statt nur `state.opened.add`), damit das State-Feld gesetzt
   wird. (Verifikationsfrage: schreibt es genau `+0x1B`?)
2. Conditional-Span-Parsing in `render_with_conditional_spans` auf `&` (0x2C)
   erweitern, damit der open-Zweig gegated wird.
3. Den fg-Kontext (`fg_context_type=0` + `condition_records` = Objekt-Records
   per `class_id`) für den EXAMINE-Pfad aufbauen, damit `g`/`i` gegen das echte
   State-Byte auflösen.

Bis Teil 1 (Feld) assembly-bestätigt ist, wäre 2+3 Raten. Nächster ehrlicher
Schritt: OPEN-Action-Block statisch dekodieren (welches `+N`-Feld er schreibt).

### Konvergenz auf die DS:0x025C-Tabelle + Build-Routine lokalisiert (2026-07-06)

Weiterverfolgt: `condition_records` (context_type 0) und `room_records`
(context_type 2) in `_evaluate_fgi_entry` sind **nirgends im Code zugewiesen**
(verifiziert per grep) — die `f/g/i`-Opcodes liefern daher immer `None`.
Isoliert-verifizierte Feld-Semantik des Evaluators (per direktem Aufruf):
Guard `condition_record[0x18] == 0`, dann `g = bool([0x1B])`, `i = not
bool([0x1B])`. Der `&g`-Operand in `examine armrest` (Symbol 3) löst auf
`entry.word='armrest', class_id=51` auf — das `&g` testet also das Objekt
selbst.

Laut fünfter-Runde-Notiz oben liest der `+0x23`-Gate (context_type 2) aus einem
`GetRoomRecord(id)`-Helfer, der **`DS:0x025C[id*4]`** dereferenziert; dieselbe
Tabelle wird für Objektklassen (`class_id`) UND Räume genutzt. Also:
`condition_records` == die per `DS:0x025C[class_id]` erreichten Records. Damit
konvergieren **Raum-Mapping, fgi-Kontext und State-Variant-Rendering alle auf
die eine Frage: wie wird DS:0x025C beim Aktivieren befüllt** (welcher Disk-Record
landet bei welchem Index).

**Build-Routine lokalisiert:** `GAME.000.asm`.
- `18a8..1917`: bei Record-Typ 2 wird `byte_19ea` (der Slot-Zähler) inkrementiert
  (`18b0`), `di = 0x25C + byte_19ea*4` (`18bd`) berechnet, und über `call 0xa6c4`
  / `call 0xafed` mit `cx=0x27` (39 Bytes) ein Record kopiert. `DS:0x025C[idx]`
  ist also ein Far-Pointer auf einen ~39/40-Byte-Record (TABLES-Stride 40).
- `1957..197f`: Init-Loop, füllt `DS:0x025C[cur*4]` für `cur = byte_19ea+1 ..
  0x77(119)` mit dem Default-Far-Pointer aus `DS:0x260` (Sentinel/leer).

`sub_AFED` ist bestätigt ein **Copy/Fill-Helfer** (`docs/data-format.md:889`,
kopiert `cx` Bytes). Damit ist `18d2..18e4` klar: es kopiert den 39-Byte-Record,
auf den `DS:0x25C[byte_19ea]` zeigt, in einen lokalen Puffer (`ss:-0x84`) zur
Verarbeitung. `18c1` (`call 0xa6c4`, Slot-Adresse `&DS:0x25C[idx]` + `cx=39`) ist
strukturell plausibel ein **Allocator** (frischen 39-Byte-Record anlegen,
Far-Ptr in den Slot schreiben) — noch zu bestätigen.

**Kern-Einsicht (starke Hypothese, assembly-gegründet):** `DS:0x025C` wird in
**Aktivierungs-Reihenfolge** befüllt — `byte_19ea` ist ein laufender Slot-Zähler,
der pro aktiviertem Typ-2-Record inkrementiert (`18b0`), und jeder Slot bekommt
eine **frisch allokierte, mutable 39/40-Byte-Kopie** des Records. Das ist *kein*
statisches Disk-Index-Mapping. ⇒ Die „room-32 mapping"-Diskrepanz und die „-1
convention" erklären sich daraus: der `0x25C`-Index ist ein **dynamischer
Aktivierungs-Slot**, nicht die Disk-Record-Position. `condition_records` müssen
also aus dieser aktivierungsbefüllten Tabelle (mutable Kopien) gelesen werden,
nicht aus den statischen Disk-Records — was auch erklärt, warum das
State-Byte (`[0x1B]`) dort per OPEN mutiert werden kann.

### Build-Routine dekodiert + wichtige Korrektur (2026-07-06, Forts.)

Routinen-Anfang `GAME.000:1848` dekodiert:
- **`byte_19ea` Seed = 1** (`1857: ax=1; 185a: byte_19ea=al`) — bestätigt.
- Pro Iteration: `a6c4(DS:0x260, cx=39)` holt/allokiert den nächsten Record,
  `afed` kopiert ihn (39 Bytes) in den lokalen Puffer `ss:-0x84`,
  `ca86/caa3/b0ed` verarbeiten ihn, dann **Record-Typ-Byte** (`ss:-0x85`)
  geprüft: `189e: cmp 2`.
- **Nur Typ==2 (Raum) bekommt den nächsten `DS:0x25C`-Slot** (`18a8`:
  `byte_19ea++`, dann Slot `DS:0x25C[byte_19ea*4]`). Typ≠2 → `191a` (andere
  Verarbeitung, kein `0x25C`-Slot).

⇒ **Bestätigt: `DS:0x025C[n]` = der n-te TYP-2-Record in Stream-Reihenfolge**
(1-basiert, Seed 1), *nicht* die Disk-Position. Das ist die Ursache der
„room-32 mapping"-Diskrepanz: der Index ist eine dynamische Aktivierungs-Slot-
Position, kein Disk-Offset. Diese Tabelle speist `_evaluate_fgi_entry`
**context_type 2** (`room_records`, Gate `+0x23`, liest `+0x24`/`+0x25`).

**KORREKTUR (vorherige Konvergenz war zu schnell):** `examine armrest` ist ein
**Objekt** → **context_type 0** (`condition_records`, Gate `+0x18`, liest
`+0x1B`/`+0x1C`) — das ist eine **SEPARATE** Tabelle, NICHT `DS:0x025C` (die nur
Typ-2/Räume enthält). Auch das reale Objekt-Disk-Record hat `[0x18]=1` (Gate
bräuchte `==0`), also sind auch die Objekt-condition_records **verarbeitete
Runtime-Kopien**, nicht die Disk-Records. Die Objekt-condition_records-Tabelle +
ihr Build sind **noch nicht lokalisiert** — das ist der nächste Schritt für den
EXAMINE-State-Variant-Fix (context_type 0). Der `DS:0x025C`-Fund oben löst das
**Raum**-Mapping (context_type 2), nicht direkt den EXAMINE-Objektfall.

**a6c4-Hinweis:** GAME.000-lokales `0xa6c4` ist eine TP3-RTL-Funktion (wie
`afed`/`b593`); Signatur `(ptr, size=39)` passt zu GetMem/Record-Fetch. Das
Overlay-`sub_A6C4` (22169) ist ein ANDERES Segment und statisch
fehl-aligniert (Overlay-Wrap-Blindspot) — nicht dafür heranziehen.

### context_type 0: Objekt-condition-Tabelle = DS:0x04B4, Handler sub_C6BB (2026-07-06)

Der native `f/g/i`-Handler ist **`sub_C6BB`** (`goldfinger_overlay.asm:26727`),
aufgerufen aus `sub_CAE0+1D`/`sub_D814+6D`. Exakt dekodiert:
```
al = [bp+6] ; der Wert (class_id); ax <<= 2
les di, [di+4B4h]      ; ES:DI = DS:0x04B4[class_id*4]  -> condition-Record
al = es:[di+18h]; cmp 0; jnz <return>   ; GUARD: record[+0x18] == 0
opcode 'g'(0x67): al = es:[di+1Bh];            byte_4B7B = [0x1B]
opcode 'i'(0x69): al = es:[di+1Bh]; xor al,1;  byte_4B7B = NOT [0x1B]
opcode 'f'(0x66): al = es:[di+1Ch];            byte_4B7B = [0x1C]
```
⇒ **`condition_records` (context_type 0) == die `DS:0x04B4`-Tabelle**, indiziert
per `class_id*4` → Far-Pointer auf den condition-Record. Semantik deckt sich
**exakt** mit `predicates.py::_evaluate_fgi_entry` (Guard `[0x18]==0`,
`g=[0x1B]`, `i=~[0x1B]`, `f=[0x1C]`). `byte_4B7B` ist das Render/Skip-Flag.

**Build lokalisiert** (`GAME.000.asm`, Aktivierungsroutine, spiegelt den
`DS:0x25C`-Build):
- `17a8..17ed`: `DS:0x04B4`-Init-Loop, **63 Slots** (`0x3f`), Zähler
  **`byte_19e9`**, Default-Far-Ptr aus `DS:0x4B8`.
- `1773..1798`: per-Index-Verarbeitung via `call 0x133a` (`sub_133A`) — die
  eigentliche Record→Slot-Zuweisung.
- Vergleich Räume: `DS:0x25C`, 119 Slots (`0x77`), Zähler `byte_19ea`, Default
  aus `DS:0x260`.

**`sub_133A` dekodiert** (`GAME.000:133a`): indiziert `DS:0x4B4` per
**`source_record[+0x17]`** (dem class-id-Link-Feld des zu aktivierenden Records),
prüft dort den Guard `DS:0x4B4[source[0x17]][+0x18] == 0` (`1388`, matcht den
fgi-Guard), und führt dann Set-Algebra (`b593`=load, `b5c3`, `b5d5`, `b67c`=op,
`b5fb`=store) zwischen dem `DS:0x4B4`-Record-Set und dem globalen Set `DS:0x699`
aus. ⇒ **`DS:0x4B4` ist per `+0x17` (class-id) verschlüsselt** und hält mutable
Runtime-Kopien der Objekt-condition-Records, die die Aktivierung per Set-Algebra
gegen `DS:0x699` fortschreibt.

**Damit ist context_type 0 vollständig auf Assembly-Ebene charakterisiert:**
Tabelle `DS:0x4B4[class_id]`, Handler `sub_C6BB` (Guard `[0x18]==0`, `g=[0x1B]`,
`i=~[0x1B]`, `f=[0x1C]`), Build/Update via `sub_133A` + der 17xx-Aktivierungs-
schleife. Die `[0x18]=1`-Diskrepanz des Disk-Records erklärt sich: die
`DS:0x4B4`-Einträge sind **Runtime-Kopien**, deren `[0x18]`/`[0x1B]` die
Aktivierung setzt — nicht die Disk-Bytes.

**Verbleibend für den EXAMINE-Fix (Implementierung von context_type 0):**
`condition_records` in Python aus dem Runtime-Objekt-Record-Array (das
`DS:0x4B4`-Äquivalent) per class_id aufbauen, `render_with_conditional_spans`
um `&`-Parsing erweitern, und OPEN das `[0x1B]`-Byte der Runtime-Kopie schreiben
lassen. Kein Assembly-Blocker mehr — reine Verdrahtung.

### context_type 0: Schlüssel bestätigt, aber DS:0x4B4-Befüllung ist dynamisch (2026-07-06)

Aufrufer von `sub_C6BB` dekodiert (`goldfinger_overlay.asm:27420` `loc_CAE3`):
`push node[+3]` (→ `[bp+6]`, der DS:0x4B4-Index) und `push ss:[bx-0Bh]` (→
`[bp+4]`, der Opcode). ⇒ **Der DS:0x4B4-Index ist `node[+3]` = die class_id** —
das existierende `_evaluate_fgi_entry`-`condition_records.get(entry.class_id)`
ist damit **korrekt**.

**Harte Grenze gefunden:** `DS:0x4B4[51]` (armrest, class_id 51) entspricht
**keinem statischen Disk-Record** — kein Record hat `[0x17]==51`, und das
Armlehnen-Objekt-Record selbst hat `[0x17]=0, [0x18]=1, [0x1b]=0`. Der native
OPEN-State-Write (`loc_DE1A`: Guard Runtime-`[0x18]==0`, dann `[0x1B]=1`) läuft
auf dem **Runtime-Record** (`DS:0x4B4`, via `[bp-15h]`), nicht dem Disk-Record.
⇒ **`DS:0x4B4` wird dynamisch bei der Aktivierung befüllt** (aus Runtime-Records,
deren `[0x17]=class_id`/`[0x18]`/`[0x1B]` erst zur Laufzeit gesetzt werden) —
`condition_records` lässt sich also **nicht aus statischen Disk-Records
rekonstruieren**. Anders als das Raum-Mapping (DS:0x25C, sequentiell-über-Typ-2,
statisch ableitbar) braucht context_type 0 die **portierte Aktivierungskette,
die DS:0x4B4 befüllt** — oder einen Live-Trace von `DS:0x4B4[51]` (closed vs
open) für die echten `[0x18]`/`[0x1B]`-Werte.

**Ehrliche Korrektur zu „reine Verdrahtung":** Das war zu optimistisch — der
EXAMINE-Fix braucht die DS:0x4B4-Aktivierungsbefüllung (Objekt-Runtime-Records
mit korrektem `[0x18]`/`[0x1B]`), nicht nur `&`-Parsing + Evaluator-Kontext.
Das Mechanismus-Verständnis ist vollständig; der Blocker ist die dynamische
Tabellen-Befüllung.

**Beim Port-Versuch (2026-07-06) aufgedeckte Inkonsistenz — statischer Port
allein reicht NICHT:** Die Aktivierungskette ist bereits weitgehend portiert
(`activation.py::phase7_nodes`, 26 Typ-1-Nodes; `AsgPhase7Evaluator`). Aber:
- Alle 26 Phase-7-Nodes haben **`raw[+3]=0`** — der `sub_C6BB`-Schlüssel
  `node[+3]` bezieht sich also NICHT auf diese Nodes, sondern auf einen
  VOCAB-aufgelösten Node im Message-Evaluator (`[bp-0Eh]` in `loc_CAE3`),
  dessen `+3` die class_id ist.
- Die Phase-7-Nodes populieren `DS:0x4B4` per ihrem `[0x17]`-Feld
  (`next_index`), dessen Werte nur bis **23** reichen.
- Für die Armlehne (class_id **51**) existiert **weder** eine Node mit
  `[0x17]=51` **noch** ein Disk-Record mit `[0x17]=51`.
⇒ `DS:0x4B4[51]` ist aus den statischen Aktivierungsdaten **nicht bestimmbar**.
Entweder ist die class_id-51-Auflösung anders (evtl. läuft `&g(armrest)` über
value_b=17, nicht class_id=51, oder über eine andere Tabelle), oder `DS:0x4B4`
wird von einer noch nicht identifizierten Aktivierungsphase befüllt. **Ein
Live-Trace von `DS:0x4B4` (Segment + Slot 51*4) während `examine armrest` ist
jetzt der einzige verlässliche Weg, den Widerspruch aufzulösen** — ohne ihn
wäre jede `condition_records`-Verdrahtung geraten. Kein Code bis dahin.

### `&g` nutzt den amp-Pfad, nicht die DS:0x4B4/class_id-Sackgasse (2026-07-06, Option b)

Statisch verfolgt, wie `examine armrest`s `&g` tatsächlich evaluiert wird:
- `AsgGame.examine_object` → `render_with_conditional_spans` →
  `_evaluate_conditional_span` → `vm.evaluate_message_control("&", (16,3), …)`.
- Dort: `decoded_opcode = 0x57 + operands[0] = 0x57+16 = 0x67` ('g'). Die
  amp-Branch-Kette behandelt `0x7D/0x74/0x62/0x64/0x6B/6C/6D/70` — **`0x67`/`0x66`
  /`0x69` (g/f/i) fehlen** → Fallback `evaluate_amp_resolved(opcode, node)`, das
  `g`/`f`/`i` ebenfalls nicht kennt → **`None`** → `&g` unaufgelöst, beide
  Zweige lecken.
- **Wichtig:** Die bestehenden amp-Branches (z.B. `0x6B`) lesen
  `self.phase7_runtime.get(resolved_node)[0x18]` — also den **phase7_runtime-
  Node** (via `resolve_amp_operand`/sub_AE9E), NICHT die separate DS:0x4B4/
  class_id-Tabelle. ⇒ **Die vorherige DS:0x4B4-Analyse betraf den `$g`-Pfad; der
  reale `&g`-Pfad ist amp+phase7_runtime — tractabel und bereits verdrahtet.**

**Verbleibende Lücke (präzise):** `resolve_amp_operand(3)` (der `&g`-Selektor
für die Armlehne) liefert aktuell **0** (ungültige Node) — der amp-Cursor
(`byte_1a4c`) ist beim EXAMINE nicht auf die Objekt-Node gesetzt. Der
EXAMINE-Pfad etabliert keinen Objekt-Kontext.

**Aktualisierter Fix-Plan (context_type 0 / EXAMINE-State-Variant), keine
Sackgasse mehr:**
1. EXAMINE-Pfad muss den Objekt-Kontext setzen (`byte_1a4c` → phase7_runtime-
   Node des examinierten Objekts), damit `resolve_amp_operand` die richtige Node
   liefert (statt 0).
2. g/f/i-Branch in `evaluate_message_control`s amp-Kette (`decoded_opcode`
   0x67/0x66/0x69) ergänzen: Guard `phase7_runtime[node][0x18]==0`,
   `g=[0x1B]`, `i=~[0x1B]`, `f=[0x1C]` (deckt sich mit `sub_C6BB`).
3. `&`-Parsing in `render_with_conditional_spans` ergänzen (parst aktuell nur
   `$`/`^`).
4. OPEN das `[0x1B]` der Objekt-phase7_runtime-Node schreiben lassen.
Offen für 1.: welche phase7_runtime-Node gehört zum examinierten Objekt (die
Objekt→Node-Zuordnung).

**Selektor bestätigt:** `resolve_amp_operand(3)` → `selector = 0x87+3 = 0x8A` →
`state.byte_1a4c` (der Node-Cursor).

### Implementierungsversuch (2026-07-06): Node wird vom Composite selbst gesetzt, nicht vom Aufrufer — echter Blocker ist die Node-38-Befüllung

Alle 4 Fix-Teile probeweise implementiert (g/f/i-Branch in `evaluate_message_
control`; EXAMINE setzt `byte_1a4c`=Objekt-id; OPEN schreibt `[0x1B]`;
`&`-Parsing war schon da). Ergebnis: **funktioniert nicht** — sauber revertiert,
keine Regression (Suite 411, nur der vorbestehende Chase-Test-Fehler).

**Warum (per byte_1a4c-Write-Trace während `examine armrest`):**
1. `game.py`-Set `byte_1a4c=17` → sofort vom **Record-Open-Reset**
   (`actions.py:83/92`, sub_7BB7) auf 0→1 überschrieben.
2. Dann setzt **`apply_message_continuation` (vm.py:188) `byte_1a4c=38`** aus
   dem `|a{30}`-Continuation-Descriptor, der direkt HINTER dem `&g`-Operand im
   Composite steht (`&g t|a{30}open`). ⇒ **Der Composite bestimmt die
   condition-Node selbst über `|aX` — nicht der Aufrufer/EXAMINE.** Objekt→Node
   ist also NICHT „Objekt-id"; die Node-Nummer (38) ist im MESSAGE-Record
   kodiert.
3. Aber `phase7_runtime[38]` hat `[0x18]=6` (Guard `==0` schlägt fehl) →
   `&g` immer False → examine **immer** „closed" (auch nach OPEN). Der
   „closed"-Render ist ein Guard-Fail-Artefakt, kein State-Tracking.

**Echter Blocker (neu, präzise):** Die vom Composite designierte condition-Node
(38 via `|a{30}`) ist in `phase7_runtime` **nicht stateful** (`[0x18]=6` statt
`0`). Entweder ist die `phase7_runtime`-Befüllung für Node 38 unvollständig/
falsch, oder der `|a{30}`-Deskriptor dekodiert zur falschen Node-Nummer
(`0x30`→38-Round-Trip prüfen).

### Aufgelöst: die Node ist ein bewusster Slot-1-Alias — jetzt eine Oracle-Frage (2026-07-06)

Beide Teilfragen geklärt:
- **(a) Decode-Bug bestätigt, aber irrelevant:** Symbol `0x30`(48) hat keinen
  Char in `DEFAULT_SYMBOL_TABLE` → `parse_conditional_spans` macht daraus `"?"`
  → `apply_message_continuation` `reverse["?"]` = 38. `byte_1a4c=38` ist also
  eine Symbol→Char→Symbol-Round-Trip-Korruption (Roh-Node wäre 48). Ein echter
  kleiner Bug, aber ohne Effekt hier, weil:
- **(b) Node 38 UND 48 sind absichtliche Slot-1-Aliase:** `vm.py:130-133` füllt
  `phase7_runtime[byte_19e9+1 .. 63]` bewusst mit einem Alias von Slot 1
  (`[0x18]=6,[0x1b]=1`) — **entspricht dem nativen `loc_179B..17F0`** (ungenutzte
  Far-Pointer-Slots → Slot-1-Alias). Die `|a{30}`-Node (48) ist also nativ wie
  in Python ein Slot-1-Alias, Guard `[0x18]==0` schlägt fehl → `&g`=False.

⇒ **Das ist keine Port-Lücke mehr, sondern eine Semantik-Frage:** Mit dem
g-Branch gäbe `&g` hier faithful False → „open"-Fragment gedroppt → „is closed".
Das aktuelle „is open…closed"-Garble entsteht nur, weil der ungehandelte `&g`
`None` (→ Fragment behalten) liefert. **Nächster Schritt braucht einen nativen
Oracle:** rendert das echte Spiel `examine armrest` nach OPEN „is open" oder
„is closed"?
- „is closed" (immer) ⇒ g-Branch ist faithful, wieder einbauen; der Open-Zustand
  wird über einen anderen Record/den `^`-Zweig angezeigt.
- „is open" ⇒ die `|a{30}`→Slot-48-Auflösung ist falsch (echte Node in 1-26),
  Descriptor-Formel revidieren.
Ohne diesen Oracle ist jede Entscheidung geraten (TP3-limitierter Live-Trace:
2 Reads — examine armrest closed vs. open).

### NATIVER ORACLE erfasst (2026-07-06, DOSBox-X selbst gefahren)

Via `DriveSession` das echte GAME.COM gefahren (N → Intro → Chase-Prompt):
```
-> open armrest
You open the armrest. It contains the buttons. ...
-> examine armrest
The leather armrest between the seats of the DB5 is open, exposing a panel with
several buttons. ...
```
⇒ **Das echte Spiel zeigt nach OPEN „is open, exposing a panel with several
buttons".** Die „faithful always-closed"-Hypothese ist damit **FALSIFIZIERT** —
State-Tracking existiert; der native `&g` liefert True (offen), also liest er
eine **stateful Node** ([0x18]==0, [0x1b]=1-nach-OPEN), NICHT den Slot-1-Alias
(Node 38/48, [0x18]=6). Die aktuelle `|a{30}`→38/48-Auflösung ist also falsch.

**Bestätigte Anforderung an den Fix:** `&g` muss auf eine stateful Node in 1-26
auflösen (Kandidaten mit `[0x18]==0`: Nodes 2,8,10,11,13,17), deren `[0x1B]`
OPEN/CLOSE trägt. Das aktuelle Garble „is open…closed" entsteht nur, weil der
ungehandelte `&g` `None` (→ beide Fragmente behalten) liefert.

**Verbleibender Kern (statisch, kein Oracle mehr nötig):** Welche Node/welcher
Pfad liefert nativ das stateful Ergebnis? Zwei Modelle noch nicht sauber
getrennt: (i) amp-Pfad `phase7_runtime[byte_1a4c]` (byte_1a4c wird aber vom
Record-Open-Reset auf 1 und der `|`-Continuation auf 38 geklobbert), vs. (ii)
`sub_C6BB` liest `DS:0x4B4[node[+3]=class_id]` direkt. Nächster Schritt:
bestimmen, ob `sub_CAE0/sub_D814` (Aufrufer von `sub_C6BB`) der `$`- oder
`&`-Dispatcher ist — das entscheidet, ob `&g` `DS:0x4B4[class_id]` (stateful,
per Objekt) oder `phase7_runtime[byte_1a4c]` liest, und damit die richtige
Node-Auflösung.

**Tooling-Notiz:** DOSBox-X-Oracles sind jetzt self-service (kein User nötig):
`DriveSession` + `dosbox-trace.conf` end-to-end gefahren (Launch → N → Intro →
Chase-Prompt → examine/open/examine gelesen).

### ✅ GELÖST: EXAMINE-State-Variant portiert + oracle-validiert (2026-07-06)

Implementiert und gegen den nativen Oracle bestätigt:
- **`vm.py`**: g/f/i-Branch (`decoded_opcode` 0x66/0x67/0x69) in der amp-Kette von
  `evaluate_message_control` — Port von `sub_C6BB` (Guard `node[+0x18]==0`,
  `g=[0x1B]`, `i=~[0x1B]`, `f=[0x1C]`). Die condition-Node ist
  `condition_node_override` (die vom EXAMINE gebundene Objekt-Node), nicht der
  vom Record-Reset/`|aX` geklobberte amp-Cursor.
- **`game.py::examine_object`**: setzt `vm.condition_node_override = vocab_id`
  (Objekt-Node = Objekt-id) um den Render, `finally`-cleared. Das umgeht die
  Cursor-Timing-Falle (sub_7BB7-Reset→1, `|a{30}`-Continuation→38) sauber, indem
  die EXAMINE-Verb-Bindung die Objekt-Node direkt liefert — funktional äquivalent
  zum nativen EXAMINE-Dispatch, der den condition-Cursor aufs Objekt setzt.
- **`game.py` OPEN/CLOSE**: schreibt `phase7_runtime[object_id][0x1B]` = 1/0
  NACH dem Response-Render (loc_DE1A, Guard `[0x18]==0`), damit OPENs eigener
  Composite noch den Vor-Zustand sieht („you open …") und ein späteres EXAMINE
  den neuen.

**Verifiziert gegen echtes GAME.COM (DOSBox-X):** closed→„is closed";
nach OPEN→„is open, exposing a panel with several buttons"; nach CLOSE wieder
„is closed". Regressionstest `test_examine_armrest_tracks_open_closed_state_
variant`. Suite 412, keine neue Regression (nur der vorbestehende Chase-Test).
Andere Objekt-Examines unverändert (Override greift nur bei `&g`/`&i`/`&f`).

**Damit ist der erste vollständige State-Variant-Predicate-Fix des Composite-
Cores gelandet** — datengetrieben aus MESSAGE, oracle-validiert, kein Hardcoding.

### Raum 61 / die Scheunen-Helikopter-Composite-Region = Section-Selector-Fall (2026-07-07)

Durchspiel-Oracle verfolgt (SAVE2 = native 43 in DOSBox-X geladen, bis zur
Scheune navigiert; die volle Navigation in die Helikopter-Cockpit war durch
Tooling-Flakiness blockiert — Digit-Slot-Prompt liefert die Taste zwar aus
[LOG `pop key code=0x0332`], aber Screen-Refresh/queued-Commands + geschlossene
Scheunentür + TP3-Crash-Risiko machten das saubere Erreichen unzuverlässig).

**Aus den Daten + Walkthrough eindeutig charakterisiert:**
- Raum 61s echter Text ist die **Helikopter-Cockpit** (Symbol **62818**, len 165):
  „Two moulded seats fill up most of the cockpit of the helicopter. …glass dome
  arcs overhead and on all sides." — **exakter Match zu walkthrough.txt Zeile
  383** (Validierungs-Input).
- **Segment-Struktur** (dict_symbols): Cockpit-Text endet bei ~62978 („…sides"),
  dann `|@@@@`-Gap, dann `xf&:g$p$|av you step…` (Prädikat-Segment = das
  „you step/already IN J/open door first"-Garble). Raum 61s `msg_off*8 = 62984`
  zeigt HINTER den Cockpit-Text auf dieses Prädikat-Segment → `render_room_
  segment` überschießt.
- **Kein Raum rendert die Cockpit-Text** (verwaist); Raum 60 rendert „You step
  out of G at I." (eine Transition, kein Raumtext — ebenfalls fehl-aufgelöst).
  ⇒ Die Scheunen/Helikopter-Region ist ein **geteiltes Composite mit mehreren
  Räumen** (60, 61, …), deren `msg_off` alle in denselben Multi-Segment-Block
  zeigen; die Auswahl braucht den **Section-Selector** (`@LABEL` gegen State),
  nicht die strukturelle Gap-Heuristik.

**Fix-Optionen:** (a) den Section-Selector portieren (groß, betrifft alle Räume,
oracle-gated), oder (b) oracle-bestätigte per-Raum-`NativeSpan`-Overrides
(MESSAGE-Zeiger, wie die config-`read_responses`/`take_responses`) — aber NUR
mit sauberem Oracle für die exakte Raum→Segment-Zuordnung (Raum 60 vs 61 ist
ohne Live-Oracle nicht sicher trennbar). Kein Patch auf Rest-Unsicherheit.

### ✅ GELÖST: der Raum-Offset ist ein RECORD-INDEX, kein Symbol-Offset (2026-07-07)

Die ganze „Section-Selector"-Saga unten war eine **falsche Abstraktion**:
`render_room_segment` behandelte `room.message_offset` (record[+1] LE) als
**Symbol-Position** (`msg_off*8`) und gap-scannte — deshalb die Overshoots,
Duplikate und der scheinbare „state-based Selector"-Bedarf.

**Der Offset ist ein MESSAGE-RECORD-INDEX.** `render_message_record(offset)`
(die native Record-Framing) rendert jedem Raum seine eigene Beschreibung:
- Duplikat-Gruppen **13 → 2**, garbled **1 → 0** über alle Räume.
- **4/4 Live-Oracles** (byte_6A9 live in DOSBox-X): native 20 (DB5-Cockpit),
  32 (Bunker), 43 (Stud graveled drive), 60 (Heli-Cockpit) — alle korrekt, wo
  mehrere vorher clean-but-wrong waren.

`room_description` nutzt jetzt `render_message_record` (Fallback:
`render_room_segment` nur wenn leer). Der per-Raum-Span-Override (Raum 60) ist
damit redundant und entfernt. **Kein state-based Section-Selector-Port nötig.**
Verbleibend: ~2 Duplikat-Gruppen + „movement"-Text-Räume (33/41/48/61…) — das
sind Transition/Subsystem-Zustände (Chase/Flug/Türen), kein statisches
Raum-Rendering. Die folgende Analyse ist damit historisch (der Diskriminator war
gar nicht nötig — es war nie ein Symbol-Offset).

### GRÖSSERER BEFUND: die Raum-Section-Selection ist BREIT falsch (2026-07-07)

Nicht nur Raum 60/61. Duplikat-Scan: **12 Gruppen** von Räumen rendern
identischen (geteilten Nachbar-)Text — z.B. rendern die Räume 23/24/25/26/28
alle „Pebbled tar covers the flat roof of the factory", 54-57 alle „You slip
into a long and narrow hall". Viele Räume rendern also *clean-but-wrong* Text
(die frühere „62/65 korrekt"-Annahme war zu optimistisch — „clean" ≠ „korrekt").

**Live-Oracle bestätigt (DOSBox-X, SAVE2):** `byte_6A9 = 43`, Spiel-Text =
„…front porch of the 'Gone with the Wind' style mansion… graveled drive". Aber
`render_room_segment(43)` = „Ankle-high bluegrass covers this empty field" —
**FALSCH**. Die *render-from-offset*-Variante von Raum 43 = „graveled drive" =
KORREKT.

**Validierungs-Datensatz (Oracle-bestätigt, welcher Ansatz korrekt ist):**
| Raum | korrekt via | rec[+6] | section_state |
|------|-------------|---------|---------------|
| 20 (DB5-Cockpit)   | beide (current+fromoff) | 0x15 | 5 |
| 41 (Fabrik-Decke)  | **current** (skip-to-gap) | 0x01 | 5 |
| 43 (graveled drive)| **fromoff** (at-offset) | 0x28 | 5 |
| 47 (Flug)          | **current** | 0x01 | 5 |
| 60 (Heli-Cockpit)  | **fromoff** | 0x3d | 5 |

⇒ **Kein einfacher Diskriminator gefunden:** alle `section_state=5`; `+6/+7`
sind Richtungs-Slots (kein Selektor); auch die Gap-Distanz trennt nicht sauber
(Raum 20 und 60 haben beide ferne Gaps ~185/164, aber 20 ist via current
korrekt, 60 nur via fromoff). Die Selektion ist genuin state/struktur-abhängig
und irregulär — der native Raum-Render-Section-Select muss im Assembly
lokalisiert werden (Diskriminator ist NICHT `turn_resolve_text`s `record[+6]`).

**Konsequenz:** per-Raum-Span-Overrides (wie Raum 60) skalieren nicht auf die
~40 betroffenen Räume — der **volle state-basierte Section-Selector-Port** ist
gerechtfertigt. Das Tooling ist jetzt gefixt (Oracles verfügbar) und ein
Validierungs-Datensatz existiert; der nächste Schritt ist, die native
Selektionslogik im Assembly zu finden (welcher Zustand/welches Feld wählt
„at-offset" vs „skip-to-gap") und gegen den Datensatz zu portieren.

### Warum die Gap-Heuristik prinzipiell nicht reicht (2026-07-07, definitiv)

`render_room_segment` hat drei Strategien, alle rein strukturell: Forward
(skip-to-`@@`-gap → render), und ein Backward-Fallback (nur wenn Forward leer).
Getraced für die betroffenen Räume:
- **Korrekt gerenderte Räume** (z.B. 20): Forward-Render ist LEER → Backward-
  Fallback greift → richtiger Text. Ihr Text liegt direkt NACH einem Gap.
- **Raum 60** (= Helikopter-Cockpit): Forward → „You step out of G at I."
  (nicht-leeres FALSCHES Nachbar-Segment), Backward → „E glance at this amazing
  flying machine…" (noch ein anderes) — **KEINER** liefert die Cockpit-Text
  („two moulded seats", Symbol 62818), die **direkt am Offset** (62816, zwischen
  zwei Gaps) liegt. Nur „render vom Offset direkt" liefert sie — aber das ändert
  **63/65 Räume** (bricht die, deren Offset korrekt auf ein `@LABEL`/Gap zeigt).
- **Raum 61**: Forward → Garble, Backward → „You step out of G at I."

**ORACLE erfasst (2026-07-07, DOSBox-X, nach dem Tooling-Fix):** In-Game bis in
die Helikopter navigiert (`GET IN`); `byte_6A9 = 60` (DS=15DC). ⇒ **Native Raum
60 IST die Helikopter-Cockpit**, echter Text „Two moulded seats fill up most of
the cockpit of the helicopter. A large cargo area stretches behind them. A great
tinted glass dome arcs overhead and on all sides." (= Symbol 62818). Meine
frühere Annahme „Raum 61 = Cockpit" war FALSCH — es ist **Raum 60** (dessen
Offset 62816 direkt auf 62818 zeigt); er rendert aktuell fälschlich „You step
out of G at I."

**Raum 60 GEFIXT (2026-07-07):** oracle-validierter per-Raum-Span-Override
(`AsgConfig.room_description_spans`, Symbol 62818) — dasselbe captured-
MESSAGE-Pointer-Pattern wie `read_responses`/`take_responses`, keine Prosa.
Regressionstest `test_room_60_renders_helicopter_cockpit_via_span_override`.

**Raum 61 ist KEIN statischer Raum, sondern der Helikopter-Flug-Zustand:**
native 60 (Cockpit) → ALLE Ausgänge (N/S/E/W/U) → 61; native 61 → 47 (Flug)
oder D → 60. Das ist das **„Trap"-Muster wie beim DB5-Chase** (alle Ausgänge auf
einen Zustand). Raum 61s Prädikat-Segment (`&:g$p$`, „already IN J"/„open door
first") ist state-gated Flug-Text. ⇒ Raum 61 gehört zum **Helikopter-Flug-
Subsystem** (analog zum Chase), NICHT zu den span-patchbaren statischen Räumen —
aufgeschoben mit dem Flug/Chase-Subsystem, kein einfacher Section-Selector-Fall.

⇒ **Es gibt keine strukturelle Einzelregel**, die sowohl „Text nach Gap" (die 62
funktionierenden) als auch „Text zwischen Gaps am Offset" (60/61) korrekt
auflöst. Genau dafür nutzt das native Engine den **state-basierten Section-
Selector**: `turn_resolve_text` (sub_4E03) liefert Record-Ref + `section_state`
(`[DS:0x4B11]` = 5/6/7), und die `@LABEL`-Auswahl matcht gegen diesen Zustand.
Der Port braucht diesen Zustandspfad für Raumbeschreibungen (nicht nur die schon
portierte `render_message_record(section=…)`-Label-Matching-Maschinerie) PLUS
ein Live-Oracle zur Validierung der Raum→Segment-Zuordnung. Das ist ein
substanzielles, oracle-gated Kernstück — kein sicherer struktureller Hack.

### context_type 2 / Raum-Mapping: bestehende Implementierung assembly-bestätigt (2026-07-06)

Der `DS:0x25C`-Build (`byte_19ea`-Seed 1, sequentieller Slot je Typ-2-Record)
sagt: **native Raum r → r-ter Typ-2-Record in Stream-Reihenfolge**. Empirisch
verifiziert gegen die Grundwahrheit (native 20 = DB5-Cockpit):
- `recs[19]` (naive Disk-Index-`r-1`-Konvention) → `''` (falsch, ist ein
  Typ-1-Objekt).
- **20.-Typ-2-Record (Disk idx 58) → „The cockpit of the DB5…"** (korrekt).

**Und genau das tut der bestehende Code schon:** `AsgGame.__init__` baut
`rooms` aus `records_by_type(0x02)` sequentiell, also `native r → rooms[r-1] →
r-ter Typ-2-Record`. Live bestätigt: native 20→Cockpit, 32→„You climb through
J…", 33→„You pass through J." rendern echten Raumtext. ⇒ **Die lang offene
„room-32 mapping / -1 convention"-Unsicherheit ist aufgelöst: das Python-
Raum-Mapping ist korrekt und entspricht dem nativen `DS:0x25C`-Mechanismus
(sequentiell über Typ-2, nicht Disk-Position).** Der „section selector" ist
damit für context_type 2 keine offene Frage mehr — der Assembly-Fund validiert
die vorhandene Implementierung.

## Testgrenze, 2026-07-02

Die Tests referenzieren den gelöschten titelspezifischen Goldfinger-Interpreter
nicht mehr. Interpreter-, Szenen-, Sequenz-, Verb-, Runtime-Record-, Play-,
Daten-, Aktivierungs- und Invalid-Path-Tests laufen direkt gegen `AsgGame`,
`AsgVm` und die gemeinsamen Engine-Primitiven. Die vollständige Discovery
führt 350 Tests fehlerfrei aus; nur der komplette 103-Züge-Walkthrough-Diff
bleibt bis zur vollständigen nativen Action-/Sequenz-Ausführung übersprungen.

`$e` folgt außerdem inzwischen über `sub_4C44` in die Phase-9-Tabelle
`DS:5B0`: `byte_1B45` wählt Abschnitt 5, andernfalls liefert der passende
Phase-9-Datensatz sein Wort an `+2` und Abschnitt 2; bei abweichendem Raum wird
der native Fallback-Zeiger in Slot 1 verwendet. Der Abschnitt-5-Abzweig
`sub_3870` ist ebenfalls portiert: die vier Byte große Kandidatenmenge im
aktuellen Phase-8-Raum entscheidet über `1A50`/`1A57`/`1A48`, anschließend
kommt das Antwortwort aus Phase-6 `+0A`. Der Matching-Room-Seiteneffekt
`sub_4936` ist nun ebenfalls portiert: gerichtete Traversierung über `6AA`,
Zyklenschutz, Kontext-Sentinel und Auswahl aus der mutablen `4ACD`-Frontier.

## Action-Cursor, 2026-07-02

Die frühere Deutung von `msg_ctrl_section` als reiner Abschnittsselektor war
falsch: sein Prolog fällt direkt in `sub_EF31`. `sub_AE27(0x32)` liest genau
einen Opcode als `MESSAGE-Symbol + 0x32`; dessen Handler kann weitere Symbole
aus demselben Cursor konsumieren. Der Renderer übergibt bei `(` deshalb die
vollständige Restfolge an `AsgVm.execute_action_block`.

Live portiert sind 32h..35h, 39h/3Ah/44h/45h, 41h, 46h, 48h, 49h, 4Ah,
4Bh, 3Dh/3Eh/3Fh und 55h: mutable Phase-7-Knoten, Runtime-Felder,
Set-/Besitztransfers, Raumflags, RNG und native Uhr. Im Walkthrough-Replay
bleiben als echte Action-Handler 38h (`sub_9AFF`) und 40h (`sub_9FBC`);
drei frühere 33h-Aufrufe waren Folge der zunächst fehlenden nativen
Zeigerauffüllung: `sub_132B` lässt alle Phase-7-Slots nach `byte_19E9` bis 63
auf Slot 1 zeigen. `1A4C=57` ist damit gültig und im Port als echte
Bytearray-Aliasbeziehung umgesetzt. 40h (`sub_9FBC`) ist einschließlich der
mutablen Phase-9-Record-Transition portiert. Im 103-Zug-Replay bleibt damit
nur 38h (`sub_9AFF`).

Der im Goldfinger-Replay aktive `38h`-Zweig (`1AEC != 1`) ist inzwischen als
gemeinsamer gerichteter Raumübergang portiert. Damit enthält der komplette
103-Zug-Replay **keinen ungelösten Action-Opcode mehr**. Offen bleibt der im
Der im Replay nicht erreichte `1AEC == 1`-Graph-Rewire-Zweig derselben Routine ist
nun ebenfalls portiert: Kontext-, aktueller, Brücken- und Zielraum werden wie
im nativen Stackframe getrennt behandelt; DS:5B0 `+0E`, `1AE5`, `+11` und die
sechs Richtungsfelder werden mutiert. Damit ist 38h vollständig abgedeckt.

> **AUSGEFÜHRT (2026-07): der Schnitt ist erfolgt.** `games/goldfinger/` ist von
> ~6.400 auf ~450 Zeilen (config + `records.py`-Daten + `play.py`) geschrumpft;
> `interpreter.py` (GoldfingerGame), `handlers.py`, `chase.py`, `scenes.py`,
> `sequences.py` wurden **gelöscht**. Goldfinger läuft jetzt über den geteilten
> VM-Pfad (`gameengine/game.py::AsgGame` + `gameengine/AsgVm`) — datengetrieben
> für die Basis (Movement/LOOK/EXAMINE/TAKE/DROP/WAIT/KILL). Verbleibend: der
> Prädikat-Kern (filtert Composite-Verb-Records OPEN/PRESS/READ) + Action-VM-
> Effekte; Tests gegen den VM-Pfad neu schreiben. Der Rest dieses Dokuments ist
> die (weiterhin gültige) RE-Analyse zum Kern-Subsystem.

## Zielprinzip (verbindlich)

Der ASG-Interpreter ist eine **VM, die pro Titel Daten ausführt**. Daraus folgt die
harte Trennung:

- **`gameengine/` (die VM) enthält ALLE Logik** — Parser, Aktivierungskette,
  Per-Turn-Dispatcher, Action-Executor, Prädikat-Evaluator, MESSAGE-Template-
  Interpreter, Save/Load-Mechanik.
- **`games/<titel>/` enthält NUR spielspezifische DATEN** — die Datendateien
  (`MESSAGE`/`VOCAB`/`TABLES`) plus eine triviale `config.py` (Launcher-Name,
  TABLES-Stride, Anzeigename).

**Kein Byte und keine Byte-Interpretation wird als Python-Logik pro Titel
nachgebaut.** Wenn die VM den Bytecode konsumieren muss, um das Spiel spielbar zu
machen, dann gehört diese Konsumtion in die VM — nicht in den Spielecode.

Der Endzustand: `games/goldfinger/` sieht aus wie `games/rambo/` (Config + Daten,
sonst nichts). Die Goldfinger-Zeilenzahl ist die Burn-down-Metrik dafür, wie
vollständig die VM wirklich ist.

## Beweis, dass das technisch möglich ist

`GAME.000` ist das Overlay mit Dispatcher + Action-VM + Aktivierungskette. Sein
MD5 über die installierten Titel (2026-07-01):

| Titel | TABLES-Stride | `GAME.000` MD5 |
|---|---|---|
| Goldfinger | 40 B | `bfa2351ac27a23bd22102a7138e40d1a` |
| Indiana Jones | 40 B | `bfa2351ac27a23bd22102a7138e40d1a` |
| High Stakes | 40 B | `bfa2351ac27a23bd22102a7138e40d1a` |
| Forbidden Castle | 47 B | `3d38582dc51fcd6b92371cd508fd6afa` |
| A View to a Kill | 47 B | `3d38582dc51fcd6b92371cd508fd6afa` |
| Rambo | 47 B | `3d38582dc51fcd6b92371cd508fd6afa` |
| The Mist | 47 B | `e495f39a61cb747ef4da8d74d88fdf6f` |
| Voodoo Island | 47 B | `0c6c760199d90129defeef78d8fde48d` |

**Dasselbe `GAME.000`-Executable (byte-identisch) fährt drei verschiedene Spiele**
(Goldfinger/Indiana/High-Stakes). Damit ist bewiesen: die komplette Spiel-Logik
ist bereits im Original geteilt; das gesamte Spielverhalten steckt in den Daten.
Der VM-Ansatz ist nicht nur richtig, er ist der Original-Entwurf. Folgerung: jede
substanzielle spielspezifische Python-*Logik* ist Port-Schuld, kein legitimer Layer.

(Randnotiz: die zwei MD5-Cluster entsprechen exakt den zwei TABLES-Strides 40/47.
The Mist und Voodoo sind kleine Overlay-Revisionen derselben Engine-Familie.)

## Audit: aktueller `games/goldfinger/`-Bestand

Gesamt ~6.650 Zeilen. Klassifikation jeder Region:

Legende: **DATA** = bleibt (echte Spieldaten/Config) · **→VM** = Logik, gehört nach
`gameengine/` · **→VM-STATE** = VM-Laufzeitzustand, gehört nach `gameengine/`
(Dublette existierender Engine-Typen) · **→VM-REKONSTRUIEREN** = eingefrorene Daten,
die die VM beim Laden selbst erzeugen müsste.

### `handlers.py` — 2.373 Zeilen → **komplett →VM**

Alle Per-Verb-Handler (`handle_take/open/press/put/examine/...`) sowie die
kuratierten Pro-Objekt-Helfer (`_plaque/_cable/_paper_branch_suppressed`,
`_white/_gray/_black_button_success`) sind Logik, die das Original aus Action-VM-
Opcodes (TABLES) + Antwort-Records (MESSAGE) erzeugt. Beispiele der Schuld:

- `handle_take` hardcodet Sonderfälle (`badge`+Helikopter, `pull`+`cable`) und
  schreibt Prädikat-Bits (`0671[32]`, `0679[32]`) **von Hand aus einem Trace**,
  statt sie via Action-Opcode aus Daten abzuleiten.
- Branch-Auswahl, die nativ über das `|`/`$`/`&`-Gate + Prädikat-Sets läuft.

Ziel: `handlers.py` → ~0. `build_default_dispatcher` wird zur Engine-Registrierung.

### `interpreter.py` / `GoldfingerGame` — 3.311 Zeilen

| Region (Methoden) | Zeilen ca. | Klassifikation | Engine-Ziel / vorhandener Typ |
|---|---:|---|---|
| `SceneGlobals` (Klasse) | 98 | **→VM-STATE** | `gameengine/activation.py::AsgActivationState` (Dublette) |
| `GameState` | 52 | teils DATA / teils →VM | `gameengine/world.py::EngineGameState` (Basis existiert) |
| `_evaluate_message_control`, `evaluate_message_predicate`, `apply_resolved_section_type` | ~120 | **→VM** | `AsgPredicateEvaluator` / `gamecom` (delegiert teils schon) |
| Aktivierungskette `activate_initial_scene`, `apply_scene_record`, `_apply_phase_1_D61`..`_apply_phase_9_1989` | ~270 | **→VM** | `AsgActivationRuntime` (Dublette — engine-compatibility.md nennt das explizit) |
| `enter_scene`, `populate_runtime_records`, `per_turn_evaluate_records`, `per_turn_execute_transfers` | ~190 | **→VM** | `AsgPerTurnDispatcher` (existiert) |
| Rendering `_render_msg`, `room_description`, `_visible_objects_text`, `opening_text` | ~140 | **→VM** | `GameComMessageEngine` / `VisibilityRules` (existieren) |
| `_native_parser_confusion` | ~10 | **→VM** | Engine-Parser-Fallback |
| `handle` (Dispatch-Schleife) | ~210 | **→VM** | `VerbDispatcher` (Framework existiert) |
| Movement/Interaktion `_handle_movement_word`, `_handle_auric_password`, `_dispatch_get_in/out`, `_handle_npc_tell_about`, `_move` | ~330 | **→VM** | Action-VM + Dialog-/Bewegungs-Daten |
| **Chase** `_handle_chase_direction`, `opening_chase_turn_response`, `opening_chase_tilly_response` | ~790 | **→VM** | größter Block; Chase muss datengetrieben über Action-VM laufen |
| Save/Load `build_save_data`, `_chase/_native_field/_scene_globals_pack/unpack`, `save_game`, `load_save` | ~360 | **→VM** | `gameengine/savegames.py` (diff-vs-pristine generisch); nur Watermark/Layout als Config |

### `records.py` — 339 Zeilen → **→VM-REKONSTRUIEREN**

`VERB_RESPONSE_RECORDS` wird laut `data-format.md` **zur Laufzeit vom GAME.COM-
Loader aus den Daten gebaut** (DS:0x5F0, nicht statisch). Wir haben sie per Memdump
eingefroren. Faithful: die VM baut sie beim Laden nach. `MESSAGE_RECORD_*`-
Konstanten sind teils geteilte Templates (Engine) / teils daten-ableitbar.

### `chase.py` (359) · `scenes.py` (88) · `sequences.py` (47)

Mischung aus Szenen-Struktur und eingefrorenen MESSAGE-Spans/Zählern. Die
Szenen-Aktivierung gehört in die VM (aus TABLES); die hardcodierten Chase-Spans
sind einzufrierende MESSAGE-Captures → **→VM** (datengetrieben rendern). Ziel:
nahe 0, ggf. ein winziger trace-bestätigter Szenen-Deskriptor als DATA.

### `config.py` (27) · `play.py` (138)

`config.py` = echte **DATA** (Launcher, Stride, Name) → bleibt.
`play.py` REPL-Einstieg → sollte auf das generische `game.py::run`-Muster
zusammenschrumpfen.

## Definition of Done + Burn-down-Reihenfolge

Fertig, wenn `games/goldfinger/` ≈ `config.py` + Datendateien ist und Goldfinger
(plus die anderen 7 Titel) allein über `gameengine/` + `gameengine/game.py` läuft.

Abbaureihenfolge (jeweils: Regel in `gameengine/` portieren → Regressionstest →
Goldfinger-Sonderfall löschen; nie neue Sonderfälle hinzufügen):

1. **`SceneGlobals` + Aktivierungskette → `gameengine/activation.py`.** Reine
   Refactor-/Dedupe-Arbeit gegen `AsgActivationState`/`AsgActivationRuntime`, kein
   Trace nötig. Entfernt ~370 Zeilen Dublette.
2. **`VERB_RESPONSE_RECORDS`-Builder in die VM** (statt eingefrorene Tabelle).
   Löst `records.py` weitgehend auf und macht die Verb-Antwort daten-getrieben.
   **✅ ERLEDIGT (2026-07-08, rein statisch):** Der native DS:0x5F0-Builder
   (`GAME.000:2df3..2e51`) ist als `AsgActivationTables.build_verb_response_
   records` portiert und in `AsgGame` verdrahtet. Quelle statisch lokalisiert:
   der **Phase-1-Aktivierungs-Record hält bei `+0x19` (LE-Word) den MESSAGE-
   Record-Index einer gepackten Verb-Tabelle** (Goldfinger: Record 7921);
   `record_symbols(ptr)` framed sie, `record = s0*0x1000+s1*0x40+s2` pro Verb.
   Reproduziert alle vier exakt-gecapturten Titel und findet zusätzlich The-Mist
   verb 0x1E (Record 3409), den die Handcapture übersah. Die eingefrorenen
   `VERB_RESPONSE_RECORDS`-Dicts sind jetzt nur noch validierte Oracles
   (`tests/test_verbs.py`), zur Laufzeit redundant. Der `sub_469C`/`sub_9711`-
   TP3-Reader musste NICHT einzeln portiert werden, weil `record_symbols` das
   Record-Framing bereits liefert.
3. **Prädikat-Set-Inhalte tracen** (Tier 0: `DS:0670..06A8`) → `AsgPredicateEvaluator`
   entscheidet die Branch-Auswahl aus Daten → `handlers.py`-Sonderfälle fallen weg.
4. **Action-VM-Wertsemantik** vervollständigen → Verb-Effekte (TAKE/OPEN/PUT/...)
   kommen aus Opcodes statt aus Handler-Code.
5. **Chase datengetrieben** über Action-VM/SequenceMachine → größter Einzelblock.
6. **Save/Load → `gameengine/savegames.py`** vollständig generisch, nur Config-Reste
   pro Titel.

Metrik: `find games/goldfinger -name '*.py' | xargs wc -l` als laufender Burn-down;
Zielkorridor = Größenordnung der `games/rambo/`-Bindung.

## Manhole-Raumbeschreibung datengetrieben (2026-07-09)

Der letzte hartkodierte **englische Prosa-Ersatz** im geteilten Render-Pfad
(`_render_room_message`: `"In the ceiling above you..."` → `"In the ground..."`
für native 19) ist entfernt und durch eine **Cursor-Bindung** ersetzt.

- Das „ground"/„ceiling"-Wort steht in der geteilten MESSAGE-Record **3863**
  (referenziert per `\`-Dictionary aus native 19 UND native 42) und wird von
  einem daten-eigenen Gate gewählt: `&:i$ee|<ground>^<ceiling>` — die
  verschachtelte `&:X$YY`-Form (`sub_D4C4`). Amp-Selektor **0x8B** liest den
  Raum-Kontext-Cursor **byte_1A52**; die Vergleichsnode 130[+3] == **19**.
- Der Top-Level-MESSAGE-Open-Reset (`sub_7BB7` /
  `initialize_dispatch_cursors`) seedet byte_1A52 = 1 → Gate false → „ceiling".
  Nativ trägt byte_1A52 beim Beschreiben eines Raums die **aktuelle Raum-ID**;
  die Bindung wird jetzt im Open-Callback (`_open_message_record`) nach dem
  Reset gesetzt (`self._room_context_native`), sodass native 19 → „ground"
  (19==19) und native 42 → „ceiling" (42≠19) **aus den Daten** rendert.
- Oracle: `walkthrough.txt:53` bestätigt „In the ground is a manhole cover."
  für die Lookout Road. Regressionstest:
  `test_room_context_cursor_selects_manhole_ground_vs_ceiling`.
- Offen (trace-gated): der genaue native Schreibpfad, der byte_1A52 nach
  `sub_7BB7` auf den aktuellen Raum setzt (viele Writer, beweglicher Cursor).
  Das Ergebnis ist oracle-bestätigt; die Bindung ist die datengetriebene
  Realisierung, kein Prosa-Hack mehr.

## Statische Nebenbefunde (2026-07-08)

- **`byte_1AEB` = aktiver Phase-8/DS:0x438-Kontext-Slot-Index** (rein statisch
  dekodiert). Seed 1 bei New-Game (`overlay:5427`); geschrieben von der
  `*`-Section-Kontextlogik (`loc_F60`) und `sub_BA7D([bp+4])`; gelesen vom
  `$a`/`&a`-Kontext, vom Verb-Builder-Prolog (`2D89`: bei ==1 → `byte_1AE7=0`,
  sonst `DS:0x438[byte_1AEB][+0x14] == byte_6A9`?) und in `sub_B4AF`
  (`byte_4ADC := byte_1AEB` wenn ≠1). Bedeutung: Wert 1 = Default-Kontext
  (aktueller Raum); ≠1 = alternativer gleichzeitiger Phase-8-Kontext. Im
  Python-VM ist das für den Einzel-Kontext-Fall **redundant mit
  `amp_current_room`** — kein Laufzeit-Change nötig; relevant erst bei mehreren
  simultanen Kontexten (Chase/Heli), was trace-gated bleibt.

- **„Qa"-Leck (native Raum 30, Record 5007) GELÖST (2026-07-09).** Ursache war
  der `$v`-Selektor (0x76) bei `$$aq|`: der frühere 2508-Fix konsumierte fix EIN
  Operandensymbol ('a'), sodass 'q' als Prosa leckte. Das korrekte Muster ist
  „bis zum nächsten Control konsumieren" — das deckt **beide** Formen ab: die
  2508-Form `$$a@` stoppt am Control `@` (unverändert 1 Symbol), die 5007-Form
  `$$aq|` konsumiert 'a'+'q' bis zum `|`. Der 0x76-Handler
  (`evaluate_message_control`) liest weiterhin nur `operands[1]` (den ersten
  Wert); das zusätzliche Deskriptor-Symbol 'q' ist Dispatcher-Metadaten und wird
  nun mitkonsumiert statt geleakt. Kein Handler-Semantik-Change. 0x76 aus
  `_DOLLAR_ONE_SYMBOL_SELECTORS` herausgelöst und über einen eigenen
  „bis-Control"-Zweig in `_native_dollar_operand_end` behandelt. Regression:
  `test_dollar_v_selector_consumes_value_operand_to_next_control` (Decoder) +
  `test_dollar_v_gate_does_not_leak_descriptor_in_office` (End-to-End, Raum 30
  rendert „A small trap door" statt „Qa small trap door"). Der bestehende
  2508-Test (`test_dollar_v_selector_decodes_two_consecutive_dollars`, end==3)
  bleibt grün — beweist, dass die `$$a@`-Form nicht betroffen ist.

- **Raum-Garble-Scan (2026-07-09): 65/65 Räume rendern sauber.** Nach dem
  `$v`-Fix (Raum 30) und der Manhole-Cursor-Bindung ist kein Raum mehr
  geflaggt. Verbleibende Sonderfälle sind KEIN Garble mehr:
  - Native 61 („You step out of G at helicopter") ist ein Transition-/Flug-
    Zustand mit unaufgelöstem `%g` — Item-3-Subsystem (Chase/Heli), nicht die
    frühere „Ta! Pjam"-Verb-Response-Leakage (die ist durch die
    Cursor-Bindungs-Arbeit verschwunden).
  - Native 46 zeigte im Zwischen-Render ein Doppel-Leerzeichen zwischen dem
    Barn-Door-Zustandsrecord 3872 („…closed. ", mit Trailing-Space) und der
    Fortsetzung („ under…"). Das ist **kein Bug**: der Anzeigepfad
    (`present()` → `layout_text` → `_normalize_separators`) kollabiert
    Whitespace-Runs zu einem Leerzeichen, exakt wie die native 80-Spalten-
    Wortumbruch-Routine. `present()`-Ausgabe: „…closed. under…".

## Fortschritt

- **2026-07-01 — Sub-Schritt 1a (erledigt):** Charakterisierungs-Test
  `tests/test_activation_characterization.py` angelegt (Sicherheitsnetz). Der
  hardcodierte Startraum (`SUB_D61_FIRST_WRITE_ROOM_INDEX`) treibt die Aktivierung
  nicht mehr — `activate_initial_scene` leitet die Raum-ID jetzt aus
  `vm.activation.initial_native_room_id` ab (Beweis: identisch 0x0F). Volle Suite
  grün (501 Tests). Offen in Schritt 1: `enter_scene`/`_on_message_record_open`-
  Konsumenten und Save/Load auf Engine-Repräsentation umstellen, dann die
  9-Phasen-`_apply_phase_*` + decomposed `SceneGlobals`-Felder entfernen und die
  `test_interpreter.py`-Aktivierungstests vom Single-Record- auf das
  Per-Record-Engine-Modell umschreiben.
- **2026-07-01 — Befund zur Reihenfolge:** Die nicht-save-Konsumenten
  (`_on_message_record_open`, `enter_scene`) nutzen bereits `vm.activate()` — dieser
  Teil ist erledigt. Die verbleibende Entfernung der superseded Single-Record-
  Aktivierung (`apply_scene_record` + `_apply_phase_1..9`) ist **mit Save/Load
  verflochten**: `apply_scene_record` seedet den Scene-Globals-Zustand im
  Round-trip-Test (`test_interpreter.py`:759, 879). Daher **nicht** vor dem
  Save-Format separierbar → Save-Format-Umstellung und Entfernung als ein
  bewusster Schritt mit dem Round-trip-Test als Oracle.
- **2026-07-01 — Sub-Schritt 1b (erledigt):** Superseded Single-Record-Aktivierung
  entfernt: `apply_scene_record` + `_apply_phase_1_D61..9_1989` +
  `SR_OFFSET_*`/`SCENE_RECORD_BASE_OFFSET` aus `interpreter.py` gelöscht (−237 Z.);
  der Live-Pfad nutzt bereits `AsgVm.activate()` (Per-Record-Modell). Redundanten
  Aktivierungs-Testblock entfernt (−229 Z.; Abdeckung liegt in `test_activation.py`
  / `test_vm.py` / `test_predicates.py`). Die zwei Save/Load-Round-trip-Tests seeden
  `SceneGlobals` jetzt direkt statt über `apply_scene_record` — **Save-Format
  unverändert**. Volle Suite grün (486), Smoke (activate + LOOK + INVENTORY) ok.
  `games/goldfinger` gesamt ~6.705 → 6.468 Z.
  Rest von Schritt 1 (optional, save-format-berührend): `SceneGlobals` von decomposed
  Feldern zu einer dünnen View über `AsgActivationState` machen und den
  `enter_scene`-Bridge (~Z. 820–850) + das Save-Format auf die Engine-Repräsentation
  umstellen.

## Kern-Restsubsystem für die VM-Vollendung (2026-07-01)

Nach der RE dieser Session ist klar: **fast alle substanziellen Restpunkte münden in
EIN Subsystem — den vollständigen bedingten Prädikat-Evaluator** (die
`$`/`&`/`^`-Operanden-Semantik + die Phase-8-Kontext-Records). Belege:

- **Chase-Status** (Record 3637) wird über `$a`/`$e` gewählt → Kontext-Record-Sets.
- **LOCK/UNLOCK** (Record 2465, 15 Conditionals) hat keinen Erfolgspfad, nur
  bedingte Fehler-Varianten → dieselbe Evaluator-Auswahl.
- **`handlers.py`** kuratierte EXAMINE-/Objekt-Zweige = dieselben Prädikate.

`AsgPredicateEvaluator` deckt heute `y/f/g/i/t/x/h/v/q/;/u` ab; **offen** ist die
Kontext-Record-Set-Familie (`a/e/w` u. a.: `contains(node.+3, set@ contextrec[+0x0C/+…])`,
`sub_4CA8`=CONTAINS bestätigt, `sub_4C44`-Semantik noch offen) **plus** das Bereitstellen
der byte_1A50/byte_1A4C-selektierten Kontext-Records aus der Aktivierung. Ist das
portiert, fallen Chase, LOCK/UNLOCK-Varianten und weite `handlers.py`-Teile
gleichzeitig — das ist der Haupthebel für „VM vollständig".

**Opcode-Semantik-Fortschritt (2026-07-01, statisch dekodiert):** `$a` = `contains(node.+3, set@contextrec(byte_1A50)[+0x0C])`; `$e` = Set-Op auf `contextrec[bp-13h]`; `:` (0x3A) = Show-Once-Flag `record[+0x1C]` (test-and-set); `$t`/`&t` bereits bekannt (Kontext-Set +18). Nicht-Prädikate: `$p`/`$#`/`$ ` fallen im Dispatch durch → Prosa/Composite. ⇒ **Die Opcode-Semantik der Chase-Prädikate ist damit erledigt**; der einzige verbleibende Kern-Gap ist die **Bindung des Dispatcher-lokalen Kontext-Records** (`byte_1A50/1A4C` + `byte_4B11`-Section-State) — trace-gated (`GAME.000:1F62..2019`).

**Statische Dekodierung des Kerns ABGESCHLOSSEN (2026-07-01):** `sub_4C44` liest
`ss:[bx-28h/29h]` (Dispatcher-Stack-Frame-Locals) + `byte_1A51/1A52` — bestätigt
**keine** reine Set-Op, sondern Dispatcher-lokaler Cursor. Damit ist alles am Prädikat-
Kern statisch geklärt, was statisch klärbar ist; der Rest (welche Werte diese Locals
zur Laufzeit tragen) **erfordert zwingend den Live-Trace** von `GAME.000:1F62..2019`
(temp. 8-Byte-Sets bei `[bp-52h]`, `DS:19EF/06A1`, Schreibungen nach `sub_F5BE`).
Die Trace-Umgebung ist derzeit flaky (siehe `traces/chase_state_localization.md`).

**De-Risking (2026-07-01):** Die Dispatcher-lokalen Selektoren wurden aus den
**vorhandenen** Broad-Dumps extrahiert (kein neuer Trace): `byte_1A50=1`,
`byte_1A4C=1`, `byte_1A51=2`, `byte_1A52=1` sind über alle drei Chase-Zustände
**stabil** → die Chase-`$a`/`$e`-Kontext-Record-Auswahl ist **fix** (Index via
DS:0x438[1]), nicht pro-Zug variabel. Damit verschiebt sich der Kern von
„trace-gated" zu **„konkrete, gegen den Walkthrough testbare Portierung"**:
`a/e`-Opcodes in `AsgPredicateEvaluator` mit festem Kontext-Record portieren →
Record 3637 rendern → gegen 50m/100m-Walkthrough-Text verifizieren. Nur noch offen
(zur endgültigen Absicherung, nicht zwingend): bestätigen, dass die Prompt-Zeit-Werte
den Mid-Render-Werten entsprechen — ein einzelner BP-Dump statt einer ganzen
Trace-Sitzung. **Nächster konkreter Schritt zur Kern-Vollendung, jetzt ohne
Trace-Abhängigkeit für die Verifikation.**

**Portfortschritt (2026-07-02):** Der gemeinsame `AsgGame`-Pfad verbindet
jetzt den Top-Level-MESSAGE-Open-Reset und den aktiven Control-Hook mit
`AsgVm`. `$a` folgt `loc_D463`: Der rohe Zwei-Symbol-Operand wird als
12-Bit-Runtime-Knotenindex gelesen; dessen `value_b` wird gegen das Set
`+0x0C` des durch `byte_1A50` gewählten Phase-8-Kontextrecords geprüft. `&a`
nutzt nun dieselbe native `DS:0438`-Tabelle statt der falschen Phase-6-Tabelle.
`ConditionalSpan` bewahrt dafür die originalen 6-Bit-Operanden. Offen bleibt
`$e/sub_4C44`, dessen Ergebnis zusätzlich von `-28/-29`, `1A51/1A52` sowie
dem Section-Nachlauf `4B11/1B45` abhängt.

Der statisch eindeutige `$e`-Präfix ist portiert: Das durch `byte_1A4C`
gewählte Phase-7-Descriptorrecord setzt über `+8/+9` den Cursor `1A52`; bei
`1A51 == local[-29]` wird `4ADF = local[-28]`. Section-State 7 liefert
unmittelbar wahr. Andere Section-States bleiben tri-state, bis der folgende
`1B45`-/`word_4B7F`-Pfad vollständig im VM-Zustand repräsentiert ist.

**Tieferes Gate (2026-07-01):** Die Set-Ops der Kontext-Opcodes (`sub_4C44`/
`sub_4CA8`/`sub_4B93`) sind KEINE reinen Set-Primitive — sie lesen den
**Dispatcher-lokalen Cursor-Kontext** (`byte_1A50/1A51/1A52/1A56/1A57` +
`byte_4B11`-Section-State-Gate). Damit hängt der Prädikat-Evaluator-Kern an der
Rekonstruktion dieses Dispatcher-lokalen Zustands — laut `asg-vm.md` das härteste
ungelöste Stück, dessen „Next trace boundary" einen Live-Trace von
`GAME.000:1F62..2019` verlangt (temporäre 8-Byte-Sets bei `[bp-52h]`,
`DS:19EF/06A1`, Zustandsschreib­ungen nach `sub_F5BE`). ⇒ Der Haupthebel ist
**trace-gated**, kein rein statischer Port. Live-Trace-Umgebung ist derzeit
flaky (siehe `traces/chase_state_localization.md`, Memory `live-trace-gotchas`).

Zusätzlich eigenständig (trace-frei): Migration 2 (TP3-`0xedd0`-Reader),
Migration-1-Rest (Save-Format), `byte_4B11`-Composite-Selektor, restliche
TABLES-Felder, Parser/Dialog; Tier-4 (voller Walkthrough-Diff) hängt am Kern.

## Root-Cause für "OPEN/PRESS/READ rendern whole/garbled" (2026-07-02, statisch)

Direkte Assembly-Verifikation in `goldfinger_overlay.asm` erklärt den
Composite-Verb-Record-Bug (nicht nur die `$`/`&`-Prädikat-Lücke, sondern eine
zweite, unabhängige Ursache im `(`-Pfad):

- **`sub_EF31` (der `(`-Handler) verarbeitet genau EINEN Opcode und kehrt
  sofort zurück.** Jeder Opcode-Zweig endet mit `call <handler>; jmp
  loc_F53F` -> `loc_F542` -> `loc_F54F` -> `retn` (verifiziert: kein
  Schleifen-Rücksprung, `sub_EF31` ist ein reiner One-Shot-Dispatcher pro
  `(`-Vorkommen).
- Composite-Verb-Records wie 2315 (OPEN) nutzen `(` auf zwei Arten:
  `(@LABEL...` für echte Abschnittsauswahl (wie im bereits verifizierten
  Prolog-Beispiel record 3899/`lqaaai`) und ein nacktes `(` direkt gefolgt von
  genau einem Opcode-Symbol.
- Der aktuelle `AsgGame`-Verb-Antwort-Pfad übergibt aber `execute_action_block`
  **den kompletten Rest des Records** (`symbols[action_start:]`); die
  Python-Schleife dort läuft über viele Symbole hinweg, ein struktureller
  Mismatch zur echten One-Shot-Semantik. Der äußere `_render_symbol_list`
  weiß zudem nicht, wie viele Symbole der Action-Executor "verbraucht" hat --
  er springt nur über das (oft falsch erkannte) Label. Dieselben Bytes werden
  danach nochmal als rohe Prosa gerendert (bestätigt an record 2315, offset 62:
  `(take %t out of \axc...` -- die meisten Folgesymbole decodieren via
  `symbol+0x32` auf gültige Opcodes im bestätigten 0x32..0x5C-Bereich).
- Selbst die schon korrekt portierte Label-Auswahl
  (`render_message_record(section=label)`, gegen den Prolog verifiziert)
  greift hier nicht: der generische Verb-Pfad ruft sie ohne `section=`-Argument
  auf, weil das nötige Label erst aus dem Section-State (`byte_4B11`/
  `turn_resolve_text`) folgt -- demselben noch offenen Kernstück oben.

**Schlussfolgerung:** "Variante 1" (OPEN/PRESS/READ sauber rendern) und der
Prädikat-Kern sind nicht trennbar -- beide Symptome (`$`/`&`-Lücken UND
`(`-Fehlinterpretation) münden in dieselbe fehlende Section-State-Bindung.
Ein sauberer Fix am `(`-Pfad würde erfordern: (a) `execute_action_block` auf
echte One-Shot-Semantik umstellen und die konsumierte Symbolzahl zurückgeben,
UND (b) die Section-Label-Auswahl aus dem echten `byte_4B11`-Zustand ableiten
-- beides trace-gated wie oben, kein rein statischer Fix mehr möglich ohne
Spekulation.

## Bezug zu bestehenden Dokumenten

- Architektur-Begründung: `docs/asg-vm.md` → „Architecture: a VM that executes data".
- Reuse-Matrix + Varianten: `docs/engine-compatibility.md`.
- Volle Record-Struktur (Daten): `docs/savegame-format.md` §6.
- Trace-Ziele für Schritt 3: `docs/runtime-trace-targets.md`.

## Turn-0-Regression neu untersucht, nachdem die TYPE/RUN-Flakiness behoben wurde (2026-07-04)

Mit dem instrumentierten DOSBox-X-Build (`LOGDUMP`/`LOGCLEAR`, siehe
`traces/ab48_section_selector.md`s "achte Runde") war TYPE/RUN erstmals über
viele Läufe hinweg zuverlässig. Das wurde genutzt, um die Turn-0-Regression
("OPEN ARMREST" rendert komplett garbled, Walkthrough-Diff nur 1/107 exakt)
live zu untersuchen, statt weiter an der Predicate-Core-Hypothese
festzuhalten. Ergebnis: **die ursprüngliche Hypothese (byte_4B11 treibt das
OPEN/PRESS/READ-Garbling) ist für diesen konkreten Fall falsifiziert**, das
eigentliche Problem liegt vermutlich eine Ebene tiefer, beim Startraum selbst.

**Falsifiziert:** `BPM 15DD:4B11` über den kompletten "OPEN ARMREST"-Zug
gesetzt (Mechanik durch einen Sanity-Check auf `byte_06AB` bestätigt, der
sofort mit "00 -> 02" feuerte) -- `byte_4B11` bleibt während der gesamten
Aktion `0x00`, keine einzige Schreibung. `sub_48B0`s Discriminator-Logik
(`goldfinger_overlay.asm:9609-9692`, record[+6] ∈ {0x1A,0x1B,0x18,0x2D} ->
byte_4B11 ∈ {0,1,8}) läuft für diese Aktion offenbar gar nicht.

**Neuer, wichtigerer Fund:** `AsgGame.load()` aktiviert Raum **14**
(0-indiziert, nativ `0x0F`) -- von `test_activation_characterization.py` als
korrekt bestätigt, aber nur bezüglich der *statischen* Herleitung aus
Pristine-TABLES (`phase1_record[0x12]`, `sub_D61`s Schreibung nach
`byte_6A9`). Dieser Raum zeigt via `game.handle("look")` einen völlig
anderen Text ("The road forks here... Auric Enterprises...") als der
Walkthrough-Prolog (Aston-Martin-Chase-Intro). Live-Trace der TATSÄCHLICHEN
`DS:06A9` (bestätigt in `data-format.md` als "current room id", einzige
Schreibstelle im gesamten Overlay: `sub_D61` bei `GAME.000:0xDE0`) direkt am
Chase-Prompt: **`0x33` (51)**, stabil über mehrere Kontrollpunkte (2s/6s/9s
nach "N"), nicht `0x0F`. Ein `BPM 15DD:6A9`-Breakpoint über den ganzen
Boot-Vorgang zeigt genau **einen** Hit: `00 -> 33` direkt (kein
Zwischenwert `0x0F` beobachtet -- kann aber an DOSBox-X's grober
BPM-Check-Granularität liegen, siehe unten).

**Noch nicht aufgelöst:** Weder `0x33` als direkter 0-basierter noch
1-basierter Index in `self.rooms` (positionale Zuordnung aus
`AsgActivationTables`/`gameengine/game.py:182`, `enumerate(records)`) noch der
in `data-format.md:1533-1539` schon früher dokumentierte Wert **`0x14`**
("First confirmed turn... room = 0x14") liefern beim Testen die korrekte
Chase-Intro-Beschreibung oder ein scope-passendes `armrest`-Objekt -- alle
drei Kandidatenwerte (`0x0F`, `0x14`, `0x33`) wurden ausprobiert, keiner
passt. `data-format.md` selbst dokumentiert, dass `DS:0x025c`/`DS:0x0438`
Far-Pointer-Tabellen sind, die über die `+0x14`-Feld-Indirektion bzw. eine
`record[0x14] << 2`-Rechnung adressiert werden -- **die Zuordnung
"byte_6A9-Wert -> welcher Raumdatensatz" läuft vermutlich über eine dieser
indirekten Tabellen, nicht über eine simple positionale oder id-Tag-basierte
Suche**, wie ich zunächst angenommen hatte (auch die Hypothese "Raumdatensatz
mit `+0x1A == byte_6A9`" ist falsifiziert -- kein einziger der 65
Raumdatensätze hat `+0x1A == 0x33`).

**Für die nächste Sitzung:** Das braucht Instruction-Level-Stepping
(`STEPINTO`/`STEPOVER`, siehe `memory/resolving-overlay-wrap-calls`) durch
`sub_D61` und die anschließende Raum-Lookup-Logik bei `GAME.000:1f6f`/`205d`/
`2141` (die `DS:0x025C`-Dispatch-Stelle laut `data-format.md:1549`), um
präzise zu klären: (a) schreibt `sub_D61` wirklich erst `0x0F` und wird das
sofort von einer zweiten, noch unidentifizierten Stelle auf `0x33`
überschrieben (eine Art gescriptete Öffnungssequenz -- passend zu den
gelöschten `scenes.py`/`sequences.py`, die genau das früher hartkodiert
hatten), oder ist die Kette komplexer; (b) wie genau übersetzt sich ein
`byte_6A9`-Wert wie `0x33` in einen konkreten Raumdatensatz -- vermutlich
über `DS:0x025C`/`DS:0x0438`, nicht über die aktuell in `gameengine/game.py`
verwendete simple positionale `enumerate()`-Zuordnung. Das ist wahrscheinlich
der eigentliche Blocker für praktisch den gesamten Walkthrough-Diff (nicht
nur Turn 0), da ein falscher Startraum jede folgende Zustandsableitung
verfälscht.

### Follow-up (2026-07-04, selbe Sitzung): Opening-Sequenz-Hypothese live bestätigt

Statt weiter zu raten wurde die exakte Schreibstelle per Signatur-Scan
lokalisiert (neues Tool: `tools/_find_sub_d61.py`, nach dem Vorbild von
`tools/_find_handler.py`): Bytes `A2 A9 06` (`MOV [06A9h], AL`, die einzige
direkte Schreibung dieser Adresse laut `data-format.md`) im gesamten
konventionellen Speicher (`0x0..0xA0000`) gesucht -- **genau ein Treffer**,
physische Adresse `0xDF88`. Ein Codebreakpoint dort (`BP 0:DF88`, feuert über
den bestätigten Linear-Adress-Match-Mechanismus unabhängig vom tatsächlichen
Runtime-CS) direkt am Restore-Prompt gesetzt, dann `n`/`RUN`:

- **Wichtige Nebenerkenntnis:** `DS` ist zum frühen Boot-Zeitpunkt `0x15DC`,
  nicht `0x15DD` (das bislang als "deterministisch über Cold-Restarts"
  dokumentierte `DS=0x15dd`, siehe `memory/dosbox-re-tooling`, war an einem
  *späteren* Zeitpunkt -- nach dem Chase-Prompt -- erfasst). Beide Segmente
  scheinen sich im Lauf der Aktivierung zu einem stabilen Wert anzugleichen;
  für frühe Boot-Traces `15DC` verwenden, nicht `15DD` blind annehmen.
- **Bestätigt per Einzelschritt (`STEPINTO`):** Die Schreibstelle wird
  **mehrfach mit unterschiedlichen Werten** angesprungen, kein einmaliger
  Wert: erster Hit `AL=0x15` (schreibt `byte_6A9` von `0x0F` -> `0x15`),
  zweiter Hit (nach `RUN`) bereits `AL=0x14` (nächste Schreibung im Gange).
  Das **beweist** (nicht nur vermutet) die Opening-Sequenz-Hypothese: es ist
  eine echte Kette mehrerer Aufrufe derselben Schreibstelle mit
  verschiedenen Datensätzen/Werten, die den Raum schrittweise Richtung
  `0x33` treibt -- passend zu den gelöschten `scenes.py`/`sequences.py`.
- **Nicht abgeschlossen:** Die Session wurde nach dem zweiten Hit instabil
  (leere TCP-Antwort, vermutlich dieselbe RUN-Übergangs-Flakiness aus der
  "achten Runde" trotz des LOGDUMP-Fixes für den TYPE/RUN-Fall -- hier war es
  ein eigenständiger BP-Fortsetzungs-Fall). Die volle Kette (`0x0F -> 0x15 ->
  0x14 -> ... -> 0x33`, wie viele Hits, welche Datensätze) ist noch nicht
  vollständig erfasst.

**Konkreter nächster Schritt:** `BP 0:DF88` am Restore-Prompt setzen, `n`
eingeben, dann **wiederholt `RUN` + kurze Pause + `R` + `MEMDUMPBIN 15DC 6A9
1`** (nicht `15DD` -- siehe oben) in einer Schleife mit robuster
Fehlerbehandlung (leere Antworten abfangen und retryen statt abbrechen), bis
entweder der Breakpoint nicht mehr trifft oder `byte_6A9` `0x33` erreicht.
Jeder Hit sollte zusätzlich `[bp-4]` (den Record-Pointer-Parameter)
mitloggen, um zu sehen, ob es eine erkennbare Sequenz-Tabelle ist, die
durchlaufen wird.

### Korrektur (2026-07-04, dritte Runde derselben Untersuchung): `0x33` war ein eigener Messfehler -- der korrekte Wert ist `0x14`

Der oben dokumentierte Wert `0x33` (gelesen über hartcodiertes `DS=0x15DD`)
war **falsch** -- ein Artefakt davon, ein benachbartes, aber physisch
komplett anderes Speicherbyte gelesen zu haben. Direkter Test: `R`s
tatsächliches Live-`DS`-Register am eingeschwungenen Chase-Prompt zeigt
**`DS=0x15DC`**, nicht `0x15DD` (die beiden Segmente sind 0x10 Byte
auseinander -- `DS:0x6A9` bei `15DC` und bei `15DD` sind zwei verschiedene
physische Adressen, keine zwei Sichten auf dieselbe Variable). Mit dem
korrekten, live abgelesenen `DS=0x15DC` liest `byte_6A9` am Chase-Prompt
**`0x14`** -- exakt der Wert, den `data-format.md:1533-1539` schon aus einer
früheren Sitzung dokumentiert ("room = 0x14"). Die "achte/neunte Runde"
dieser Sitzung hat also nur den eigenen Fehler der letzten Runde korrigiert,
keine neue native Sequenzlänge widerlegt: Die per Einzelschritt beobachtete
Kette `0x0F -> 0x15 -> 0x14` (siehe oben) landet konsistent beim
**korrekten** Endwert `0x14`, nicht bei `0x33`.

**Beide bisherigen Lookup-Hypothesen für "wie wird `0x14` zu einem
Raumdatensatz" sind jetzt falsifiziert:**

1. Simple positionale Zuordnung (`self.rooms[0x14-1]` bzw. `[0x14]`,
   `gameengine/game.py`s aktuelle `enumerate()`-Logik): liefert bei Position 19
   oder 20 garbled/falschen Text, kein Chase-Intro.
2. Raumdatensatz mit `+0x1A == 0x14` direkt suchen (Datensatz an
   Dateiposition 31 hat diesen Tag): liefert ebenfalls einen falschen Raum
   ("Ankle-high bluegrass covers this empty field..." -- offenbar ein
   Garten/Feld-Areal, nicht die Chase-Szene).

Damit ist bestätigt: die Übersetzung `byte_6A9`-Wert -> Raumdatensatz läuft
tatsächlich über die in `data-format.md:1549` dokumentierten indirekten
Far-Pointer-Tabellen (`DS:0x025C`, indiziert über `record[0x14] << 2`, sowie
`DS:0x0438`) und NICHT über einen der beiden einfacheren, jetzt
ausgeschlossenen Mechanismen. Der nächste, methodisch andere Schritt ist
daher **nicht** mehr weiteres Live-Memory-Vergleichen (das hat in dieser
Sitzung zweimal zu falschen Schlussfolgerungen geführt -- einmal durchs
falsche Segment, einmal durch zwei falsifizierte Lookup-Hypothesen), sondern
sorgfältiges **statisches Lesen der eigentlichen Lookup-Dispatch-Stelle**
bei `GAME.000:1f6f`/`205d`/`2141` in `goldfinger_overlay.asm`, um die
tatsächliche Indexierungsrechnung zu verstehen, bevor wieder live verifiziert
wird.

### Follow-up (2026-07-04, vierte Runde): die zitierten Adressen existieren nicht -- echte Fundstelle in `goldfinger.asm` (Haupt-EXE, nicht Overlay)

`GAME.000:1f6f`/`205d`/`2141` kommen weder in `goldfinger_overlay.asm` noch
in `goldfinger.asm` als Label oder Referenz vor -- diese Doku-Zeile
(`data-format.md:1549`) ist damit entweder aus einer anderen
Disassembly-Version oder schlicht ungenau. Stattdessen liefert ein Grep nach
`byte_6A9` in `goldfinger.asm` (der Haupt-EXE, **nicht** dem Overlay) einen
bislang übersehenen Fundort: `goldfinger.asm:12760-12920`, eine
Raumwechsel-/Türverknüpfungsroutine mit sowohl Lese- als auch Schreibzugriff
auf `byte_6A9`. Konkret bestätigt (reine Disassembly-Lektüre, kein neuer
Live-Trace):

```
loc_5E33:
    mov al, byte_1AE3
    mov byte_1AE4, al       ; byte_1AE4 = alter byte_1AE3
    mov al, byte_6A9
    mov byte_1AE3, al       ; byte_1AE3 = alter Raum (vor dieser Transition)
    mov al, [bp+4]
    mov byte_6A9, al        ; byte_6A9 = NEUER Raum (Funktionsparameter!)
    ...
loc_5E58:
    mov al, byte_1AEB
    shl ax, 1
    shl ax, 1               ; index = byte_1AEB * 4
    xchg ax, di
    les di, [di+438h]       ; ES:DI = Far-Pointer aus DS:0x0438-Tabelle[index]
    ...
loc_5EB0:
    mov al, byte_1AE4
    shl ax, 1
    shl ax, 1               ; index = byte_1AE4 (alter Raum) * 4
    xchg ax, di
    les di, [di+25Ch]       ; ES:DI = Far-Pointer aus DS:0x025C-Tabelle[index]
    mov al, es:[di+23h]     ; liest Feld +0x23 des SO gefundenen Raumdatensatzes
```

Das ist **diese Funktion selbst ist `MoveToRoom(target)`**: `[bp+4]` ist der
Zielraum-Parameter, `byte_6A9` wird direkt daraus gesetzt (kein weiterer
Lookup nötig, um "den aktuellen Raum" zu setzen -- der IST einfach der
Parameterwert). Die `DS:0x025C`/`DS:0x0438`-Tabellen werden hier mit `<<2`
(4-Byte-Far-Pointer-Einträge) indiziert -- aber **nicht direkt mit
`byte_6A9`**, sondern mit `byte_1AE4` (der alten Raum-ID) bzw. `byte_1AEB`
(eine noch nicht identifizierte dritte Kennung). Das bestätigt zwar die in
`data-format.md` genannten Tabellen als real (mit `<<2`-Indexierung, wie
dokumentiert), zeigt aber, dass die Indexierungskette komplexer ist als "Room
ID direkt rein" -- mindestens zwei weitere Variablen (`byte_1AEB`,
`byte_1AE3`/`byte_1AE4`) sind zwischengeschaltet, deren genaue Rolle noch
unbekannt ist.

**Aktuell bestätigter Stand für `gameengine/game.py`s Positions-Hypothese:**
`byte_19ea` (`len(room_records)`) ist aktuell `65` -- Python geht davon aus,
dass alle 65 Disk-Type-2-Records unverändert zu Tabellen-Slots werden. Ob die
native Tabellen-Konstruktion (die eigentliche Phase-6..9-Aktivierung, noch
nicht selbst nachvollzogen) wirklich diese einfache 1:1-Sequenz baut, oder
Slots ausgelassen/umsortiert werden, ist die noch offene Kernfrage --
plausibler Grund, warum direkte Positions-Indizierung (Raum 19/20) bislang
falschen Text lieferte.

**Ehrlicher Stand nach vier Runden derselben Untersuchung:** Das ist kein
Fünf-Minuten-Fund mehr, sondern ein eigenständiges, mehrschichtiges
RE-Subsystem (mindestens: `byte_1AEB`s Bedeutung klären, die
Tabellen-Bauroutine für `DS:0x025C`/`DS:0x0438` während der Aktivierung
finden und nachvollziehen, dann erst `byte_6A9`/Raum-0x14 tatsächlich
auflösen). Jede der vier Runden hat neue, aber jeweils unvollständige Teile
freigelegt; eine davon (die `0x33`-Schlussfolgerung) war schlicht falsch. Für
die nächste Sitzung: bei `goldfinger.asm:12760` weiterlesen (was ruft diese
Funktion mit welchem `[bp+4]` auf, was ist `byte_1AEB`), statt weiter an
`byte_6A9` selbst zu drehen.

### Follow-up (2026-07-04, fünfte Runde): der reine Lookup-Helfer gefunden -- Indexierung bestätigt einfach, Tabelleninhalt bleibt offen

`goldfinger.asm:12758` beginnt eine **eigenständige, einfachere** Hilfsfunktion
(anonym, kein IDA-Name -- direkt nach `sub_5C7B endp`):

```
push bp
mov bp, sp
push bp
jmp $+3
dec sp
mov al, [bp+4]      ; EINZIGER Parameter: eine Raum-ID
shl ax, 1
shl ax, 1           ; index = raum_id * 4 (4-Byte-Far-Pointer-Eintraege)
xchg ax, di
les di, [di+25Ch]   ; ES:DI = DS:0x025C-Tabelle[index]  (Ergebnis als lokale Variable gepusht)
...
les di, [bp-7]      ; das eben geholte ES:DI wieder laden
mov al, es:[di+23h] ; liest Feld +0x23 des gefundenen Datensatzes
```

Das ist vermutlich der generische `GetRoomRecord(id)`-Helfer: **die Raum-ID
wird direkt (kein Tag-Match, keine Zwischenvariable) `*4` als Index in die
`DS:0x025C`-Tabelle verwendet.** Das bestätigt die einfachste ursprüngliche
Hypothese für die *Indexierungsformel* -- das `+0x23`-Feld, das direkt danach
gelesen wird, ist bereits als Gate in `predicates.py::_evaluate_fgi_entry`
bekannt (`record[0x23] == 0` -> false), dort aber über `entry.class_id`
(Objekt-Klassen-ID) adressiert, nicht über eine Raum-ID -- **dieselbe
`0x25C`-Tabelle wird also für mehrere Schlüsselräume (Objektklassen UND
Räume) gemeinsam genutzt**, was erklärt, warum eine simple 1:1-Reihenfolge
aus den 65 Disk-Type-2-Records für "Raum-IDs" allein nicht zwingend passt.

**Der eigentliche verbleibende Kern ist damit klar benannt, nicht mehr
vage:** nicht die Indexierungs*formel* (die ist jetzt bestätigt: `id * 4` in
eine Far-Pointer-Tabelle), sondern **wie diese Tabelle beim Aktivieren
befüllt wird** -- welcher Disk-Record landet bei welchem Index. Das ist eine
separate, noch nicht lokalisierte Bauroutine (vermutlich Teil der
Phase-6..9-Aktivierungskette, die `AsgActivationTables`/`AsgVm.activate()`
in Python bereits teilweise nachbildet, aber ohne diese konkrete
Tabellen-Konstruktion 1:1 zu spiegeln -- Python nimmt aktuell simple
Datei-Reihenfolge an).

**Für eine künftige Sitzung, konkret:** die Bauroutine finden, die
`DS:0x025C` initial befüllt (vermutlich ein Schleifen-Konstrukt ähnlich
`sub_D12`/`sub_11C6`, die laut `AsgActivationTables`-Kommentaren schon für
Phase-6-Records bekannt sind), dort nachvollziehen, ob/wie Records nach
einem ID-Feld (nicht Dateiposition) einsortiert werden, dann erst
`byte_6A9=0x14` gegen den korrekten Slot verifizieren.

### Follow-up (2026-07-04, sechste Runde): versuchter Fix zurückgerollt -- und ein wichtigerer, verbindender Fund

Versuch, `games/goldfinger/config.py`s `INITIAL_NATIVE_ROOM_ID` von `15` auf
`19` zu ändern (damit `- 1` Python-Index `18` ergibt, der laut Formel
`byte_6A9(=0x14) - 2` bestätigte Slot). Ergebnis: **Walkthrough-Diff bleibt
bei 1/107 exakten Treffern** -- Raum 18 ist zwar real und intern konsistent
(seine Nachbarräume passen zueinander), aber sein LOOK-Text entspricht
Walkthrough-**Zug 4**s Ankunftsort ("northern pass... snow-clad peaks...",
`walkthrough.txt:41`), nicht Zug 0. **Der Versuch wurde zurückgerollt**
(inkl. der beiden angepassten Tests) -- ein bestätigt-falscher Wert im Code
ist schlechter als der alte, ebenfalls falsche, aber wenigstens
dokumentiert-unklare Ausgangswert.

**Beim Versuch, per Richtungswechseln vom bestätigten Raum 18 rückwärts zu
Zug 0 zu wandern, ein wichtigerer, alles verbindender Fund:** Raum-Index `2`
und Raum `18` haben **unterschiedliche** `message_offset`-Werte (`4481` vs
`4482`, nur 1 Symbol auseinander) -- rendern aber **identischen** LOOK-Text
("northern pass..." für beide). Das ist **kein Raum-Indexierungsfehler**,
sondern derselbe, von Anfang dieser Sitzung an bekannte Composite-Record-
Rendering-Gap: `gamecom.py::render_room_segment`s eigener Docstring
dokumentiert das bereits explizit als "known limitation": *"For rooms whose
+2 lands within a composite with multiple sibling segments, this returns the
FIRST sibling's prose rather than the specific room's -- a known limitation
until the dispatcher's section selector is ported."* Zwei benachbarte, aber
inhaltlich verschiedene Raum-Records können also auf denselben Composite-
MESSAGE-Block zeigen und werden beide fälschlich mit demselben "ersten
Geschwister"-Text gerendert.

**Das ist die entscheidende Erkenntnis dieser Sitzung:** Die Raum-Identifizierungs-
Suche (Runden 2-6) hat **Text-Vergleich gegen den Walkthrough** als Oracle
benutzt, um Raum-Hypothesen zu verifizieren -- aber genau dieses Oracle ist
selbst durch dieselbe Predicate-Core-/Composite-Rendering-Lücke unzuverlässig,
die auch OPEN/PRESS/READ (Zug 0) garbled rendern lässt. Ein "Treffer" beim
Textvergleich beweist nicht zwingend den richtigen Raum -- er könnte genauso
gut ein Composite-Block-Nachbar sein, der zufällig dieselbe "erste
Geschwister"-Prosa zeigt. **Die beiden Probleme (Raum-Lookup-Tabelle UND
Composite-Record-Rendering) sind also nicht unabhängig lösbar** -- die
Composite-Rendering-Lücke muss zuerst (oder zumindest gemeinsam) angegangen
werden, sonst bleibt jede Raum-Hypothese unverifizierbar per Textvergleich.

**Ehrlicher Gesamtstand nach sechs Runden:** Kein Fix gelandet, aber der
Suchraum ist jetzt erheblich präziser eingegrenzt: (1) die `DS:0x025C`-
Indexformel ist bestätigt (`id*4`), ihre Bau-Reihenfolge nicht; (2) die
"opening sequence" ist bestätigt real (mehrere `byte_6A9`-Schreibungen vor
dem ersten Prompt), ihr genauer Ablauf nicht; (3) **neu**: Textvergleich
gegen den Walkthrough ist als alleiniges Verifikationsmittel für Raum-
Hypothesen ungeeignet, solange die Composite-Rendering-Lücke offen ist --
künftige Verifikation sollte stattdessen auf eindeutige, nicht-composite
Signale zurückgreifen (z. B. `direction_available`-Bitmuster gegen bekannte
Walkthrough-Richtungsangaben, oder Live-Trace von `word_4B7F` direkt gegen
Screen-Text, wie in `data-format.md:1531-1539`s ursprünglicher Methode).

### Follow-up (2026-07-05, siebte Runde): DS:0x025C-Konvention per Direktmessung geschlossen (kein Text-Oracle)

Die in Runde 4/5 offen gelassene Frage -- **wie ein `byte_6A9`-Wert auf einen
konkreten Raumdatensatz abgebildet wird** -- ist jetzt eindeutig geklärt, und
zwar über genau das in Runde 6 empfohlene non-composite Oracle: die
**DS:0x025C-Far-Pointer-Tabelle selbst** (nicht über gerenderten Text, der
durch die Composite-Lücke unzuverlässig ist).

Messung am Chase-Prompt (live DS = `0x15DC`): die Tabelle bei `DS:0x25C` mit
4-Byte-Far-Pointern ausgelesen, jeden Slot dereferenziert und die ersten
Bytes byte-für-byte gegen die Python-`records_by_type(0x02)` gematcht:

| Slot | Far-Ptr-Ziel (Bytes ab +0) | = Python-Record |
|---|---|---|
| 2  | `36 12 b8 00 01 0d` | `rooms[1].raw[1:7]` |
| 3  | `ee 11 81 00 13 01` | `rooms[2].raw[1:7]` |
| 19 | `cb 11 82 00 01 03` | `rooms[18].raw[1:7]` |
| 20 | `55 1e 29 00 15 15` | `rooms[19].raw[1:7]` |

Jeder Slot `k` zeigt auf den Type-2-Record an **Datei-Index `k-1`** (gelesen
ab Record+1, d.h. das führende Typbyte `0x02` ist im Runtime-Record
weggelassen). Damit ist die Zuordnung **`native room id r -> slot r ->
rooms[r-1]`** -- die **`-1`-Konvention, die `gameengine/game.py` bereits
verwendet**. `byte_6A9=0x14` (20) dereferenziert exakt auf `rooms[19]`.

**Falsifiziert:** die "-2"-/"Raum 18"-Hypothese aus Runde 6 war eine
Composite-Render-Koinzidenz (rooms[18] und rooms[19] rendern beide "northern
pass", weil beide `message_offset`s vor denselben `@@@@@@@q'`-Gap zeigen), kein
echter Indexierungs-Bug. Der `config.py`-Kommentar wurde entsprechend
korrigiert.

**Folgerung:** Der Raum-Lookup ist damit **kein offener Punkt mehr** -- die
Indexierung war die ganze Zeit korrekt. `byte_6A9=0x14 -> rooms[19]` ist der
echte Turn-0-Raum, aber `rooms[19]` ist die **Chase-Szene** (alle sechs
Richtungsslots zeigen auf nativ 21, `direction_available` komplett False --
Chase-Bewegung läuft über den ungeporteten Spezialmechanismus, nicht die
normale Raumnavigation). Deshalb bleibt `INITIAL_NATIVE_ROOM_ID` bewusst beim
pristine-navigierbaren `0x0F`/rooms[14] statt beim korrekten-aber-
ungerenderten `0x14`/rooms[19]: bis Opening-Sequenz **und** Chase (Item 3)
portiert sind, würde ein Start in rooms[19] den Spieler in einer nicht
gerenderten Chase gefangen halten, während rooms[14] wenigstens die
Zu-Fuß-Welt navigierbar lässt. Der Walkthrough-Diff (1/107) ändert sich durch
keinen der beiden Startwerte -- die Chase ist ohnehin durch den
Composite/Predicate-Core blockiert.

## Chase subsystem: step-1 trigger identified (2026-07-05)

Started the chase port (item 3) with the structural analysis:

- **The chase is a dedicated special mode, not the normal room graph.** Native
  room 20 (the DB5 cockpit, LOOK now = "The cockpit of the DB5...") and native
  21 form a trap pair: all six exits of 20 -> 21 and all of 21 -> 20, and
  native 21 renders "you're already IN [the DB5]. you'll have to open the door
  first." So normal navigation cannot leave the DB5; W/N/E during the chase
  must be intercepted as *driving* commands (show scenery + Mercedes distance,
  stay in the DB5).
- **Chase-mode marker CONFIRMED: room field +0x19 == 16 is UNIQUE to native
  room 20** across all 65 rooms (`+0x19` distribution: 60x 0, and one each of
  4/8/16/60/192). There is a SECOND DB5 trap pair (native 60 <-> 61, the parked
  DB5 reachable on foot) with +0x19 == 0 -- i.e. +0x19 == 16 distinguishes the
  *chase-active* DB5 from the parked one.
- `byte_1AEC`/`byte_1AE5` are both 0 at chase start, so the chase is NOT the
  already-ported `sub_9AFF` 1AEC==1 graph-rewire branch.

**Still open (the substantial part):** locate the native movement-intercept
that special-cases a direction command when the current room carries the chase
marker, and port the driving state machine (scenery sequence, Mercedes/distance
tracking via record 3637's "gaining ground"/"50 meters"/"lost ground" status,
per-button destruction). Static grep for the +0x19 read that gates this is too
noisy (+0x19 is read in many object/set contexts, e.g. sub_C111). The clean
path is a live trace from SAVE1 (parked in the DB5): breakpoint the direction
dispatch, type W, and watch which room-field test branches into the chase --
gated on the flaky TYPE/RUN command delivery. PRESS button-colour selection
(BLACK->oil, WHITE->spikes) is already ported; the driving dispatcher is the
remaining core.

### Fahr/Flug-Subsystem: foundational Mechanik + Scope (2026-07-07)

Live getract (SAVE1 = DB5-Cockpit, native 20, mit dem gefixten Tooling):
- **Ein Fahrzug ändert `byte_6A9` NICHT** — nach „w" bleibt `byte_6A9 = 20`, aber
  der Screen rendert eine andere Raum-Beschreibung als Szenerie (z.B. „This
  steep section of the road climbs north to a sharp curve" = native Raum 13).
  ⇒ **Der Chase ist eine In-Place-Zustandsmaschine im Fahrzeug-Raum**: eine
  Progress-Variable wählt, welche *Szenerie-Raum-Beschreibung* gezeigt wird.
  (Schöne Konsequenz des record-index-Fixes: diese Szenerie-Beschreibungen
  rendern jetzt korrekt.)
- **Heikel/todes-anfällig:** ein falscher Fahrzug endet das Spiel („You can't
  drive in that direction, 007." bei ungültig; ein anderer Zug führte direkt zu
  „Service for malfeasance. The End."). Bestätigt die alte
  [[live-trace-gotchas]]-Notiz „Chase-MOVEs crashen das Spiel".

**Scope-Einschätzung (ehrlich):** Das ist das letzte große Subsystem und
umfasst DB5-Chase + Helikopter-Flug + die „pass through"/Kampf/Szenen-Transitions
— alle das In-Place-Zustandsmaschinen-Muster. Ein treuer, data-driven Port
(NICHT hardcoded wie der abgelehnte alte `chase.py`) braucht:
1. Die Progress-Variable(n) + den Fahr-Dispatch (welche Richtung → welcher
   Szenerie-Zustand; gültig/ungültig/tödlich) — heikel zu tracen (jeder
   Fehlzug beendet das Spiel; braucht sorgfältige SAVE-Punkte pro Segment).
2. Distanz-Status (Record 3637, `$`/`&`-gated) + PRESS-Button-Effekte.
3. Flug + Kampf-Szenen (dasselbe Muster).
Das ist ein substanzielles mehrschrittiges Stück. Foundational Mechanik steht;
der nächste konkrete Schritt ist, die Progress-Variable per Memory-Diff über
einen GÜLTIGEN (nicht-tödlichen) Fahrzug zu isolieren — vorsichtig, mit einem
SAVE direkt vor einem bekannten sicheren Zug.

### Chase-Kern-Variable gefunden: byte_1AE5 = Szenerie-Raum (2026-07-07)

Memory-Diff über einen GÜLTIGEN Fahrzug (frischer Chase → OPEN ARMREST → W):
`DS:0x1AE5` ändert sich **0x0F → 0x10** (15 → **16** = native Raum 16 = hairpin),
und der `DS:0x1BE0`-Bereich füllt sich mit dem gerenderten Szenerie-Text
(„The road jackknif…"). Weiterverfolgt: nach den Zügen hält `byte_1AE5` die
Szenerie-Raum-ID der Sequenz **16→7→17→18→19→2→13** (hairpin→south pass→pass
road→north pass→lookout→sharp curve→steep road; via Richtungen N/E UND
Button-Presses, mit Tod bei Fehlzug).

⇒ **Chase-Mechanik (data-driven, kein Hardcoding):** `byte_6A9` bleibt am
Fahrzeug (20), **`byte_1AE5` hält den Szenerie-Raum**, und die Szenerie ist
schlicht `render room[byte_1AE5]`. Alle 7 Szenerie-Räume rendern in Python
bereits KORREKT (via des record-index-`render_message_record`-Fixes verifiziert)
— der Raum-Fix entblockt direkt das Chase-Szenerie-Rendering.

**Solide Grundlage für den Port** (die abgelehnte hardcoded `chase.py`-Route
ist NICHT nötig): der VM muss (a) Chase-aktiv erkennen, (b) `byte_1AE5` tracken
und `room[byte_1AE5]` rendern, (c) auf gültigen Zug `byte_1AE5` per Transitions-
Logik vorschieben, (d) Distanz-Status (Record 3637) + PRESS-Effekte. (a),(b) und
das Rendering (c-Teil) stehen; verbleibend: die Transitions-Logik (welcher Zug
→ welcher nächster `byte_1AE5`; gültig/tödlich) + Distanz/PRESS — per weiterem
sorgfältigem, todes-bewusstem Trace (SAVE vor jedem sicheren Zug).

### Chase-Survival-Maschine: Trace-Funde + Tooling-Blocker (2026-07-07)

Weiter getract (nach der Chase-Fahr-Implementierung), um PRESS-Advance +
Mercedes-Distanz-State zu isolieren:
- **`byte_1AE5`** = Szenerie-Cursor (bestätigt: 16 hairpin → 7 south pass) —
  bereits data-driven implementiert.
- **`DS:0x1B8C`** inkrementiert pro Chase-Zug = ein **Zug-Zähler**.
- Distanz-Status variiert live („50 meters" → „lost ground, 100 meters" nach
  Mercedes-Zerstörung → „caught up ... fires a shot"), aber die Distanz-/
  Mercedes-State-Variable ist **nicht sauber isoliert**.

**Tooling-Blocker (ehrlich):** Der Survival-Trace braucht `press white button`
(18 Zeichen), aber die Long-Command-Injektion **während des Chase** ist genuin
**flaky** — inkonsistent truncated (mal „press white button" voll, mal nur
„press w"), weil der schnell aktualisierende Chase-Screen mit der Key-Injektion
konkurriert. `type_line` (wartet jetzt auf volle Injektion vor ENTER) hilft für
normale Prompts, aber nicht zuverlässig im Chase. Ein sauberer Survival-Trace
braucht entweder robustere Long-Command-Injektion (per-Zeichen-Echo-Feedback
statt Zeit-Heuristik) oder einen Ansatz mit kurzen Befehlen (Distanz-Variable
über DRIVES statt Button-Presses isolieren — die Distanz ändert sich jeden Zug).

**Stand Chase:** Fahren + GET OUT sind data-driven implementiert und validiert
(Suite 413/0). Die Survival-Maschine (PRESS-Advance, Mercedes-Distanz, Tod) ist
der verbleibende Teil, blockiert auf die zuverlässige Long-Command-Injektion.

## Chase/Fight/Dialog-Mechanik nach `gameengine/vehicle_scene.py` verallgemeinert (2026-07-23)

`games/goldfinger/scenes.py`s `GoldfingerScene`/`GoldfingerHooks` (782 Zeilen)
enthielten keine Goldfinger-spezifische *Logik* — nur harte Raum-/Verb-IDs
(47, 65, 61, 13, 37, 0x1E/0x1F/0x20/0x11/0x1C) und Anzeige-Strings ("the DB5")
in ansonsten generischen Mechanismen (Raum-Flag-gated Vehicle-Mode +
Szenerie-Cursor, Verb-ID-Phasen-Sequenz für Fights, `(addressee, topic)`-
Span-Lookup für Dialog). Genau das Zielprinzip oben verlangt: Logik →
`gameengine/`, Werte → `games/<titel>/`.

**Durchgeführt:** Die IDs/Strings in neue `VehicleSceneConfig`-Felder
extrahiert (`chase_start_room_id`, `vehicle_name`, `vehicle_door_object_id`,
`gadget_press_action_id`, `cargo_entry_room_id`, `aircraft_name`, …), Fights
als generische `FightSceneConfig` (Raum-/Prädikat-Gate + Verb→Phase-Mapping,
deckt sowohl den eskalierenden Pussy-Fight als auch den festen Goldfinger-
Fight ab) und Ambient-Dialog als `AmbientSpeechConfig` (Raum-gated zyklischer
Span-Index) modelliert. Die Klasse selbst (`VehicleScene`) ist nach
`gameengine/vehicle_scene.py` gezogen; `gameengine/title_hooks.py`
(`TitleHooks`-Protokoll) ist damit überflüssig und gelöscht —
`AsgConfig.vehicle_scene: VehicleSceneConfig | None` ersetzt es direkt.

**Bewusst NICHT verallgemeinert:** Die Tilly-Masterson-Namens-/Pronomen-
Textchirurgie nach einem erfolgreichen Gadget-Press (`render_press_followup`)
ist echte, nicht generalisierbare Story-Prosa eines Titels — sie bliebe in
`games/goldfinger/scenes.py` als einzige verbleibende Datei (~100 Zeilen,
vorher 782), angebunden über den neuen `VehicleSceneConfig.press_followup_hook`-
Callback. Das ist der korrekte Per-Titel-Escape-Hatch, keine Ausnahme vom
Prinzip.

**Ergebnis:** Suite 440/1 grün, keine Verhaltensänderung (nur 2 Tests mussten
auf die neue generische API umgestellt werden, die vorher direkt
`GoldfingerHooks`-Methoden aufriefen). `games/goldfinger/` Zeilenzahl:
~976 (Burn-down-Metrik). Der Mechanismus ist jetzt für jeden Sibling-Titel
mit passenden Daten sofort nutzbar, ohne eigene ~700-Zeilen-`scenes.py`.

## Prädikat-Kontext-Pfad portiert: Cursor tragen eine Resolver-Art (2026-10-13)

Der als "`context_type`-Maschinerie" offene Punkt ist portiert. Er war nicht
ein fehlender Opcode, sondern eine **durchgehend falsche Annahme**: der Port
behandelte jeden Cursor als Resolver-Art 0.

### Befund aus der Disassembly

`sub_AE9E` liefert `msg_ctrl_amp` einen aufgelösten Cursor **und** dessen
Resolver-Art. Der Render-Frame hält die Art auf `ss:[bx-19h]`, den Wert auf
`ss:[bx-17h]`. Vier Dispatcher lesen das Paar gemeinsam:

| Dispatcher | Art 0 | Art 2 |
|---|---|---|
| `sub_D814` (`$f`/`$g`/`$i`) | `sub_C6BB`: DS:04B4, Guard `+18==0`, `+1B`/`+1C` | `sub_C74C`: DS:025C, Guard `+23!=0`, `+24`/`+25` |
| `sub_D6FD` (Amp-Opcode 74h, "ist das hier") | `index` in `room[+18..+20]` vereinigt lokale Menge | `sub_665B` -> immer 1 |
| `loc_F12B` (Aktions-Opcodes 39h/3Ah/44h/45h) | `sub_DCAD` | `sub_E048` |
| `evaluate_star_candidate` Modus 3 | Direktvergleich | 025C-Exit-Walk, gefiltert über 4ABE |

`sub_D6FD` hat die vollständige Tabelle: Art 1 -> `room[+14..+18]`, Art 2/4 ->
`sub_665B` (jeder Pfad mündet in `loc_672A`, schreibt 1), Art 3 ->
`DS:05B0[index][+0E] == Raum-Cursor`, Art 5/6 -> 0.

Das Paar ist `(value_a, value_b)` eines VOCAB-Eintrags. Unabhängig bestätigt:
`loc_DC44` liest `[di+6B5h]` = Node `+3` und benutzt es als `value_b`, also ist
Node `+2` = `value_a` -- genau das, was `loc_F12B` als Kontext-Art liest.

### Der Deskriptor war nie Metadaten

Der Zwei-Symbol-Operand von `$f`/`$g`/`$i` wurde mit dem Kommentar "dispatcher
metadata, not needed for this cursor-based evaluation" verworfen. Er ist der
12-Bit-Index des VOCAB-Eintrags und damit das, was ein Gate überhaupt erst auf
ein *bestimmtes* Stück Szenerie zeigen lässt. Raum 27 enthält drei davon:

- `$g td|af open ^ab closed` -> Node 213 = "trap door" (`value_a=2, value_b=35`)
- `$g eg|af open ^ab closed` -> Node 144 = "office door" (`value_b=4`)
- `$g e3|a,to the east`      -> Node 183 = "secret door" (`value_b=36`)

Cursor-basiert sind die drei nicht unterscheidbar. Mit Deskriptor kippt Raum 27
von "A small closed trap door" auf "A small open trap door", wenn Raum-Record 35
sein `+24` setzt -- und Raum 30s Satz über die Bürotür folgt Record 4.

### Szenerie liegt auf Raum-Exits

Das erklärt die Walkthrough-Formulierungen, die wie ein Synonym-Problem
aussahen. Szenerie-Records (`[0x23] != 0`) stehen in den sechs Exit-Bytes der
Räume:

| Raum | Szenerie-Exits | `OPEN DOOR` laut Walkthrough |
|---|---|---|
| 27 (Chateau-Dach) | 35 | "you open the trap door." |
| 30 (Büro) | 4 N, 36 O, 35 oben | (Beschreibung nennt genau diese drei) |
| 46 (Hof) | 33 | "You open the barn door." |
| 59 (Tunnel) | 58 | Pussy/Grand-Slam-Zweig |
| 32 | 37 N, 63 W | "The steel door opens." (37) |

Das generische Substantiv "door" (`value_b=37`) wird also per Kandidaten-
Selektion am Raum aufgelöst, nicht lexikalisch. Genau das macht Modus 3s
Art-2-Zweig: Direkttreffer auf `value_b`, sonst Walk über die sechs Exit-Bytes
von `025C[candidate+3]`, gefiltert über `4ABE`.

### Warum die Weiche nicht kosmetisch ist

Die beiden Id-Räume überlappen vollständig: Szenerie-Ids sind Raum-Ids 2..65,
Phase-7-Nodes sind 2..26, und 5/9/15/22 sind beides. Ein falsch geroutetes
Schreiben korrumpiert ein fremdes Objekt, statt zu scheitern. In beiden
Richtungen durch Tests festgenagelt.

### Ergebnis

- Szenerie-Zustand ist lesbar *und* schreibbar über das eigene Record; OPENs
  `+24`-Schreiben erreicht die Beschreibung, die es zurückliest.
- Szenerie ist ein legitimes Verb-Ziel. `break window` rendert
  "You can't break the window!" statt " Is not here." -- die native Antwort
  auf "was soll ein Verb mit einem Ortssubstantiv tun" lautet: Präsenztest
  bedingungslos wahr, Name = das getippte Wort, weil es kein Objekt-Record mit
  Anzeigenamen gibt.
- Zug 25 `OPEN DOOR` antwortet "you can't open the door!" statt
  " is not here." -- Subjekt und Präsenz stimmen, der Zweig nicht.

### Was Zug 25 jetzt noch blockiert (scharf eingegrenzt)

Die Phase-7-Tabelle enthält **keine** Szenerie: ihre 26 lebenden Nodes sind
device/chart/car key/ball/club/hole/frame/desk/letter/badge/cable/keyboard/
armrest/button/oil slick/spikes/plans/plaque/lighter/panel/gun -- keine
einzige Tür. Die Gate-Kette, durch die Record 2315 für Objekte fällt
(`&je` = Verb-`value_b` in Node `+0E`, `&ot` = Node `+18 == 0`), liest
unbedingt DS:04B4 (`loc_DC44` hat keine Kontext-Weiche). Für eine Tür kann sie
unter **keinem** Cursor-Wert wahr werden.

Also rendert der native Dispatcher für ein Art-2-Substantiv nicht linear durch
2315, sondern betritt eine der mit `@` + Label markierten Sektionen. Record
2315 hat genau dafür eine Tür-Sektion in der hinteren Hälfte:

```
[334:@]etas ... [359:@]e3am ... [368:@]ttal "the door doesn't budge."
[396:@]akp5 ... "in the flickering light of your %d@unhill lighter,
                 you find the latch and %e the door."
[537:@]e: ...   "as you try to open the door, %p@ussy motions you aside."
[847:@]aaay ... \axp \apf.
```

Der verbleibende Punkt ist damit **Sektions-Selektion für Verb-Composites**,
nicht ein weiteres Prädikat. `render_room_segment` überspringt Labels bereits
(`_skip_section_label`), *matcht* sie aber nicht gegen Zustand -- die Regel ist
im Port selbst als "not yet traced" vermerkt. `_find_section_span` matcht nach
`(` (0x1E), und `(` ist belegt: es führt genau einen Aktions-Opcode aus. Die
Labels hier stehen nach `@` (0x21). Das ist der nächste Trace.
