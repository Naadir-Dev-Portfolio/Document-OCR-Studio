from __future__ import annotations

import csv
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .ocr_engine import (
    IMAGE_EXTENSIONS,
    OCREngineError,
    OCRResult,
    parse_text_to_grid,
    rows_to_tsv,
    scan_image,
    write_rows_to_csv,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False


COLORS = {
    "bg": "#111417",
    "panel": "#181d21",
    "panel_alt": "#20262b",
    "panel_soft": "#252c31",
    "border": "#354047",
    "accent": "#2bb3a3",
    "accent_2": "#d39d35",
    "text": "#eef4f2",
    "muted": "#a8b4b0",
    "muted_2": "#788781",
    "danger": "#ef6b63",
    "ok": "#76c893",
    "canvas": "#0d1012",
}


class DocumentOCRStudio:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Document OCR Studio")
        self.root.geometry("1320x820")
        self.root.minsize(1080, 680)
        self.root.configure(bg=COLORS["bg"])

        self.image_path: Path | None = None
        self.preview_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.last_result: OCRResult | None = None
        self.grid_rows: list[list[str]] = []
        self.edit_mode = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="Ready")
        self.confidence_text = tk.StringVar(value="Confidence --")
        self.engine_text = tk.StringVar(
            value="Tesseract OCR" if DND_AVAILABLE else "Tesseract OCR | drop support optional"
        )
        self.active_editor: tk.Entry | None = None

        self._configure_style()
        self._build_layout()
        self._bind_shortcuts()
        self._enable_drop_target()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["panel_alt"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["panel"],
            darkcolor=COLORS["panel"],
            troughcolor=COLORS["panel_soft"],
            font=("Segoe UI", 10),
        )
        style.configure("TFrame", background=COLORS["panel"])
        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Soft.TFrame", background=COLORS["panel_alt"])
        style.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("Hero.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure(
            "TButton",
            background=COLORS["panel_soft"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            focusthickness=0,
            padding=(14, 8),
        )
        style.map("TButton", background=[("active", COLORS["border"])])
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#061312",
            bordercolor=COLORS["accent"],
            font=("Segoe UI", 10, "bold"),
            padding=(18, 9),
        )
        style.map("Accent.TButton", background=[("active", "#38caba")])
        style.configure(
            "Ghost.TButton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            padding=(12, 8),
        )
        style.configure(
            "TNotebook",
            background=COLORS["panel"],
            borderwidth=0,
            tabmargins=(0, 4, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel_alt"],
            foreground=COLORS["muted"],
            padding=(16, 9),
            bordercolor=COLORS["border"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["panel_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Treeview",
            background=COLORS["panel_alt"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["panel_alt"],
            bordercolor=COLORS["border"],
            rowheight=30,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel_soft"],
            foreground=COLORS["text"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#224d49")], foreground=[("selected", COLORS["text"])])
        style.configure(
            "TCheckbutton",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            focuscolor=COLORS["panel"],
        )

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame")
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        self._build_header(outer)

        body = ttk.Frame(outer, style="App.TFrame")
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=5, minsize=460)
        body.columnconfigure(1, weight=7, minsize=560)
        body.rowconfigure(0, weight=1)

        self._build_preview_panel(body)
        self._build_results_panel(body)
        self._build_status_bar(outer)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="App.TFrame")
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)

        title_block = ttk.Frame(header, style="App.TFrame")
        title_block.grid(row=0, column=0, sticky="w")
        ttk.Label(title_block, text="Document OCR Studio", style="Hero.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="Local deterministic OCR with editable data grids and CSV export",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(header, style="App.TFrame")
        actions.grid(row=0, column=1, sticky="e")
        ttk.Button(actions, text="Open Image", command=self.open_image, style="Ghost.TButton").pack(side="left", padx=(0, 8))
        self.scan_button = ttk.Button(actions, text="Scan", command=self.scan_current_image, style="Accent.TButton")
        self.scan_button.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Convert to Data", command=self.convert_text_to_data).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Copy", command=self.copy_active_selection).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Export CSV", command=self.export_csv).pack(side="left")

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        panel = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        top = tk.Frame(panel, bg=COLORS["panel"])
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        tk.Label(top, text="Original", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(top, textvariable=self.engine_text, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(
            side="right"
        )

        self.preview_canvas = tk.Canvas(
            panel,
            bg=COLORS["canvas"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.preview_canvas.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.preview_canvas.bind("<Configure>", lambda _event: self._draw_preview())
        self._draw_empty_preview()

    def _build_results_panel(self, parent: ttk.Frame) -> None:
        panel = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        top = tk.Frame(panel, bg=COLORS["panel"])
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        tk.Label(top, text="Extracted Workspace", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(
            side="left"
        )
        ttk.Checkbutton(top, text="Edit mode", variable=self.edit_mode).pack(side="right")
        tk.Label(top, textvariable=self.confidence_text, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(
            side="right", padx=(0, 14)
        )

        self.notebook = ttk.Notebook(panel)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        self.text_widget = tk.Text(
            self.notebook,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            relief="flat",
            wrap="word",
            padx=14,
            pady=12,
            font=("Cascadia Mono", 10),
            undo=True,
        )
        self.notebook.add(self.text_widget, text="Text")

        grid_frame = ttk.Frame(self.notebook, style="Soft.TFrame")
        grid_frame.rowconfigure(0, weight=1)
        grid_frame.columnconfigure(0, weight=1)
        self.table_tree = ttk.Treeview(grid_frame, show="headings", selectmode="extended")
        self.table_tree.grid(row=0, column=0, sticky="nsew")
        grid_y = ttk.Scrollbar(grid_frame, orient="vertical", command=self.table_tree.yview)
        grid_x = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.table_tree.xview)
        self.table_tree.configure(yscrollcommand=grid_y.set, xscrollcommand=grid_x.set)
        grid_y.grid(row=0, column=1, sticky="ns")
        grid_x.grid(row=1, column=0, sticky="ew")
        self.table_tree.bind("<Double-1>", self._start_cell_edit)
        self.notebook.add(grid_frame, text="Data Grid")

        sections_frame = ttk.Frame(self.notebook, style="Soft.TFrame")
        sections_frame.rowconfigure(0, weight=1)
        sections_frame.columnconfigure(0, weight=1)
        self.sections_tree = ttk.Treeview(
            sections_frame,
            columns=("kind", "value", "confidence"),
            show="tree headings",
            selectmode="extended",
        )
        self.sections_tree.heading("#0", text="Section")
        self.sections_tree.heading("kind", text="Type")
        self.sections_tree.heading("value", text="Value")
        self.sections_tree.heading("confidence", text="Conf.")
        self.sections_tree.column("#0", width=150, minwidth=110)
        self.sections_tree.column("kind", width=100, anchor="center")
        self.sections_tree.column("value", width=420, minwidth=220)
        self.sections_tree.column("confidence", width=80, anchor="center")
        self.sections_tree.grid(row=0, column=0, sticky="nsew")
        sections_y = ttk.Scrollbar(sections_frame, orient="vertical", command=self.sections_tree.yview)
        self.sections_tree.configure(yscrollcommand=sections_y.set)
        sections_y.grid(row=0, column=1, sticky="ns")
        self.notebook.add(sections_frame, text="Sections")

        self._set_grid([])

    def _build_status_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="App.TFrame")
        bar.pack(fill="x", pady=(10, 0))
        tk.Label(
            bar,
            textvariable=self.status_text,
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(side="left")
        tk.Label(
            bar,
            text="No cloud calls. No generative AI.",
            bg=COLORS["bg"],
            fg=COLORS["muted_2"],
            font=("Segoe UI", 9),
        ).pack(side="right")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.open_image())
        self.root.bind("<Control-s>", lambda _event: self.scan_current_image())
        self.root.bind("<Control-e>", lambda _event: self.export_csv())
        self.root.bind("<Control-Return>", lambda _event: self.convert_text_to_data())

    def _enable_drop_target(self) -> None:
        if not DND_AVAILABLE:
            return
        for widget in (self.root, self.preview_canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        self.load_image(paths[0])

    def open_image(self) -> None:
        filetypes = [
            ("Images", " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))),
            ("All files", "*.*"),
        ]
        selected = filedialog.askopenfilename(title="Open document image", filetypes=filetypes)
        if selected:
            self.load_image(selected)

    def load_image(self, path: str | Path) -> None:
        image_path = Path(path)
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            messagebox.showerror("Unsupported image", "Choose a PNG, JPG, WEBP, BMP or TIFF image.")
            return
        try:
            image = Image.open(image_path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return

        self.image_path = image_path
        self.preview_image = image.convert("RGB")
        self.last_result = None
        self.grid_rows = []
        self.text_widget.delete("1.0", "end")
        self._clear_sections()
        self._set_grid([])
        self._draw_preview()
        self.status_text.set(f"Loaded {image_path.name}")
        self.confidence_text.set("Confidence --")

    def scan_current_image(self) -> None:
        if not self.image_path:
            self.open_image()
            if not self.image_path:
                return

        self.scan_button.configure(state="disabled")
        self.status_text.set("Scanning image...")
        worker = threading.Thread(target=self._scan_worker, args=(self.image_path,), daemon=True)
        worker.start()

    def _scan_worker(self, image_path: Path) -> None:
        try:
            result = scan_image(image_path)
        except OCREngineError as exc:
            self.root.after(0, lambda: self._scan_failed(str(exc)))
        except Exception as exc:
            self.root.after(0, lambda: self._scan_failed(f"Unexpected scan failure: {exc}"))
        else:
            self.root.after(0, lambda: self._scan_complete(result))

    def _scan_failed(self, message: str) -> None:
        self.scan_button.configure(state="normal")
        self.status_text.set(message)
        messagebox.showerror("Scan failed", message)

    def _scan_complete(self, result: OCRResult) -> None:
        self.scan_button.configure(state="normal")
        self.last_result = result
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", result.text)
        rows = [list(row) for row in result.table_rows] or self._fallback_grid(result)
        self._set_grid(rows)
        self._set_sections(result)
        self.confidence_text.set(f"Confidence {result.confidence:.1f}%")
        self.status_text.set(f"Scan complete: {len(result.lines)} lines, {len(self.grid_rows)} data rows")
        self.notebook.select(1 if self.grid_rows else 0)

    def convert_text_to_data(self) -> None:
        text = self.text_widget.get("1.0", "end").strip()
        rows = parse_text_to_grid(text)
        self._set_grid(rows)
        self.notebook.select(1)
        self.status_text.set(f"Converted text to {len(rows)} grid rows")

    def copy_active_selection(self) -> None:
        active_tab = self.notebook.index(self.notebook.select())
        if active_tab == 0:
            try:
                payload = self.text_widget.get("sel.first", "sel.last")
            except tk.TclError:
                payload = self.text_widget.get("1.0", "end").strip()
        elif active_tab == 1:
            payload = rows_to_tsv(self._selected_grid_rows() or self.grid_rows)
        else:
            payload = rows_to_tsv(self._selected_section_rows())

        if not payload.strip():
            self.status_text.set("Nothing to copy")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(payload)
        self.status_text.set("Copied selection")

    def export_csv(self) -> None:
        rows = self.grid_rows or parse_text_to_grid(self.text_widget.get("1.0", "end"))
        if not rows:
            messagebox.showinfo("No data", "Scan or convert text before exporting.")
            return
        suggested = "document_ocr_export.csv"
        if self.image_path:
            suggested = f"{self.image_path.stem}_ocr.csv"
        target = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            initialfile=suggested,
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not target:
            return
        write_rows_to_csv(target, rows)
        self.status_text.set(f"Exported {len(rows)} rows to {Path(target).name}")

    def _draw_empty_preview(self) -> None:
        self.preview_canvas.delete("all")
        width = max(self.preview_canvas.winfo_width(), 520)
        height = max(self.preview_canvas.winfo_height(), 520)
        self.preview_canvas.create_rectangle(28, 28, width - 28, height - 28, outline=COLORS["border"], dash=(4, 4))
        self.preview_canvas.create_text(
            width / 2,
            height / 2 - 12,
            text="Drop image",
            fill=COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        )
        self.preview_canvas.create_text(
            width / 2,
            height / 2 + 18,
            text="or open a document image",
            fill=COLORS["muted"],
            font=("Segoe UI", 10),
        )

    def _draw_preview(self) -> None:
        self.preview_canvas.delete("all")
        if not self.preview_image:
            self._draw_empty_preview()
            return

        canvas_width = max(self.preview_canvas.winfo_width(), 1)
        canvas_height = max(self.preview_canvas.winfo_height(), 1)
        image = self.preview_image.copy()
        image.thumbnail((canvas_width - 36, canvas_height - 36), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        x = canvas_width // 2
        y = canvas_height // 2
        self.preview_canvas.create_image(x, y, image=self.preview_photo, anchor="center")
        box_left = x - image.width // 2
        box_top = y - image.height // 2
        box_right = x + image.width // 2
        box_bottom = y + image.height // 2
        self.preview_canvas.create_rectangle(box_left, box_top, box_right, box_bottom, outline=COLORS["accent"], width=2)
        if self.image_path:
            self.preview_canvas.create_text(
                box_left + 12,
                box_top + 12,
                text=self.image_path.name,
                fill=COLORS["text"],
                anchor="nw",
                font=("Segoe UI", 9, "bold"),
            )

    def _set_grid(self, rows: list[list[str]]) -> None:
        self._cancel_cell_edit()
        for item in self.table_tree.get_children():
            self.table_tree.delete(item)

        self.grid_rows = [list(row) for row in rows]
        if not rows:
            columns = ["status"]
            self.table_tree.configure(columns=columns)
            self.table_tree.heading("status", text="Data")
            self.table_tree.column("status", width=520, minwidth=260, stretch=True)
            self.table_tree.insert("", "end", values=("No data yet",))
            return

        max_cols = max(len(row) for row in rows)
        normalized = [row + [""] * (max_cols - len(row)) for row in rows]
        headers, data_rows = self._derive_headers(normalized)
        columns = [f"c{index}" for index in range(len(headers))]
        self.table_tree.configure(columns=columns)
        for column, header in zip(columns, headers):
            self.table_tree.heading(column, text=header)
            self.table_tree.column(column, width=max(120, min(260, len(header) * 12 + 80)), minwidth=90, stretch=True)

        for row in data_rows:
            self.table_tree.insert("", "end", values=tuple(row))
        self.grid_rows = [headers, *data_rows]

    def _derive_headers(self, rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        first = [cell.strip() for cell in rows[0]]
        if len(rows) > 1 and self._looks_like_header(first, rows[1:]):
            headers = [cell or f"Column {index + 1}" for index, cell in enumerate(first)]
            return headers, rows[1:]
        return [f"Column {index + 1}" for index in range(len(first))], rows

    def _looks_like_header(self, row: list[str], remaining: list[list[str]]) -> bool:
        if not any(row):
            return False
        alpha_cells = sum(any(char.isalpha() for char in cell) for cell in row)
        numeric_below = 0
        checked = 0
        for data_row in remaining[:4]:
            for cell in data_row:
                if cell.strip():
                    checked += 1
                    numeric_below += int(any(char.isdigit() for char in cell))
        return alpha_cells >= max(1, len(row) // 2) and numeric_below >= max(1, checked // 3)

    def _fallback_grid(self, result: OCRResult) -> list[list[str]]:
        if result.key_values:
            return [["Field", "Value"], *[list(row) for row in result.key_values]]
        return [["Line", "Text"], *[[str(index + 1), line.text] for index, line in enumerate(result.lines)]]

    def _set_sections(self, result: OCRResult) -> None:
        self._clear_sections()
        for index, (key, value) in enumerate(result.key_values, start=1):
            self.sections_tree.insert("", "end", text=f"Field {index}", values=("Key value", value, ""))
        for index, line in enumerate(result.lines, start=1):
            self.sections_tree.insert(
                "",
                "end",
                text=f"Line {index}",
                values=("Text", line.text, f"{line.confidence:.0f}%"),
            )

    def _clear_sections(self) -> None:
        for item in self.sections_tree.get_children():
            self.sections_tree.delete(item)

    def _selected_grid_rows(self) -> list[list[str]]:
        selected = self.table_tree.selection()
        if not selected:
            return []
        headings = [self.table_tree.heading(column)["text"] for column in self.table_tree["columns"]]
        rows = [headings]
        for item in selected:
            rows.append([str(value) for value in self.table_tree.item(item, "values")])
        return rows

    def _selected_section_rows(self) -> list[list[str]]:
        selected = self.sections_tree.selection()
        if not selected:
            selected = self.sections_tree.get_children()
        rows = [["Section", "Type", "Value", "Confidence"]]
        for item in selected:
            values = self.sections_tree.item(item, "values")
            rows.append([self.sections_tree.item(item, "text"), *[str(value) for value in values]])
        return rows

    def _start_cell_edit(self, event) -> None:
        if not self.edit_mode.get():
            return
        region = self.table_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.table_tree.identify_row(event.y)
        column_id = self.table_tree.identify_column(event.x)
        if not item or not column_id:
            return
        column_index = int(column_id.replace("#", "")) - 1
        bbox = self.table_tree.bbox(item, column_id)
        if not bbox:
            return

        values = list(self.table_tree.item(item, "values"))
        current = values[column_index] if column_index < len(values) else ""
        self._cancel_cell_edit()
        editor = tk.Entry(
            self.table_tree,
            bg="#f5fbf9",
            fg="#111417",
            relief="flat",
            insertbackground="#111417",
            font=("Segoe UI", 10),
        )
        editor.insert(0, current)
        editor.select_range(0, "end")
        editor.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        editor.focus_set()
        self.active_editor = editor

        def save(_event=None):
            values[column_index] = editor.get()
            self.table_tree.item(item, values=values)
            self._sync_grid_from_tree()
            self._cancel_cell_edit()

        editor.bind("<Return>", save)
        editor.bind("<FocusOut>", save)
        editor.bind("<Escape>", lambda _event: self._cancel_cell_edit())

    def _cancel_cell_edit(self) -> None:
        if self.active_editor is not None:
            self.active_editor.destroy()
            self.active_editor = None

    def _sync_grid_from_tree(self) -> None:
        if not self.table_tree["columns"]:
            return
        headings = [self.table_tree.heading(column)["text"] for column in self.table_tree["columns"]]
        rows = [headings]
        for item in self.table_tree.get_children():
            values = [str(value) for value in self.table_tree.item(item, "values")]
            if values != ["No data yet"]:
                rows.append(values)
        self.grid_rows = rows


def run() -> None:
    root_class = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = root_class()
    app = DocumentOCRStudio(root)
    root.mainloop()
