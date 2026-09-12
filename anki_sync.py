#!/usr/bin/env python3
"""
Anki Sync - a tiny standalone script that keeps a dictionary.json file (as
produced/used by chinese_reader.py) and an Anki deck in sync, by word
existence only - no field-level merging, no touching existing notes:

  - Words in dictionary.json that Anki doesn't have yet -> pushed to Anki
    as brand new notes (Front = word, Back = notes), starting fresh in
    the review queue like any new card.
  - Words already in Anki (e.g. ones you added on your phone) that
    dictionary.json doesn't have yet -> pulled in as new dictionary
    entries (word + note, familiarity level defaults to 3 - set it
    properly next time you're in the reader).
  - Words that exist on BOTH sides are left completely untouched. If you
    edit a word's notes on either side, this script will never overwrite
    that edit or touch the Anki card's review history/scheduling - it
    only ever adds brand new items, never modifies existing ones.

One-time setup:
  1. Install Anki desktop (https://apps.ankiweb.net) if you haven't.
  2. In Anki: Tools > Add-ons > Get Add-ons..., paste code 2055492159,
     install, then restart Anki. That's the AnkiConnect add-on - it runs
     a small local server Anki listens on whenever it's open.
  3. Keep Anki desktop open whenever you run this script.

Usage:
    python3 anki_sync.py chinese.json
    python3 anki_sync.py korean.json --deck Korean
    python3 anki_sync.py chinese.json --no-web-sync

By default the Anki deck name is the dictionary's filename without the
extension (chinese.json -> deck "chinese"), and the script triggers a
normal AnkiWeb sync at the end so your phone picks up the changes next
time its Anki app syncs. No extra Python packages needed - standard
library only.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error

DEFAULT_LEVEL = 3
VALID_LEVELS = (1, 2, 3, 4, 5)


# ------------------------------------------------------------ AnkiConnect --
def anki_request(url, action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise ConnectionError(
            f"Could not reach AnkiConnect at {url} ({e}).\n"
            "Make sure Anki desktop is open and the AnkiConnect add-on is installed\n"
            "(Tools > Add-ons > Get Add-ons..., code 2055492159, then restart Anki)."
        )
    if body.get("error"):
        raise RuntimeError(f"AnkiConnect error on '{action}': {body['error']}")
    return body["result"]


# --------------------------------------------------------- HTML <-> text --
# Anki fields are HTML. Keep this deliberately simple (regex, not a real
# HTML parser) - good enough for plain word/definition notes, which is all
# this app produces or expects.
def html_to_text(html):
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</div>\s*<div[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?div[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def text_to_html(text):
    return text.replace("\n", "<br>")


# ------------------------------------------------------------- dictionary --
def load_dictionary(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object of word -> entry")
    normalized = {}
    for word, value in data.items():
        word = word.strip()
        if not word:
            continue
        if isinstance(value, str):
            normalized[word] = {"notes": value, "level": DEFAULT_LEVEL}
        elif isinstance(value, dict):
            level = value.get("level", DEFAULT_LEVEL)
            if not isinstance(level, int) or level not in VALID_LEVELS:
                level = DEFAULT_LEVEL
            normalized[word] = {"notes": str(value.get("notes", "")), "level": level}
    return normalized


def save_dictionary(dictionary, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=2, sort_keys=True)


def get_anki_words(url, deck):
    note_ids = anki_request(url, "findNotes", query=f'deck:"{deck}"')
    if not note_ids:
        return {}
    infos = anki_request(url, "notesInfo", notes=note_ids)
    words = {}
    for info in infos:
        fields = info.get("fields", {})
        front = fields.get("Front", {}).get("value", "")
        word = html_to_text(front).strip()
        if word and word not in words:  # first match wins if Anki has dupes
            back = fields.get("Back", {}).get("value", "")
            words[word] = html_to_text(back)
    return words


# ------------------------------------------------------------------ main --
def run(dict_path, deck=None, tag=None, url="http://127.0.0.1:8765", do_web_sync=True, out=print):
    deck = deck or os.path.splitext(os.path.basename(dict_path))[0]
    tag = tag or deck

    out(f"Dictionary file : {dict_path}")
    out(f"Anki deck       : {deck}")

    anki_request(url, "version")  # raises ConnectionError with a clear message if unreachable
    anki_request(url, "createDeck", deck=deck)

    dictionary = load_dictionary(dict_path)
    local_words = set(dictionary.keys())
    anki_words_map = get_anki_words(url, deck)
    anki_words = set(anki_words_map.keys())

    to_push = sorted(local_words - anki_words)
    to_pull = sorted(anki_words - local_words)
    shared = local_words & anki_words

    for word in to_push:
        entry = dictionary[word]
        anki_request(
            url, "addNote",
            note={
                "deckName": deck,
                "modelName": "Basic",
                "fields": {"Front": word, "Back": text_to_html(entry["notes"])},
                "tags": [tag],
            },
        )
    out(f"Pushed {len(to_push)} new word(s) to Anki" + (f": {', '.join(to_push)}" if to_push else ""))

    for word in to_pull:
        dictionary[word] = {"notes": anki_words_map[word], "level": DEFAULT_LEVEL}
    if to_pull:
        save_dictionary(dictionary, dict_path)
    out(f"Pulled {len(to_pull)} new word(s) into {os.path.basename(dict_path)}" + (f": {', '.join(to_pull)}" if to_pull else ""))

    out(f"{len(shared)} word(s) already on both sides - left untouched.")

    if do_web_sync:
        try:
            anki_request(url, "sync")
            out("Triggered AnkiWeb sync.")
        except Exception as e:
            out(f"Note: could not trigger AnkiWeb sync ({e}). You can sync manually from Anki.")

    return {"pushed": to_push, "pulled": to_pull, "shared": sorted(shared)}


def main():
    parser = argparse.ArgumentParser(
        description="Sync a dictionary.json file's words with an Anki deck (new words only, in both directions)."
    )
    parser.add_argument("dictionary", help="Path to your dictionary.json file")
    parser.add_argument("--deck", help="Anki deck name (default: dictionary filename without extension)")
    parser.add_argument("--tag", help="Tag added to notes this script creates (default: same as deck name)")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help=argparse.SUPPRESS)  # for testing against a mock server
    parser.add_argument("--no-web-sync", action="store_true", help="Skip triggering the AnkiWeb sync at the end")
    args = parser.parse_args()

    try:
        run(args.dictionary, deck=args.deck, tag=args.tag, url=args.url, do_web_sync=not args.no_web_sync)
    except ConnectionError as e:
        print(f"\n{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nSync failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()