#!/usr/bin/env python3
"""
Language Reader - a simple local app for reading foreign-language text
against your own personal vocabulary dictionary. Works for any language
(Chinese, Korean, etc.) - just keep a separate dictionary file per
language and switch between them from the File menu.

Left panel:  shows notes for whatever word you click on in the reader,
             editable and savable.
Right panel: paste text to read; any word that exists in the currently
             open dictionary gets highlighted (longest-match, no NLP /
             segmentation - you build the vocabulary list yourself);
             click a highlighted word to see/edit its notes on the left;
             also lets you add brand new words straight into the
             dictionary.

Use the File menu to open a different dictionary file (e.g. one for
Chinese, one for Korean) or create a new one. Whichever file is open
stays open for the rest of the session - paste text, click words, add
words, all read/write to that same file until you switch again. The app
also remembers the last dictionary you had open and reopens it
automatically next time, so a typical session is just: launch app, paste
text, study.

Dictionary file format (a plain JSON file, human readable / hand
editable) - a flat word -> {notes, level} mapping. `level` is your
familiarity with the word, 1 (barely know it) to 5 (mastered) - it
controls the highlight color in the reader (red -> green):

{
    "你好": {"notes": "hello / hi - common greeting", "level": 5},
    "谢谢": {"notes": "thank you", "level": 3}
}

Run with:
    python3 chinese_reader.py

Requires only the Python standard library (tkinter). On some Linux
distros tkinter isn't installed by default - if you get an import error,
install it with something like: sudo apt install python3-tk
"""

import json
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox
from tkinter import filedialog
from tkinter import ttk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DICT_PATH = os.path.join(SCRIPT_DIR, "dictionary.json")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "reader_config.json")
MAX_RECENT = 8

DEFAULT_DICTIONARY = {
    "你好": {"notes": "hello / hi - common greeting", "level": 3},
    "谢谢": {"notes": "thank you", "level": 3},
    "再见": {"notes": "goodbye", "level": 3},
}

DEFAULT_LEVEL = 3
LEVELS = [1, 2, 3, 4, 5]

# Highlight color per familiarity level, red (barely know it) -> green
# (mastered). Pastel Material-Design-ish colors, all readable with black text.
LEVEL_COLORS = {
    1: "#ef9a9a",
    2: "#ffcc80",
    3: "#fff59d",
    4: "#c5e1a5",
    5: "#a5d6a7",
}


def level_color(level):
    return LEVEL_COLORS.get(level, LEVEL_COLORS[DEFAULT_LEVEL])

# Fonts that reliably render CJK / Hangul characters, checked in order.
# Noto Sans CJK is a unified Pan-CJK family and covers Hangul too, but a
# few Korean-specific fonts are listed as extra fallbacks.
CJK_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
    "Noto Sans CJK KR",
    "Microsoft YaHei",
    "Malgun Gothic",
    "PingFang SC",
    "PingFang TC",
    "Apple SD Gothic Neo",
    "AppleGothic",
    "STHeiti",
    "SimHei",
    "NanumGothic",
    "Noto Sans KR",
    "Arial Unicode MS",
    "WenQuanYi Zen Hei",
]


def pick_cjk_font():
    available = set(tkfont.families())
    for name in CJK_FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


def _normalize_entry(value):
    """Accepts either the old format (a plain notes string) or the new
    format ({"notes": ..., "level": ...}) and returns a clean
    {"notes": str, "level": int in 1..5} dict either way."""
    if isinstance(value, str):
        return {"notes": value, "level": DEFAULT_LEVEL}
    if isinstance(value, dict):
        notes = value.get("notes", "")
        level = value.get("level", DEFAULT_LEVEL)
        if not isinstance(level, int) or level not in LEVELS:
            level = DEFAULT_LEVEL
        return {"notes": str(notes), "level": level}
    return {"notes": "", "level": DEFAULT_LEVEL}


def load_dictionary(path, default_content=None):
    """Loads the dictionary at `path`. If the file doesn't exist yet, it's
    created with `default_content` (or empty if not given). Old-format
    (word -> plain string) entries are transparently upgraded. Returns
    None (after showing an error dialog) if the file exists but can't be
    parsed, or can't be created - callers should treat None as "the
    switch failed, keep whatever was open before"."""
    if not os.path.exists(path):
        content = default_content if default_content is not None else {}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception as e:
            messagebox.showerror("Could not create dictionary", f"Could not create {path}:\n{e}")
            return None
        return {word: _normalize_entry(value) for word, value in content.items()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("dictionary file must contain a JSON object of word -> entry")
        return {word: _normalize_entry(value) for word, value in data.items()}
    except Exception as e:
        messagebox.showerror("Dictionary load error", f"Could not read {path}:\n{e}")
        return None


def save_dictionary(dictionary, path):
    """Returns True on success. Shows an error dialog and returns False on
    failure instead of failing silently (e.g. bad file permissions)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except Exception as e:
        messagebox.showerror("Save failed", f"Could not write {path}:\n{e}")
        return False


# ------------------------------------------------------ session config --
# A tiny local file (next to this script) that just remembers which
# dictionary file you had open last, plus a short recent-files list, so
# reopening the app drops you back into the same language session.

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # remembering the last file is a nicety, not worth crashing over


def remember_dict_path(path):
    config = load_config()
    config["last_dictionary_path"] = path
    recent = [p for p in config.get("recent", []) if p != path]
    recent.insert(0, path)
    config["recent"] = recent[:MAX_RECENT]
    save_config(config)


def resolve_startup_dict_path():
    """Decide which dictionary file to open on launch: the last one used,
    if it's still there, otherwise the bundled default (created with a
    few sample words the very first time the app is ever run)."""
    config = load_config()
    last = config.get("last_dictionary_path")
    if last:
        if os.path.exists(last):
            return last, None
        return DEFAULT_DICT_PATH, last  # remembered path is gone - fall back, and warn
    return DEFAULT_DICT_PATH, None


class ChineseReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.geometry("1200x750")

        startup_path, missing_path = resolve_startup_dict_path()
        if missing_path:
            messagebox.showwarning(
                "Dictionary not found",
                f"Couldn't find the last dictionary file you had open:\n{missing_path}\n\n"
                "Opening the default dictionary instead. Use File > Open Dictionary...\n"
                "to point back at it if it's just been moved or renamed.",
            )
        default_content = DEFAULT_DICTIONARY if startup_path == DEFAULT_DICT_PATH else None
        result = load_dictionary(startup_path, default_content=default_content)
        self.dict_path = startup_path
        self.dictionary = result if result is not None else {}
        print(f"[chinese_reader] dictionary file: {self.dict_path}")
        remember_dict_path(self.dict_path)

        self.current_word = None
        self.cjk_font_name = pick_cjk_font()

        self.reader_font = tkfont.Font(family=self.cjk_font_name, size=18)
        self.notes_font = tkfont.Font(family=self.cjk_font_name, size=14)

        self._build_menu()
        self._build_ui()
        self._update_window_title()
        self.highlight_text()

    # -------------------------------------------------------- menu bar --
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Dictionary...", command=self.open_dictionary_dialog)
        file_menu.add_command(label="New Dictionary...", command=self.new_dictionary_dialog)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.delete(0, "end")
        recent = [p for p in load_config().get("recent", []) if p != self.dict_path]
        if not recent:
            self.recent_menu.add_command(label="(no other recent files)", state=tk.DISABLED)
            return
        for p in recent:
            self.recent_menu.add_command(label=os.path.basename(p), command=lambda p=p: self.switch_dictionary(p))

    def open_dictionary_dialog(self):
        path = filedialog.askopenfilename(
            title="Open dictionary file",
            initialdir=os.path.dirname(self.dict_path) or SCRIPT_DIR,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.switch_dictionary(path)

    def new_dictionary_dialog(self):
        path = filedialog.asksaveasfilename(
            title="Create new dictionary file (e.g. korean.json)",
            initialdir=os.path.dirname(self.dict_path) or SCRIPT_DIR,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        self.switch_dictionary(path, default_content={})

    def switch_dictionary(self, path, default_content=None):
        result = load_dictionary(path, default_content=default_content)
        if result is None:
            return False  # error already shown by load_dictionary; keep current file open
        self.dictionary = result
        self.dict_path = path
        self.current_word = None
        self.word_label.config(text="(click a highlighted word)")
        self.notes_text.delete("1.0", "end")
        self.level_combo.config(state="disabled")
        self.level_var.set(str(DEFAULT_LEVEL))
        self.save_btn.config(state=tk.DISABLED)
        self.delete_btn.config(state=tk.DISABLED)
        self._update_dict_count()
        self._update_path_label()
        self._update_top_label()
        self._update_window_title()
        self.highlight_text()
        remember_dict_path(path)
        self._rebuild_recent_menu()
        print(f"[chinese_reader] switched to dictionary file: {path} ({len(self.dictionary)} words)")
        return True

    def _update_window_title(self):
        self.root.title(f"Language Reader - {os.path.basename(self.dict_path)}")

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED)
        paned.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(paned, padx=10, pady=10)
        right = tk.Frame(paned, padx=10, pady=10)
        paned.add(left, minsize=280, width=340)
        paned.add(right, minsize=500)

        self._build_left_panel(left)
        self._build_right_panel(right)

    def _build_left_panel(self, parent):
        tk.Label(parent, text="Selected word", font=(None, 11, "bold")).pack(anchor="w")
        self.word_label = tk.Label(
            parent, text="(click a highlighted word)",
            font=(self.cjk_font_name, 26), fg="#1a5276", wraplength=300, justify="left",
        )
        self.word_label.pack(anchor="w", pady=(0, 10))

        tk.Label(parent, text="Notes", font=(None, 11, "bold")).pack(anchor="w")
        self.notes_text = tk.Text(parent, wrap="word", font=self.notes_font, height=14, undo=True)
        self.notes_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        level_row = tk.Frame(parent)
        level_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(level_row, text="Familiarity:", font=(None, 11, "bold")).pack(side=tk.LEFT)
        self.level_var = tk.StringVar(value=str(DEFAULT_LEVEL))
        self.level_combo = ttk.Combobox(
            level_row, textvariable=self.level_var, values=[str(n) for n in LEVELS],
            state="disabled", width=4,
        )
        self.level_combo.pack(side=tk.LEFT, padx=(6, 8))
        tk.Label(level_row, text="(1=new, 5=mastered)", fg="#888", font=(None, 9)).pack(side=tk.LEFT)

        btn_row = tk.Frame(parent)
        btn_row.pack(fill=tk.X)
        self.save_btn = tk.Button(btn_row, text="Save", command=self.save_current_notes, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT)
        self.delete_btn = tk.Button(btn_row, text="Delete Word", command=self.delete_current_word, state=tk.DISABLED)
        self.delete_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.left_status = tk.Label(parent, text="", fg="#117a65")
        self.left_status.pack(anchor="w", pady=(6, 0))

        self.dict_count_label = tk.Label(parent, text="", fg="#555")
        self.dict_count_label.pack(anchor="w", pady=(20, 0))
        self._update_dict_count()

        self.path_label = tk.Label(
            parent, text="", fg="#888",
            font=(None, 8), wraplength=320, justify="left",
        )
        self.path_label.pack(anchor="w", pady=(2, 0))
        self._update_path_label()

    def _build_right_panel(self, parent):
        top_row = tk.Frame(parent)
        top_row.pack(fill=tk.X, side=tk.TOP)
        self.top_label = tk.Label(top_row, text="", font=(None, 11, "bold"))
        self.top_label.pack(side=tk.LEFT)
        tk.Button(top_row, text="Highlight / Refresh", command=self.highlight_text).pack(side=tk.RIGHT)
        self._update_top_label()

        legend = tk.Frame(parent)
        legend.pack(fill=tk.X, side=tk.TOP, pady=(4, 0))
        tk.Label(legend, text="Familiarity:", fg="#666", font=(None, 9)).pack(side=tk.LEFT)
        for lvl in LEVELS:
            tk.Label(
                legend, text=str(lvl), bg=level_color(lvl), width=2,
                relief="ridge", font=(None, 9),
            ).pack(side=tk.LEFT, padx=(4, 0))

        # --- add new word section ---
        # IMPORTANT: this is packed to the BOTTOM *before* the reader text
        # box below is packed. Tk's packer hands out cavity space in the
        # order widgets are packed; an expand=True widget packed first
        # would claim all the leftover space and squeeze this frame down
        # to nothing. Anchoring it to the bottom first guarantees it always
        # keeps its space, however big the text box wants to grow.
        add_frame = tk.LabelFrame(parent, text="Add new word to dictionary", padx=8, pady=8)
        add_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        row1 = tk.Frame(add_frame)
        row1.pack(fill=tk.X)
        tk.Label(row1, text="Word:").pack(side=tk.LEFT)
        self.new_word_entry = tk.Entry(row1, font=(self.cjk_font_name, 14), width=14)
        self.new_word_entry.pack(side=tk.LEFT, padx=(4, 12))
        tk.Label(row1, text="Notes:").pack(side=tk.LEFT)
        self.new_word_notes = tk.Entry(row1, font=self.notes_font)
        self.new_word_notes.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 12))
        tk.Label(row1, text="Level:").pack(side=tk.LEFT)
        self.new_word_level = tk.StringVar(value="1")
        ttk.Combobox(
            row1, textvariable=self.new_word_level, values=[str(n) for n in LEVELS],
            state="readonly", width=3,
        ).pack(side=tk.LEFT, padx=(4, 12))
        tk.Button(row1, text="Add & Save", command=self.add_new_word).pack(side=tk.LEFT)
        # NOTE: intentionally not binding Enter here - it can hijack the
        # keystroke IMEs use to confirm a composed Chinese character,
        # silently cutting off what actually gets typed into the field.

        self.right_status = tk.Label(add_frame, text="", fg="#117a65")
        self.right_status.pack(anchor="w", pady=(4, 0))

        # Reader text box is packed LAST so it fills whatever cavity space
        # remains between the top bar/legend and the add-word frame above.
        self.reader_text = tk.Text(parent, wrap="word", font=self.reader_font, undo=True)
        self.reader_text.pack(fill=tk.BOTH, expand=True, pady=(4, 10))
        # Auto re-highlight shortly after a paste (give the insert time to land).
        self.reader_text.bind("<<Paste>>", lambda e: self.root.after(100, self.highlight_text))

    # ----------------------------------------------------------- helpers --
    def _update_dict_count(self):
        self.dict_count_label.config(text=f"{len(self.dictionary)} words in {os.path.basename(self.dict_path)}")

    def _update_path_label(self):
        self.path_label.config(text=f"file: {self.dict_path}")

    def _update_top_label(self):
        self.top_label.config(text=f"Paste text to read  \u2014  {os.path.basename(self.dict_path)}")

    def _flash_status(self, label, text, ms=4000):
        label.config(text=text, wraplength=420, justify="left")
        label.after(ms, lambda: label.config(text=""))

    # ----------------------------------------------------------- reader --
    def highlight_text(self):
        """Longest-match highlight: at every character position, try the
        longest dictionary key that starts there; if found, tag it (colored
        by that word's familiarity level) and jump past it, otherwise move
        forward one character. No word segmentation."""
        text_widget = self.reader_text
        content = text_widget.get("1.0", "end-1c")

        # Wipe out any highlight tags/bindings from the previous pass.
        for tag in list(text_widget.tag_names()):
            if tag.startswith("w_"):
                text_widget.tag_delete(tag)

        if not self.dictionary:
            return

        max_len = max((len(k) for k in self.dictionary), default=0)
        n = len(content)
        i = 0
        bound_tags = set()
        while i < n:
            match_len = 0
            matched_word = None
            upper = min(max_len, n - i)
            for L in range(upper, 0, -1):
                candidate = content[i:i + L]
                if candidate in self.dictionary:
                    match_len = L
                    matched_word = candidate
                    break
            if match_len > 0:
                start_index = f"1.0+{i}c"
                end_index = f"1.0+{i + match_len}c"
                tag_name = "w_" + str(abs(hash(matched_word)))
                if tag_name not in bound_tags:
                    bound_tags.add(tag_name)
                    level = self.dictionary.get(matched_word, {}).get("level", DEFAULT_LEVEL)
                    text_widget.tag_configure(tag_name, background=level_color(level))
                    text_widget.tag_bind(tag_name, "<Button-1>", lambda e, w=matched_word: self.select_word(w))
                    text_widget.tag_bind(tag_name, "<Enter>", lambda e: text_widget.config(cursor="hand2"))
                    text_widget.tag_bind(tag_name, "<Leave>", lambda e: text_widget.config(cursor="xterm"))
                text_widget.tag_add(tag_name, start_index, end_index)
                i += match_len
            else:
                i += 1

    def select_word(self, word):
        self.current_word = word
        entry = self.dictionary.get(word, {"notes": "", "level": DEFAULT_LEVEL})
        self.word_label.config(text=word)
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", entry.get("notes", ""))
        self.level_combo.config(state="readonly")
        self.level_var.set(str(entry.get("level", DEFAULT_LEVEL)))
        self.save_btn.config(state=tk.NORMAL)
        self.delete_btn.config(state=tk.NORMAL)

    # ------------------------------------------------------------ notes --
    def save_current_notes(self):
        if not self.current_word:
            return
        notes = self.notes_text.get("1.0", "end-1c")
        try:
            level = int(self.level_var.get())
        except ValueError:
            level = DEFAULT_LEVEL
        if level not in LEVELS:
            level = DEFAULT_LEVEL
        self.dictionary[self.current_word] = {"notes": notes, "level": level}
        if save_dictionary(self.dictionary, self.dict_path):
            self._update_dict_count()
            self._flash_status(self.left_status, "Saved.")
            self.highlight_text()  # recolor in case the level changed

    def delete_current_word(self):
        if not self.current_word:
            return
        if not messagebox.askyesno("Delete word", f"Remove '{self.current_word}' from the dictionary?"):
            return
        removed_word = self.current_word
        backup_entry = self.dictionary.get(removed_word)
        self.dictionary.pop(removed_word, None)
        if not save_dictionary(self.dictionary, self.dict_path):
            self.dictionary[removed_word] = backup_entry  # roll back in-memory state
            return
        self.current_word = None
        self.word_label.config(text="(click a highlighted word)")
        self.notes_text.delete("1.0", "end")
        self.level_combo.config(state="disabled")
        self.level_var.set(str(DEFAULT_LEVEL))
        self.save_btn.config(state=tk.DISABLED)
        self.delete_btn.config(state=tk.DISABLED)
        self._update_dict_count()
        self.highlight_text()

    # -------------------------------------------------------- add words --
    def add_new_word(self):
        word = self.new_word_entry.get().strip()
        notes = self.new_word_notes.get().strip()
        try:
            level = int(self.new_word_level.get())
        except ValueError:
            level = 1
        if level not in LEVELS:
            level = 1
        if not word:
            messagebox.showwarning("Missing word", "Type a word before adding it.")
            return
        self.dictionary[word] = {"notes": notes, "level": level}
        if not save_dictionary(self.dictionary, self.dict_path):
            return
        print(f"[chinese_reader] added '{word}' (level {level}) -> dictionary now has {len(self.dictionary)} entries")
        self.new_word_entry.delete(0, "end")
        self.new_word_notes.delete(0, "end")
        self.new_word_level.set("1")
        self._update_dict_count()
        self._flash_status(
            self.right_status,
            f"Added '{word}'. (It will only highlight in the text above if that exact text is already pasted there.)",
        )
        self.highlight_text()


def main():
    root = tk.Tk()
    ChineseReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()