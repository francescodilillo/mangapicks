# Manga Picks Chat

A manga recommendation chatbot. It builds a "reader profile" from your
AniList history (if you have one!) and uses that as context for an LLM (local via Ollama, or hosted via
Mistral) so the recommendations are grounded in what you've actually read. The model's
replies are post-processed to attach AniList covers and links automatically, if you're using Mistral.

## How it works

- **`server.py`** — FastAPI app. Serves the chat UI, streams LLM responses over SSE,
  and exposes the profile/reset/refresh endpoints.
- **`lib/anilist.py`** — talks to the AniList GraphQL API: fetches your manga list,
  builds the reader profile, fetches cover/link info for recommended titles, and
  injects that into the HTML response.
- **`lib/llm.py`** — builds the system prompt sent to the model (different prompt
  depending on whether a profile was loaded or you're in anonymous mode).
- **`index.html`** — single-page chat UI (vanilla JS, no build step).
- **`config/config.example.yaml`** — template for your local config.

## Requirements

- Python 3.10+
- One of:
  - [Ollama](https://ollama.com) running locally with a model pulled (e.g. `ollama pull llama3.1:8b`), **or**
  - A [Mistral API key](https://console.mistral.ai/)
- An AniList account/username if you want personalized recommendations (optional —
  the app also runs in anonymous mode)

## Setup

1. **Install dependencies** (there's no `requirements.txt` yet, so install directly):

   Run `pip install -r requirements.txt`

2. **Create your config file** from the example:

   ```bash
   cp config/config.example.yaml config/config.yaml
   ```

   Then edit `config/config.yaml`:

   ```yaml
   anilist:
     ANILIST_USERNAME: "your_anilist_username"   # remove/leave blank for anonymous mode
     DATA_FILE: "manga_list.json"

   llm_model:
       ollama:
         OLLAMA_MODEL: "llama3.1:8b"              # any model you've pulled in Ollama
         OLLAMA_URL: "http://localhost:11434/api/chat"
         PORT: 8001
       mistral:
         MISTRAL_MODEL: "mistral-large-2512"
         API_KEY: "YOUR_KEY"
   ```

   Note: the server always binds to the port under `llm_model.ollama.PORT`, even when
   using Mistral as the model — that field doubles as the app's web server port
   regardless of which model you pick.

3. **Pick your model** in `server.py`:

   ```python
   model_of_choice = 'mistral'   # or 'ollama'
   ```

4. **Run it:**

   ```bash
   python server.py
   ```

   Then open `http://localhost:8001` (or whatever port you set) in your browser.

## Using the app

- On startup, if `ANILIST_USERNAME` is set, your manga list is fetched once and cached
  in `<username>-manga_list.json` for the day (re-fetched the next calendar day, or via
  the `/refresh` endpoint).
- Chat normally — the assistant only gives recommendations when you actually ask for
  them ("recommend me something dark and psychological", "what should I read next",
  etc.). Otherwise it just chats.
- Recommended titles automatically get their AniList cover image and link injected
  into the reply.
- The sidebar reset button clears the conversation (`/reset`) without touching your
  cached profile.

## Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the chat UI |
| `/profile` | GET | Returns the loaded reader profile summary |
| `/chat` | POST | `{"message": "..."}` → streams the reply via SSE |
| `/reset` | POST | Clears in-memory chat history |
| `/refresh` | POST | Force re-fetches your AniList list |

