from django.urls import path
from . import views

urlpatterns = [
    path('home/', views.home_redirect, name='home-redirect'),
        path('auth/login/', views.unified_login, name='unified-login'),
    path('auth/switch/<str:role>/', views.switch_role, name='switch-role'),
    path('auth/logout/', views.unified_logout, name='unified-logout'),
    path('login/', views.legacy_login_redirect, name='admin-login'),
    path('logout/', views.legacy_logout_redirect, name='admin-logout'),
    # Admin pages
    path('dashboard/', views.admin_dashboard, name='admin-dashboard'),
    path('dashboard/guests/', views.admin_guests_page, name='admin-guests-page'),
    path('dashboard/invitations/', views.admin_invitations_page, name='admin-invitations-page'),
    path('dashboard/controllers/', views.controllers_page, name='controllers-page'),
    path('dashboard/drinks/', views.drinks_page, name='drinks-page'),
    path('dashboard/orders/', views.orders_page, name='orders-page'),
    path('dashboard/confirmations/', views.confirmations_page, name='confirmations-page'),
    path('dashboard/tables/', views.tables_page, name='tables-page'),
    path('dashboard/settings/', views.settings_page, name='settings-page'),
    path('dashboard/billing/', views.billing_page, name='billing-page'),
    path('dashboard/api/billing/status/', views.api_billing_status, name='api-billing-status'),
    path('dashboard/api/billing/purchase/', views.api_billing_purchase, name='api-billing-purchase'),
    path('dashboard/api/billing/config/update/', views.api_billing_config_update, name='api-billing-config-update'),
    path('dashboard/api/billing/side-config/', views.api_billing_side_config, name='api-billing-side-config'),
    path('dashboard/api/billing/purchase-side/', views.api_billing_purchase_for_side, name='api-billing-purchase-side'),
    path('dashboard/families/', views.families_page, name='families-page'),
    path('dashboard/api/families/', views.api_families_list, name='api-families-list'),
    path('dashboard/api/families/create/', views.api_family_create, name='api-family-create'),
    path('dashboard/api/families/<int:family_id>/update/', views.api_family_update, name='api-family-update'),
    path('dashboard/api/families/<int:family_id>/revoke/', views.api_family_revoke, name='api-family-revoke'),
    path('dashboard/api/families/<int:family_id>/delete/', views.api_family_delete, name='api-family-delete'),

    path('dashboard/proposals/', views.proposals_page, name='proposals-page'),
    path('dashboard/api/proposals/', views.api_proposals_list, name='api-proposals-list'),
    path('dashboard/api/proposals/<int:proposal_id>/approve/', views.api_proposal_approve, name='api-proposal-approve'),
    path('dashboard/api/proposals/<int:proposal_id>/reject/', views.api_proposal_reject, name='api-proposal-reject'),

    path('famille/login/', views.legacy_login_redirect, name='family-login'),
    path('famille/logout/', views.legacy_logout_redirect, name='family-logout'),
    path('famille/', views.family_dashboard, name='family-dashboard'),
    path('famille/api/data/', views.api_family_my_data, name='api-family-data'),
    path('famille/api/propose/', views.api_family_propose, name='api-family-propose'),
    path('famille/guests/', views.family_guests_page, name='family-guests-page'),
    path('famille/api/usage/', views.api_family_usage, name='api-family-usage'),
    path('famille/api/add-guest/', views.api_family_add_guest, name='api-family-add-guest'),
    path('famille/api/import-excel/', views.api_family_import_excel, name='api-family-import-excel'),
    path('famille/api/download-template/', views.api_family_download_template, name='api-family-download-template'),

    path('dashboard/family-guests/', views.family_guests_admin_page, name='family-guests-admin-page'),
    path('dashboard/api/family-requests/', views.api_admin_family_requests, name='api-admin-family-requests'),
    path('dashboard/api/family-requests/<int:request_id>/approve/', views.api_admin_approve_request, name='api-admin-approve-request'),
    path('dashboard/api/family-requests/<int:request_id>/reject/', views.api_admin_reject_request, name='api-admin-reject-request'),
    path('dashboard/api/family-requests/bulk-approve/', views.api_admin_bulk_approve, name='api-admin-bulk-approve'),
    path('dashboard/api/admin/add-guest/', views.admin_add_guest_to_family, name='admin-add-guest-to-family'),
    path('dashboard/api/admin/download-template/', views.admin_download_template, name='admin-download-template'),
    path('dashboard/api/admin/import-excel/', views.admin_import_excel_any_family, name='admin-import-excel-any-family'),
    path('dashboard/api/tables/', views.api_tables_list, name='api-tables-list'),
    path('dashboard/api/tables/create/', views.api_table_create, name='api-table-create'),
    path('dashboard/api/tables/<int:table_id>/update/', views.api_table_update, name='api-table-update'),
    path('dashboard/api/tables/<int:table_id>/delete/', views.api_table_delete, name='api-table-delete'),
    path('dashboard/api/tables/reorder/', views.api_table_reorder, name='api-table-reorder'),
    path('dashboard/api/settings/', views.api_settings_get, name='api-settings-get'),
    path('dashboard/api/settings/update/', views.api_settings_update, name='api-settings-update'),

    # Controleur
    path('controleur/login/', views.legacy_login_redirect, name='control-login'),
    path('controleur/logout/', views.legacy_logout_redirect, name='control-logout'),
    path('controleur/', views.control_dashboard, name='control-dashboard'),

    # API guests
    path('dashboard/api/guests/', views.api_guests, name='api-guests'),
    path('dashboard/api/stats/', views.api_stats, name='api-stats'),
    path('dashboard/api/guests/create/', views.api_guest_create, name='api-guest-create'),
    path('dashboard/api/guests/<uuid:guest_id>/update/', views.api_guest_update, name='api-guest-update'),
    path('dashboard/api/guests/<uuid:guest_id>/delete/', views.api_guest_delete, name='api-guest-delete'),
    path('dashboard/export.csv', views.export_csv, name='export-csv'),

    # API controllers
    path('dashboard/api/controllers/', views.api_controllers_list, name='api-controllers-list'),
    path('dashboard/api/controllers/create/', views.api_controller_create, name='api-controller-create'),
    path('dashboard/api/controllers/<int:controller_id>/update/', views.api_controller_update, name='api-controller-update'),
    path('dashboard/api/controllers/<int:controller_id>/revoke/', views.api_controller_revoke, name='api-controller-revoke'),
    path('dashboard/api/controllers/<int:controller_id>/delete/', views.api_controller_delete, name='api-controller-delete'),

    # API drinks
    path('dashboard/api/drinks/', views.api_drinks_list, name='api-drinks-list'),
    path('dashboard/api/drinks/create/', views.api_drink_create, name='api-drink-create'),
    path('dashboard/api/drinks/<int:drink_id>/update/', views.api_drink_update, name='api-drink-update'),
    path('dashboard/api/drinks/<int:drink_id>/delete/', views.api_drink_delete, name='api-drink-delete'),

    # API orders
    path('dashboard/api/orders/', views.api_orders_list, name='api-orders-list'),
    path('dashboard/api/orders/<int:order_id>/update/', views.api_order_update_status, name='api-order-update'),

    # API confirmations
    path('dashboard/api/confirmations/', views.api_confirmations_list, name='api-confirmations-list'),

    # API checkin
    path('dashboard/api/checkin/', views.api_checkin_by_token, name='api-checkin'),
]