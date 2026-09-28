#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sbrows — a small but polished PyQt6 web browser.

Run:
    pip install PyQt6 PyQt6-WebEngine
    python sbrows.py

State files (history.json, bookmarks.json, session.json) are written next to
this script. No external icon/image assets are required — everything falls back
to Unicode glyphs, so it runs out of the box.
"""

import os
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-media-stream")

import sys
import re
import json
from datetime import datetime

from PyQt6.QtCore import QUrl, Qt, QStringListModel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineDownloadRequest,
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestInfo,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QLineEdit, QPushButton, QToolButton, QTabWidget, QCompleter,
    QDockWidget, QGroupBox, QListWidget, QListWidgetItem, QDialog,
    QMessageBox, QProgressDialog, QFileDialog, QStatusBar,
    QSizePolicy,
)
from PyQt6.QtGui import (
    QAction, QIcon, QKeySequence, QShortcut, QFont, QPixmap, QPainter,
    QColor,
)

try:  # optional, Qt >= 6.8 permission API
    from PyQt6.QtWebEngineCore import QWebEnginePermission
except Exception:
    QWebEnginePermission = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[warn] could not save {path}: {exc}")


def text_icon(char, color="#cdd0d5", size=22):
    """Build an QIcon by painting a single Unicode glyph onto a pixmap."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont()
    f.setPointSize(int(size * 0.62))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, char)
    p.end()
    return QIcon(pm)


def fmt_url(u):
    return QUrl(u).toString() if isinstance(u, str) else u.toString()


# --------------------------------------------------------------------------- #
#  Ad blocker
# --------------------------------------------------------------------------- #
AD_DOMAINS = [
    "doubleclick.net", "googleadservices.com", "ads.youtube.com",
    "pagead2.googlesyndication.com", "googlesyndication.com",
    "securepubads.g.doubleclick.net", "ytads.youtube.com",
    "adnxs.com", "trackcmp.net", "adroll.com", "adservice.google.com",
    "acdn.tsyndicate.com", "static.wolf-327b.com", "cdn.wolf-327b.com",
    "scorecardresearch.com", "googletagmanager.com", "googletagservices.com",
    "criteo.com", "criteo.net", "pubmatic.com", "rubiconproject.com",
    "taboola.com", "outbrain.com", "adsrvr.org", "adform.net",
]

_AD_REGEX = re.compile(
    r"(?:^|[./?&=_\-])(?:ad|ads|adv|advert|advertis(?:e|ing|ement)|"
    r"track(?:er|ing)?|analytics|telemetry|banner|beacon|pixel)"
    r"(?:[./?&=_\-]|$)",
    re.IGNORECASE,
)


class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Blocks known ad/tracker domains and request paths matching ad keywords."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner          # MainWindow, for the live counter
        self.blocked = 0

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString()
        if not url:
            return
        if any(d in url for d in AD_DOMAINS) or _AD_REGEX.search(url):
            info.block(True)
            self.blocked += 1
            if self.owner is not None:
                try:
                    self.owner.on_ad_blocked()
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
#  Web page
# --------------------------------------------------------------------------- #
class CustomWebEnginePage(QWebEnginePage):
    """A page that asks the user for mic/camera permission, supports popups,
    and offers Save-as-PDF."""

    def __init__(self, profile, parent, main_window=None, private=False):
        super().__init__(profile, parent)
        self.main_window = main_window
        self.private = private
        self._forced_dark = False
        self._pending_pdf = None

        try:
            self.featurePermissionRequested.connect(self._on_feature_permission)
        except Exception:
            pass
        # Qt >= 6.8 permission API (optional)
        if hasattr(self, "permissionRequested"):
            try:
                self.permissionRequested.connect(self._on_permission)
            except Exception:
                pass
        try:
            self.pdfGenerated.connect(self._on_pdf_generated)
        except Exception:
            pass

    # ----- permissions (legacy) ----- #
    def _on_feature_permission(self, url, feature):
        want = (feature in (
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture,
        ))
        grant = want and self._ask(url, feature)
        self.setFeaturePermission(
            url, feature,
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if grant else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
        )

    # ----- permissions (Qt >= 6.8) ----- #
    def _on_permission(self, permission):
        ask = False
        t = None
        try:
            t = permission.permissionType()
            if QWebEnginePermission is not None and t in (
                QWebEnginePermission.PermissionType.MediaAudioCapture,
                QWebEnginePermission.PermissionType.MediaVideoCapture,
                QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
            ):
                ask = True
        except Exception:
            ask = True
        if ask and self._ask(None, t):
            permission.grant()
        else:
            permission.deny()

    def _ask(self, url, feature):
        text = "This website wants to access your camera/microphone. Allow it?"
        if feature == QWebEnginePage.Feature.MediaAudioCapture:
            text = "This website wants to use your microphone. Allow it?"
        elif feature == QWebEnginePage.Feature.MediaVideoCapture:
            text = "This website wants to use your camera. Allow it?"
        elif feature == QWebEnginePage.Feature.MediaAudioVideoCapture:
            text = "This website wants to use your camera and microphone. Allow it?"
        box = QMessageBox(self.main_window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Permission Request")
        box.setText(text)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    # ----- popups ----- #
    def createWindow(self, _type):
        if self.main_window is None:
            return None
        return self.main_window.create_new_tab_from_page(
            profile=self.profile(), private=self.private)

    # ----- PDF ----- #
    def save_pdf(self, path):
        self._pending_pdf = path
        try:
            self.printToPdf(path)
        except Exception as exc:
            QMessageBox.warning(self.main_window, "PDF", f"Could not print: {exc}")

    def _on_pdf_generated(self, file_path):
        if self._pending_pdf:
            QMessageBox.information(
                self.main_window, "PDF Saved",
                f"Page saved as PDF:\n{file_path}")
            self._pending_pdf = None


# --------------------------------------------------------------------------- #
#  Browser tab
# --------------------------------------------------------------------------- #
class BrowserTab(QWidget):
    def __init__(self, main_window, profile=None, private=False, url=None):
        super().__init__()
        self.main_window = main_window
        self.private = private
        self.profile = profile or main_window.profile

        self.browser = QWebEngineView()
        self.page = CustomWebEnginePage(
            self.profile, self.browser, main_window=main_window, private=private)
        self.browser.setPage(self.page)
        if private:                       # dark canvas behind pages while loading
            self.page.setBackgroundColor(QColor("#17131f"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.browser)

        if url is not None:
            self.browser.setUrl(url)


# --------------------------------------------------------------------------- #
#  Find bar
# --------------------------------------------------------------------------- #
class FindBar(QWidget):
    def __init__(self, on_find, on_close):
        super().__init__()
        self.on_find = on_find
        self.on_close = on_close

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Find in page…")
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._find)
        self.input.returnPressed.connect(self._find_next)
        lay.addWidget(self.input, 1)

        prev = QPushButton("▲")
        prev.setFixedWidth(34)
        prev.setToolTip("Previous (Shift+Enter)")
        prev.clicked.connect(lambda: self._find(backward=True))
        nxt = QPushButton("▼")
        nxt.setFixedWidth(34)
        nxt.setToolTip("Next (Enter)")
        nxt.clicked.connect(self._find_next)
        close = QPushButton("✕")
        close.setFixedWidth(34)
        close.clicked.connect(self.hide)
        for b in (prev, nxt, close):
            lay.addWidget(b)

        QShortcut(QKeySequence("Shift+Return"), self, activated=lambda: self._find(backward=True))
        QShortcut(QKeySequence("Esc"), self, activated=self.hide)

        self.hide()

    def _find(self, backward=False):
        self.on_find(self.input.text(), backward)

    def _find_next(self):
        self._find(backward=False)

    def show(self):
        super().show()
        self.input.setFocus()
        self.input.selectAll()


# --------------------------------------------------------------------------- #
#  Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    MAX_HISTORY = 200

    def __init__(self, restore_session=True):
        super().__init__()
        self.setWindowTitle("Sbrows")
        self.resize(1280, 800)   # sane default; main() calls showMaximized()
        self.setWindowIcon(text_icon("✦", "#5865f2", 32))
        self.setStyleSheet(STYLE)
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)

        self.child_windows = []
        self._initializing = True

        # ---- profiles ---- #
        self.profile = QWebEngineProfile("SbrowsProfile", self)   # persistent
        self.private_profile = QWebEngineProfile(self)            # off-the-record
        self.adblock = AdBlocker(self)
        self.adblock_private = AdBlocker(self)
        self.profile.setUrlRequestInterceptor(self.adblock)
        self.private_profile.setUrlRequestInterceptor(self.adblock_private)
        for prof in (self.profile, self.private_profile):
            try:
                prof.downloadRequested.connect(self.handle_download)
            except Exception:
                pass
            try:
                prof.setPersistentCookiesPolicy(
                    QWebEngineProfile.PersistentCookiesPolicy
                    .AllowPersistentCookies if prof is self.profile
                    else QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            except Exception:
                pass

        # ---- data ---- #
        # migrate old-format history (plain URL strings) to dicts
        self.history = [e if isinstance(e, dict) else {"url": e, "title": e, "time": ""}
                        for e in read_json(os.path.join(BASE_DIR, "history.json"), [])
                        if e]
        self.bookmarks = [e if isinstance(e, dict) else {"url": e, "title": e}
                          for e in read_json(os.path.join(BASE_DIR, "bookmarks.json"), [])
                          if e]

        # ---- UI ---- #
        self.completer_model = QStringListModel()
        self.completer = QCompleter()
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setModel(self.completer_model)
        self._refresh_completer()

        self._init_tabs_widget()
        self._init_ui()
        self._init_shortcuts()
        self._refresh_adblock_label()

        restored = restore_session and self._restore_session()
        if not restored:
            self.add_new_tab(QUrl("https://www.google.com"), "New Tab")

        self._initializing = False

    # ------------------------------------------------------------------ #
    #  Layout
    # ------------------------------------------------------------------ #
    def _init_tabs_widget(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setTabShape(QTabWidget.TabShape.Rounded)
        self.tabs.tabCloseRequested.connect(self.close_current_tab)
        self.tabs.currentChanged.connect(lambda i: self.update_url_bar())
        self.tabs.setStyleSheet(TAB_STYLE)

        new_tab_btn = QToolButton()
        new_tab_btn.setText("＋")
        new_tab_btn.setStyleSheet("font-size: 20px; font-weight: bold;")
        new_tab_btn.setToolTip("New Tab  (Ctrl+T)")
        new_tab_btn.clicked.connect(
            lambda: self.add_new_tab(QUrl("https://www.google.com"), "New Tab"))
        self.tabs.setCornerWidget(new_tab_btn, Qt.Corner.TopRightCorner)

        self.find_bar = FindBar(on_find=self._do_find, on_close=self._clear_find)

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.tabs)
        v.addWidget(self.find_bar)
        self.setCentralWidget(container)

    def _init_ui(self):
        navbar = QToolBar()
        navbar.setMovable(True)
        navbar.setStyleSheet("font-size: 18px; spacing: 4px;")
        self.addToolBar(navbar)

        self.back_btn = QAction("🡸", self)
        self.back_btn.setToolTip("Back (Alt+Left)")
        self.back_btn.setShortcut("Alt+Left")
        self.back_btn.triggered.connect(lambda: self._browser().back())
        navbar.addAction(self.back_btn)

        self.fwd_btn = QAction("🡺", self)
        self.fwd_btn.setToolTip("Forward (Alt+Right)")
        self.fwd_btn.setShortcut("Alt+Right")
        self.fwd_btn.triggered.connect(lambda: self._browser().forward())
        navbar.addAction(self.fwd_btn)

        self.reload_btn = QAction("⟳", self)
        self.reload_btn.setToolTip("Reload (F5 / Ctrl+R)")
        self.reload_btn.setShortcuts(["Ctrl+R", "F5"])
        self.reload_btn.triggered.connect(lambda: self._browser().reload())
        navbar.addAction(self.reload_btn)

        home_btn = QAction("🏠", self)
        home_btn.setToolTip("Go Home")
        home_btn.triggered.connect(
            lambda: self._browser().setUrl(QUrl("https://www.google.com")))
        navbar.addAction(home_btn)

        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Search Google or type a URL")
        self.url_bar.setClearButtonEnabled(True)
        self.url_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.url_bar.setCompleter(self.completer)
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        self.url_bar.setStyleSheet(URL_STYLE)
        self.url_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        navbar.addWidget(self.url_bar)

        self.star_action = self.url_bar.addAction(
            text_icon("☆", "#cdd0d5"), QLineEdit.ActionPosition.TrailingPosition)
        self.star_action.setToolTip("Bookmark this page (Ctrl+D)")
        self.star_action.triggered.connect(self.toggle_bookmark)

        # purple "PRIVATE" badge shown only while a private tab is active
        self.private_badge = QLabel(" PRIVATE ")
        self.private_badge.setStyleSheet(
            "background: #7c3aed; color: #ffffff; border-radius: 6px;"
            "padding: 3px 10px; font-weight: bold; font-size: 11px;"
            "letter-spacing: 1px;")
        self.private_badge.hide()
        navbar.addWidget(self.private_badge)

        # right-side actions
        private_btn = QAction("🕶", self)
        private_btn.setToolTip("New Private Tab (Ctrl+Shift+P)")
        private_btn.triggered.connect(
            lambda: self.add_new_tab(QUrl("https://www.google.com"), "Private",
                                     private=True))
        navbar.addAction(private_btn)

        pdf_btn = QAction("🖨", self)
        pdf_btn.setToolTip("Save page as PDF (Ctrl+P)")
        pdf_btn.triggered.connect(self.save_pdf)
        navbar.addAction(pdf_btn)

        sidebar_btn = QAction("☰", self)
        sidebar_btn.setToolTip("Sidebar (Ctrl+B)")
        sidebar_btn.triggered.connect(self.toggle_sidebar)
        navbar.addAction(sidebar_btn)

        self._create_sidebar()

    def _init_shortcuts(self):
        binds = {
            "Ctrl+T": lambda: self.add_new_tab(QUrl("https://www.google.com"), "New Tab"),
            "Ctrl+Shift+P": lambda: self.add_new_tab(
                QUrl("https://www.google.com"), "Private", private=True),
            "Ctrl+W": lambda: self.close_current_tab(self.tabs.currentIndex()),
            "Ctrl+L": lambda: self.url_bar.setFocus(),
            "Ctrl+Tab": lambda: self._cycle_tab(1),
            "Ctrl+Shift+Tab": lambda: self._cycle_tab(-1),
            "Ctrl+D": self.toggle_bookmark,
            "Ctrl+F": self.find_bar.show,
            "Ctrl+B": self.toggle_sidebar,
            "Ctrl+H": self.show_history,
            "F11": self.toggle_fullscreen,
            "Ctrl++": self.zoom_in,
            "Ctrl+=": self.zoom_in,
            "Ctrl+-": self.zoom_out,
            "Ctrl+0": self.zoom_reset,
        }
        for key, fn in binds.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(fn)

    def _create_sidebar(self):
        self.sidebar = QDockWidget("Sidebar", self)
        self.sidebar.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.sidebar.setFixedWidth(240)

        root = QWidget()
        v = QVBoxLayout(root)

        # Tabs
        tabs_group = QGroupBox("Tabs")
        tl = QVBoxLayout()
        for label, fn in (
            ("New Tab", lambda: self.add_new_tab(
                QUrl("https://www.google.com"), "New Tab")),
            ("New Private Tab", lambda: self.add_new_tab(
                QUrl("https://www.google.com"), "Private", private=True)),
            ("New Window", self.open_new_window),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            tl.addWidget(b)
        tabs_group.setLayout(tl)
        v.addWidget(tabs_group)

        # Bookmarks
        bk_group = QGroupBox("Bookmarks")
        bkl = QVBoxLayout()
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemDoubleClicked.connect(
            lambda it: self.add_new_tab(QUrl(it.data(Qt.ItemDataRole.UserRole)
                                             or it.text()), "Tab"))
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self._remove_bookmark_selected)
        bkl.addWidget(self.bookmark_list)
        bkl.addWidget(rm)
        bk_group.setLayout(bkl)
        v.addWidget(bk_group)

        # Privacy
        priv_group = QGroupBox("Privacy")
        pl = QVBoxLayout()
        for label, fn in (
            ("Clear Cookies", self.clear_cookies),
            ("Clear All History", self.clear_history),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            pl.addWidget(b)
        self.adblock_label = QLabel()
        pl.addWidget(self.adblock_label)
        priv_group.setLayout(pl)
        v.addWidget(priv_group)

        # Appearance
        app_group = QGroupBox("Appearance")
        al = QHBoxLayout()
        zout = QPushButton("－")
        zin = QPushButton("＋")
        zreset = QPushButton("100%")
        for b, fn in ((zout, self.zoom_out), (zreset, self.zoom_reset),
                      (zin, self.zoom_in)):
            b.clicked.connect(fn)
            al.addWidget(b)
        app_group.setLayout(al)
        v.addWidget(app_group)

        dark_btn = QPushButton("Force Dark Mode (page)")
        dark_btn.clicked.connect(self.toggle_dark_mode)
        v.addWidget(dark_btn)

        hist_btn = QPushButton("Show History")
        hist_btn.clicked.connect(self.show_history)
        v.addWidget(hist_btn)

        close_btn = QPushButton("Close Browser")
        close_btn.clicked.connect(self.close)
        v.addWidget(close_btn)

        v.addStretch()
        self.sidebar.setWidget(root)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sidebar)
        self.sidebar.setVisible(False)
        self._refresh_bookmark_list()

    # ------------------------------------------------------------------ #
    #  Tabs
    # ------------------------------------------------------------------ #
    def _browser(self):
        w = self.tabs.currentWidget()
        return w.browser if isinstance(w, BrowserTab) else None

    # keep a back-compat alias used in some handlers
    current_browser = _browser

    def add_new_tab(self, qurl=None, label="New Tab", private=False, profile=None):
        if qurl is None:
            qurl = QUrl("https://www.google.com")
        prof = profile or (self.private_profile if private else self.profile)
        tab = BrowserTab(self, profile=prof, private=private, url=qurl)
        index = self.tabs.addTab(tab, "🕶 " + label if private else label)
        self.tabs.setCurrentIndex(index)
        if private:
            self.tabs.setTabToolTip(index, "Private tab — browsing is not saved")
        tab_icon = (text_icon("🕶", "#a78bfa") if private
                    else text_icon("⏳", "#7a8290"))
        self.tabs.setTabIcon(index, tab_icon)

        b = tab.browser
        b.loadStarted.connect(
            lambda i=index, p=private: self.tabs.setTabIcon(
                i, text_icon("🕶", "#a78bfa") if p
                else text_icon("⏳", "#7a8290")))
        b.iconChanged.connect(
            lambda icon, i=index, p=private:
                (not p and not icon.isNull())
                and self.tabs.setTabIcon(i, icon))
        b.urlChanged.connect(lambda q, bb=b: self.update_url_bar(q, bb))
        b.titleChanged.connect(
            lambda title, t=tab: self.update_tab_title(title, t))
        b.loadProgress.connect(
            lambda p, t=tab: self.update_tab_title(f"({p}%) {b.title() or 'Loading…'}", t))
        b.loadFinished.connect(lambda ok, t=tab, bb=b: self._on_load_finished(ok, t, bb))
        b.page().linkHovered.connect(
            lambda txt: self.status.showMessage(txt, 3000))
        self.update_url_bar(b.url(), b)
        return tab

    def create_new_tab_from_page(self, profile=None, private=False):
        prof = profile or (self.private_profile if private else self.profile)
        tab = BrowserTab(self, profile=prof, private=private)
        index = self.tabs.addTab(tab, "New Tab")
        self.tabs.setCurrentIndex(index)
        return tab.page

    def close_current_tab(self, index):
        if self.tabs.count() > 1:
            w = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if isinstance(w, BrowserTab):
                try:
                    w.browser.stop()
                    w.browser.page().deleteLater()
                    w.browser.deleteLater()
                except Exception:
                    pass
                w.deleteLater()
        else:
            self.close()

    def _cycle_tab(self, delta):
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + delta) % n)

    def _on_load_finished(self, ok, tab, browser):
        url = browser.url()
        self.update_tab_title(browser.title() or "Untitled", tab)
        if tab:
            self.tabs.setTabToolTip(self.tabs.indexOf(tab), url.toString())
        if ok and not tab.private:
            try:
                self.update_history(url, browser.title())
            except Exception as exc:
                print(f"[warn] history update failed: {exc}")
        self.update_url_bar(url, browser)

    def update_tab_title(self, title, tab):
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        if not title:
            title = "New Tab"
        if len(title) > 42:
            title = title[:41] + "…"
        prefix = "🕶 " if getattr(tab, "private", False) else ""
        self.tabs.setTabText(index, prefix + title)

    # ------------------------------------------------------------------ #
    #  URL bar
    # ------------------------------------------------------------------ #
    def navigate_to_url(self):
        text = self.url_bar.text().strip()
        if not text:
            return
        if not text.startswith(("http://", "https://")):
            if re.match(r"^[\w\-]+(\.[\w\-]+)+([/?#:].*)?$", text):
                text = "https://" + text
            else:
                text = ("https://www.google.com/search?q="
                        + QUrl.toPercentEncoding(text).data().decode())
        url = QUrl(text)
        b = self._browser()
        if b is not None:
            b.setUrl(url)
        if b is not None and not getattr(b.page(), "private", False):
            self.update_history(url, b.title())

    def update_url_bar(self, qurl=None, browser=None):
        b = browser or self._browser()
        if isinstance(qurl, QUrl):
            url = qurl
        elif isinstance(qurl, str):
            url = QUrl(qurl)
        elif b is not None:
            url = b.url()
        else:
            url = QUrl()

        self.url_bar.blockSignals(True)
        self.url_bar.setText(url.toString())
        self.url_bar.blockSignals(False)

        # lock / star icons
        if not hasattr(self, "lock_action"):
            self.lock_action = self.url_bar.addAction(
                text_icon("🔓", "#e0a020"),
                QLineEdit.ActionPosition.LeadingPosition)
        self.lock_action.setIcon(
            text_icon("🔒", "#5bc55b") if url.scheme() == "https"
            else text_icon("🔓", "#e0a020"))
        self._update_star(url.toString())

        # private-tab theming: purple URL bar, badge, placeholder text
        is_private = b is not None and getattr(b.page(), "private", False)
        self.url_bar.setStyleSheet(
            URL_STYLE_PRIVATE if is_private else URL_STYLE)
        self.url_bar.setPlaceholderText(
            "Private — history and cookies are not saved" if is_private
            else "Search Google or type a URL")
        if hasattr(self, "private_badge"):
            self.private_badge.setVisible(is_private)

    def _update_star(self, url):
        starred = any(bm.get("url") == url for bm in self.bookmarks)
        self.star_action.setIcon(text_icon("★" if starred else "☆",
                                           "#f2c14e" if starred else "#cdd0d5"))

    # ------------------------------------------------------------------ #
    #  History
    # ------------------------------------------------------------------ #
    def update_history(self, url, title=""):
        if url is None:
            return
        u = url.toString() if isinstance(url, QUrl) else url
        if not u or u in ("about:blank",):
            return
        top = self.history[0] if self.history else None
        if isinstance(top, dict) and top.get("url") == u:
            top["title"] = title or top.get("title", u)
            top["time"] = datetime.now().isoformat(timespec="seconds")
        else:
            self.history.insert(0, {
                "url": u,
                "title": title or u,
                "time": datetime.now().isoformat(timespec="seconds"),
            })
        if len(self.history) > self.MAX_HISTORY:
            self.history = self.history[:self.MAX_HISTORY]
        write_json(os.path.join(BASE_DIR, "history.json"), self.history)
        self._refresh_completer()

    def clear_history(self):
        if QMessageBox.question(
                self, "Clear History",
                "Clear all browsing history?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        self.history = []
        write_json(os.path.join(BASE_DIR, "history.json"), self.history)
        self._refresh_completer()
        self.status.showMessage("History cleared", 2000)

    def show_history(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("History")
        dlg.resize(620, 480)
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        for entry in self.history:
            text = f"{entry.get('title') or entry.get('url')}\n   {entry.get('url')}  ·  {entry.get('time', '')}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.get("url"))
            lst.addItem(item)
        lay.addWidget(lst)

        def open_selected():
            items = lst.selectedItems()
            if items:
                self.add_new_tab(QUrl(items[0].data(Qt.ItemDataRole.UserRole)), "Tab")
                dlg.accept()

        def delete_selected():
            items = lst.selectedItems()
            if not items:
                return
            url = items[0].data(Qt.ItemDataRole.UserRole)
            if QMessageBox.question(
                    dlg, "Delete",
                    f"Remove '{url}' from history?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self.history = [h for h in self.history if h.get("url") != url]
                write_json(os.path.join(BASE_DIR, "history.json"), self.history)
                self._refresh_completer()
                for it in items:
                    lst.takeItem(lst.row(it))

        row = QHBoxLayout()
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(open_selected)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(delete_selected)
        clr = QPushButton("Clear All")
        clr.clicked.connect(lambda: (self.clear_history(), lst.clear()))
        for b in (open_btn, del_btn, clr):
            row.addWidget(b)
        lay.addLayout(row)
        lst.itemDoubleClicked.connect(lambda *_: open_selected())
        dlg.exec()

    # ------------------------------------------------------------------ #
    #  Bookmarks
    # ------------------------------------------------------------------ #
    def toggle_bookmark(self):
        b = self._browser()
        if b is None:
            return
        url = b.url().toString()
        title = b.title() or url
        if not url or url == "about:blank":
            return
        existing = [bm for bm in self.bookmarks if bm.get("url") == url]
        if existing:
            self.bookmarks = [bm for bm in self.bookmarks if bm.get("url") != url]
            self.status.showMessage("Bookmark removed", 2000)
        else:
            self.bookmarks.insert(0, {"url": url, "title": title})
            self.status.showMessage("Bookmark added", 2000)
        write_json(os.path.join(BASE_DIR, "bookmarks.json"), self.bookmarks)
        self._refresh_bookmark_list()
        self._refresh_completer()
        self._update_star(url)

    def _refresh_bookmark_list(self):
        self.bookmark_list.clear()
        for bm in self.bookmarks:
            title = bm.get("title") or bm.get("url")
            it = QListWidgetItem(title[:50])
            it.setToolTip(bm.get("url"))
            it.setData(Qt.ItemDataRole.UserRole, bm.get("url"))
            self.bookmark_list.addItem(it)

    def _remove_bookmark_selected(self):
        items = self.bookmark_list.selectedItems()
        if not items:
            return
        url = items[0].data(Qt.ItemDataRole.UserRole)
        self.bookmarks = [bm for bm in self.bookmarks if bm.get("url") != url]
        write_json(os.path.join(BASE_DIR, "bookmarks.json"), self.bookmarks)
        self._refresh_bookmark_list()
        self._refresh_completer()
        self._update_star(url)

    # ------------------------------------------------------------------ #
    #  Completer + ad-block label
    # ------------------------------------------------------------------ #
    def _refresh_completer(self):
        urls = []
        seen = set()
        for src in (self.history, self.bookmarks):
            for entry in src:
                u = entry.get("url") if isinstance(entry, dict) else entry
                if u and u not in seen:
                    seen.add(u)
                    urls.append(u)
        self.completer_model.setStringList(urls)

    def on_ad_blocked(self):
        if hasattr(self, "adblock_label"):
            total = self.adblock.blocked + self.adblock_private.blocked
            self.adblock_label.setText(f"Ads blocked: {total}")

    def _refresh_adblock_label(self):
        if hasattr(self, "adblock_label"):
            self.on_ad_blocked()

    # ------------------------------------------------------------------ #
    #  Cookies / privacy
    # ------------------------------------------------------------------ #
    def clear_cookies(self):
        for prof in (self.profile, self.private_profile):
            try:
                prof.cookieStore().deleteAllCookies()
            except Exception as exc:
                print(f"[warn] clear cookies: {exc}")
        self.status.showMessage("Cookies cleared", 2000)

    # ------------------------------------------------------------------ #
    #  Find / zoom / dark mode / pdf
    # ------------------------------------------------------------------ #
    def _do_find(self, text, backward=False):
        b = self._browser()
        if b is None:
            return
        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)
        b.page().findText(text, flags)

    def _clear_find(self):
        b = self._browser()
        if b is not None:
            b.page().findText("")

    def zoom_in(self):
        b = self._browser()
        if b is not None:
            b.page().setZoomLevel(min(round(b.page().zoomLevel() + 0.1, 2), 5.0))

    def zoom_out(self):
        b = self._browser()
        if b is not None:
            b.page().setZoomLevel(max(round(b.page().zoomLevel() - 0.1, 2), 0.25))

    def zoom_reset(self):
        b = self._browser()
        if b is not None:
            b.page().setZoomLevel(1.0)

    def toggle_dark_mode(self):
        b = self._browser()
        if b is None:
            return
        page = b.page()
        page._forced_dark = not page._forced_dark
        js = (
            "document.documentElement.style.filter='invert(0.92) hue-rotate(180deg) brightness(0.95)';"
            "document.documentElement.style.background='#fff';"
            if page._forced_dark else
            "document.documentElement.style.filter='';"
        )
        page.runJavaScript(js)
        self.status.showMessage(
            "Dark mode on" if page._forced_dark else "Dark mode off", 1500)

    def save_pdf(self):
        b = self._browser()
        if b is None:
            return
        title = b.title() or "page"
        safe = re.sub(r"[^\w\-]+", "_", title)[:60] or "page"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as PDF", os.path.expanduser(f"~/{safe}.pdf"),
            "PDF Document (*.pdf)")
        if path:
            b.page().save_pdf(path)

    # ------------------------------------------------------------------ #
    #  Downloads
    # ------------------------------------------------------------------ #
    def handle_download(self, download: QWebEngineDownloadRequest):
        default_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        suggested = os.path.join(default_dir, download.downloadFileName())
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save File", suggested)
        if not save_path:
            download.cancel()
            return
        download.setDownloadDirectory(os.path.dirname(save_path) or ".")
        download.setDownloadFileName(os.path.basename(save_path))
        download.accept()

        dlg = QProgressDialog(
            f"Downloading {download.downloadFileName()}…", "Cancel",
            0, 100, self)
        dlg.setWindowTitle("Download")
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setAutoClose(True)
        dlg.setMinimumDuration(0)
        dlg.show()

        def on_progress(received, total):
            if total > 0:
                pct = int(received / total * 100)
                dlg.setValue(pct)
                dlg.setLabelText(
                    f"{download.downloadFileName()}: "
                    f"{received // 1024} KB / {total // 1024} KB")

        def on_finished():
            dlg.close()
            QMessageBox.information(self, "Download Finished",
                                   f"Saved to:\n{save_path}")

        def on_cancel():
            download.cancel()
            dlg.close()

        download.downloadProgress.connect(on_progress)
        download.finished.connect(on_finished)
        dlg.canceled.connect(on_cancel)

    # ------------------------------------------------------------------ #
    #  Sidebar / window / fullscreen
    # ------------------------------------------------------------------ #
    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())
        if self.sidebar.isVisible():
            self._refresh_bookmark_list()
            self.on_ad_blocked()

    def open_new_window(self):
        w = MainWindow(restore_session=False)
        w.showMaximized()
        self.child_windows.append(w)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    # ------------------------------------------------------------------ #
    #  Session save / restore
    # ------------------------------------------------------------------ #
    def _restore_session(self):
        session = read_json(os.path.join(BASE_DIR, "session.json"), [])
        if not session:
            return False
        for u in session:
            self.add_new_tab(QUrl(u), "Tab")
        return True

    def closeEvent(self, event):
        urls = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, BrowserTab) and not w.private:
                u = w.browser.url().toString()
                if u and u != "about:blank":
                    urls.append(u)
        write_json(os.path.join(BASE_DIR, "session.json"), urls)
        write_json(os.path.join(BASE_DIR, "history.json"), self.history)
        write_json(os.path.join(BASE_DIR, "bookmarks.json"), self.bookmarks)
        super().closeEvent(event)


# we need QLabel for the sidebar
from PyQt6.QtWidgets import QLabel


# --------------------------------------------------------------------------- #
#  Stylesheets
# --------------------------------------------------------------------------- #
STYLE = """
* { font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans', sans-serif; }
QMainWindow, QWidget { background: #1e1f22; color: #e6e6e6; }
QToolBar { background: #2b2d31; border: none; padding: 4px; spacing: 4px; }
QToolBar QToolButton, QToolBar QPushButton {
    background: transparent; border: none; padding: 4px 8px; border-radius: 6px;
}
QToolBar QToolButton:hover, QToolBar QPushButton:hover { background: #3a3d44; }
QLineEdit { background: #383a40; color: #e6e6e6; border: 1px solid #4a4d55;
           border-radius: 8px; padding: 7px 10px; font-size: 14px; }
QLineEdit:focus { border: 1px solid #5865f2; }
QDockWidget { border: none; titlebar-close-icon: none; }
QDockWidget::title { background: #2b2d31; padding: 4px; }
QGroupBox { border: 1px solid #3a3d44; border-radius: 8px; margin-top: 12px;
            padding: 8px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QPushButton { background: #404249; color: #e6e6e6; border: none;
              border-radius: 6px; padding: 6px 10px; }
QPushButton:hover { background: #4e515a; }
QPushButton:pressed { background: #35373d; }
QListWidget { background: #26282c; border: 1px solid #3a3d44; border-radius: 6px; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #5865f2; }
QStatusBar { background: #2b2d31; color: #aaa; }
QProgressBar { background: #383a40; border: none; border-radius: 4px; }
QProgressDialog { background: #2b2d31; }
"""

TAB_STYLE = """
QTabWidget::pane { border: 1px solid #3a3d44; top: -1px; }
QTabBar::tab { background: #2b2d31; color: #c7c7c7; padding: 8px 12px;
               min-width: 110px; max-width: 280px; text-align: left;
               border-radius: 6px; margin: 2px 3px; }
QTabBar::tab:!selected { border: 1px solid transparent; }
QTabBar::tab:selected { background: #1e1f22; border: 1px solid #5865f2; }
QTabBar::tab:hover:!selected { background: #35373d; }
QTabBar::close-button { image: none; subcontrol-position: right;
                        border-radius: 4px; padding: 2px; }
QTabBar::close-button:hover { background: #e04040; }
"""

URL_STYLE = """
QLineEdit { font-size: 14px; border: 1px solid #4a4d55; border-radius: 8px;
            padding: 7px 30px 7px 30px; }
QLineEdit:focus { border: 1px solid #5865f2; }
"""

URL_STYLE_PRIVATE = """
QLineEdit { font-size: 14px; background: #2d2038; color: #f0e6ff;
            border: 1px solid #7c3aed; border-radius: 8px;
            padding: 7px 30px 7px 30px; }
QLineEdit:focus { border: 1px solid #a78bfa; background: #3a2a4a; }
"""


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sbrows")
    app.setApplicationDisplayName("Sbrows")
    f = QFont()
    f.setPointSize(11)
    app.setFont(f)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
