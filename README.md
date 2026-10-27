# Tracker profili Instagram (senza token)

Segue i profili elencati nel secret `PROFILES` usando solo i dati pubblici di Instagram.
Ogni 6 ore GitHub Actions scarica i dati, li salva **cifrati** nel repo e ripubblica la dashboard su GitHub Pages.

**Protetto da password:** il repo è pubblico, ma i dati stanno solo in `docs/data.enc`, cifrato con AES-256
e la password della dashboard. La lista dei profili è nei *Secrets* (invisibili) e i log di Actions non mostrano gli username.
Chi apre il sito senza password vede solo la schermata di accesso.

**Cosa raccoglie:** follower, seguiti, numero di post, ultimi ~12 post con like, commenti e views dei reel. La crescita (24 ore, 7 giorni, grafico) è calcolata dallo storico salvato a ogni giro.
**Cosa non può raccogliere:** reach, impression, storie, Insights (servono i token).

## Messa in funzione (una volta sola)

1. **Crea un nuovo repository** su GitHub. Con un account gratuito deve essere *pubblico* perché GitHub Pages funzioni (i dati sono comunque quelli già visibili su Instagram).
2. **Carica tutti i file** di questa cartella, compresa la cartella nascosta `.github`.
   Se trascinando i file la cartella `.github` non viene caricata: *Add file → Create new file*, scrivi come nome `.github/workflows/track.yml` e incolla il contenuto del file.
3. **Settings → Pages → Source:** scegli *GitHub Actions*.
4. **Settings → Actions → General → Workflow permissions:** scegli *Read and write permissions* e salva.
5. **Settings → Secrets and variables → Actions → New repository secret**, creane due:
   - `DASHBOARD_PASSWORD`: la password per entrare nella dashboard.
   - `PROFILES`: gli username da seguire, separati da virgola (es. `profilo1, profilo2`).
   - `APIFY_TOKEN` (consigliato): il *Personal API token* di [Apify](https://apify.com) (*Settings → API & Integrations*).
     Instagram blocca quasi sempre le richieste dai server di GitHub (HTTP 429); con Apify i dati arrivano lo stesso.
     Senza questo secret lo script prova a interrogare Instagram direttamente.
6. **Actions → Aggiorna tracker → Run workflow** per il primo giro.
7. Dopo 1-2 minuti la dashboard è su `https://<tuo-utente>.github.io/<nome-repo>/`
   (il link esatto compare anche in *Settings → Pages*).

## Uso quotidiano

- **Aggiungere o togliere un profilo:** nella dashboard premi **Gestisci profili**, aggiungi lo username (o incolla il link del profilo) e premi *Salva*.
  Il tracker parte da solo e i dati arrivano in pochi minuti. La lista viene salvata cifrata in `docs/profiles.enc` e da quel momento
  ha la precedenza sul secret `PROFILES`. Il profilo tolto sparisce dalla dashboard, il suo storico resta nel file cifrato.
  La prima volta serve un **token GitHub** (fine-grained, solo questo repository, permessi *Contents* e *Actions* in *Read and write*):
  le istruzioni sono nella finestra stessa e il token resta salvato solo sul tuo dispositivo.
- **Aggiorna ora:** con il token salvato lancia subito una raccolta; senza token apre la pagina di GitHub dove premere *Run workflow*.
- **Cambiare password:** non cambiare solo il secret, altrimenti lo storico già cifrato non si legge più. Se la cambi, cancella anche `docs/data.enc` e `docs/profiles.enc` (lo storico riparte da zero e la lista profili torna al secret `PROFILES`).
- **Aggiornare subito:** *Actions → Aggiorna tracker → Run workflow*.
- **Cambiare frequenza:** in `.github/workflows/track.yml` la riga `cron: "17 */6 * * *"` (orario UTC). Sotto le 3 ore aumenta il rischio di blocchi.

## Se qualcosa non va

- **Avviso giallo su un profilo:** Instagram ha rifiutato la richiesta in quel giro (di solito HTTP 401 o 429, blocco temporaneo). La dashboard tiene gli ultimi dati validi e il giro dopo riprova.
- **Workflow rosso:** nessun profilo è stato aggiornato in quel giro. Se succede per più giorni di fila, i server di GitHub sono stati bloccati da Instagram: si può far girare lo stesso script da un altro computer o server, oppure passare a un servizio esterno.
- **Workflow rosso con "Manca il secret" o "Impossibile decifrare":** controlla i secret `DASHBOARD_PASSWORD` e `PROFILES`.
- **"Profilo inesistente (404)" o "privato":** controlla lo username in `PROFILES`. Dei profili privati si vedono solo follower e numero di post.

## File

| File | A cosa serve |
|---|---|
| `scripts/fetch.py` | Scarica i dati (solo libreria standard di Python) |
| `scripts/vault.py` | Cifra e decifra i dati con la password |
| `.github/workflows/track.yml` | Pianificazione ogni 6 ore e pubblicazione |
| `docs/index.html` | La dashboard |
| `docs/data.enc` | Dati, storico e archivio dei post cifrati (creato in automatico) |
| `docs/profiles.enc` | Lista profili salvata dalla dashboard, cifrata |
