# Hand Tracking Mouse

Piccolo controller multipiattaforma che usa webcam e MediaPipe per muovere il mouse con l'indice e fare click tramite pinch tra pollice e indice.

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

Per ridurre ulteriormente l'ampiezza del movimento della mano, aumenta la sensibilita. Per un movimento piu morbido, riduci il valore di smoothing:

```powershell
python hand_tracker.py --camera 1 --sensitivity 2.6 --smoothing 0.14
```

La sensibilita predefinita e `2.1`; `smoothing` accetta valori da `0.01` a `1.0`, dove valori minori sono piu fluidi ma introducono un po' piu ritardo.

## Comandi e gesti

- Tieni uniti pollice e indice e sposta la mano: muove il cursore come se lo afferrassi e trascinassi.
- Un pinch breve senza spostare la mano: equivale a un click sinistro, utile per selezionare elementi.
- All'avvio il mouse e in pausa. Premi `m` per attivarlo; premi di nuovo `m` per sospenderlo.
- `q` o `Esc`: chiude l'applicazione e rilascia sempre il pulsante del mouse.

La finestra video deve restare attiva per ricevere i comandi da tastiera. Il cursore viene filtrato per ridurre i tremolii e una piccola fascia ai bordi dell'immagine viene usata per raggiungere gli estremi dello schermo senza dover tendere la mano.

## Permessi macOS

Alla prima esecuzione, macOS puo chiedere l'accesso alla Fotocamera. Per muovere e cliccare il cursore, abilita anche il terminale o l'IDE usato in **Impostazioni di Sistema > Privacy e sicurezza > Accessibilita**. Potrebbe comparire anche la richiesta in **Monitoraggio input**.

## Risoluzione problemi

- Schermata nera o errore webcam: chiudi Teams, Zoom e le schede browser che la stanno usando; in Windows verifica anche **Impostazioni > Privacy e sicurezza > Fotocamera**, poi prova `python hand_tracker.py --camera 1`.
- Cursore troppo sensibile: riduci `--sensitivity` (ad esempio `1.6`) oppure aumenta `--smoothing` (ad esempio `0.30`).
- Pinch che scatta troppo facilmente o troppo tardi: regola `pinch_down_threshold` e `pinch_up_threshold` in `Settings`, mantenendo il secondo valore maggiore del primo.
