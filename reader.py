#!/usr/bin/env python3
"""
Chinese Reader - a simple local app for reading Chinese text against a
personal vocabulary dictionary.

Left panel:  shows notes for whatever word you click on in the reader,
             editable and savable.
Right panel: paste text to read; any word that exists in your dictionary
             gets highlighted (longest-match, no NLP/segmentation - you
             build the vocabulary list yourself); click a highlighted word
             to see/edit its notes on the left; also lets you add brand
             new words straight into the dictionary.

Dictionary format (dictionary.json, sits next to this script) - a flat
word -> {notes, level} mapping, still human readable / hand-editable.
`level` is your familiarity with the word, 1 (barely know it) to 5
(mastered) - it controls the highlight color in the reader (red -> green):

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
from tkinter import ttk

DICT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictionary.json")

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

# Fonts that reliably render Chinese characters, checked in order.
CJK_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
    "Microsoft YaHei",
    "PingFang SC",
    "PingFang TC",
    "STHeiti",
    "SimHei",
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


def load_dictionary():
    if not os.path.exists(DICT_PATH):
        with open(DICT_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DICTIONARY, f, ensure_ascii=False, indent=2, sort_keys=True)
        return {k: dict(v) for k, v in DEFAULT_DICTIONARY.items()}
    try:
        with open(DICT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("dictionary.json must contain a JSON object of word -> entry")
        # Transparently upgrades entries saved by the older word->string
        # format, so existing dictionary.json files keep working.
        return {word: _normalize_entry(value) for word, value in data.items()}
    except Exception as e:
        messagebox.showerror("Dictionary load error", f"Could not read {DICT_PATH}:\n{e}")
        return {}


def save_dictionary(dictionary):
    """Returns True on success. Shows an error dialog and returns False on
    failure instead of failing silently (e.g. bad file permissions)."""
    try:
        with open(DICT_PATH, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except Exception as e:
        messagebox.showerror("Save failed", f"Could not write {DICT_PATH}:\n{e}")
        return False


class ChineseReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Chinese Reader")
        self.root.geometry("1200x750")

        self.dictionary = load_dictionary()
        self.current_word = None
        self.cjk_font_name = pick_cjk_font()

        self.reader_font = tkfont.Font(family=self.cjk_font_name, size=18)
        self.notes_font = tkfont.Font(family=self.cjk_font_name, size=14)

        self._build_ui()
        self.highlight_text()

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

        tk.Label(
            parent, text=f"file: {DICT_PATH}", fg="#888",
            font=(None, 8), wraplength=320, justify="left",
        ).pack(anchor="w", pady=(2, 0))

    def _build_right_panel(self, parent):
        top_row = tk.Frame(parent)
        top_row.pack(fill=tk.X, side=tk.TOP)
        tk.Label(top_row, text="Paste text to read", font=(None, 11, "bold")).pack(side=tk.LEFT)
        tk.Button(top_row, text="Highlight / Refresh", command=self.highlight_text).pack(side=tk.RIGHT)

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
        self.dict_count_label.config(text=f"{len(self.dictionary)} words in dictionary.json")

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
        if save_dictionary(self.dictionary):
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
        if not save_dictionary(self.dictionary):
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
        if not save_dictionary(self.dictionary):
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
    print(f"[chinese_reader] dictionary file: {DICT_PATH}")
    root = tk.Tk()
    ChineseReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()