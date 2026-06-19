import time

import requests
import datetime
import yaml
import json
import os
from bs4 import BeautifulSoup
import markdown
import re

with open('config/config.yaml', 'r') as stream:
    config = yaml.safe_load(stream)

anilist = config['anilist']
llm_model = config['llm_model']

# ── QUERIES ────────────────────────────────────────────────────────────────────

ANILIST_QUERY = """
query($username: String) {
  MediaListCollection(userName: $username, type: MANGA) {
    lists {
      status
      entries {
        score
        media {
          title { 
            romaji
			english
			native }
          genres
          tags { name rank }
        }
      }
    }
  }
  User (name: $username){
    avatar {
      large
    }
  }
}
"""

MEDIA_QUERY = """
query ($search: String!) {
  Page {
    media(search: $search, type: MANGA) {
      id
      title {
        romaji
        english
        native
      }
      genres
      coverImage {
        large
      }
      rankings {
        allTime
      }
      siteUrl
    }
  }
}
"""

def fetch_anilist(username: str) -> dict:
    resp = requests.post(
        "https://graphql.anilist.co",
        json={"query": ANILIST_QUERY, "variables": {"username": username}},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(str(data["errors"]))

    avatar_url = data["data"]["User"]["avatar"]["large"]
    avatar_name = avatar_url.rsplit('/', 1)[1]

    if not(os.path.exists("./rsc/"+avatar_name)):
        avatar_content = requests.get(avatar_url, allow_redirects=True)
        open("./rsc/" + avatar_name, 'wb').write(avatar_content.content)
        open("./rsc/user_avatar.jpg", 'wb').write(avatar_content.content)

    return data["data"]["MediaListCollection"]["lists"]

def fetch_media_info(title: str) -> dict :
    print(title)

    siteUrl = ''
    coverImage = ''

    try:
        resp = requests.post(
            "https://graphql.anilist.co",
            json={"query": MEDIA_QUERY, "variables": {"search": title}},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Sort the media list by ID (ascending) and pick the first one
        media_list = data["data"]["Page"]["media"]
        sorted_media = sorted(media_list, key=lambda x: x["id"])
        print(sorted_media)
        if len(sorted_media) == 0:
            original_media = sorted_media
            site_url = original_media.get('siteUrl')
            cover_image = original_media.get('coverImage', {}).get("large")
        else:
            original_media = sorted_media[0]
            site_url = original_media["siteUrl"]
            cover_image = original_media["coverImage"]["large"]

    except requests.exceptions.RequestException as e:
        # Handles connection errors, timeouts, etc.
        print(f"Request failed: {e}")
        return None

    except json.JSONDecodeError as e:

        # Handles invalid JSON responses
        print(f"Invalid JSON response: {e}")
        if hasattr(resp, 'text'):
            print(f"Raw response: {resp.text}")
        return None


    except (KeyError, IndexError, TypeError) as e:

        # Handles missing keys, empty lists, or wrong types
        print(f"Data structure error: {e}")
        print(f"Response data: {data}")
        return None


    except Exception as e:

        # Catch-all for unexpected errors
        print(f"Unexpected error: {e}")
        return None

    return {

        "siteUrl": site_url,
        'coverImage': cover_image,

    }

def parse_profile(lists: list) -> dict:
    titles, loved, genres, tags = [], [], {}, {}
    for lst in lists:
        if lst["status"] not in {"COMPLETED", "CURRENT", "PAUSED"}:
            continue
        for entry in lst["entries"]:
            m = entry["media"]
            title = m["title"]["english"] or m["title"]["romaji"] or m["title"]["native"]
            titles.append(title)
            if entry.get("score", 0) >= 8:
                loved.append(title)
            for g in m.get("genres") or []:
                genres[g] = genres.get(g, 0) + 1
            for t in m.get("tags") or []:
                if t["rank"] >= 60:
                    tags[t["name"]] = tags.get(t["name"], 0) + 1

    return {
        "fetched_date": datetime.date.today().isoformat(),
        "username": anilist['ANILIST_USERNAME'],
        "all_titles": titles,
        "loved": loved[:20],
        "top_genres": sorted(genres, key=genres.get, reverse=True)[:8],
        "top_tags":   sorted(tags,   key=tags.get,   reverse=True)[:10],
    }

def extract_manga_titles(text: str) -> list[str]:
    titles = text.split('$$')[1].split('$$')[0]
    return titles.split(',')

def load_or_fetch_profile() -> dict:

    profile = None
    if anilist['ANILIST_USERNAME'] is not None:
        today = datetime.date.today().isoformat()

        manga_list_fn = anilist['ANILIST_USERNAME']+'-'+anilist['DATA_FILE']

        if os.path.exists(manga_list_fn):
            with open(manga_list_fn, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fetched_date") == today:
                return cached

        lists   = fetch_anilist(anilist['ANILIST_USERNAME'])
        profile = parse_profile(lists)
        with open(manga_list_fn, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)

    return profile

def augment_response_with_links_and_covers(response: str):


    # print("Original message:", response)  # Debug
    # print()

    # Enhancing messages with recommendations
    if response.find('$$') >= 0:

        # Send intermediate message to keep the conversation going
        payload = json.dumps({'token': '🔍 Searching for manga details... <br>'})
        yield f"data: {payload}\n\n"

        response = response.replace('<<General>>','')
        debug_titles = '$$'+ response.split('$$')[1].split('$$')[0] +'$$'
        titles = extract_manga_titles(response)
        # print("Extracted titles:", titles)  # Debug
        # print()

        payload = json.dumps({'token': f'📚 Found {len(titles)} titles in the response. <br>'})
        yield f"data: {payload}\n\n"
        payload = json.dumps({'token': '🖼️ Fetching covers and links from AniList... <br>'})
        yield f"data: {payload}\n\n"

        response_cleanup = response.replace(debug_titles, '')
        response_cleanup = markdown.markdown(response_cleanup,
                                            extensions=["nl2br"])

        # print("Cleaned up message - pre photo injection:", response_cleanup)  # Debug
        # print()

        for index, title in enumerate(titles):
            anilist_data = fetch_media_info(title)
            if anilist_data:
                site_url = anilist_data["siteUrl"]
                cover_url = anilist_data["coverImage"]

                # Adding cover image and links
                other_occurrences = f"<strong>{title}</strong>"
                first_occurrence = (
                                        '<div style="display:flex; align-items:flex-start; gap:15px; margin-bottom:20px;">'
                                        f'<img src="{cover_url}" alt="{title}" style="width:120px; border-radius:5px;" />'
                                        '<div style="flex:1;">'
                                        f'<strong><a href="{site_url}">{title}</a></strong>'
                                    )

                # In case the model decides to add the index next to each title
                if response_cleanup.find(str(index+1) +'. ' + title) >= 0:
                    response_cleanup = response_cleanup.replace('<strong>'+str(index+1) +'. ' + title+'</strong>', first_occurrence)
                else:
                    response_cleanup = response_cleanup.replace('<strong>' + title + '</strong>',
                                                                first_occurrence)

                response_cleanup = response_cleanup.replace(
                        '<strong>' + title + '</strong>', other_occurrences)
                pos = response_cleanup.find('<hr />',  + index + 1)
                response_cleanup = response_cleanup[:pos] + response_cleanup[pos:].replace('<hr />', '</div></div><hr />', 1)

                time.sleep(1)                                       # Safety measure to avoid API failure due to too many calls in short time

        # print("Cleaned up message - pre BeautifulSoup:", response_cleanup)  # Debug
        # print()

        response_cleanup = str(BeautifulSoup(response_cleanup, "html.parser"))

        # Yield the final answer
        payload = json.dumps({'token': '✅ Finalizing response... <br>'})
        yield f"data: {payload}\n\n"
        # print(response_cleanup)
        yield f"data: {json.dumps({'token': response_cleanup, 'isHTML': True})}\n\n"

    elif response.find('<<General>>') >= 0:

        # No processing required if it's a conversational message

        response_cleanup = response.replace('<<General>>','')

        # Yield the final answer
        # print(response_cleanup)                                                       #Debug
        yield f"data: {json.dumps({'token': response_cleanup, 'isHTML': False})}\n\n"

    else:

        yield f"data: {json.dumps({'token': response, 'isHTML': False})}\n\n"
