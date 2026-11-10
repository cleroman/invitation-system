from django.urls import path
from . import views

urlpatterns = [
    path("api/guests/", views.download_guest_list, name="guest-list"),
    path("api/sync-checkin/", views.sync_checkin, name="sync-checkin"),
    path("api/qr/<str:token>/", views.qr_png, name="qr-png"),
    path("api/qr/<str:token>/download/", views.qr_download, name="qr-download"),
    path("invitation/<str:token>/", views.public_invitation, name="public-invitation"),
    path("invitations/", views.invitation_list, name="invitation-list"),
    # Nouveaux endpoints publics
    path("api/invitation/<str:token>/info/", views.api_invitation_info, name="api-invitation-info"),
    path("api/invitation/<str:token>/confirm/", views.api_confirm_attendance, name="api-confirm-attendance"),
    path("api/invitation/<str:token>/wish/", views.api_add_wish, name="api-add-wish"),
    path("api/invitation/<str:token>/order-drink/", views.api_order_drink, name="api-order-drink"),
]