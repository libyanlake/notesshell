# Please consult LICENSE. Copyright 2025 LL

# version 1.0

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog, colorchooser
import os, sys, subprocess, signal, time
import pty
import threading, queue
import markdown2
from tkhtmlview import HTMLLabel
import re
import select
# fcntl is Unix-specific, use conditionally
if sys.platform != "win32":
    import fcntl
import string
import json

class NoteShellApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NotesShell")
        self.root.geometry("1200x800")

        # configuration
        self.app_data_dir = os.path.expanduser("~/.notesshell")
        self.notes_dir = os.path.join(self.app_data_dir, "notes")
        self.config_path = os.path.join(self.app_data_dir, "config.json")
        self.config = {}

        self.var_shell_cmd = tk.StringVar()
        self.var_term_bg = tk.StringVar()
        self.var_term_fg = tk.StringVar()
        self.var_show_help = tk.BooleanVar()
        self.var_theme = tk.StringVar()
        self.var_editor_font_size = tk.IntVar()

        self.load_config() # load/set defaults and update tk.vars

        # application state
        self.current_note = None
        self.is_dirty = False # flag for unsaved changes
        self.md = markdown2.Markdown(extras=["fenced-code-blocks", "tables", "code-friendly", "footnotes"])

        # live preview debouncing state to prevent excessive rerenderings
        self._preview_debounce_ms = 550 # in ms (should be made an option)
        self._preview_update_job_id = None

        self.base_editor_font = ('Monospace', self.config.get("editor_font_size", 11))
        self.preview_css_template = ''

        # shell state
        self.running = True
        self.shell_process = None
        self.master_fd = None
        self.slave_fd = None
        self.reader_thread = None
        self.output_queue = queue.Queue()
        self._poll_id = None

        # history attributes
        self.command_history = []
        self.history_index = -1
        self.current_input_buffer = ""

        # F11 double-press state
        self._last_f11_time = 0
        self._f11_press_count = 0
        self._f11_timeout_ms = 500

        # notes filtering state
        self._all_notes = []
        self.filter_entry = None
        self.delete_button = None

        self.style = ttk.Style(root)
        self.apply_theme()
        self.setup_ui()
        self.setup_key_bindings()
        self.load_notes()
        self._apply_editor_font_size() # apply initial font size

        self._schedule_initial_shell_start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._update_save_status() # initial status update

    def load_config(self):
        default_shell = ["bash", "--norc"] if sys.platform != "win32" else ["cmd.exe"]
        default_theme = 'clam'
        default_font_size = 11
        default_config = {"shell_cmd": default_shell, "term_bg": "#f0f0f0", "term_fg": "#333333", "show_help": True, "theme": default_theme, "editor_font_size": default_font_size}

        config_loaded = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f: config_loaded = json.load(f)
                print(f"[+] Loaded config from {self.config_path}")
            except Exception as e: print(f"[!] Error loading config: {e}. Using defaults."); config_loaded = {}
        else: print(f"[!] Config file not found at {self.config_path}. Using defaults.")

        self.config = {**default_config, **config_loaded}

        # validation and type correction
        if not isinstance(self.config.get("shell_cmd"), list) or not self.config.get("shell_cmd"): self.config["shell_cmd"] = default_config["shell_cmd"]
        if not isinstance(self.config.get("term_bg"), str): self.config["term_bg"] = default_config["term_bg"]
        if not isinstance(self.config.get("term_fg"), str): self.config["term_fg"] = default_config["term_fg"]
        if not isinstance(self.config.get("show_help"), bool): self.config["show_help"] = default_config["show_help"]
        if not isinstance(self.config.get("theme"), str): self.config["theme"] = default_config["theme"]
        try: self.config["editor_font_size"] = int(self.config.get("editor_font_size"))
        except (ValueError, TypeError): self.config["editor_font_size"] = default_config["editor_font_size"]

        # update tk.vars AFTER self.config is finalized
        self.var_shell_cmd.set(" ".join(self.config["shell_cmd"]))
        self.var_term_bg.set(self.config["term_bg"])
        self.var_term_fg.set(self.config["term_fg"])
        self.var_show_help.set(self.config["show_help"])
        self.var_theme.set(self.config["theme"])
        self.var_editor_font_size.set(self.config["editor_font_size"])

        if not os.path.exists(self.config_path):
             try:
                  os.makedirs(self.app_data_dir, exist_ok=True)
                  with open(self.config_path, 'w') as f: json.dump(self.config, f, indent=4)
                  print(f"Created default config file at {self.config_path}")
             except Exception as e: print(f"Warning: Could not create default config file: {e}")
        self.base_editor_font = ('Monospace', self.config["editor_font_size"])


    def save_config(self):
        try:
            shell_cmd_str = self.var_shell_cmd.get().strip()
            # assumes no quotes in args
            self.config["shell_cmd"] = shell_cmd_str.split() if shell_cmd_str else []
            self.config["term_bg"] = self.var_term_bg.get()
            self.config["term_fg"] = self.var_term_fg.get()
            self.config["show_help"] = self.var_show_help.get()
            self.config["theme"] = self.var_theme.get()
            try: self.config["editor_font_size"] = int(self.var_editor_font_size.get())
            except ValueError: messagebox.showerror("Config Error", "Font size must be an integer."); return

            os.makedirs(self.app_data_dir, exist_ok=True)
            with open(self.config_path, 'w') as f: json.dump(self.config, f, indent=4)
            print(f"Configuration saved to {self.config_path}")
            messagebox.showinfo("Settings Saved", "Settings saved. Apply changes where possible. Restart shell/app if needed.")
            self.apply_settings()

        except Exception as e: messagebox.showerror("Save Error", f"Failed to save configuration: {e}"); print(f"Error saving config: {e}")

    def apply_theme(self):
        try:
             selected_theme = self.config.get("theme", "clam")
             if selected_theme in self.style.theme_names(): self.style.theme_use(selected_theme); print(f"[+] Applied theme: {selected_theme}")
             else: print(f"[-] Theme '{selected_theme}' not available."); self.var_theme.set(self.style.theme())
        except Exception as e: print(f"Error applying theme: {e}")

    def apply_terminal_colors(self):
        bg = self.config.get("term_bg", "#f0f0f0")
        fg = self.config.get("term_fg", "#333333")
        if hasattr(self, 'terminal_output') and self.terminal_output.winfo_exists(): self.terminal_output.config(bg=bg, fg=fg, insertbackground=fg)
        print("Terminal colors updated (config value).")

    def apply_help_visibility(self):
        if hasattr(self, 'help_label') and self.help_label.winfo_exists():
            show = self.config.get("show_help", True)
            is_packed = self.help_label.winfo_ismapped()
            if show and not is_packed: self.help_label.pack(side=tk.RIGHT, padx=5)
            elif not show and is_packed: self.help_label.pack_forget()

    def _apply_editor_font_size(self):
        """Applies the configured font size to the editor and updates base font."""
        try:
            size = self.config.get("editor_font_size", 11)
            new_font = ('Monospace', size)
            if hasattr(self, 'text_editor') and self.text_editor.winfo_exists(): self.text_editor.config(font=new_font)
            self.base_editor_font = new_font
            print(f"[+] Editor font size set to {size}pt.")
            # trigger preview update AFTER applying editor size
            self._debounced_update() # use debounced update for preview
        except Exception as e: print(f"Error applying editor font size: {e}")

    def apply_settings(self):
        """Applies currently saved settings."""
        self.apply_theme()
        self.apply_terminal_colors()
        self.apply_help_visibility()
        self._apply_editor_font_size()


    def setup_ui(self):
        self.root.configure(bg="#f8f9fa")

        # Toolbar
        self.toolbar = ttk.Frame(self.root, style='Toolbar.TFrame')
        self.toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        ttk.Button(self.toolbar, text="New", command=self.new_note).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text="Save", command=self.save_note).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text="Save As...", command=self.save_note_as).pack(side=tk.LEFT, padx=2)
        self.help_label = ttk.Label(self.toolbar, text=" | F12: Term | F11x2: RShell | Ctrl+/-/0: Size", font=('Arial', 9, 'italic'), foreground="#666")
        self.apply_help_visibility() # Apply initial state

        # Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # notes Tab
        self.notes_tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.notes_tab_frame, text=' Notes ')

        self.sidebar_frame = ttk.Frame(self.notes_tab_frame, width=200)
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5), pady=(5,0))

        self.filter_entry = ttk.Entry(self.sidebar_frame, font=('Arial', 10), foreground='grey')
        self.filter_entry.pack(fill=tk.X, padx=5, pady=2)
        self.filter_entry.insert(0, "Search notes...")
        self.filter_entry.bind("<FocusIn>", self._clear_filter_placeholder)
        self.filter_entry.bind("<FocusOut>", self._restore_filter_placeholder)
        self.filter_entry.bind("<KeyRelease>", self.filter_notes)

        self.notes_list = tk.Listbox(self.sidebar_frame, font=('Arial', 11), borderwidth=0, highlightthickness=0, selectbackground="#e9ecef", selectforeground="#000000", activestyle='none')
        self.notes_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 2))
        self.notes_list.bind("<<ListboxSelect>>", self.load_note_content)

        self.delete_button = ttk.Button(self.sidebar_frame, text="Delete Selected", command=self.delete_selected_note, state=tk.DISABLED)
        self.delete_button.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.notes_list.bind("<<ListboxSelect>>", lambda e: self._update_delete_button_state(), add='+')

        self.paned = ttk.PanedWindow(self.notes_tab_frame, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, pady=(5,0))

        self.editor_frame = ttk.Frame(self.paned)
        self.text_editor = tk.Text(self.editor_frame, wrap=tk.WORD, font=self.base_editor_font, padx=10, pady=10, undo=True, borderwidth=0, bg="#ffffff", fg="#333333", insertbackground="#333333")
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        self.paned.add(self.editor_frame, weight=1)

        self.preview_frame = ttk.Frame(self.paned, style='Preview.TFrame')
        self.preview = HTMLLabel(self.preview_frame, background="#ffffff", padx=10, pady=10)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.paned.add(self.preview_frame, weight=1)

        # editor change binding
        self.text_editor.bind("<KeyRelease>", self._on_editor_change)
        # <<Modified>> is implicitly handled by setting the dirty flag in _on_editor_change

        # Settings Tab
        self.settings_tab_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.settings_tab_frame, text=' Settings ')

        settings_content_frame = ttk.LabelFrame(self.settings_tab_frame, text="Configuration", padding="10")
        settings_content_frame.pack(fill=tk.BOTH, expand=True)
        settings_content_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(settings_content_frame, text="Show Help Hints in Toolbar", variable=self.var_show_help, command=self.apply_help_visibility).grid(row=0, column=0, columnspan=3, sticky="w", pady=5)

        ttk.Label(settings_content_frame, text="UI Theme:").grid(row=1, column=0, sticky="w", pady=5, padx=(0,5))
        theme_combo = ttk.Combobox(settings_content_frame, textvariable=self.var_theme, values=self.style.theme_names(), state="readonly", width=15)
        theme_combo.grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(settings_content_frame, text="(Requires app restart)").grid(row=1, column=2, sticky="w", padx=5)

        ttk.Label(settings_content_frame, text="Editor Font Size:").grid(row=2, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Spinbox(settings_content_frame, from_=6, to=72, textvariable=self.var_editor_font_size, width=5).grid(row=2, column=1, sticky="w", pady=5)

        ttk.Label(settings_content_frame, text="Shell Command:").grid(row=3, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Entry(settings_content_frame, textvariable=self.var_shell_cmd, width=40).grid(row=3, column=1, columnspan=2, sticky="ew", pady=5)
        ttk.Label(settings_content_frame, text="(Restart shell with F11x2 after saving)").grid(row=3, column=3, sticky="w", padx=5)

        def pick_color(var, title="Choose Color"):
             color_code = colorchooser.askcolor(title=title, initialcolor=var.get())
             if color_code and color_code[1]: var.set(color_code[1])

        ttk.Label(settings_content_frame, text="Terminal BG Color:").grid(row=4, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Entry(settings_content_frame, textvariable=self.var_term_bg, width=10).grid(row=4, column=1, sticky="w", pady=5)
        ttk.Button(settings_content_frame, text="Choose...", command=lambda: pick_color(self.var_term_bg, "Terminal Background")).grid(row=4, column=2, sticky="w", padx=5)

        ttk.Label(settings_content_frame, text="Terminal FG Color:").grid(row=5, column=0, sticky="w", pady=5, padx=(0,5))
        ttk.Entry(settings_content_frame, textvariable=self.var_term_fg, width=10).grid(row=5, column=1, sticky="w", pady=5)
        ttk.Button(settings_content_frame, text="Choose...", command=lambda: pick_color(self.var_term_fg, "Terminal Foreground")).grid(row=5, column=2, sticky="w", padx=5)
        ttk.Label(settings_content_frame, text="(Toggle terminal/Restart shell after saving)").grid(row=5, column=3, sticky="w", padx=5)

        ttk.Button(settings_content_frame, text="Save Settings", command=self.save_config).grid(row=6, column=0, columnspan=4, pady=20)

        # setup Terminal widgets (but don't pack)
        self.setup_terminal()

    def _on_editor_change(self, event=None):
        if not self.is_dirty:
             self.is_dirty = True
             self._update_save_status()
        self._debounced_update()

    def _debounced_update(self):
        if self._preview_update_job_id: self.root.after_cancel(self._preview_update_job_id)
        self._preview_update_job_id = self.root.after(self._preview_debounce_ms, self._perform_update)

    def _perform_update(self):
        self._preview_update_job_id = None
        self.update_live_preview()
        # status is updated immediately when is_dirty is first set

    def _clear_filter_placeholder(self, event):
        if self.filter_entry.get() == "Search notes...": self.filter_entry.delete(0, tk.END); self.filter_entry.config()
    def _restore_filter_placeholder(self, event):
        if not self.filter_entry.get().strip(): self.filter_entry.insert(0, "Search notes..."); self.filter_entry.config()

    def filter_notes(self, event=None):
        query = self.filter_entry.get().lower().strip()
        self.notes_list.delete(0, tk.END)
        notes_to_display = sorted([fname for fname in self._all_notes if not query or query == "search notes..." or query in fname.lower()])
        for fname in notes_to_display: self.notes_list.insert(tk.END, fname)
        if self.current_note and self.current_note in notes_to_display:
             try: idx = notes_to_display.index(self.current_note); self.notes_list.selection_clear(0, tk.END); self.notes_list.selection_set(idx); self.notes_list.activate(idx)
             except ValueError: pass
        self._update_delete_button_state()

    def _update_delete_button_state(self):
        if self.delete_button and self.delete_button.winfo_exists():
            state = tk.NORMAL if self.notes_list.curselection() else tk.DISABLED
            self.delete_button.config(state=state)

    def delete_selected_note(self):
        selection = self.notes_list.curselection()
        if not selection: return
        filename = self.notes_list.get(selection[0])
        path = os.path.join(self.notes_dir, filename)
        if messagebox.askyesno("Confirm Deletion", f"Delete '{filename}'?"):
            try:
                os.remove(path); print(f"Deleted: {filename}")
                was_current = (self.current_note == filename)
                self.load_notes() # reloads list and applies filter
                if was_current: self.new_note(confirm_discard=False)
            except Exception as e: messagebox.showerror("Delete Error", f"Failed to delete: {e}"); self.load_notes()

    def _update_save_status(self):
        title = "NotesShell"
        if self.current_note: title += f" - {self.current_note}"
        else: title += " - Untitled"
        if self.is_dirty: title += " *"
        self.root.title(title)

    def _change_font_size(self, delta):
        # print(f"Attempting font size change by {delta}")
        current_size = self.config.get("editor_font_size", 11)
        new_size = max(6, current_size + delta)
        self.config["editor_font_size"] = new_size
        self.var_editor_font_size.set(new_size)
        self._apply_editor_font_size()

    def _reset_font_size(self, event=None): # Add event=None for binding
        # print("Attempting font size reset")
        default_size = 11
        self.config["editor_font_size"] = default_size
        self.var_editor_font_size.set(default_size)
        self._apply_editor_font_size()

    def update_live_preview(self, event=None):
        try:
            md_text = self.text_editor.get("1.0", tk.END).strip()
            html_content = self.md.convert(md_text)

            editor_size = self.config.get("editor_font_size", 11)
            code_size = max(8, int(editor_size * 0.9)) # Code font size relative to editor
            formatted_css = self.preview_css_template.format(size=editor_size, code_size=code_size)

            # wrap in proper HTML structure
            full_html = f"<!DOCTYPE html><html><head>{formatted_css}</head><body>{html_content}</body></html>"

            if self.preview and self.preview.winfo_exists():
                self.preview.set_html(full_html) # Pass the full HTML string
        except Exception as e:
            print(f"Error updating preview: {e}")
            if self.preview and self.preview.winfo_exists():
                self.preview.set_html(f"<pre>Error rendering Markdown:\n{e}</pre>")


    def setup_terminal(self):
        self.terminal_container = ttk.Frame(self.root)
        bg = self.config.get("term_bg", "#f0f0f0")
        fg = self.config.get("term_fg", "#333333")
        prompt_fg = "#666666"
        self.terminal_output = scrolledtext.ScrolledText(self.terminal_container, bg=bg, fg=fg, font=('Monospace', 10), wrap=tk.WORD, borderwidth=0, highlightthickness=0, insertbackground=fg)
        self.terminal_output.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 0))
        self.terminal_output.configure(state='disabled')
        self.input_frame = ttk.Frame(self.terminal_container)
        self.input_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(self.input_frame, text="$", font=('Monospace', 10), foreground=prompt_fg).pack(side=tk.LEFT, padx=(0, 5))
        self.terminal_input = ttk.Entry(self.input_frame, font=('Monospace', 10))
        self.terminal_input.pack(fill=tk.X, expand=True)
        # Don't pack container initially

    def setup_key_bindings(self):
        self.root.bind_all("<F12>", self.toggle_terminal)
        self.root.bind_all("<F11>", self.handle_f11)
        self.root.bind_all("<Control-c>", self.send_interrupt)
        self.root.bind_all("<Control-plus>", lambda e: self._change_font_size(1))
        self.root.bind_all("<Control-equal>", lambda e: self._change_font_size(1))
        self.root.bind_all("<Control-minus>", lambda e: self._change_font_size(-1))
        self.root.bind_all("<Control-0>", self._reset_font_size)

        if self.terminal_input and self.terminal_input.winfo_exists():
            self.terminal_input.bind("<Return>", self.execute_command)
            self.terminal_input.bind("<Up>", self.navigate_history_up)
            self.terminal_input.bind("<Down>", self.navigate_history_down)
            self.terminal_input.bind("<Tab>", self.handle_tab_complete)
            self.terminal_input.bind("<Control-d>", self.send_eot)

        if self.terminal_output and self.terminal_output.winfo_exists():
            self.terminal_output.bind("<Control-Shift-c>", self.copy_terminal_selection)
            self.terminal_output.bind("<Control-c>", self.send_interrupt)

    def _schedule_initial_shell_start(self):
        self.root.after(500, self.start_shell)
        print("[+] Scheduled initial shell startup.")

    def start_shell(self):
        if self.shell_process and self.shell_process.poll() is None: print("[-] Shell already appears to be running."); self._queue_message("[Shell already running]\n"); self.start_polling_output(); return
        print("[+] Attempting to start shell..."); self._cleanup_shell_resources_full()
        try:
            self.master_fd, self.slave_fd = pty.openpty()
            if sys.platform != "win32": flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL); fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            shell_cmd = self.config.get("shell_cmd", ["bash", "--norc"])
            def is_command_available(cmd_path):
                if not cmd_path: return False
                if os.path.isabs(cmd_path): return os.path.exists(cmd_path) and os.access(cmd_path, os.X_OK)
                penv = os.environ.get("PATH", os.defpath)
                for pdir in penv.split(os.pathsep):
                    fp = os.path.join(pdir, cmd_path)
                    if os.path.exists(fp) and os.access(fp, os.X_OK): return True
                    if sys.platform == "win32":
                         for ext in ['.exe', '.cmd', '.bat', '.com']:
                             if os.path.exists(fp + ext) and os.access(fp + ext, os.X_OK): return True
                return False
            if not shell_cmd or not shell_cmd[0] or not is_command_available(shell_cmd[0]):
                 cfg_cmd = shell_cmd[0] if shell_cmd and shell_cmd[0] else 'N/A'
                 print(f"Configured shell '{cfg_cmd}' not found/executable. Falling back to system default.")
                 if sys.platform != "win32": shell_cmd = ["sh"]
                 else: shell_cmd = ["cmd.exe"]
                 if not is_command_available(shell_cmd[0]): raise FileNotFoundError(f"Fallback '{shell_cmd[0]}' not found.")
            env = os.environ.copy(); env['TERM'] = 'xterm-256color'; print(f"[+] Starting shell: {' '.join(shell_cmd)}")
            self.running = True
            self.shell_process = subprocess.Popen(shell_cmd, stdin=self.slave_fd, stdout=self.slave_fd, stderr=self.slave_fd, preexec_fn=os.setsid if sys.platform != "win32" else None, close_fds=True, env=env)
            print(f"[+] Shell process started with PID: {self.shell_process.pid}")
            self.reader_thread = threading.Thread(target=self.read_shell_output, daemon=True); self.reader_thread.start(); print("[+] Shell reader thread started.")
            if self.terminal_output and self.terminal_output.winfo_exists(): self.root.after_idle(self.clear_terminal_display); self._queue_message("[Shell session started]\n")
            self.start_polling_output() # ensure polling starts
        except FileNotFoundError as e: msg = f"Shell command not found: {e}"; messagebox.showerror("Shell Error", msg); print(msg); self.running = False; self._queue_error_message(f"\n[Shell startup failed: {msg}]\n"); self._cleanup_shell_resources_light()
        except Exception as e: msg = f"Failed to start shell: {e}"; messagebox.showerror("Shell Error", msg); print(msg); self.running = False; self._queue_error_message(f"\n[Shell startup failed: {e}]\n"); self._cleanup_shell_resources_light()

    def read_shell_output(self):
        print("[+] Shell output reader thread running.")
        buffer = b""
        while self.running and self.master_fd is not None:
            try:
                data_bytes = b""
                if sys.platform != "win32":
                    r, _, _ = select.select([self.master_fd], [], [], 0.005)
                    if r: data_bytes = os.read(self.master_fd, 4096)
                else:
                    try: data_bytes = os.read(self.master_fd, 1024)
                    except BlockingIOError: pass
                    except OSError as e:
                         if e.errno == os.errno.EBADF: print("Reader thread got EBADF on Windows read.")
                         else: print(f"OSError during Windows read: {e}")
                         break
                if data_bytes:
                    buffer += data_bytes
                    try:
                        decoded_str = buffer.decode('utf-8', errors='replace'); buffer = b""
                        filtered_data, clear_detected = self.filter_ansi(decoded_str)
                        if clear_detected: self.root.after_idle(self.clear_terminal_display)
                        if filtered_data: self.output_queue.put(filtered_data)
                    except UnicodeDecodeError: pass
                    except Exception as e: print(f"Error decoding/filtering: {e}"); buffer = b""
                elif sys.platform != "win32" and r and not data_bytes: print("Shell process likely exited (EOF on read)."); break
                if not data_bytes and sys.platform != "win32": time.sleep(0.0005)
            except select.error as e:
                 if e.errno == select.EINTR: continue
                 print(f"Select error in reader: {e}")
                 break
            except OSError as e:
                if e.errno == os.errno.EIO: print("PTY master got EIO. Shell likely exited.")
                elif e.errno == os.errno.EBADF: print("Reader thread got EBADF.")
                else: print(f"OSError during read in reader: {e}")
                break
            except Exception as e: print(f"[!] Unexpected error in read_shell_output loop: {e}"); break
        print("[+] Shell output reader thread finished.")
        if self.terminal_output and self.terminal_output.winfo_exists(): self.output_queue.put("\n[Shell process ended]\n"); self.root.after_idle(self.start_polling_output)
        self._cleanup_shell_resources_light()

    def filter_ansi(self, data):
        clear_detected = False; ansi_escape_pattern = re.compile(r'\x1b\[[0-?]*[ -/]*[\@-~]'); osc_escape_pattern = re.compile(r'\x1b\].*?(\x07|\x1b\\)'); other_escape_pattern = re.compile(r'\x1b[<=>NM78HPZ=c()]')
        if '\x1b[2J' in data: clear_detected = True; data = data.replace('\x1b[H\x1b[2J', '').replace('\x1b[2J\x1b[H', '').replace('\x1b[H', '').replace('\x1b[2J', '')
        data = data.replace('\r', ''); data = ansi_escape_pattern.sub('', data); data = osc_escape_pattern.sub('', data); data = other_escape_pattern.sub('', data); data = data.replace('\x1b', '')
        allowed_chars = set(string.printable); allowed_chars.discard('\r'); final_filtered_data = ''.join(c for c in data if c in allowed_chars)
        return final_filtered_data, clear_detected

    def start_polling_output(self):
        if self._poll_id is None and self.running: self._poll_id = self.root.after(10, self.poll_shell_output)

    def stop_polling_output(self):
        if self._poll_id is not None: self.root.after_cancel(self._poll_id); self._poll_id = None

    def poll_shell_output(self):
        if not self.running: self.stop_polling_output(); return
        try:
            while True:
                message = self.output_queue.get_nowait()
                if self.terminal_output and self.terminal_output.winfo_exists() and self.terminal_container and self.terminal_container.winfo_ismapped():
                     self.terminal_output.configure(state='normal'); self.terminal_output.insert(tk.END, message); self.terminal_output.configure(state='disabled'); self.terminal_output.see(tk.END)
        except queue.Empty: pass
        except tk.TclError: print("[!] TclError during poll. Widget destroyed?"); self.stop_polling_output()
        except Exception as e: print(f"[!] Error processing shell output queue: {e}")
        if self.running: self._poll_id = self.root.after(10, self.poll_shell_output)
        else: self.stop_polling_output()

    def clear_terminal_display(self):
        if self.terminal_output and self.terminal_output.winfo_exists(): self.terminal_output.configure(state='normal'); self.terminal_output.delete("1.0", tk.END); self.terminal_output.configure(state='disabled')

    def execute_command(self, event=None):
        cmd = self.terminal_input.get()
        if cmd.strip():
            if not self.command_history or (self.command_history[-1].strip() != cmd.strip()): self.command_history.append(cmd)
        self.history_index = len(self.command_history); self.current_input_buffer = ""
        self.terminal_input.delete(0, tk.END); cmd_bytes = (cmd + "\n").encode('utf-8', errors='ignore')
        if self.master_fd is not None and self.shell_process and self.shell_process.poll() is None:
            try:
                if sys.platform != "win32": _, w, _ = select.select([], [self.master_fd], [], 0.05); os.write(self.master_fd, cmd_bytes) if w else self._queue_error_message("\n[Shell write busy]\n")
                else: os.write(self.master_fd, cmd_bytes)
            except OSError as e: print(f"[!] Error writing: {e}"); self._queue_error_message(f"\n[Write Error: {e}]\n")
            except Exception as e: print(f"[!] Unexpected write error: {e}"); self._queue_error_message(f"\n[Write Error: {e}]\n")
        else: self._queue_error_message("\nShell not running]\n")
        return "break"

    def navigate_history_up(self, event=None):
        if not self.command_history: return "break"
        if self.history_index == len(self.command_history): self.current_input_buffer = self.terminal_input.get()
        target_index = -1
        if self.history_index > 0: target_index = self.history_index - 1
        elif self.history_index == -1 and self.command_history: target_index = len(self.command_history) - 1
        if target_index != -1: self.history_index = target_index; self.terminal_input.delete(0, tk.END); self.terminal_input.insert(0, self.command_history[self.history_index])
        return "break"

    def navigate_history_down(self, event=None):
        if not self.command_history or self.history_index == -1: return "break"
        target_index = -1; target_text = ""
        if self.history_index < len(self.command_history) - 1: target_index = self.history_index + 1; target_text = self.command_history[target_index]
        elif self.history_index == len(self.command_history) - 1: target_index = len(self.command_history); target_text = self.current_input_buffer; self.current_input_buffer = ""
        if target_index != -1: self.history_index = target_index; self.terminal_input.delete(0, tk.END); self.terminal_input.insert(0, target_text)
        return "break"

    def handle_tab_complete(self, event=None):
        if self.master_fd is not None and self.shell_process and self.shell_process.poll() is None:
            try: os.write(self.master_fd, b'\t') # Send a literal tab character. upgrading would require extensive rework.
            except OSError as e: print(f"[!] Error writing Tab: {e}"); self._queue_error_message(f"\n[Tab Error: {e}]\n")
            except Exception as e: print(f"[!] Unexpected Tab error: {e}"); self._queue_error_message(f"\n[Tab Error: {e}]\n")
        return "break"

    def send_eot(self, event=None): # Ctrl+D handler
        if self.master_fd is not None and self.shell_process and self.shell_process.poll() is None:
            try: os.write(self.master_fd, b'\x04')
            except OSError as e: print(f"[!] OSError writing Ctrl+D byte: {e}"); self._queue_error_message(f"\n[Ctrl+D Error: {e}]\n")
            except Exception as e: print(f"[!] Unexpected error writing Ctrl+D byte: {e}"); self._queue_error_message(f"\n[Ctrl+D Error: {e}]\n")
        else: print("[!] Ctrl+D pressed but shell is not running or PTY unavailable.")
        return "break"

    def send_interrupt(self, event=None): # Ctrl+C handler
        if self.master_fd is not None and self.shell_process and self.shell_process.poll() is None:
            try: os.write(self.master_fd, b'\x03'); self.root.after_idle(self._display_interrupt_feedback)
            except OSError as e: print(f"[!] OSError writing Ctrl+C byte to shell: {e}"); self._queue_error_message(f"\n[Interrupt Error: {e}]\n")
            except Exception as e: print(f"[!] Unexpected error writing Ctrl+C byte: {e}"); self._queue_error_message(f"\n[Interrupt Error: {e}]\n")
        else: print("[!] Ctrl+C pressed but shell is not running or PTY unavailable.")
        return "break"

    def _queue_error_message(self, message):
        if self.terminal_output and self.terminal_output.winfo_exists(): self.output_queue.put(message); self.root.after_idle(self.start_polling_output)
        else: print(f"[-] Terminal not ready, error message: {message}")

    def _queue_message(self, message):
        if self.terminal_output and self.terminal_output.winfo_exists(): self.output_queue.put(message); self.root.after_idle(self.start_polling_output)

    def _display_interrupt_feedback(self):
        if self.terminal_output and self.terminal_output.winfo_exists():
            try: self.terminal_output.configure(state='normal'); self.terminal_output.insert(tk.END, "^C\n"); self.terminal_output.configure(state='disabled'); self.terminal_output.see(tk.END)
            except tk.TclError: pass

    def copy_terminal_selection(self, event=None):
        if self.terminal_output and self.terminal_output.winfo_exists():
            try:
                selected_text = self.terminal_output.get(tk.SEL_FIRST, tk.SEL_LAST)
                if selected_text: self.root.clipboard_clear(); self.root.clipboard_append(selected_text); print("[+] Terminal selection copied.")
                return "break"
            except tk.TclError: pass
            except Exception as e: print(f"[!] Error copying terminal selection: {e}"); return "break"
        return None

    def handle_f11(self, event=None):
        current_time = int(time.time() * 1000)
        if current_time - self._last_f11_time < self._f11_timeout_ms:
            self._f11_press_count += 1
            if self._f11_press_count == 2: print("[+] Double F11 detected. Restarting shell..."); self._f11_press_count = 0; self.root.after_idle(self.restart_shell)
        else: self._f11_press_count = 1
        self._last_f11_time = current_time
        return "break"

    def restart_shell(self):
        print("[+] Restarting shell...")
        self._cleanup_shell_resources_full()
        self.root.after(100, self.start_shell)


    def toggle_terminal(self, event=None):
        """Toggles the visibility of the terminal container."""
        if not (self.terminal_container and self.terminal_input and self.terminal_output): print("Error: Terminal UI elements not initialized for toggle."); return

        if self.terminal_container.winfo_ismapped():
            self.terminal_container.pack_forget()
            if self.notebook and not self.notebook.winfo_ismapped(): self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            if self.text_editor and self.text_editor.winfo_exists(): self.text_editor.focus()
            self.stop_polling_output()
        else:
            if self.notebook and self.notebook.winfo_ismapped(): self.notebook.pack_forget()
            self.terminal_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.terminal_input.focus()
            if not self.shell_process or self.shell_process.poll() is not None: self.start_shell()
            self.start_polling_output()

    def new_note(self, confirm_discard=True):
        if confirm_discard and self.is_dirty:
            if not messagebox.askyesno("Unsaved Changes", "Discard unsaved changes and create new?"): return
        self.text_editor.delete("1.0", tk.END); self.current_note = None; self.notes_list.selection_clear(0, tk.END)
        self.is_dirty = False; self._update_save_status(); self.update_live_preview(); self.text_editor.edit_reset(); self.text_editor.edit_modified(False)

    def save_note(self):
        if not self.current_note: self.save_note_as(); return
        content = self.text_editor.get("1.0", tk.END).strip()
        path = os.path.join(self.notes_dir, self.current_note)
        try:
            os.makedirs(self.notes_dir, exist_ok=True);
            with open(path, "w", encoding='utf-8') as f: f.write(content + "\n")
            print(f"[+] Note saved as {self.current_note}")
            self.is_dirty = False; self._update_save_status(); self.text_editor.edit_modified(False)
        except Exception as e: messagebox.showerror("Save Error", f"Failed to save note:\n{e}")

    def save_note_as(self):
        content = self.text_editor.get("1.0", tk.END).strip()
        initial_filename = self.current_note if self.current_note else "Untitled.md"
        save_path = filedialog.asksaveasfilename(initialfile=initial_filename, defaultextension=".md", filetypes=[("Markdown Files", "*.md"), ("All Files", "*.*")], initialdir=self.notes_dir)
        if not save_path: return
        try:
            save_dir = os.path.dirname(save_path); os.makedirs(save_dir, exist_ok=True)
            with open(save_path, "w", encoding='utf-8') as f: f.write(content + "\n")
            print(f"[+] Note saved as {save_path}")
            abs_save_path = os.path.abspath(save_path); abs_notes_dir = os.path.abspath(self.notes_dir)
            if abs_save_path.startswith(abs_notes_dir):
                 filename = os.path.basename(save_path); self.load_notes()
                 try: idx = list(self.notes_list.get(0, tk.END)).index(filename); self.notes_list.selection_clear(0, tk.END); self.notes_list.selection_set(idx); self.notes_list.activate(idx)
                 except ValueError: pass
                 self.current_note = filename; self.is_dirty = False; self._update_save_status(); self.text_editor.edit_modified(False)
            else: messagebox.showinfo("Save As", f"Note successfully saved to {save_path}")
        except Exception as e: messagebox.showerror("Save As Error", f"Failed to save note as {os.path.basename(save_path) if save_path else 'file'}:\n{e}")

    def load_notes(self):
        """Loads the list of notes from the notes directory and updates internal list."""
        self._all_notes = []
        os.makedirs(self.notes_dir, exist_ok=True)
        try:
            note_files = sorted([fname for fname in os.listdir(self.notes_dir) if fname.endswith(".md") and os.path.isfile(os.path.join(self.notes_dir, fname))])
            self._all_notes = note_files
            self.filter_notes()
            self._update_delete_button_state()
        except Exception as e: messagebox.showerror("Load Error", f"Failed to load notes list:\n{e}")

    def load_note_content(self, event=None):
        selection = self.notes_list.curselection()
        if not selection:
            if self.current_note is None or self.current_note not in self._all_notes: self.new_note(confirm_discard=False)
            self._update_delete_button_state()
            return
        fname = self.notes_list.get(selection[0]); path = os.path.join(self.notes_dir, fname)
        is_loading_different_note = (self.current_note is None or self.current_note != fname)
        if is_loading_different_note and self.is_dirty:
            if not messagebox.askyesno("Unsaved Changes", "Discard unsaved changes and load selected?"):
                if self.current_note and self.current_note in self._all_notes:
                     try:
                          filtered_list_items = list(self.notes_list.get(0, tk.END))
                          if self.current_note in filtered_list_items: idx = filtered_list_items.index(self.current_note); self.notes_list.selection_clear(0, tk.END); self.notes_list.selection_set(idx); self.notes_list.activate(idx)
                          else: self.notes_list.selection_clear(0, tk.END)
                     except ValueError: self.notes_list.selection_clear(0, tk.END)
                else: self.notes_list.selection_clear(0, tk.END)
                return
        try:
            with open(path, "r", encoding='utf-8') as f: content = f.read()
            self.text_editor.delete("1.0", tk.END); self.text_editor.insert("1.0", content)
            self.current_note = fname; self.is_dirty = False; self._update_save_status(); self.update_live_preview(); self.text_editor.edit_reset(); self.text_editor.edit_modified(False)
        except Exception as e: messagebox.showerror("Load Error", f"Failed to load note content:\n{e}"); self.current_note = None; self.text_editor.delete("1.0", tk.END); self.is_dirty = False; self._update_save_status(); self.update_live_preview(); self.text_editor.edit_modified(False)
        self._update_delete_button_state()

    def _cleanup_shell_resources_light(self):
        if self.master_fd is not None:
            try: os.close(self.master_fd)
            except OSError: pass
            except Exception as e: print(f"[!] Unexpected error closing master_fd (light cleanup): {e}")
            self.master_fd = None
        if self.slave_fd is not None:
            try: os.close(self.slave_fd)
            except OSError: pass
            except Exception as e: print(f"[!] Unexpected error closing slave_fd (light cleanup): {e}")
            self.slave_fd = None

    def _cleanup_shell_resources_full(self):
        print("[+] Performing full shell resource cleanup...")
        self.running = False; self.stop_polling_output()
        if self.reader_thread and self.reader_thread.is_alive():
            print("[+] Waiting for reader thread...");
            try:
                self.reader_thread.join(timeout=0.5)
                if self.reader_thread.is_alive():
                    print("[-] Reader thread did not join, attempting to close master_fd...")
                    if self.master_fd is not None:
                        try: os.close(self.master_fd)
                        except OSError as e: print(f"[!] Error closing master_fd during join attempt: {e}")
                    self.reader_thread.join(timeout=1.0)
                    if self.reader_thread.is_alive(): print("[-] Reader thread still alive after closing master_fd.")
                else: print("[+] Reader thread joined successfully.")
            except RuntimeError as e: print(f"[!] RuntimeError during thread join: {e}")
            except Exception as e: print(f"[!] Unexpected error during thread join: {e}")
            finally:
                if self.reader_thread and not self.reader_thread.is_alive(): del self.reader_thread; self.reader_thread = None
                elif self.reader_thread: print("[-] Warning: Reader thread reference not cleared.")
        if self.shell_process and self.shell_process.poll() is None:
            print(f"[+] Terminating shell process group (PID: {self.shell_process.pid})...")
            try:
                if sys.platform != "win32": os.killpg(os.getpgid(self.shell_process.pid), signal.SIGTERM)
                else: self.shell_process.terminate()
                self.shell_process.wait(timeout=0.5)
            except (ProcessLookupError, PermissionError, OSError): pass
            except subprocess.TimeoutExpired:
                print("[-] Shell process unresponsive, sending SIGKILL.")
                try:
                    if sys.platform != "win32": os.killpg(os.getpgid(self.shell_process.pid), signal.SIGKILL)
                    else: self.shell_process.kill()
                    self.shell_process.wait(timeout=0.5)
                except Exception as kill_e: print(f"[!] Error sending SIGKILL: {kill_e}")
            except Exception as e: print(f"[!] Error terminating shell process: {e}")
            finally: self.shell_process = None
        if self.master_fd is not None:
             try: os.close(self.master_fd)
             except OSError: pass
             self.master_fd = None
        if self.slave_fd is not None:
             try: os.close(self.slave_fd)
             except OSError: pass
             self.slave_fd = None


    def on_close(self):
        print("[+] Close requested...")
        if self.is_dirty:
             if not messagebox.askyesno("Unsaved Changes", "Quit without saving?"): return
        self._cleanup_shell_resources_full(); self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style(root)
    app = NoteShellApp(root)
    root.mainloop()
