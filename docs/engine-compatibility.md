# Engine-Kompatibilität — Goldfinger Engine über 8 Spiele

Goldfinger nutzt eine Adventure-Engine die von Mindscape / verwandten
Entwicklern in mehreren 1985-86 DOS-Adventure-Titeln eingesetzt wurde.
Diese Doku hält fest welche Spiele die Engine teilen und in welchen
Varianten — als Grundlage für späteren `engine/` + `games/<title>/`
Refactor.

> **Warum die Wiederverwendung so hoch ist:** `GAME.COM`+`GAME.000` sind eine
> **VM, die pro Titel Daten ausführt**, keine Engine mit fest verdrahteter
> Spiellogik. Alle Titel teilen dasselbe Executable und tauschen nur
> `MESSAGE`/`VOCAB`/`TABLES`. Die unten stehende Reuse-Tabelle ist die
> praktische Folge dieser Architektur. Details + Code-Belege:
> [`docs/asg-vm.md`](asg-vm.md) → „Architecture: a VM that executes data".

> **ÜBERHOLT (2026-07): fast der gesamte Rest dieses Dokuments (Reuse-Tabelle,
> Layout-Bäume, "Was noch zu migrieren ist") beschreibt den handgeschriebenen
> Goldfinger-Stack (`interpreter.py`/`handlers.py`/`chase.py`/`scenes.py`/
> `saveload.py`), der inzwischen komplett gelöscht ist.** Goldfinger läuft
> jetzt über den generischen VM-Pfad `gameengine/game.py::AsgGame` +
> `gameengine/AsgVm`; `games/goldfinger/` ist nur noch Config + Daten
> (`config.py` + `records.py` + `play.py`). Aktueller Stand + offene Punkte:
> `docs/vm-migration-audit.md`. Die Datei-/Modul-Namen unten existieren
> **nicht mehr** — als historische Momentaufnahme belassen, nicht als
> aktuelle Referenz lesen.

## Detection-Tools

- `tools/_detect_engine.py <gamedir>` — prüft ein einzelnes Verzeichnis,
  Exit 0 bei Match
- `tools/_scan_engine_siblings.py <parent>` — scannt alle Subdirectories
  einer Eltern-Directory und gibt eine Verdict-Tabelle aus

(RE-/Dev-Tools unter `tools/` sind `_`-präfixiert = nicht Teil der Runtime.)

Die Detektion stützt sich auf die folgenden strukturellen Invarianten:

1. **`GAME.000`** Overlay-File präsent (immer dieser Name, alle Titel)
2. Mindestens eine `*.COM` Datei (Launcher; Name variiert je Game —
   `GAME.COM`, `CASTLE.COM`, etc.)
3. `GAME.000` startet mit TP3-typischem Code (`0xE8` near-call ODER
   `0x55` push-bp)
4. **`MESSAGE`** Dateigröße = Vielfaches von 512 Bytes (paged Format
   mit 2-Byte Page-Header + 510 Daten-Bytes)
5. **`VOCAB`** Dateigröße = Vielfaches von 26 Bytes (Pascal-Length-String
   + 4 Metadata-Bytes je Record)
6. **`TABLES`** Dateigröße = Vielfaches von **40 ODER 47 Bytes** —
   das ist der Hauptunterschied zwischen den zwei Engine-Varianten
7. MESSAGE-Byte-Distribution ist weit (gepackter 6-bit Stream zeigt
   ~250 distinct Bytes; reiner ASCII wäre <100)

## Bestätigte Engine-Spiele (scan vom 2026-06-21)

### Variante A — 40-Byte TABLES Records (Goldfinger-kompatibel)

| Game-Directory | MESSAGE Pages | VOCAB Records | TABLES Records |
|---|---|---|---|
| `dick-francis-high-stakes` | 94 | 255 | 87 |
| `indiana-jones-in-revenge-of-the-ancients` | 94 | 236 | 107 |
| `james-bond-007-goldfinger` (Referenz) | 94 | 236 | 108 |

Diese Variante kann mit dem AKTUELLEN `goldfinger/`-Code direkt geladen
werden — `TABLE_RECORD_SIZE = 40` in `gameengine/tables.py` stimmt.

### Variante B — 47-Byte TABLES Records (neuere Engine-Revision)

| Game-Directory | MESSAGE Pages | VOCAB Records | TABLES Records | Besonderheit |
|---|---|---|---|---|
| `forbidden-castle` | 92 | 254 | 108 | Launcher = `CASTLE.COM` |
| `james-bond-007-a-view-to-a-kill` | 84 | 314 | 148 | |
| `rambo-first-blood-part-ii` | 92 | 275 | 97 | |
| `stephen-kings-the-mist` | 90 | 275 | 114 | |
| `voodoo-island` | 89 | 275 | 127 | |

Diese Variante braucht nur **eine Konstante anders** (`TABLE_RECORD_SIZE = 47`).
Field-Offsets innerhalb der Records sind nicht verifiziert — manche Felder
sind eventuell verschoben oder es gibt zusätzliche Bytes.

## Binär-Provenienz: `GAME.COM` + `GAME.000` (Prüfsummen & Größen)

**Enthalten diese Dateien Code oder Daten?** Beide sind **Code** — zusammen bilden
sie die zweiteilige Engine (VM):

- **`GAME.COM`** = residenter Teil: Parser, gepackter MESSAGE-6-Bit-Codec,
  Bildschirm/Keyboard, Save/Load, Heap.
- **`GAME.000`** = Overlay-Teil: VOCAB-/TABLES-Loader, Szenen-Aktivierungskette
  (`0xD61`), Per-Turn-Dispatcher und die **Action-VM** (`loc_EF31` usw.). Es ist
  reiner Code, keine Daten: es disassembliert zu ~28k Zeilen 8086
  (`docs/disassembly/GAME.000.asm`) und ist über mehrere Titel **byte-identisch**
  (siehe Tabelle) — also spiel-agnostischer VM-Code, nicht pro-Titel-Daten.

Die **einzigen reinen Daten** sind `MESSAGE`/`VOCAB`/`TABLES`. (Ein dritter
Code-Teil, der Message-Renderer, lebt im Segment `CS=0815h` und ist in keiner der
beiden Dateien statisch enthalten — per Live-Memdump rekonstruiert.)

**Prüfsummen (MD5) und Größen** (erfasst 2026-07-01). „Resident" = die Engine-`*.COM`
(bei Forbidden Castle `CASTLE.COM`); Titel-/Intro-COMs (`TITLE.COM`, `*TTL.COM`,
`GAME1.COM`) und DOS-Dateien (`COMMAND.COM`, `IBMBIO/IBMDOS.COM`) sind **nicht** die
Engine und hier ausgelassen.

| Titel | Variante | Resident `*.COM` | Größe | Resident MD5 | `GAME.000` Größe | `GAME.000` MD5 |
|---|---|---|---:|---|---:|---|
| Goldfinger | A (40B) | `GAME.COM` | 25.983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69.888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| Indiana Jones | A (40B) | `GAME.COM` | 25.983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69.888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| High Stakes | A (40B) | `GAME.COM` | 25.983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69.888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| A View to a Kill | B (47B) | `GAME.COM` | 25.835 | `18cc3721c39cad2857a025bfbb21827e` | 67.840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| Rambo | B (47B) | `GAME.COM` | 25.835 | `18cc3721c39cad2857a025bfbb21827e` | 67.840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| Forbidden Castle | B (47B) | `CASTLE.COM` | 25.835 | `71eb05d5af1793dc6375be7ad3d9c90c` | 67.840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| The Mist | B (47B) | `GAME.COM` | 24.552 | `410c75624269ce996652e64da44a17aa` | 67.584 | `e495f39a61cb747ef4da8d74d88fdf6f` |
| Voodoo Island | B (47B) | `GAME.COM` | 25.835 | `e9c980de5f5f9d7d2e685cda46ee1e87` | 67.840 | `0c6c760199d90129defeef78d8fde48d` |

Beobachtungen:

- **`GAME.000` byte-identisch über die drei 40-B-Titel** (Goldfinger/Indiana/High
  Stakes) — der stärkste Beweis, dass die VM-Logik geteilt und das Spielverhalten
  vollständig in den Daten liegt. Ebenso identisch über View-to-a-Kill / Rambo /
  Forbidden Castle (47-B-Kern).
- Der **residente Teil** clustert ähnlich, aber nicht deckungsgleich: die 40-B-Titel
  teilen `GAME.COM` `cd9cb0…`; View/Rambo teilen `18cc37…`; Forbidden Castle nutzt
  denselben Overlay-Kern, aber einen leicht abweichenden Residenten (`CASTLE.COM`
  `71eb05…`). The Mist und Voodoo sind eigenständige Revisionen derselben
  Engine-Familie.
- Die Goldfinger-`GAME.COM`-MD5 `cd9cb0…` stimmt mit dem IDA-Header von
  `goldfinger.asm` (`CD9CB01548F705CFE02F9A926D4D4DBD`) überein — bestätigt, dass
  `goldfinger.asm` = diese `GAME.COM` ist.

**Keine Versions-/Buildnummern.** Weder `GAME.COM` noch `GAME.000` enthält eine
Spiel-Versions-/Buildnummer. Die einzigen versionsähnlichen Strings in `GAME.COM`
sind der Turbo-Pascal-3-Compiler-Stempel `(C) 1985 BORLAND Inc` und ein
`version$`-Fragment einer DOS-Prüfmeldung; `GAME.000` enthält gar keine
Versions-/Copyright-/Datums-Strings. Titel werden also allein über Prüfsumme +
Größe + Datenmerkmale identifiziert, nicht über eine eingebettete Version.

## Was vom aktuellen Code direkt reusable ist

| Modul | Reuse-Grad | Begründung |
|---|---|---|
| `gameengine/packing.py` | 100% | 6-bit `xtrnip`-Format ist Engine-Invariante |
| `gameengine/message.py` | 100% | `depage()` und Record-Reader hängen nur an 512B-Page-Format |
| `gameengine/vocab.py` | 95% | 26B-Format identisch; nur Record-Count variiert |
| `gameengine/gamecom.py` Renderer | 90% | Control-Alphabet, %-/@-/|-/\- Handler generisch; Layout-Konstanten 79/24 sind engine-weit |
| `gameengine/tables.py` | 80% | Framing generisch; TABLE_RECORD_SIZE auto-detectet 40B/47B; Field-Offsets pro Variante prüfen |
| `gameengine/parser.py` | 95% | Longest-Match-VOCAB-Parser algorithmus-generisch |
| `gameengine/verbs.py` Dispatcher-Framework | 100% | `VerbDispatcher`/`CommandContext` reine Routing-Infrastruktur |
| `gameengine/world.py` + `games/goldfinger/interpreter.py` | 80% | `Room`/`GameObject`/Engine-Basis reusable; `GameState`/`SceneGlobals` game-spezifisch |
| Save/Load (`build_save_data`/`load_save`) | 90% | Diff-vs-pristine Mechanik generisch, nur Watermark + Bitmap-Offsets game-spezifisch |

## Was IMMER game-spezifisch bleibt (per Game neu zu erstellen)

- **VOCAB-IDs** — jedes Spiel hat eigenes Vokabular (verschiedene Verben,
  Objekte, NPCs)
- **`MESSAGE_RECORD_*` Konstanten** in `verbs.py` — alle Template-Indices
  sind game-spezifisch
- **Konkrete Verb-Handler** (`handle_open`, `handle_duck` etc.) — die
  Semantik pro Verb hängt von Game-State und Game-Logik ab
- **Room-/Object-Daten** — kompletter Inhalt der TABLES-Records
- **Scene-/Chase-spezifische Logik** (Aston Martin Chase in Goldfinger,
  möglicherweise andere scripted Sequences in anderen Games)
- **DOSBox-X Trace-Konstanten** (`DS=0x15DD` etc. — pro Build verschieden)

## Refactor-Status (Stand 2026-06-23)

> **ÜBERHOLT (2026-07):** Der Umbau ist weiter, als dieser Abschnitt beschreibt.
> Der handgeschriebene Goldfinger-Stack (`interpreter.py`/`handlers.py`/
> `chase.py`/`scenes.py`) wurde **gelöscht**; Goldfinger läuft jetzt über den
> generischen VM-Pfad `gameengine/game.py::AsgGame` und ist nur noch
> Config + Daten (`config.py` + `records.py` + `play.py`). Die Zeilen unten
> (Reuse-Tabelle, „Was noch zu migrieren ist", Layout mit `handlers.py`) sind
> historisch. Aktueller Stand: `docs/vm-migration-audit.md`.

**Phasen 1-4 abgeschlossen** — die Engine-Trennung steht. Aktuelles Layout:

```
gameengine/                  <- 100% reusable, alle codec + framework
    packing.py               <- 6-bit unpack
    message.py               <- paging + record reader (+ DEFAULT_SYMBOL_TABLE)
    vocab.py                 <- 26B parser
    tables.py                <- 40B/47B framing (record_size auto-detect)
    gamecom.py               <- control dispatch + layout
    parser.py                <- longest-match
    runtime_records.py       <- DS:0x4BE0 32-byte runtime record
    pascal_set.py            <- TP3 RTL set primitives
    scenes.py                <- SceneDefinition base
    verbs.py                 <- VerbDispatcher framework + CommandContext + QuitSignal
    world.py                 <- Room, GameObject, EngineGameState base
    input_encoding.py        <- ASCII->symbol
    data.py                  <- GameData.load (launcher_name param)

games/
    goldfinger/              <- erste Game-Binding
        __init__.py
        config.py            <- LAUNCHER_NAME, TABLES_RECORD_SIZE, DISPLAY_NAME
        play.py              <- REPL entry point
        records.py           <- VERB_*-Konstanten, MESSAGE_RECORD_*, VERB_RESPONSE_RECORDS
        handlers.py          <- handle_quit/look/take/.../build_default_dispatcher

goldfinger/
    cli.py                   <- CLI entry point; importiert gameengine/ + games/goldfinger direkt
    __init__.py
```

Layering-Invariante automatisiert durch `tests/test_gameengine_layering.py`:
gameengine/ darf NICHT aus goldfinger/ oder games/ importieren.

## Was noch zu migrieren ist

- ~~Goldfinger-spezifische `verbs.py`-Handler + MESSAGE_RECORD_*-Konstanten~~
  ✓ erledigt (`games/goldfinger/handlers.py` + `records.py`)
- ~~`interpreter.py` Game-State Struktur~~
  ✓ partial: `Room`/`GameObject`/`EngineGameState` jetzt in `gameengine/world.py`;
  `SceneGlobals`/`GoldfingerGame` bleiben Goldfinger-spezifisch
- `GoldfingerGame.activate_initial_scene` + activation-chain phases:
  Phase-Implementierungen sind heute alle in `games/goldfinger/interpreter.py`;
  könnten als `apply_phase_1` ... `apply_phase_9` callables in
  `gameengine/activation.py` rausgezogen werden (alle 8 sibling games
  benutzen die gleiche Phase-Sequenz)
- Goldfinger save/load specifics -> `games/goldfinger/saveload.py`

## Originaler Plan-Layout (Referenz)

```
gameengine/                      <- 100% reusable
    packing.py                   <- 6-bit unpack
    message.py                   <- paging + record reader
    vocab.py                     <- 26B parser
    tables.py                    <- 40B/47B framing (record_size as param)
    renderer.py                  <- ex-gamecom.py, control dispatch + layout
    parser.py                    <- longest-match
    verbs.py                     <- dispatcher framework + base CommandContext
    saveload.py                  <- diff-vs-pristine
    detect.py                    <- engine detection (ex-tools/detect_engine.py)

games/
    goldfinger/                  <- game-specific binding
        __init__.py
        records.py               <- MESSAGE_RECORD_DUCK_RESPONSE, etc.
        handlers.py              <- handle_open, handle_duck, etc.
        chase.py                 <- chase state machine (when ported)
        play.py                  <- REPL entry point
        config.py                <- TABLES_RECORD_SIZE=40, etc.

    indiana_jones/               <- new game, ~200 lines per game
        __init__.py
        records.py               <- IJ-specific record indices
        handlers.py              <- IJ-specific verb handlers
        config.py                <- TABLES_RECORD_SIZE=40

    forbidden_castle/
        ...
        config.py                <- TABLES_RECORD_SIZE=47, COM=CASTLE.COM
```

Pro neuem Spiel ist dann nur das `games/<title>/` Package neu zu
schreiben (geschätzt 200-500 Zeilen Code pro Game). Engine-Updates
profitieren ALLE Spiele gleichzeitig.

Bis dahin bleibt das Code in `goldfinger/` — der Detector-Output und
diese Doku reichen als Beweis dass die Engine-Annahme korrekt ist.
