# Audio adattivo per SM-P610 / gta4xlwifi

Progetto sperimentale per **Galaxy Tab S6 Lite Wi-Fi 2020 SM-P610** con
**LineageOS 23.2 / Android 16**. Non compatibile con SM-P613, SM-P615,
altre revisioni o One UI. Non e un progetto ufficiale Samsung/Dolby/LineageOS.

## Obiettivo

Riapplicare lo stesso preset audio dopo una nightly compatibile, senza
riflashare una vendor vecchia. Il preset riduce di **6 dB le curve speaker**
(anche sveglie, notifiche e chiamate) e applica soli tagli all'optimizer
Dolby. Cuffie e altri endpoint conservano le curve originali.

Non e una replica misurata dell'audio Samsung, ne un limite universale
anti-distorsione. I flussi interni rerouting/patch/call_assistant non sono
coperti; elaborazioni successive possono compensare il livello.

## Utilizzo

1. Leggere [compilazione](BUILD.md): gli ZIP si generano localmente dalla
   ROM ufficiale di riferimento, verificata con SHA256.
2. Conservare backup dati, ROM completa e tutti e tre gli ZIP.
3. In recovery eseguire preflight, poi install, accettando soltanto
   il proprio ZIP verificato quando chiede conferma della firma.
4. Richiedere i messaggi `ADAPTIVE PREFLIGHT OK` e `ADAPTIVE APPLY OK`.
   Il solo trasferimento ADB non dimostra l'esito.
5. Ascoltare a volume basso, aumentando gradualmente. Non sommare Wavelet
   o altri EQ al test. Interrompere al primo gracchiare.

[Istruzioni complete: installazione, ripristino, OTA ed errori](INSTALL.md).

## Dopo un aggiornamento

Se una nuova nightly 23.2 compatibile sovrascrive vendor, basta riflashare
**lo stesso installer adattivo**. Il tool legge la nuova vendor e non
ripristina componenti vecchi. Se il formato o gli XML non corrispondono,
si ferma. Riflashare quando e gia applicato non somma altri -6 dB.

Per un OTA incrementale puo essere ancora necessario ripristinare prima
vendor originale: l'installer adattivo non risolve i requisiti del delta.

Il backup dei tre blocchi modificati e in
`/cache/lineage-audio-adaptive/`, vincolato all'identita della vendor.
**Non cancellare cache prima del ripristino.** Se il preset era gia presente
dal vecchio ZIP, non viene inventato un backup: conservare il vecchio restore
per quella build. Dopo una nuova vendor integra verra creato il backup adattivo.

## Stato reale delle prove

Un tablet: il preset precedente e stato scritto e ascoltato con esito
positivo. Il nuovo tool e stato provato su immagini file host e ARM64,
con ripristino esatto. I nuovi ZIP sono stati eseguiti nella recovery reale
quando il preset era gia presente, senza doppia attenuazione e con avvio
riuscito. **Non ancora provati scrittura/ripristino adattivi su partizione
originale o un aggiornamento reale a una nightly successiva.**

Vedere [matrice delle prove](TESTING.md). Non si modificano root, boot,
vbmeta, EFS o metadati super. Le verifiche non vanno rimosse per forzare
l'installazione.

## Pubblicazione e licenze

Codice del progetto MIT; componenti terzi con proprie licenze.
Non pubblichiamo firmware, log personali, immagini vendor o tuning
proprietario Dolby. Per questo la release e di **soli sorgenti**, con una
procedura per generare localmente gli ZIP. I file generati non diventano
automaticamente MIT. Vedere [attribuzioni](../THIRD_PARTY.md).
