# 🌐 Sbrows — a PyQt6 Web Browser

**Sbrows** is a lightweight, fully functional web browser built with Python, [PyQt6](https://www.riverbankcomputing.com/software/pyqt/intro) and QtWebEngine — tabbed browsing, private tabs, bookmarks, a built-in ad blocker, downloads, find-in-page, PDF export and session restore, all in a single ~1,100-line file with no external icon assets.

---

## 🚀 Features

- **Tabbed browsing** — movable, closable tabs with favicons, loading indicators and tooltips
- **Private tabs** (Ctrl+Shift+P) — off-the-record profile with a distinct purple theme so you always know which mode you're in; nothing is saved to history or cookies
- **Built-in ad blocker** — blocks 25+ known ad/tracker domains plus keyword-matched request paths, with a live "ads blocked" counter
- **Bookmarks** — star the current page (Ctrl+D), manage them in the sidebar, open with a double-click
- **History** — timestamped entries with page titles, URL autocomplete, delete/clear from the history dialog
- **Session restore** — your open tabs are saved on exit and reloaded on the next launch
- **Downloads** — save dialog, progress bar and completion notification
- **Find in page** (Ctrl+F) — next/previous navigation, Esc to close
- **Save page as PDF** (Ctrl+P)
- **Zoom controls** (Ctrl +/−/0) and per-page **Force Dark Mode** toggle
- **Media permission handling** — prompts for mic/camera access, with automatic support for both the legacy and Qt ≥ 6.8 permission APIs
- **HTTPS indicator** in the URL bar, link-hover status bar, dark themed UI

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+T` | New tab |
| `Ctrl+Shift+P` | New private tab |
| `Ctrl+W` | Close tab |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous tab |
| `Ctrl+L` | Focus URL bar |
| `Ctrl+D` | Toggle bookmark |
| `Ctrl+F` | Find in page |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+H` | Show history |
| `Ctrl+P` | Save page as PDF |
| `Ctrl+R` / `F5` | Reload |
| `Alt+Left` / `Alt+Right` | Back / forward |
| `Ctrl +/−/0` | Zoom in / out / reset |
| `F11` | Toggle fullscreen |

## 🛠️ Setup

Requires Python 3.9+ (3.10+ recommended).

```bash
git clone https://github.com/shivang1809/sbrows.git
cd sbrows
pip install -r requirements.txt
python browser.py
```

### Requirements

- [PyQt6](https://pypi.org/project/PyQt6/)
- [PyQt6-WebEngine](https://pypi.org/project/PyQt6-WebEngine/)

## 📁 Project Structure

```
sbrows/
├── browser.py       # the entire browser (UI, ad blocker, profiles, downloads)
├── requirements.txt
├── history.json     # created at runtime — browsing history
├── bookmarks.json   # created at runtime — bookmarks
└── session.json     # created at runtime — open tabs on exit
```

State files are written next to the script and are git-ignored.

## 📸 Screenshots

> _Coming soon_

## 🧭 Roadmap Ideas

- [ ] Custom context menu (open image/link in new tab, copy link)
- [ ] Built-in download manager page with history
- [ ] Search engine selector (Google / DuckDuckGo / Bing)
- [ ] Reader mode
- [ ] Pinned tabs

## 📄 License

MIT — feel free to fork and build on it.
