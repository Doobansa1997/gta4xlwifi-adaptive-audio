# Audio adattivo per SM-P610 / gta4xlwifi

Configurazione definitiva scelta sul tablet: **SoundBooster Samsung + Dolby
originale, attenuazione delle curve speaker -7 dB**.
Solo **Galaxy Tab S6 Lite Wi-Fi 2020 SM-P610**, **LineageOS 23.2 / Android 16**,
sulla build di riferimento verificata. Non compatibile con SM-P613, SM-P615,
One UI o altre build non esaminate.

La scelta finale resta **sperimentale**, non una garanzia contro distorsione o
danni agli altoparlanti, ne una replica acustica misurata di One UI.

## Verifiche

- Installazione in recovery con esito 0 e rilettura completa della vendor
  corrispondente all'immagine -7 dB.
- Android avviato e hash delle due policy -7 dB corretti.
- SoundBooster operativo nella riproduzione reale: stato 0, stereo float
  a 48 kHz, uscita speaker, frame 6772800 -> 6970560 e zero bypass.
- Dolby originale mantenuto; motore e parametri SoundBooster invariati.
- 79 test privati superati; senza firmware 73 superati e sei test opzionali saltati.

L'attenuazione riguarda anche **sveglie, notifiche e chiamate**. Le curve cuffie
e Bluetooth non cambiano. Il DSP puo compensare il livello: iniziare sempre
a volume basso e fermarsi al primo gracchiare.

## File e installazione

La distribuzione locale conservata e `dist/soundbooster-final/`: preflight,
install, restore, `SHA256SUMS` e `manifest.json`.
Il repository GitHub contiene **solo sorgenti e documentazione**, non librerie
Samsung, parametri proprietari, immagini, log personali o ZIP flashabili.

Seguire [compilazione finale](BUILD.md#final-selected-build--7-db) e
[installazione finale](INSTALL.md#final-selected-version--7-db).
In recovery usare **Apply update -> Apply from ADB**; prima del riavvio
abilitare **Advanced -> Enable ADB** per controllare log e hash vendor.
Il solo trasferimento ADB completato non dimostra l'installazione.

**Restore riporta tutta la vendor alla ROM originale**, rimuovendo SoundBooster
e attenuazione, non torna a -9/-11 dB. Nessun backup viene creato sul tablet.
Conservare il restore corrispondente e una procedura ufficiale di recupero ROM.

## OTA e limiti

Questa versione ricostruisce la vendor per immagini esatte: **non riutilizzare
gli ZIP dopo una OTA**, neppure un'altra nightly 23.2. Non e il precedente
installer XML adattivo. I vecchi sorgenti restano per test e riproducibilita,
non come configurazione consigliata.

Non disabilitare AVB/SELinux, non ribloccare il bootloader e non aggirare i
controlli di compatibilita. Blocchi sconosciuti o scritture interrotte possono
richiedere il recupero ufficiale della ROM; non formattare dati alla cieca.

[README completo](../README.md) · [Test](TESTING.md) · [Design](DESIGN.md) ·
[Licenze e componenti](../THIRD_PARTY.md)
