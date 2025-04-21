# NotesShell

## I. Introduction

**NotesShell** is a lightweight Markdown note-taking application with a discreet, integrated terminal/system shell. It’s built for security professionals, penetration testers, and researchers who need to blend into their environment—whether working in public or operating under scrutiny.

At first glance, NotesShell behaves like any typical Markdown editor. However, beneath the surface lies a fully functional shell interface, accessible via a keyboard shortcut and designed to be inconspicuous and invisible to the casual observer.

> **Disclaimer:** Use NotesShell responsibly and legally. Only interact with systems and networks for which you have explicit permission. The author and contributors assume no liability for misuse or unauthorized activity. The code contained herein is explicitly made for researchers and authorised professionals.

## II. Features

- **Dual Interface:** A clean Markdown editor with a live preview pane and sidebar for managing notes.
- **Stealth Terminal:** Hidden terminal view (toggle with `F12`), styled with a light theme to reduce visibility and mimic non-technical applications. Has multiple themes, each worse than the last.
- **Integrated Shell:** Launches a system shell (e.g., Bash, Zsh, or Cmd.exe) within the app, with interactive input/output.
- **Persistent Notes:** Markdown files are stored locally at `~/.noteshell/notes`.
- **Live Preview:** Real-time rendering of Markdown as you type.
- **Note Management:** Create, load, save (including "Save As..."), and delete notes from the built-in interface.
- **Search & Filter:** Filter notes by filename using a search box above the sidebar.
- **Configurable Shell:** Shell command and arguments are configurable via `~/.noteshell/config.json`.
- **Sample Notes:** Comes with example notes (e.g., math, physics, chemistry) to help the interface look convincingly academic under casual inspection. These are stored in notes/ in the repository. Copy them to your NotesShell install folder.
- **Usable as a Notes App:** While designed with stealth in mind, NotesShell functions fully as a standalone Markdown notepad—ideal for real-time documentation or note-taking during engagements.

## III. Implementation Overview

- **Language & Libraries:** Developed in Python 3.x using `tkinter` for the UI, `tkhtmlview` for HTML rendering, and `markdown2` for Markdown parsing.
- **Terminal Integration:** Uses a pseudo-terminal (PTY) for shell interaction, connecting the shell process to a background thread that streams output to the UI.
- **I/O Handling:** Asynchronous output is queued and displayed in a `ScrolledText` widget. Commands are written to the shell via `os.write`.
- **Control Support:** Simulates terminal control characters (e.g., `Ctrl+C`, `Ctrl+D`) and interprets simple output like `clear`.
- **Cross-Platform Support:** Designed primarily for Unix-like environments (Linux/macOS); Windows support is present but more limited due to PTY differences.

## IV. Usage
![image](https://github.com/user-attachments/assets/f650241b-6dc9-4194-a939-83e52225e283)
![image](https://github.com/user-attachments/assets/34cc634b-b74f-41f6-b5dc-132c0559dfbe)

### Requirements

- Python 3.x
- [`tkinter`](https://docs.python.org/3/library/tkinter.html) (usually included with Python)
- [`tkhtmlview`](https://pypi.org/project/tkhtmlview/)
- [`markdown2`](https://pypi.org/project/markdown2/)

### Installation

```bash
pip install tkhtmlview markdown2
```

### Running

```bash
python3 noteshell.py
```

### Keyboard Shortcuts

- `F12`: Toggle between Markdown and terminal view
- `Enter`: Execute terminal command
- `Up` / `Down`: Navigate shell command history
- `Ctrl+C`: Send interrupt signal
- `Ctrl+D`: Send EOF (End of Transmission)
- `Ctrl+Shift+C`: Copy selected terminal output
- `F11` (double-press): Restart shell
- `Tab`: Insert tab character (note: read Limitations section)

## V. Notes Management

- Notes are saved as `.md` files in `~/.notesshell/notes`.
- The filename is auto-generated from the first non-empty line of the note.
- **New:** Clears the editor to start a new note.
- **Save / Save As...:** Saves to file, prompting for filename if necessary.
- **Delete Selected:** Permanently deletes the selected note after confirmation.
- Unsaved changes trigger a warning if switching notes or exiting.
- The window title reflects save status (an asterisk `*` indicates unsaved changes).

## VI. Limitations & Future Work

- **Terminal Emulation:** Lacks support for complex terminal features like ANSI color, cursor movement, or full-screen apps (e.g., `htop`, `vim`).
- **Windows Compatibility**: Basic PTY‑based shell functionality works on Windows, but full feature parity and performance are focused on Unix‑like systems (Linux/macOS). Windows support is currently a proof‑of‑concept -- advanced users are encouraged to run NotesShell on Linux for the most polished experience.
- **Tab Completion:** Shell completions are visible in the output but not supported in the input line.
- **Visual Stealth:** The default light theme is intended as a deterrent, but it does not ensure complete privacy.
- **Command History:** The app’s command history is session-bound and not saved between runs. This is deliberate. (Shell-level history may persist, depending on shell configuration.)
