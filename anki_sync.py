#!/usr/bin/env python3
"""
Anki Sync - a tiny standalone script that keeps a dictionary.json file (as
produced/used by chinese_reader.py) and an Anki deck in sync:

  - Words in dictionary.json that Anki doesn't have yet -> pushed to Anki
    as brand new notes (Front = word, Back = notes), starting fresh in
    the review queue like any new card.
  - Words already in Anki (e.g. ones you added on your phone) that
    dictionary.json doesn't have yet -> pulled in as new dictionary
    entries (word + note, familiarity level defaults to 3 - set it
    properly next time you're in the reader).
  - Words that exist on BOTH sides have their NOTES kept in sync too, but
    safely: a small local state file (dictionary.json.sync_state.json)
    remembers a short checksum of what was last agreed between the two
    sides for each word (not the full text - just enough to detect
    change, keeping that file tiny). Only three things can happen to a
    shared word's notes:
      - Neither side changed since last sync -> nothing happens.
      - Only one side changed -> that change is copied to the other side
        automatically (safe, unambiguous).
      - BOTH sides changed to something different -> flagged as a
        conflict and never auto-resolved. When run in a terminal you can
        pick "local" or "anki" for each conflicted word on the spot;
        otherwise (e.g. run from a script/cron) conflicts are just
        listed, left alone, and asked about again next run.
    Familiarity level never syncs either direction - that stays a purely
    local, manual thing in the reader app. Updating a note's fields never
    touches its Anki review history/scheduling either way - that's a
    separate thing Anki tracks per-card, untouched by field edits.
  - Duplicate checking against Anki is scoped to the target deck, not your
    whole collection - so the same word can exist as independent cards in
    different decks (e.g. studying Mandarin and Cantonese, where a lot of
    vocabulary shares the same written word but different pronunciation/
    notes). Each deck gets its own copy with its own review schedule; a
    word already sitting in a *different* deck won't block it from being
    added here too.
  - If one word still fails to push for some reason, it's skipped with a
    clear message and the rest of the batch keeps going - one bad word
    can't stop everything else from syncing.

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
import hashlib
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


# ------------------------------------------------------------ sync state --
# Tiny local file remembering, per word, a short checksum of the notes text
# both sides last agreed on. Storing just a checksum (not the full text)
# keeps this file small - we only need to know WHETHER something changed
# since last sync, never what the old text actually was.
def sync_state_path(dict_path):
    return dict_path + ".sync_state.json"


def load_sync_state(dict_path):
    path = sync_state_path(dict_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sync_state(dict_path, state):
    with open(sync_state_path(dict_path), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def notes_checksum(text):
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def get_words_in_scope(url, query):
    """Returns {word: {"note_id": ..., "back": plain_text}} for notes
    matching an AnkiConnect search query, using the note's first field as
    the word (works for "Basic" and any similar note type where the first
    field holds the word/term)."""
    note_ids = anki_request(url, "findNotes", query=query)
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
            words[word] = {"note_id": info.get("noteId"), "back": html_to_text(back)}
    return words


def resolve_conflict(dict_path, url, word, choice, local_text, anki_text, note_id):
    """Applies a manual decision for one conflicted word: choice "local"
    pushes the local notes to the Anki card, "anki" pulls the Anki notes
    into the dictionary; anything else is a no-op (still a conflict next
    sync). Always reads dictionary.json and the sync-state file fresh from
    disk first, since a sync pass may have already written other changes -
    this is meant to be called standalone, after (or independent of) run().
    Returns True if a change was applied, False for a skip."""
    if choice not in ("local", "anki"):
        return False
    sync_state = load_sync_state(dict_path)
    if choice == "local":
        anki_request(url, "updateNoteFields", note={"id": note_id, "fields": {"Back": text_to_html(local_text)}})
        sync_state[word] = notes_checksum(local_text)
    else:
        dictionary = load_dictionary(dict_path)
        if word in dictionary:
            dictionary[word]["notes"] = anki_text
        else:
            dictionary[word] = {"notes": anki_text, "level": DEFAULT_LEVEL}
        save_dictionary(dictionary, dict_path)
        sync_state[word] = notes_checksum(anki_text)
    save_sync_state(dict_path, sync_state)
    return True


# ------------------------------------------------------------------ main --
def run(dict_path, deck=None, tag=None, url="http://127.0.0.1:8765", do_web_sync=True,
        out=print, interactive=None, input_func=input):
    deck = deck or os.path.splitext(os.path.basename(dict_path))[0]
    tag = tag or deck
    if interactive is None:
        interactive = sys.stdin.isatty()

    out(f"Dictionary file : {dict_path}")
    out(f"Anki deck       : {deck}")

    anki_request(url, "version")  # raises ConnectionError with a clear message if unreachable
    anki_request(url, "createDeck", deck=deck)

    dictionary = load_dictionary(dict_path)
    local_words = set(dictionary.keys())

    # Only checks THIS deck's notes - both for deciding what to push/pull,
    # and (via duplicateScope below) for what Anki itself treats as a
    # duplicate. This is deliberately deck-scoped rather than collection-
    # wide: it lets the same word exist as independent cards in different
    # decks, which matters if you study more than one language that shares
    # some vocabulary (e.g. Mandarin and Cantonese sharing characters) -
    # each deck gets its own copy with its own notes and its own review
    # schedule, rather than the second language being silently blocked
    # because the word "already exists" in the other one.
    deck_words_map = get_words_in_scope(url, f'deck:"{deck}" note:Basic')
    deck_words = set(deck_words_map.keys())

    to_push = sorted(local_words - deck_words)
    to_pull = sorted(deck_words - local_words)
    shared = sorted(local_words & deck_words)

    pushed, push_failures = [], []
    for word in to_push:
        entry = dictionary[word]
        try:
            anki_request(
                url, "addNote",
                note={
                    "deckName": deck,
                    "modelName": "Basic",
                    "fields": {"Front": word, "Back": text_to_html(entry["notes"])},
                    "tags": [tag],
                    "options": {"duplicateScope": "deck"},
                },
            )
            pushed.append(word)
        except Exception as e:
            # One bad word (weird characters, a genuine same-deck dupe we
            # somehow missed, whatever) must not take the rest down with it.
            push_failures.append((word, str(e)))
    out(f"Pushed {len(pushed)} new word(s) to Anki" + (f": {', '.join(pushed)}" if pushed else ""))
    if push_failures:
        out(f"{len(push_failures)} word(s) could not be pushed and were skipped:")
        for word, err in push_failures:
            out(f"  - {word}: {err}")

    for word in to_pull:
        dictionary[word] = {"notes": deck_words_map[word]["back"], "level": DEFAULT_LEVEL}
    if to_pull:
        save_dictionary(dictionary, dict_path)
    out(f"Pulled {len(to_pull)} new word(s) into {os.path.basename(dict_path)}" + (f": {', '.join(to_pull)}" if to_pull else ""))

    # --- sync notes text for words that exist on both sides ---
    sync_state = load_sync_state(dict_path)
    notes_pushed, notes_pulled, conflicts, conflicts_resolved = [], [], [], []
    state_dirty = False

    for word in shared:
        local_notes = dictionary[word]["notes"]
        anki_note_id = deck_words_map[word]["note_id"]
        anki_notes = deck_words_map[word]["back"]
        local_hash = notes_checksum(local_notes)
        anki_hash = notes_checksum(anki_notes)

        if local_hash == anki_hash:
            if sync_state.get(word) != local_hash:
                sync_state[word] = local_hash
                state_dirty = True
            continue

        base_hash = sync_state.get(word)
        if base_hash is None:
            # Never tracked before and they differ right now - no way to
            # know who changed, so treat it like any other conflict.
            conflicts.append(word)
            continue

        local_changed = local_hash != base_hash
        anki_changed = anki_hash != base_hash

        if local_changed and not anki_changed:
            try:
                anki_request(url, "updateNoteFields", note={"id": anki_note_id, "fields": {"Back": text_to_html(local_notes)}})
                sync_state[word] = local_hash
                state_dirty = True
                notes_pushed.append(word)
            except Exception as e:
                out(f"  - could not push updated notes for '{word}': {e}")
        elif anki_changed and not local_changed:
            dictionary[word]["notes"] = anki_notes
            sync_state[word] = anki_hash
            state_dirty = True
            notes_pulled.append(word)
        else:
            conflicts.append(word)

    if notes_pushed:
        out(f"Pushed updated notes to Anki for {len(notes_pushed)} word(s): {', '.join(notes_pushed)}")
    if notes_pulled:
        save_dictionary(dictionary, dict_path)
        out(f"Pulled updated notes from Anki for {len(notes_pulled)} word(s): {', '.join(notes_pulled)}")
    if state_dirty:
        # Flush BEFORE any conflict resolution below, since resolve_conflict()
        # does its own fresh load/save cycle per word - it needs to start
        # from this up-to-date file, and nothing after this point should
        # overwrite the sync-state file wholesale again (that would clobber
        # whatever resolve_conflict() just wrote).
        save_sync_state(dict_path, sync_state)

    conflict_details = {}
    if conflicts:
        out(f"{len(conflicts)} word(s) changed on both sides with different content - needs a decision:")
        for word in conflicts:
            local_text = dictionary[word]["notes"]
            anki_text = deck_words_map[word]["back"]
            note_id = deck_words_map[word]["note_id"]
            conflict_details[word] = {"local": local_text, "anki": anki_text, "note_id": note_id}
            out(f"  '{word}':")
            out(f"    [1] local : {local_text}")
            out(f"    [2] anki  : {anki_text}")
            if not interactive:
                out("    (not resolved - run this in a terminal to choose, or edit one side to match the other)")
                continue
            choice_raw = input_func(f"    Keep which for '{word}'? [1=local / 2=anki / s=skip]: ").strip().lower()
            choice = {"1": "local", "2": "anki"}.get(choice_raw)
            if choice:
                try:
                    resolve_conflict(dict_path, url, word, choice, local_text, anki_text, note_id)
                    conflicts_resolved.append((word, choice))
                    if choice == "anki":
                        dictionary[word]["notes"] = anki_text  # keep our in-memory copy consistent too
                except Exception as e:
                    out(f"    could not apply '{word}' ({e}) - will ask again next sync")
            else:
                out(f"    skipped '{word}' - will ask again next sync")

    out(f"{len(shared) - len(conflicts)} shared word(s) confirmed in sync.")

    if do_web_sync:
        try:
            anki_request(url, "sync")
            out("Triggered AnkiWeb sync.")
        except Exception as e:
            out(f"Note: could not trigger AnkiWeb sync ({e}). You can sync manually from Anki.")

    return {
        "pushed": pushed,
        "push_failures": push_failures,
        "pulled": to_pull,
        "shared": shared,
        "notes_pushed": notes_pushed,
        "notes_pulled": notes_pulled,
        "conflicts": conflicts,
        "conflict_details": conflict_details,
        "conflicts_resolved": conflicts_resolved,
    }


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
        result = run(args.dictionary, deck=args.deck, tag=args.tag, url=args.url, do_web_sync=not args.no_web_sync)
    except ConnectionError as e:
        print(f"\n{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nSync failed: {e}")
        sys.exit(1)

    if result["push_failures"] or result["conflicts"]:
        sys.exit(2)  # partial success: worth a non-zero exit, but not the same as a hard failure


if __name__ == "__main__":
    main()