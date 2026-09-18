# Hand Tracking Mouse

Piccolo controller multipiattaforma che usa webcam e MediaPipe per controllare il mouse con una mano.

## Requisiti

- Python 3.10 o successivo
- Webcam disponibile
- Windows 10/11 oppure macOS

## Installazione

Da PowerShell o Terminale, nella cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Su macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Avvio

```powershell
python hand_tracker.py
```

Se la webcam corretta non e la prima, prova ad esempio:

```powershell
python hand_tracker.py --camera 1
```

Per vedere quali videocamere e backend espone OpenCV, senza avviare il controllo del mouse:

```powershell
python hand_tracker.py --list-cameras
```

Per aumentare l'ampiezza del movimento con il pinch o durante il trascinamento con il pugno, aumenta la sensibilita. Per un movimento piu morbido, riduci il valore di smoothing:

```powershell
python hand_tracker.py --camera 1 --sensitivity 2.6 --smoothing 0.14
```

La sensibilita predefinita e `1.0`; `smoothing` accetta valori da `0.01` a `1.0`, dove valori minori sono piu fluidi ma introducono un po' piu ritardo.

Il movimento usa il pinch tra pollice e indice. Se dovesse iniziare troppo facilmente, riduci la soglia:

```powershell
python hand_tracker.py --camera 0 --move-threshold 0.18
```

Il click usa il pinch tra pollice e medio. Se dovesse attivarsi troppo facilmente, riduci la soglia:

```powershell
python hand_tracker.py --camera 0 --click-threshold 0.18
```

## Comandi e gesti

- Tieni uniti pollice e indice: afferra e muove il cursore. Il movimento e relativo, quindi il cursore non salta quando inizi il gesto.
- Unisci pollice e medio: click sinistro. Apri nuovamente le dita prima di eseguire un altro click. Il click scatta solo quando il medio e chiaramente piu vicino al pollice dell'indice; il pinch indice-pollice ha sempre la priorita.
- Pugno chiuso: tiene premuto il pulsante sinistro e consente il trascinamento. Apri la mano per rilasciarlo.
- Indice e medio estesi e ravvicinati: attivano lo scorrimento. Tieni fermo il palmo e muovi solo le due dita unite in alto o in basso; il movimento dell'intera mano viene ignorato.
- Il cursore puo attraversare tutti i monitor collegati a Windows. Il fail-safe resta attivo solo negli angoli esterni del desktop virtuale, quindi non interrompe il passaggio tra due monitor.
- All'avvio il mouse e in pausa. Premi `m` per attivarlo; premi di nuovo `m` per sospenderlo.
- `q` o `Esc`: chiude l'applicazione e rilascia sempre il pulsante del mouse.

La finestra video deve restare attiva per ricevere i comandi da tastiera. Il cursore viene filtrato per ridurre i tremolii e una piccola fascia ai bordi dell'immagine viene usata per raggiungere gli estremi dello schermo senza dover tendere la mano.

## Permessi macOS

Alla prima esecuzione, macOS puo chiedere l'accesso alla Fotocamera. Per muovere e cliccare il cursore, abilita anche il terminale o l'IDE usato in **Impostazioni di Sistema > Privacy e sicurezza > Accessibilita**. Potrebbe comparire anche la richiesta in **Monitoraggio input**.

## Risoluzione problemi

- Schermata nera o errore webcam: chiudi Teams, Zoom e le schede browser che la stanno usando; in Windows verifica anche **Impostazioni > Privacy e sicurezza > Fotocamera**, poi prova `python hand_tracker.py --camera 1`.
- Movimento o trascinamento troppo sensibili: riduci `--sensitivity` (ad esempio `0.8`) oppure aumenta `--smoothing` (ad esempio `0.30`).
- Scorrimento: usa solo indice e medio estesi e vicini, con anulare e mignolo piegati; lascia il palmo fermo e muovi le due punte insieme in verticale. Il movimento viene accumulato, quindi non serve uno spostamento ampio in un solo frame.
- Pinch indice-pollice poco reattivo o click involontari: tieni il medio lontano dal pollice durante il movimento; se serve, aumenta `middle_pinch_margin` in `Settings` per rendere il click piu difficile da attivare per errore.
- Pinch di movimento che scatta troppo facilmente o troppo tardi: regola `move_down_threshold` e `move_up_threshold` in `Settings`, mantenendo il secondo valore maggiore del primo.
- Errore `PyAutoGUI fail-safe`: il controllo passa in pausa anziche chiudere l'app. Sposta il mouse fisico fuori dall'angolo esterno del desktop e premi `m` per riprenderlo.
- Click che scatta troppo facilmente o troppo tardi: regola `click_down_threshold` e `click_up_threshold` in `Settings`, mantenendo il secondo valore maggiore del primo.
