from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Guest


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = [
        "name", "status", "table_name", "phone",
        "is_checked_in", "qr_preview_link", "invitation_actions",
    ]
    list_filter = ["status", "is_checked_in"]
    search_fields = ["name", "table_name", "qr_token", "phone"]
    readonly_fields = ["qr_token", "qr_preview", "invitation_link"]
    fieldsets = (
        ("Informations invite", {
            "fields": ("name", "phone", "email", "status", "table_name")
        }),
        ("QR code", {
            "fields": ("qr_token", "qr_preview"),
        }),
        ("Invitation numerique", {
            "fields": ("invitation_link",),
            "description": "Lien personnel a envoyer par WhatsApp a l'invite",
        }),
        ("Controle d'acces", {
            "fields": ("is_checked_in", "checked_in_at"),
        }),
    )

    def qr_preview_link(self, obj):
        if not obj.qr_token:
            return "-"
        url = reverse("qr-png", args=[obj.qr_token])
        dl = reverse("qr-download", args=[obj.qr_token])
        return format_html(
            '<a href="{}" target="_blank">Voir</a> | '
            '<a href="{}" download>Telecharger</a>',
            url, dl
        )
    qr_preview_link.short_description = "QR code"

    def qr_preview(self, obj):
        if not obj.qr_token:
            return "-"
        url = reverse("qr-png", args=[obj.qr_token])
        return format_html(
            '<img src="{}" style="width:200px;height:200px;" />'
            '<br/><a href="{}" target="_blank">Ouvrir en grand</a>',
            url, url
        )
    qr_preview.short_description = "Apercu du QR"

    def invitation_link(self, obj):
        if not obj.qr_token:
            return "-"
        url = reverse("public-invitation", args=[obj.qr_token])
        return format_html(
            '<a href="{}" target="_blank">{}</a><br>'
            '<small style="color:#888;">Copiez ce lien et envoyez-le par WhatsApp.</small>',
            url, url
        )
    invitation_link.short_description = "Lien personnel"

    def invitation_actions(self, obj):
        url = reverse("public-invitation", args=[obj.qr_token])
        return format_html('<a href="{}" target="_blank">Voir</a>', url)
    invitation_actions.short_description = "Invitation"