"""
server.py — Manga Picks Chat
-----------------------------
FastAPI backend with streaming Ollama responses and full session history.

Install:
    pip install fastapi uvicorn requests

Run:
    python server.py
    → open http://localhost:8000
"""

import json
import os
import lib.anilist as anilist_lib
import lib.llm as llm_lib
import yaml
import requests
from mistralai import Mistral, SDKError
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── CONFIG ────────────────────────────────────────────────────────────────────

with open('config/config.yaml', 'r') as stream:
    config = yaml.safe_load(stream)

anilist = config['anilist']

llm_model = config['llm_model'].get('ollama')
llm_mistral = config['llm_model'].get('mistral')
mistral_model = llm_mistral.get('MISTRAL_MODEL')

# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI()
app.mount("/rsc", StaticFiles(directory="rsc"), name="rsc")

# In-memory session history: list of {role, content}
chat_history = []
manga_profile = None

# Model selector
model_of_choice = 'mistral' # 'ollama' / 'mistral'

# ── Routes ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global manga_profile, chat_history
    manga_profile = anilist_lib.load_or_fetch_profile()
    chat_history = []

    if manga_profile is not None:
        print(f"Loaded profile: {len(manga_profile['all_titles'])} titles for @{anilist['ANILIST_USERNAME']}")
    else:
        print(f"No profile found, starting anonymous session")

    if model_of_choice == 'ollama':
        print(f"Server running at http://localhost:{llm_model.get('PORT')}")
    else:
        print('Mistral model in use: ' + mistral_model)


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/profile")
async def get_profile():
    if not manga_profile:
        return JSONResponse({"error": "Profile not loaded"}, status_code=503)
    return {
        "username": manga_profile["username"],
        "total": len(manga_profile["all_titles"]),
        "top_genres": manga_profile["top_genres"][:5],
        "fetched_date": manga_profile["fetched_date"],
    }


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    user_message = body.get("message", "").strip()
    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)


    chat_history.append({"role": "user", "content": user_message})
    system_prompt = llm_lib.build_system_prompt(manga_profile)

    async def stream_response():
        full_reply = ""
        try:
            if model_of_choice == 'ollama':

                with requests.post(
                    llm_model.get('OLLAMA_URL'),
                    json={
                        "model": llm_model.get('OLLAMA_MODEL'),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            *chat_history,
                        ],
                        "stream": True,
                    },
                    stream=True,
                    timeout=120,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                full_reply += token
                                yield f"data: {json.dumps({'token': token})}\n\n"
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

            else:

                payload = json.dumps({'token': '🧠 Thinking & planning... <br>'})
                yield f"data: {payload}\n\n"

                with Mistral(api_key = llm_mistral.get('API_KEY')) as mistral:

                    response = mistral.chat.complete(model = mistral_model,
                                                messages=[
                                                    {
                                                        'role': 'system',
                                                        'content': system_prompt

                                                    },
                                                    *chat_history,
                                                ]
                                                ).choices[0].message.content

                chat_history.append({"role": "assistant", "content": response})

                # Augment the response with links and covers
                for chunk in anilist_lib.augment_response_with_links_and_covers(response):
                    yield chunk

        except SDKError as e:
            # Covers bad/expired API key, rate limits, invalid model name, etc.
            if e.status_code == 401:
                msg = "Mistral API key is invalid or missing. Check config.yaml."
            elif e.status_code == 429:
                msg = "Mistral rate limit hit. Wait a moment and try again."
            else:
                msg = f"Mistral API error ({e.status_code}): couldn't get a response."
            yield f"data: {json.dumps({'error': msg})}\n\n"
            return

        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'error': 'Cannot connect to the model. Is it running?'})}\n\n"
            return

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@app.post("/reset")
async def reset_chat():
    global chat_history
    chat_history = []
    return {"status": "ok"}


@app.post("/refresh")
async def refresh_profile():
    global manga_profile, chat_history
    lists = anilist_lib.fetch_anilist(anilist['ANILIST_USERNAME'])
    manga_profile = anilist_lib.parse_profile(lists)
    with open(anilist['ANILIST_USERNAME']+'-'+anilist['DATA_FILE'], "w", encoding="utf-8") as f:
        json.dump(manga_profile, f, ensure_ascii=False, indent=2)
    chat_history = []
    return {
        "status": "ok",
        "total": len(manga_profile["all_titles"]),
        "fetched_date": manga_profile["fetched_date"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=llm_model['PORT'], reload=False)
