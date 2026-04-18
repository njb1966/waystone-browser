"""Settings dialog — homepage, JS toggle, Gemini TOFU certificate management."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from . import async_utils
from .settings_service import SettingsService
from .tofu_store import TOFUStore


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(
        self,
        parent: Gtk.Widget,
        settings: SettingsService,
        tofu_store: TOFUStore,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._tofu = tofu_store
        self._cert_rows: list[Adw.ActionRow] = []
        self._build()
        self.present(parent)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # ── General page ──────────────────────────────────────────────
        general = Adw.PreferencesPage(
            title="General",
            icon_name="preferences-system-symbolic",
        )
        self.add(general)

        browsing = Adw.PreferencesGroup(title="Browsing")
        general.add(browsing)

        self._homepage_row = Adw.EntryRow(title="Homepage URL")
        self._homepage_row.set_text(self._settings.homepage)
        self._homepage_row.connect("changed", self._on_homepage_changed)
        browsing.add(self._homepage_row)

        self._js_row = Adw.SwitchRow(
            title="Enable JavaScript",
            subtitle="Applies to new web (HTTP/HTTPS) tabs",
        )
        self._js_row.set_active(self._settings.js_enabled)
        self._js_row.connect("notify::active", self._on_js_toggled)
        browsing.add(self._js_row)

        self._bar_row = Adw.SwitchRow(
            title="Show Bookmarks Bar",
            subtitle="Toolbar below the address bar (Ctrl+Shift+B)",
        )
        self._bar_row.set_active(self._settings.show_bookmarks_bar)
        self._bar_row.connect("notify::active", self._on_bar_toggled)
        browsing.add(self._bar_row)

        appearance = Adw.PreferencesGroup(title="Appearance")
        general.add(appearance)

        self._scheme_row = Adw.ComboRow(title="Color Scheme")
        self._scheme_row.set_model(Gtk.StringList.new(["System Default", "Light", "Dark"]))
        self._scheme_row.set_selected(
            {"default": 0, "light": 1, "dark": 2}.get(self._settings.color_scheme, 0)
        )
        self._scheme_row.connect("notify::selected", self._on_scheme_changed)
        appearance.add(self._scheme_row)

        # ── Gemini page ────────────────────────────────────────────────
        gemini = Adw.PreferencesPage(
            title="Gemini",
            icon_name="security-high-symbolic",
        )
        self.add(gemini)

        self._cert_group = Adw.PreferencesGroup(
            title="Trusted Certificates",
            description="TOFU fingerprints stored for Gemini hosts. "
                        "Remove a certificate to be prompted again on next visit.",
        )
        gemini.add(self._cert_group)

        async_utils.run(self._load_certs_async())

    # ------------------------------------------------------------------
    # Settings callbacks
    # ------------------------------------------------------------------

    def _on_homepage_changed(self, row: Adw.EntryRow) -> None:
        self._settings.homepage = row.get_text()

    def _on_js_toggled(self, row: Adw.SwitchRow, _param) -> None:
        self._settings.js_enabled = row.get_active()

    def _on_bar_toggled(self, row: Adw.SwitchRow, _param) -> None:
        self._settings.show_bookmarks_bar = row.get_active()

    def _on_scheme_changed(self, row: Adw.ComboRow, _param) -> None:
        keys   = ["default", "light", "dark"]
        schemes = [Adw.ColorScheme.DEFAULT, Adw.ColorScheme.FORCE_LIGHT, Adw.ColorScheme.FORCE_DARK]
        idx = row.get_selected()
        self._settings.color_scheme = keys[idx]
        Adw.StyleManager.get_default().set_color_scheme(schemes[idx])

    # ------------------------------------------------------------------
    # TOFU cert list
    # ------------------------------------------------------------------

    async def _load_certs_async(self) -> None:
        certs = await self._tofu.list_all()
        GLib.idle_add(self._populate_certs, certs)

    def _populate_certs(self, certs: list[dict]) -> None:
        for row in self._cert_rows:
            self._cert_group.remove(row)
        self._cert_rows.clear()

        if not certs:
            row = Adw.ActionRow(title="No stored certificates")
            self._cert_group.add(row)
            self._cert_rows.append(row)
            return

        for cert in certs:
            host = cert["host"]
            port = cert["port"]
            fp   = cert["fingerprint"]
            row  = Adw.ActionRow(
                title=f"{host}:{port}",
                subtitle=f"{fp[:16]}…{fp[-8:]}",
            )
            btn = Gtk.Button(icon_name="edit-delete-symbolic")
            btn.set_valign(Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.set_tooltip_text("Remove certificate")
            btn.connect("clicked", lambda _, h=host, p=port: self._on_forget(h, p))
            row.add_suffix(btn)
            self._cert_group.add(row)
            self._cert_rows.append(row)

    def _on_forget(self, host: str, port: int) -> None:
        async_utils.run(self._forget_and_reload(host, port))

    async def _forget_and_reload(self, host: str, port: int) -> None:
        await self._tofu.forget(host, port)
        certs = await self._tofu.list_all()
        GLib.idle_add(self._populate_certs, certs)
