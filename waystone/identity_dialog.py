"""Identity management dialog — create, import, export, and delete Gemini client certificates."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from . import async_utils
from .identity_service import IdentityService, import_p12


class IdentityDialog(Adw.PreferencesDialog):
    def __init__(
        self,
        parent: Gtk.Widget,
        service: IdentityService,
        on_change: object = None,
    ) -> None:
        super().__init__()
        self.set_title("Gemini Identities")
        self._service = service
        self._on_change = on_change
        self._parent = parent
        self._rows: list[Adw.ActionRow] = []
        self._group: Adw.PreferencesGroup | None = None
        self._build()
        self.present(parent)
        async_utils.run(self._load())

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        page = Adw.PreferencesPage(
            title="Identities",
            icon_name="contact-new-symbolic",
        )
        self.add(page)

        # Action buttons in the group header
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        btn_import = Gtk.Button(label="Import .p12…")
        btn_import.add_css_class("flat")
        btn_import.connect("clicked", self._on_import_clicked)

        btn_new = Gtk.Button(label="New Identity…")
        btn_new.add_css_class("flat")
        btn_new.connect("clicked", self._on_new_clicked)

        btn_box.append(btn_import)
        btn_box.append(btn_new)

        self._group = Adw.PreferencesGroup(
            title="Your Identities",
            description="Client certificates sent to Gemini capsules that require authentication. "
                        "Certificates are stored locally and can be exported as .p12 files "
                        "to use in other browsers.",
        )
        self._group.set_header_suffix(btn_box)
        page.add(self._group)

    # ------------------------------------------------------------------
    # Load / populate
    # ------------------------------------------------------------------

    async def _load(self) -> None:
        identities = await self._service.list_all()
        data = []
        for identity in identities:
            hosts = await self._service.list_hosts_for_identity(identity["id"])
            data.append({**identity, "hosts": hosts})
        GLib.idle_add(self._populate, data)

    def _populate(self, data: list[dict]) -> None:
        for row in self._rows:
            self._group.remove(row)
        self._rows.clear()

        if not data:
            row = Adw.ActionRow(
                title="No identities yet",
                subtitle='Click "New Identity…" to create one.',
            )
            self._group.add(row)
            self._rows.append(row)
            return

        for item in data:
            host_parts = [f"{h['host']}:{h['port']}" for h in item["hosts"]]
            subtitle = ", ".join(host_parts) if host_parts else "No capsules assigned"

            row = Adw.ActionRow(
                title=item["name"],
                subtitle=subtitle,
            )

            btn_export = Gtk.Button(icon_name="document-save-symbolic")
            btn_export.set_valign(Gtk.Align.CENTER)
            btn_export.add_css_class("flat")
            btn_export.set_tooltip_text("Export as .p12")
            btn_export.connect(
                "clicked",
                lambda _, iid=item["id"], name=item["name"]: self._on_export(iid, name),
            )

            btn_delete = Gtk.Button(icon_name="edit-delete-symbolic")
            btn_delete.set_valign(Gtk.Align.CENTER)
            btn_delete.add_css_class("flat")
            btn_delete.set_tooltip_text("Delete identity")
            btn_delete.connect(
                "clicked",
                lambda _, iid=item["id"], name=item["name"]: self._on_delete(iid, name),
            )

            row.add_suffix(btn_export)
            row.add_suffix(btn_delete)
            self._group.add(row)
            self._rows.append(row)

    def _reload(self) -> None:
        async_utils.run(self._load())
        if self._on_change:
            self._on_change()

    # ------------------------------------------------------------------
    # Create new identity
    # ------------------------------------------------------------------

    def _on_new_clicked(self, _btn) -> None:
        entry = Gtk.Entry()
        entry.set_placeholder_text("e.g. your username or handle")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        dlg = Adw.AlertDialog(
            heading="New Identity",
            body="Enter a name for this identity. This becomes the certificate's "
                 "Common Name and helps you identify it later.",
        )
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("create", "Create")
        dlg.set_default_response("create")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp):
            if resp != "create":
                return
            name = entry.get_text().strip()
            if not name:
                return
            async_utils.run(self._do_create(name))

        dlg.connect("response", on_response)
        dlg.present(self)

    async def _do_create(self, name: str) -> None:
        await self._service.create(name)
        GLib.idle_add(self._reload)

    # ------------------------------------------------------------------
    # Import .p12
    # ------------------------------------------------------------------

    def _on_import_clicked(self, _btn) -> None:
        file_filter = Gtk.FileFilter()
        file_filter.set_name("PKCS#12 files (*.p12, *.pfx)")
        file_filter.add_pattern("*.p12")
        file_filter.add_pattern("*.pfx")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)

        dlg = Gtk.FileDialog()
        dlg.set_title("Import Identity (.p12)")
        dlg.set_filters(filters)
        dlg.open(self._parent, None, self._on_import_file_chosen)

    def _on_import_file_chosen(self, dlg: Gtk.FileDialog, result) -> None:
        try:
            gfile = dlg.open_finish(result)
        except Exception:
            return
        if not gfile:
            return
        path = gfile.get_path()
        if not path:
            return
        # Ask for password (optional)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_placeholder_text("Leave blank if not password-protected")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        pw_dlg = Adw.AlertDialog(
            heading="Import Identity",
            body=f"Enter the password for this .p12 file, or leave blank if none.",
        )
        pw_dlg.set_extra_child(entry)
        pw_dlg.add_response("cancel", "Cancel")
        pw_dlg.add_response("import", "Import")
        pw_dlg.set_default_response("import")
        pw_dlg.set_close_response("cancel")
        pw_dlg.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)

        def on_pw_response(_d, resp):
            if resp != "import":
                return
            pw_text = entry.get_text()
            password = pw_text.encode() if pw_text else None
            async_utils.run(self._do_import(path, password))

        pw_dlg.connect("response", on_pw_response)
        pw_dlg.present(self)

    async def _do_import(self, path: str, password) -> None:
        try:
            with open(path, "rb") as f:
                data = f.read()
            name, cert_pem, key_pem = import_p12(data, password)
            await self._service.store(name, cert_pem, key_pem)
            GLib.idle_add(self._reload)
        except Exception as e:
            GLib.idle_add(self._show_error, "Import Failed", str(e))

    # ------------------------------------------------------------------
    # Export .p12
    # ------------------------------------------------------------------

    def _on_export(self, identity_id: int, name: str) -> None:
        # Ask for an optional password first
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.set_placeholder_text("Leave blank for no password")
        entry.set_activates_default(True)
        entry.set_margin_top(8)

        dlg = Adw.AlertDialog(
            heading="Export Identity",
            body="Optionally set a password to protect the exported .p12 file.\n\n"
                 "You will need this password when importing into another browser.",
        )
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("export", "Choose File…")
        dlg.set_default_response("export")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("export", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp):
            if resp != "export":
                return
            pw_text = entry.get_text()
            password = pw_text.encode() if pw_text else None
            self._pick_export_file(identity_id, name, password)

        dlg.connect("response", on_response)
        dlg.present(self)

    def _pick_export_file(self, identity_id: int, name: str, password) -> None:
        save_dlg = Gtk.FileDialog()
        save_dlg.set_title("Export Identity")
        save_dlg.set_initial_name(f"{name}.p12")
        save_dlg.save(self._parent, None,
                      lambda d, r: self._on_export_file_chosen(d, r, identity_id, password))

    def _on_export_file_chosen(self, dlg: Gtk.FileDialog, result,
                               identity_id: int, password) -> None:
        try:
            gfile = dlg.save_finish(result)
        except Exception:
            return
        if not gfile:
            return
        path = gfile.get_path()
        if not path:
            return
        async_utils.run(self._do_export(identity_id, path, password))

    async def _do_export(self, identity_id: int, path: str, password) -> None:
        try:
            p12_bytes = await self._service.export_p12(identity_id, password)
            loop = async_utils.get_loop()
            await loop.run_in_executor(
                None, lambda: open(path, "wb").write(p12_bytes)
            )
            GLib.idle_add(self._show_info, "Identity Exported",
                          f"Saved to:\n{path}")
        except Exception as e:
            GLib.idle_add(self._show_error, "Export Failed", str(e))

    # ------------------------------------------------------------------
    # Delete identity
    # ------------------------------------------------------------------

    def _on_delete(self, identity_id: int, name: str) -> None:
        dlg = Adw.AlertDialog(
            heading="Delete Identity",
            body=f'Delete "{name}"?\n\nThis will also remove its capsule assignments. '
                 f"This cannot be undone.",
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, resp):
            if resp == "delete":
                async_utils.run(self._do_delete(identity_id))

        dlg.connect("response", on_response)
        dlg.present(self)

    async def _do_delete(self, identity_id: int) -> None:
        await self._service.delete(identity_id)
        GLib.idle_add(self._reload)

    # ------------------------------------------------------------------
    # Helper dialogs
    # ------------------------------------------------------------------

    def _show_error(self, heading: str, body: str) -> None:
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("ok", "OK")
        dlg.present(self)

    def _show_info(self, heading: str, body: str) -> None:
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("ok", "OK")
        dlg.present(self)


