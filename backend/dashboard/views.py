import csv
import json
import uuid
from datetime import datetime
from urllib.parse import quote

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from guests.models import Guest, ControllerProfile, Drink, GuestConfirmation, Wish, DrinkOrder, Table, VenueConfig, TableProposal, FamilyAccount, BillingConfig, PaymentTransaction
from guests.excel_utils import get_billing_usage, generate_template, import_excel, create_guest_from_request
from .auth import controller_required, admin_required, family_required


# --- Evenement ---
EVENT_TITLE = 'Mariage de Juguel & Viviane'
EVENT_DATE  = '19 Decembre 2026'
EVENT_VENUE = 'Kinshasa, RDC'


# ========== PAGES ADMIN ==========

@admin_required
def admin_dashboard(request):
    return render(request, 'dashboard/admin.html', {
        'event_title': EVENT_TITLE,
        'event_date': EVENT_DATE,
        'event_venue': EVENT_VENUE,
        'is_admin': True,
    })


@admin_required
def controllers_page(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Acces reserve a l'administrateur.")
    return render(request, 'dashboard/controllers.html', {
        'event_title': EVENT_TITLE,
    })


# ========== LOGIN CONTROLEUR ==========

def control_login(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.controller_profile
            if profile.is_active and request.session.get("controller_token") == profile.current_session_token:
                return redirect("control-dashboard")
        except ControllerProfile.DoesNotExist:
            pass
        logout(request)

    error = request.session.pop("login_error", None)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "Identifiants incorrects."
        else:
            try:
                profile = user.controller_profile
            except ControllerProfile.DoesNotExist:
                error = "Ce compte n'est pas un compte controleur."
            else:
                if not profile.is_active:
                    error = "Votre acces a ete revoque. Contactez l'administrateur."
                else:
                    # Invalider l'ancienne session (session unique)
                    profile.current_session_token = uuid.uuid4().hex
                    profile.current_session_started = timezone.now()
                    profile.last_login_ip = request.META.get("REMOTE_ADDR")
                    profile.save()

                    login(request, user)
                    request.session["controller_token"] = profile.current_session_token
                    return redirect("control-dashboard")

    return render(request, "dashboard/control_login.html", {"error": error})


def control_logout(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.controller_profile
            profile.revoke()
        except ControllerProfile.DoesNotExist:
            pass
        logout(request)
    return redirect("control-login")


# ========== DASHBOARD CONTROLEUR (protege) ==========

@controller_required
def control_dashboard(request):
    profile = getattr(request, 'controller_profile', None)
    is_admin = getattr(request, 'is_admin_scanner', False)

    if is_admin:
        controller_name = f"{request.user.username} (admin)"
    elif profile:
        controller_name = profile.display_name
    else:
        controller_name = "Controleur"

    return render(request, 'dashboard/control.html', {
        'event_title': EVENT_TITLE,
        'controller_name': controller_name,
        'is_admin_scanner': is_admin,
    })

@controller_required
@require_http_methods(["POST"])
def api_checkin_by_token(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    token = (data.get('token') or '').strip()
    if not token:
        return JsonResponse({'error': 'Token requis'}, status=400)

    try:
        g = Guest.objects.get(qr_token=token)
    except Guest.DoesNotExist:
        return JsonResponse({'status': 'unknown'}, status=404)

    # --- Verification du blocage ---
    if g.is_blocked:
        return JsonResponse({
            'status': 'blocked',
            'guest': {
                'name': g.name,
                'status_display': g.get_status_display(),
                'table_name': g.table_name,
                'block_reason': g.block_reason,
            }
        })

    result = {
        'status': 'already' if g.is_checked_in else 'ok',
        'guest': {
            'name': g.name,
            'status_display': g.get_status_display(),
            'table_name': g.table_name,
            'is_checked_in': g.is_checked_in,
        }
    }
    if not g.is_checked_in:
        g.is_checked_in = True
        g.checked_in_at = timezone.now()
        g.save()
    return JsonResponse(result)


# ========== API ADMIN (guests, stats, CRUD) ==========

def _guest_to_dict(g, request):
    rel = reverse('public-invitation', args=[g.qr_token])
    abs_url = request.build_absolute_uri(rel)
    phone_clean = ''.join(c for c in (g.phone or '') if c.isdigit())
    msg = (
        f"*{EVENT_TITLE}*\n\n"
        f"Bonjour {g.name},\n\n"
        f"*Date :* {EVENT_DATE}\n"
        f"*Lieu :* {EVENT_VENUE}\n"
        f"*Table :* {g.table_name}\n"
        f"*Personnes :* {g.get_status_display()}\n\n"
        f"Votre invitation : {abs_url}"
    )
    if phone_clean:
        whatsapp_url = f"https://wa.me/{phone_clean}?text={quote(msg)}"
    else:
        whatsapp_url = f"https://wa.me/?text={quote(msg)}"

    return {
        'id': str(g.id),
        'name': g.name,
        'phone': g.phone or '',
        'email': g.email or '',
        'family': g.family or '',
        'status': g.status,
        'status_display': g.get_status_display(),
        'table_name': g.table_name,
        'qr_token': g.qr_token,
        'is_checked_in': g.is_checked_in,
        'is_blocked': g.is_blocked,
        'block_reason': g.block_reason,
        'checked_in_at': g.checked_in_at.isoformat() if g.checked_in_at else None,
        'qr_url': request.build_absolute_uri(reverse('qr-png', args=[g.qr_token])),
        'qr_download_url': request.build_absolute_uri(reverse('qr-download', args=[g.qr_token])),
        'invitation_url': abs_url,
        'whatsapp_url': whatsapp_url,
    }


@admin_required
def api_guests(request):
    guests = Guest.objects.all().order_by('name')
    return JsonResponse({'guests': [_guest_to_dict(g, request) for g in guests]})


@admin_required
def api_stats(request):
    qs = Guest.objects.all()
    return JsonResponse({
        'total': qs.count(),
        'checked_in': qs.filter(is_checked_in=True).count(),
        'remaining': qs.filter(is_checked_in=False).count(),
        'couples': qs.filter(status='couple').count(),
        'singles': qs.filter(status='single').count(),
        'total_persons': sum(g.num_persons for g in qs),
        'blocked': qs.filter(is_blocked=True).count(),
    })


@admin_required
@require_http_methods(['POST'])
def api_guest_create(request):
    # Verification de la limite de places
    cfg = BillingConfig.get_solo()
    if cfg.is_enabled and cfg.is_at_limit:
        return JsonResponse({
            'error': 'limit_reached',
            'current': cfg.current_guests,
            'limit': cfg.total_limit,
            'needed': 1,
            'price_usd': str(cfg.price_per_place_usd),
            'price_cdf': cfg.price_per_place_cdf,
        }, status=402)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'Le nom est requis'}, status=400)

    g = Guest.objects.create(
        name=name,
        phone=(data.get('phone') or '').strip(),
        email=(data.get('email') or '').strip(),
        status=data.get('status') or 'single',
        table_name=(data.get('table_name') or '').strip(),
        family=(data.get('family') or '').strip(),
    )
    return JsonResponse({'guest': _guest_to_dict(g, request)}, status=201)


@admin_required
@require_http_methods(['POST'])
def api_guest_update(request, guest_id):
    g = get_object_or_404(Guest, id=guest_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    for field in ('name', 'phone', 'email', 'status', 'table_name', 'block_reason', 'family'):
        if field in data:
            setattr(g, field, (data[field] or '').strip() if isinstance(data[field], str) else data[field])

    if 'is_checked_in' in data:
        g.is_checked_in = bool(data['is_checked_in'])
        g.checked_in_at = timezone.now() if g.is_checked_in else None

    if 'is_blocked' in data:
        g.is_blocked = bool(data['is_blocked'])

    g.save()
    return JsonResponse({'guest': _guest_to_dict(g, request)})


@admin_required
@require_http_methods(['POST'])
def api_guest_delete(request, guest_id):
    g = get_object_or_404(Guest, id=guest_id)
    g.delete()
    return JsonResponse({'ok': True})


@admin_required
def export_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="invites.csv"'
    response.write('\ufeff')
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Nom', 'Statut', 'Table', 'Telephone', 'Email', 'Entre', 'Bloque', 'Heure entree'])
    for g in Guest.objects.all().order_by('name'):
        writer.writerow([
            g.name,
            g.get_status_display(),
            g.table_name,
            g.phone,
            g.email,
            'Oui' if g.is_checked_in else 'Non',
            'Oui' if g.is_blocked else 'Non',
            g.checked_in_at.strftime('%d/%m/%Y %H:%M') if g.checked_in_at else '',
        ])
    return response


# ========== API ADMIN - GESTION CONTROLEURS ==========

def _controller_to_dict(profile):
    return {
        'id': str(profile.id),
        'username': profile.user.username,
        'display_name': profile.display_name,
        'is_active': profile.is_active,
        'is_logged_in': bool(profile.current_session_token),
        'last_login_ip': profile.last_login_ip or '',
        'current_session_started': (
            profile.current_session_started.isoformat()
            if profile.current_session_started else None
        ),
        'created_at': profile.created_at.isoformat() if profile.created_at else None,
    }


@admin_required
def api_controllers_list(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin uniquement'}, status=403)
    profiles = ControllerProfile.objects.select_related('user').order_by('display_name')
    return JsonResponse({'controllers': [_controller_to_dict(p) for p in profiles]})


@admin_required
@require_http_methods(['POST'])
def api_controller_create(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin uniquement'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    # Limite a 5 controleurs
    if ControllerProfile.objects.count() >= 5:
        return JsonResponse({'error': 'Maximum 5 controleurs autorises.'}, status=400)

    username = (data.get('username') or '').strip().lower()
    password = (data.get('password') or '').strip()
    display_name = (data.get('display_name') or '').strip()

    if not username or not password:
        return JsonResponse({'error': 'Login et mot de passe requis.'}, status=400)
    if len(password) < 6:
        return JsonResponse({'error': 'Mot de passe : 6 caracteres minimum.'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'error': 'Ce login existe deja.'}, status=400)

    user = User.objects.create_user(username=username, password=password, is_staff=False)
    profile = ControllerProfile.objects.create(
        user=user,
        display_name=display_name or username,
        is_active=True,
    )
    return JsonResponse({'controller': _controller_to_dict(profile)}, status=201)


@admin_required
@require_http_methods(['POST'])
def api_controller_update(request, controller_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin uniquement'}, status=403)

    profile = get_object_or_404(ControllerProfile, id=controller_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    if 'display_name' in data:
        profile.display_name = (data['display_name'] or '').strip()

    if 'new_password' in data and data['new_password']:
        if len(data['new_password']) < 6:
            return JsonResponse({'error': 'Mot de passe : 6 caracteres minimum.'}, status=400)
        profile.user.set_password(data['new_password'])
        profile.user.save()
        profile.revoke()  # Force reconnexion

    if 'is_active' in data:
        profile.is_active = bool(data['is_active'])
        if not profile.is_active:
            profile.revoke()  # Revocation immediate si desactive

    profile.save()
    return JsonResponse({'controller': _controller_to_dict(profile)})


@admin_required
@require_http_methods(['POST'])
def api_controller_revoke(request, controller_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin uniquement'}, status=403)
    profile = get_object_or_404(ControllerProfile, id=controller_id)
    profile.revoke()
    return JsonResponse({'ok': True, 'controller': _controller_to_dict(profile)})


@admin_required
@require_http_methods(['POST'])
def api_controller_delete(request, controller_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin uniquement'}, status=403)
    profile = get_object_or_404(ControllerProfile, id=controller_id)
    user = profile.user
    profile.delete()
    user.delete()
    return JsonResponse({'ok': True})

# ============================================================
#  VUES ADMIN - BOISSONS
# ============================================================

def _drink_to_dict(d):
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "category": d.category,
        "category_label": d.get_category_display(),
        "is_available": d.is_available,
        "stock": d.stock,
        "is_in_stock": d.is_in_stock,
        "order_count": d.orders.exclude(status="cancelled").count(),
    }


@admin_required
def drinks_page(request):
    return render(request, "dashboard/drinks.html", {
        "event_title": EVENT_TITLE,
        "categories": Drink.CATEGORY_CHOICES,
    })


@admin_required
def api_drinks_list(request):
    drinks = Drink.objects.all().order_by("category", "name")
    return JsonResponse({"drinks": [_drink_to_dict(d) for d in drinks]})


@admin_required
@require_http_methods(["POST"])
def api_drink_create(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Le nom est requis"}, status=400)

    d = Drink.objects.create(
        name=name,
        description=(data.get("description") or "").strip()[:200],
        category=data.get("category") or "soft",
        is_available=bool(data.get("is_available", True)),
        stock=int(data.get("stock", -1)),
    )
    return JsonResponse({"drink": _drink_to_dict(d)}, status=201)


@admin_required
@require_http_methods(["POST"])
def api_drink_update(request, drink_id):
    d = get_object_or_404(Drink, id=drink_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    for field in ("name", "description", "category"):
        if field in data:
            setattr(d, field, (data[field] or "").strip() if isinstance(data[field], str) else data[field])

    if "is_available" in data:
        d.is_available = bool(data["is_available"])
    if "stock" in data:
        d.stock = int(data["stock"])

    d.save()
    return JsonResponse({"drink": _drink_to_dict(d)})


@admin_required
@require_http_methods(["POST"])
def api_drink_delete(request, drink_id):
    d = get_object_or_404(Drink, id=drink_id)
    # Ne pas supprimer si des commandes existent
    if d.orders.exclude(status="cancelled").exists():
        d.is_available = False
        d.save()
        return JsonResponse({"ok": True, "soft_deleted": True,
                             "message": "Boisson desactivee (commandes existantes)"})
    d.delete()
    return JsonResponse({"ok": True})


# ============================================================
#  VUES ADMIN - COMMANDES
# ============================================================

def _order_to_dict(o):
    return {
        "id": o.id,
        "guest_name": o.guest.name,
        "guest_table": o.guest.table_name,
        "drink_name": o.drink.name,
        "drink_category": o.drink.get_category_display(),
        "quantity": o.quantity,
        "status": o.status,
        "status_label": o.get_status_display(),
        "note": o.note,
        "created_at": o.created_at.isoformat(),
        "served_at": o.served_at.isoformat() if o.served_at else None,
    }


@admin_required
def orders_page(request):
    return render(request, "dashboard/orders.html", {"event_title": EVENT_TITLE})


@admin_required
def api_orders_list(request):
    qs = DrinkOrder.objects.select_related("guest", "drink").all().order_by("-created_at")
    status_filter = request.GET.get("status")
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)
    return JsonResponse({
        "orders": [_order_to_dict(o) for o in qs],
        "counts": {
            "pending": DrinkOrder.objects.filter(status="pending").count(),
            "preparing": DrinkOrder.objects.filter(status="preparing").count(),
            "served": DrinkOrder.objects.filter(status="served").count(),
        }
    })


@admin_required
@require_http_methods(["POST"])
def api_order_update_status(request, order_id):
    o = get_object_or_404(DrinkOrder, id=order_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    new_status = data.get("status")
    if new_status not in dict(DrinkOrder.STATUS_CHOICES):
        return JsonResponse({"error": "Statut invalide"}, status=400)

    o.status = new_status
    if new_status == "served":
        o.served_at = timezone.now()
    o.save()
    return JsonResponse({"order": _order_to_dict(o)})


# ============================================================
#  VUES ADMIN - CONFIRMATIONS + VOEUX
# ============================================================

@admin_required
def confirmations_page(request):
    return render(request, "dashboard/confirmations.html", {"event_title": EVENT_TITLE})


@admin_required
def api_confirmations_list(request):
    confs = GuestConfirmation.objects.select_related("guest").all().order_by("-updated_at")
    data = []
    for c in confs:
        data.append({
            "id": c.id,
            "guest_name": c.guest.name,
            "guest_table": c.guest.table_name,
            "guest_status": c.guest.status,
            "confirmed": c.confirmed,
            "num_persons": c.num_persons_confirmed,
            "message": c.message,
            "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
        })
    wishes = Wish.objects.select_related("guest").filter(is_approved=True).order_by("-created_at")
    wish_data = [{
        "id": w.id,
        "guest_name": w.guest.name,
        "message": w.message,
        "created_at": w.created_at.isoformat(),
    } for w in wishes]
    return JsonResponse({
        "confirmations": data,
        "wishes": wish_data,
        "stats": {
            "total_confirmed": GuestConfirmation.objects.filter(confirmed=True).count(),
            "total_persons": sum(c.num_persons_confirmed for c in GuestConfirmation.objects.filter(confirmed=True)),
            "total_pending": GuestConfirmation.objects.filter(confirmed=False).count() + (Guest.objects.count() - GuestConfirmation.objects.count()),
            "total_guests": Guest.objects.count(),
            "total_wishes": Wish.objects.filter(is_approved=True).count(),
        }
    })

# ============================================================
#  VUES ADMIN - CONFIGURATION SALLE + TABLES
# ============================================================

def _table_to_dict(t):
    return {
        "id": t.id,
        "name": t.name,
        "capacity": t.capacity,
        "family": t.family,
        "family_label": t.get_family_display(),
        "position_x": t.position_x,
        "position_y": t.position_y,
        "notes": t.notes,
        "is_active": t.is_active,
        "guests_count": t.guests_count,
        "available_seats": t.available_seats,
        "is_full": t.is_full,
    }


@admin_required
def tables_page(request):
    return render(request, "dashboard/tables.html", {"event_title": EVENT_TITLE})


@admin_required
def api_tables_list(request):
    tables = Table.objects.all().order_by("family", "name")
    return JsonResponse({
        "tables": [_table_to_dict(t) for t in tables],
        "stats": {
            "total_tables": tables.count(),
            "total_capacity": sum(t.capacity for t in tables),
            "total_assigned": sum(t.guests_count for t in tables),
        }
    })


@admin_required
@require_http_methods(["POST"])
def api_table_create(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Le nom est requis"}, status=400)

    if Table.objects.filter(name=name).exists():
        return JsonResponse({"error": "Ce nom de table existe deja"}, status=400)

    t = Table.objects.create(
        name=name,
        capacity=int(data.get("capacity", 8)),
        family=data.get("family") or "neutral",
        position_x=int(data.get("position_x", 0)),
        position_y=int(data.get("position_y", 0)),
        notes=(data.get("notes") or "").strip()[:200],
        is_active=bool(data.get("is_active", True)),
    )
    return JsonResponse({"table": _table_to_dict(t)}, status=201)


@admin_required
@require_http_methods(["POST"])
def api_table_update(request, table_id):
    t = get_object_or_404(Table, id=table_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    # Si on renomme, propager aux invites
    old_name = t.name
    for field in ("name", "notes"):
        if field in data:
            setattr(t, field, (data[field] or "").strip())

    if "name" in data and data["name"] != old_name:
        Guest.objects.filter(table_name=old_name).update(table_name=t.name)

    for field in ("capacity", "position_x", "position_y"):
        if field in data:
            setattr(t, field, int(data[field]))

    if "family" in data:
        t.family = data["family"]
    if "is_active" in data:
        t.is_active = bool(data["is_active"])

    t.save()
    return JsonResponse({"table": _table_to_dict(t)})


@admin_required
@require_http_methods(["POST"])
def api_table_delete(request, table_id):
    t = get_object_or_404(Table, id=table_id)
    # Retirer les invites de cette table
    Guest.objects.filter(table_name=t.name).update(table_name="")
    t.delete()
    return JsonResponse({"ok": True})


@admin_required
@require_http_methods(["POST"])
def api_table_reorder(request):
    """Met a jour les positions X/Y de plusieurs tables d'un coup."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    updates = data.get("updates", [])
    for u in updates:
        Table.objects.filter(id=u["id"]).update(
            position_x=u["x"], position_y=u["y"]
        )
    return JsonResponse({"ok": True, "updated": len(updates)})


# ============================================================
#  VUES ADMIN - CONFIGURATION SALLE
# ============================================================

@admin_required
def settings_page(request):
    return render(request, "dashboard/settings.html", {"event_title": EVENT_TITLE})


@admin_required
def api_settings_get(request):
    cfg = VenueConfig.get_solo()
    return JsonResponse({
        "id": cfg.id,
        "name": cfg.name,
        "address": cfg.address,
        "total_capacity": cfg.total_capacity,
        "max_guests": cfg.max_guests,
        "notes": cfg.notes,
    })


@admin_required
@require_http_methods(["POST"])
def api_settings_update(request):
    cfg = VenueConfig.get_solo()
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    for field in ("name", "address", "notes"):
        if field in data:
            setattr(cfg, field, (data[field] or "").strip())
    for field in ("total_capacity", "max_guests"):
        if field in data:
            setattr(cfg, field, int(data[field]))
    cfg.save()
    return JsonResponse({"ok": True})

# ============================================================
#  ADMIN - COMPTES FAMILLES
# ============================================================

def _family_to_dict(f):
    return {
        "id": f.id,
        "username": f.user.username,
        "display_name": f.display_name,
        "side": f.side,
        "side_label": f.get_side_display(),
        "is_active": f.is_active,
        "is_logged_in": bool(f.current_session_token),
        "last_login_ip": f.last_login_ip or "",
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@admin_required
def families_page(request):
    return render(request, "dashboard/families.html", {"event_title": EVENT_TITLE})


@admin_required
def api_families_list(request):
    accounts = FamilyAccount.objects.select_related("user").order_by("side", "display_name")
    return JsonResponse({"families": [_family_to_dict(f) for f in accounts]})


@admin_required
@require_http_methods(["POST"])
def api_family_create(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    display_name = (data.get("display_name") or "").strip()
    side = data.get("side") or "groom"

    if not username or not password or not display_name:
        return JsonResponse({"error": "Tous les champs sont requis"}, status=400)
    if side not in ("groom", "bride"):
        return JsonResponse({"error": "Cote invalide"}, status=400)
    if len(password) < 6:
        return JsonResponse({"error": "Mot de passe : 6 caracteres minimum"}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "Ce login existe deja"}, status=400)

    user = User.objects.create_user(username=username, password=password, is_staff=False)
    profile = FamilyAccount.objects.create(
        user=user, side=side, display_name=display_name, is_active=True
    )
    return JsonResponse({"family": _family_to_dict(profile)}, status=201)


@admin_required
@require_http_methods(["POST"])
def api_family_update(request, family_id):
    profile = get_object_or_404(FamilyAccount, id=family_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    if "display_name" in data:
        profile.display_name = (data["display_name"] or "").strip()
    if "new_password" in data and data["new_password"]:
        if len(data["new_password"]) < 6:
            return JsonResponse({"error": "Mot de passe : 6 caracteres minimum"}, status=400)
        profile.user.set_password(data["new_password"])
        profile.user.save()
        profile.revoke()
    if "is_active" in data:
        profile.is_active = bool(data["is_active"])
        if not profile.is_active:
            profile.revoke()

    profile.save()
    return JsonResponse({"family": _family_to_dict(profile)})


@admin_required
@require_http_methods(["POST"])
def api_family_revoke(request, family_id):
    profile = get_object_or_404(FamilyAccount, id=family_id)
    profile.revoke()
    return JsonResponse({"ok": True, "family": _family_to_dict(profile)})


@admin_required
@require_http_methods(["POST"])
def api_family_delete(request, family_id):
    profile = get_object_or_404(FamilyAccount, id=family_id)
    user = profile.user
    profile.delete()
    user.delete()
    return JsonResponse({"ok": True})


# ============================================================
#  ADMIN - PROPOSITIONS
# ============================================================

def _proposal_to_dict(p):
    return {
        "id": p.id,
        "family_side": p.family,
        "family_label": p.get_family_display(),
        "action": p.action,
        "action_label": p.get_action_display(),
        "target_table_name": p.target_table.name if p.target_table else None,
        "target_guest_name": p.target_guest.name if p.target_guest else None,
        "payload": p.payload,
        "reason": p.reason,
        "status": p.status,
        "status_label": p.get_status_display(),
        "admin_note": p.admin_note,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@admin_required
def proposals_page(request):
    return render(request, "dashboard/proposals.html", {"event_title": EVENT_TITLE})


@admin_required
def api_proposals_list(request):
    proposals = TableProposal.objects.select_related("target_table", "target_guest").order_by("-created_at")
    pending = proposals.filter(status="pending").count()
    approved = proposals.filter(status="approved").count()
    rejected = proposals.filter(status="rejected").count()
    return JsonResponse({
        "proposals": [_proposal_to_dict(p) for p in proposals],
        "counts": {"pending": pending, "approved": approved, "rejected": rejected},
    })


@admin_required
@require_http_methods(["POST"])
def api_proposal_approve(request, proposal_id):
    p = get_object_or_404(TableProposal, id=proposal_id)
    if p.status != "pending":
        return JsonResponse({"error": "Proposition deja traitee"}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    payload = json.loads(p.payload) if p.payload else {}
    error = None

    try:
        if p.action == "create_table":
            if Table.objects.filter(name=payload.get("name")).exists():
                error = f"La table '{payload.get('name')}' existe deja"
            else:
                Table.objects.create(
                    name=payload.get("name"),
                    capacity=int(payload.get("capacity", 8)),
                    family=p.family,
                    notes=payload.get("notes", ""),
                )
        elif p.action == "update_table":
            if p.target_table:
                if "capacity" in payload:
                    p.target_table.capacity = int(payload["capacity"])
                if "notes" in payload:
                    p.target_table.notes = payload["notes"]
                p.target_table.save()
        elif p.action == "delete_table":
            if p.target_table:
                Guest.objects.filter(table_name=p.target_table.name).update(table_name="")
                p.target_table.delete()
        elif p.action == "assign_guest":
            if p.target_guest and payload.get("table_name"):
                p.target_guest.table_name = payload["table_name"]
                p.target_guest.save()
        elif p.action == "unassign_guest":
            if p.target_guest:
                p.target_guest.table_name = ""
                p.target_guest.save()
    except Exception as e:
        error = str(e)

    if error:
        return JsonResponse({"error": error}, status=400)

    p.status = "approved"
    p.admin_note = (data.get("admin_note") or "").strip()[:300]
    p.reviewed_at = timezone.now()
    p.save()
    return JsonResponse({"ok": True, "proposal": _proposal_to_dict(p)})


@admin_required
@require_http_methods(["POST"])
def api_proposal_reject(request, proposal_id):
    p = get_object_or_404(TableProposal, id=proposal_id)
    if p.status != "pending":
        return JsonResponse({"error": "Proposition deja traitee"}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    p.status = "rejected"
    p.admin_note = (data.get("admin_note") or "").strip()[:300]
    p.reviewed_at = timezone.now()
    p.save()
    return JsonResponse({"ok": True, "proposal": _proposal_to_dict(p)})


# ============================================================
#  FAMILLE - LOGIN / LOGOUT
# ============================================================

def family_login(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.family_profile
            if profile.is_active and request.session.get("family_token") == profile.current_session_token:
                return redirect("family-dashboard")
        except FamilyAccount.DoesNotExist:
            pass
        logout(request)

    error = request.session.pop("family_login_error", None)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "Identifiants incorrects."
        else:
            try:
                profile = user.family_profile
            except FamilyAccount.DoesNotExist:
                error = "Ce compte n'est pas un compte famille."
            else:
                if not profile.is_active:
                    error = "Votre acces est revoque. Contactez l'administrateur."
                else:
                    profile.current_session_token = uuid.uuid4().hex
                    profile.current_session_started = timezone.now()
                    profile.last_login_ip = request.META.get("REMOTE_ADDR")
                    profile.save()

                    login(request, user)
                    request.session["family_token"] = profile.current_session_token
                    return redirect("family-dashboard")

    return render(request, "dashboard/family_login.html", {"error": error})


def family_logout(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.family_profile
            profile.revoke()
        except FamilyAccount.DoesNotExist:
            pass
        logout(request)
    return redirect("family-login")


# ============================================================
#  FAMILLE - DASHBOARD
# ============================================================

@family_required
def family_dashboard(request):
    profile = request.family_profile
    return render(request, "dashboard/family_dashboard.html", {
        "event_title": EVENT_TITLE,
        "family_name": profile.display_name,
        "family_side": profile.get_side_display(),
        "family_side_code": profile.side,
    })


@family_required
def api_family_my_data(request):
    """Retourne les tables et invites de ma famille + propositions."""
    profile = request.family_profile
    side = profile.side

    # Mes tables
    my_tables = Table.objects.filter(family=side).order_by("name")
    tables_data = []
    for t in my_tables:
        tables_data.append({
            "id": t.id,
            "name": t.name,
            "capacity": t.capacity,
            "guests_count": t.guests_count,
            "available_seats": t.available_seats,
            "is_full": t.is_full,
            "notes": t.notes,
        })

    # Mes invites (avec family=side)
    my_guests = Guest.objects.filter(family=side).order_by("name")
    guests_data = [{
        "id": str(g.id),
        "name": g.name,
        "status": g.status,
        "status_display": g.get_status_display(),
        "table_name": g.table_name,
        "num_persons": g.num_persons,
    } for g in my_guests]

    # Mes propositions
    my_proposals = TableProposal.objects.filter(family=side).select_related(
        "target_table", "target_guest"
    ).order_by("-created_at")
    proposals_data = [_proposal_to_dict(p) for p in my_proposals]

    return JsonResponse({
        "family": {
            "display_name": profile.display_name,
            "side": side,
            "side_label": profile.get_side_display(),
        },
        "tables": tables_data,
        "guests": guests_data,
        "proposals": proposals_data,
        "stats": {
            "tables_count": my_tables.count(),
            "guests_count": my_guests.count(),
            "total_persons": sum(g.num_persons for g in my_guests),
            "pending_proposals": my_proposals.filter(status="pending").count(),
        }
    })


@family_required
@require_http_methods(["POST"])
def api_family_propose(request):
    """Cree une proposition."""
    profile = request.family_profile
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    action = data.get("action")
    if action not in ("create_table", "update_table", "delete_table", "assign_guest", "unassign_guest"):
        return JsonResponse({"error": "Action invalide"}, status=400)

    payload = data.get("payload", {})
    reason = (data.get("reason") or "").strip()[:300]
    target_table_id = data.get("target_table_id")
    target_guest_id = data.get("target_guest_id")

    target_table = None
    if target_table_id:
        try:
            target_table = Table.objects.get(id=target_table_id)
            if target_table.family != profile.side:
                return JsonResponse({"error": "Cette table n'appartient pas a votre famille"}, status=403)
        except Table.DoesNotExist:
            return JsonResponse({"error": "Table introuvable"}, status=404)

    target_guest = None
    if target_guest_id:
        try:
            target_guest = Guest.objects.get(id=target_guest_id)
            if target_guest.family != profile.side:
                return JsonResponse({"error": "Cet invite n'appartient pas a votre famille"}, status=403)
        except Guest.DoesNotExist:
            return JsonResponse({"error": "Invite introuvable"}, status=404)

    # Validations specifiques
    if action == "create_table" and not payload.get("name"):
        return JsonResponse({"error": "Le nom de la table est requis"}, status=400)
    if action in ("update_table", "delete_table") and not target_table:
        return JsonResponse({"error": "Table cible requise"}, status=400)
    if action in ("assign_guest", "unassign_guest") and not target_guest:
        return JsonResponse({"error": "Invite cible requis"}, status=400)
    if action == "assign_guest" and not payload.get("table_name"):
        return JsonResponse({"error": "Table cible requise"}, status=400)

    p = TableProposal.objects.create(
        family=profile.side,
        action=action,
        target_table=target_table,
        target_guest=target_guest,
        payload=json.dumps(payload),
        reason=reason,
        status="pending",
    )
    return JsonResponse({"ok": True, "proposal": _proposal_to_dict(p)}, status=201)

# ============================================================
#  LOGIN / LOGOUT ADMIN - Page personnalisee professionnelle
# ============================================================

def admin_login(request):
    """Page de connexion admin avec design personnalise."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin-dashboard")

    # Si deja connecte mais pas admin, on deconnecte
    if request.user.is_authenticated and not request.user.is_staff:
        logout(request)

    error = request.session.pop("admin_login_error", None)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "Identifiants incorrects."
        elif not user.is_staff:
            error = "Ce compte n'a pas les droits administrateur."
        elif not user.is_active:
            error = "Ce compte est desactive."
        else:
            login(request, user)
            request.session["admin_login_at"] = timezone.now().isoformat()
            # Redirection vers la page demandee initialement
            next_url = request.POST.get("next") or request.GET.get("next") or "/dashboard/"
            return redirect(next_url)

    return render(request, "dashboard/admin_login.html", {
        "error": error,
        "next": request.GET.get("next", "/dashboard/"),
    })


def admin_logout(request):
    """Deconnexion admin."""
    logout(request)
    return redirect("admin-login")


# ============================================================
#  NETTOYAGE : remplacer @admin_required residuels par @admin_required
# ============================================================

# ============================================================
#  BILLING - Configuration et achats de places
# ============================================================

def _billing_to_dict(cfg):
    return {
        'base_limit': cfg.base_limit,
        'extra_places_purchased': cfg.extra_places_purchased,
        'total_limit': cfg.total_limit,
        'current_guests': cfg.current_guests,
        'remaining_slots': cfg.remaining_slots,
        'price_usd': str(cfg.price_per_place_usd),
        'price_cdf': cfg.price_per_place_cdf,
        'is_enabled': cfg.is_enabled,
        'is_at_limit': cfg.is_at_limit,
    }


@admin_required
def billing_page(request):
    return render(request, 'dashboard/billing.html', {'event_title': EVENT_TITLE})


@admin_required
def api_billing_status(request):
    cfg = BillingConfig.get_solo()
    transactions = PaymentTransaction.objects.all()[:20]
    return JsonResponse({
        'config': _billing_to_dict(cfg),
        'transactions': [
            {
                'id': t.id,
                'reference': t.reference,
                'places_purchased': t.places_purchased,
                'amount_usd': str(t.amount_usd),
                'amount_cdf': t.amount_cdf,
                'payment_method': t.get_payment_method_display(),
                'status': t.status,
                'status_label': t.get_status_display(),
                'created_at': t.created_at.isoformat(),
            }
            for t in transactions
        ],
    })


@admin_required
@require_http_methods(['POST'])
def api_billing_purchase(request):
    """Achete des places supplementaires (paiement simule pour l'instant)."""
    cfg = BillingConfig.get_solo()
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    places = int(data.get('places', 1))
    method = data.get('payment_method', 'simulated')

    if places < 1 or places > 500:
        return JsonResponse({'error': 'Nombre de places invalide (1-500)'}, status=400)

    amount_usd = float(cfg.price_per_place_usd) * places
    amount_cdf = cfg.price_per_place_cdf * places
    reference = f"PAY-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    t = PaymentTransaction.objects.create(
        reference=reference,
        places_purchased=places,
        amount_usd=amount_usd,
        amount_cdf=amount_cdf,
        payment_method=method,
        status='completed',
        note=f"Achat de {places} place(s)",
    )

    cfg.extra_places_purchased += places
    cfg.save()

    return JsonResponse({
        'ok': True,
        'transaction': {
            'reference': t.reference,
            'places_purchased': t.places_purchased,
            'amount_usd': str(t.amount_usd),
            'amount_cdf': t.amount_cdf,
        },
        'config': _billing_to_dict(cfg),
    })


@admin_required
@require_http_methods(['POST'])
def api_billing_config_update(request):
    cfg = BillingConfig.get_solo()
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    if 'base_limit' in data:
        cfg.base_limit = max(1, int(data['base_limit']))
    if 'price_per_place_usd' in data:
        cfg.price_per_place_usd = float(data['price_per_place_usd'])
    if 'price_per_place_cdf' in data:
        cfg.price_per_place_cdf = max(1, int(data['price_per_place_cdf']))
    if 'is_enabled' in data:
        cfg.is_enabled = bool(data['is_enabled'])

    cfg.save()
    return JsonResponse({'ok': True, 'config': _billing_to_dict(cfg)})

# ============================================================
#  PORTAIL D'AUTHENTIFICATION UNIQUE
#  Un seul login pour admin / controleur / famille
# ============================================================

def unified_login(request):
    """
    Page de connexion unique. Detecte automatiquement le type de compte.
    Si l'utilisateur est deja connecte mais avec un role different du
    'next' demande, il est deconnecte pour permettre le changement de compte.
    """
    next_url = request.GET.get("next") or request.POST.get("next") or ""

    if request.user.is_authenticated:
        # Determiner le type attendu par next
        expected_type = None
        if next_url.startswith("/dashboard"):
            expected_type = "admin"
        elif next_url.startswith("/famille"):
            expected_type = "family"
        elif next_url.startswith("/controleur"):
            expected_type = "controller"

        # Determiner le type actuel de l'utilisateur
        current_type = None
        if request.user.is_staff:
            current_type = "admin"
        else:
            try:
                request.user.controller_profile
                current_type = "controller"
            except ControllerProfile.DoesNotExist:
                try:
                    request.user.family_profile
                    current_type = "family"
                except FamilyAccount.DoesNotExist:
                    pass

        # Si le next demande un role DIFFERENT du role actuel -> deconnecter
        if expected_type and current_type and expected_type != current_type:
            logout(request)
            # On continue vers l'affichage du formulaire
        elif current_type:
            # Meme role -> redirection normale
            if current_type == "admin":
                return redirect("admin-dashboard")
            elif current_type == "controller":
                try:
                    profile = request.user.controller_profile
                    if profile.is_active and request.session.get("controller_token") == profile.current_session_token:
                        return redirect("control-dashboard")
                except ControllerProfile.DoesNotExist:
                    pass
                logout(request)
            elif current_type == "family":
                try:
                    profile = request.user.family_profile
                    if profile.is_active and request.session.get("family_token") == profile.current_session_token:
                        return redirect("family-dashboard")
                except FamilyAccount.DoesNotExist:
                    pass
                logout(request)
            else:
                logout(request)
        else:
            logout(request)

    error = request.session.pop("unified_login_error", None)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        next_url = request.POST.get("next", "")

        if not username or not password:
            error = "Identifiant et mot de passe requis."
        else:
            user = authenticate(request, username=username, password=password)

            if user is None:
                error = "Identifiants incorrects."
            elif not user.is_active:
                error = "Ce compte est desactive."
            elif user.is_staff:
                login(request, user)
                request.session["admin_login_at"] = timezone.now().isoformat()
                if next_url and next_url.startswith("/dashboard"):
                    return redirect(next_url)
                return redirect("admin-dashboard")
            else:
                # Controleur ou famille
                profile = None
                profile_type = None

                try:
                    profile = user.controller_profile
                    profile_type = "controller"
                except ControllerProfile.DoesNotExist:
                    pass

                if not profile:
                    try:
                        profile = user.family_profile
                        profile_type = "family"
                    except FamilyAccount.DoesNotExist:
                        pass

                if not profile:
                    error = "Ce compte n'est associe a aucun espace."
                elif not profile.is_active:
                    error = "Votre acces a ete revoque. Contactez l'administrateur."
                else:
                    profile.current_session_token = uuid.uuid4().hex
                    profile.current_session_started = timezone.now()
                    profile.last_login_ip = request.META.get("REMOTE_ADDR")
                    profile.save()

                    login(request, user)

                    if profile_type == "controller":
                        request.session["controller_token"] = profile.current_session_token
                        return redirect("control-dashboard")
                    else:
                        request.session["family_token"] = profile.current_session_token
                        return redirect("family-dashboard")

    return render(request, "dashboard/unified_login.html", {
        "error": error,
        "next": next_url,
    })



def unified_logout(request):
    """
    Deconnexion unique. Revoque les sessions controleur/famille
    et deconnecte l'utilisateur.
    """
    if request.user.is_authenticated:
        # Revoquer la session controleur si elle existe
        try:
            request.user.controller_profile.revoke()
        except ControllerProfile.DoesNotExist:
            pass
        # Revoquer la session famille si elle existe
        try:
            request.user.family_profile.revoke()
        except FamilyAccount.DoesNotExist:
            pass
        logout(request)
    return redirect("unified-login")


def legacy_login_redirect(request):
    """Redirige les anciennes URLs de login vers /auth/login/."""
    next_url = request.GET.get("next", "")
    if next_url:
        from urllib.parse import quote
        return redirect(f"/auth/login/?next={quote(next_url)}")
    return redirect("unified-login")


def legacy_logout_redirect(request):
    """Redirige les anciennes URLs de logout vers /auth/logout/."""
    return redirect("unified-logout")

# ============================================================
#  FAMILLE - AJOUT D'INVITES + IMPORT EXCEL
# ============================================================

@family_required
def family_guests_page(request):
    """Page de gestion des invites pour la famille connectee."""
    profile = request.family_profile
    usage = get_billing_usage()
    return render(request, "dashboard/family_guests_manage.html", {
        "event_title": EVENT_TITLE,
        "family_name": profile.display_name,
        "family_side": profile.get_side_display(),
        "family_side_code": profile.side,
        "usage": usage,
    })


@family_required
def api_family_usage(request):
    """Retourne l'utilisation actuelle pour la famille (par cote)."""
    profile = request.family_profile
    usage = get_billing_usage(side=profile.side)

    # Mes demandes
    my_requests = GuestRequest.objects.filter(
        family_account=profile
    ).order_by("-created_at")[:50]

    my_requests_data = [{
        "id": r.id,
        "full_name": r.full_name,
        "phone": r.phone,
        "guest_status": r.guest_status,
        "guest_status_display": r.get_guest_status_display(),
        "table_name": r.table_name,
        "request_status": r.request_status,
        "request_status_display": r.get_request_status_display(),
        "created_at": r.created_at.isoformat(),
        "admin_note": r.admin_note,
    } for r in my_requests]

    my_pending = sum(1 for r in my_requests if r.request_status == "pending")
    my_awaiting = sum(1 for r in my_requests if r.request_status == "awaiting_payment")
    my_approved = sum(1 for r in my_requests if r.request_status == "approved")
    my_rejected = sum(1 for r in my_requests if r.request_status == "rejected")

    return JsonResponse({
        "usage": usage,
        "requests": my_requests_data,
        "my_stats": {
            "pending": my_pending,
            "awaiting_payment": my_awaiting,
            "approved": my_approved,
            "rejected": my_rejected,
            "total": len(my_requests),
        },
    })


@family_required
@require_http_methods(["POST"])
def api_family_add_guest(request):
    """La famille ajoute un invite (cree une GuestRequest)."""
    profile = request.family_profile
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    phone = (data.get("phone") or "").strip()[:20]
    guest_status = data.get("guest_status") or "single"
    table_name = (data.get("table_name") or "").strip()[:50]
    note = (data.get("note") or "").strip()[:300]

    if not first_name or not last_name:
        return JsonResponse({"error": "Nom et prenom requis"}, status=400)
    if guest_status not in ("single", "couple"):
        return JsonResponse({"error": "Statut invalide"}, status=400)

    # Verifier la limite
    usage = get_billing_usage(side=profile.side)
    if usage["remaining"] < 1:
        return JsonResponse({
            "error": "limit_reached",
            "message": "Limite atteinte. Demandez au super administrateur d'acheter des places.",
            "usage": usage,
        }, status=402)

    # Creer la demande
    req = GuestRequest.objects.create(
        family_account=profile,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        guest_status=guest_status,
        table_name=table_name,
        family_note=note,
        request_status="pending",
    )

    # Auto-approuver si configure
    usage_after = get_billing_usage(side=profile.side)
    if usage_after["auto_approve"] and usage_after["remaining"] >= 0:
        try:
            create_guest_from_request(req)
            return JsonResponse({
                "ok": True,
                "auto_approved": True,
                "guest_name": req.full_name,
                "request": {
                    "id": req.id,
                    "full_name": req.full_name,
                    "request_status": req.request_status,
                },
            }, status=201)
        except Exception as e:
            pass

    return JsonResponse({
        "ok": True,
        "auto_approved": False,
        "request": {
            "id": req.id,
            "full_name": req.full_name,
            "request_status": req.request_status,
            "message": "Demande envoyee. En attente d'approbation du super administrateur.",
        },
    }, status=201)


@family_required
@require_http_methods(["POST"])
def api_family_import_excel(request):
    """Import Excel fait par une famille."""
    profile = request.family_profile

    if "file" not in request.FILES:
        return JsonResponse({"error": "Aucun fichier fourni"}, status=400)

    excel_file = request.FILES["file"]
    if not excel_file.name.lower().endswith((".xlsx", ".xls")):
        return JsonResponse({"error": "Format accepte : .xlsx ou .xls"}, status=400)

    try:
        file_bytes = excel_file.read()
    except Exception as e:
        return JsonResponse({"error": f"Erreur lecture : {e}"}, status=400)

    # Parser le fichier
    success, errors, requests_list = import_excel(file_bytes, profile)

    if success == 0:
        return JsonResponse({
            "error": "Aucun invite valide dans le fichier",
            "errors": errors[:10],
        }, status=400)

    # Verifier la limite
    usage = get_billing_usage(side=profile.side)
    remaining = usage["remaining"]

    # Creer les GuestRequest
    created_requests = []
    auto_approved = 0
    awaiting_payment = 0
    pending = 0

    for req in requests_list:
        # Recalculer les places disponibles
        current_usage = get_billing_usage(side=profile.side)

        if current_usage["remaining"] > 0:
            # Place disponible
            if current_usage["auto_approve"]:
                req.request_status = "pending"
                req.save()
                try:
                    create_guest_from_request(req)
                    auto_approved += 1
                except Exception:
                    req.save()
                    pending += 1
            else:
                req.request_status = "pending"
                req.save()
                pending += 1
        else:
            # Plus de place
            req.request_status = "awaiting_payment"
            req.save()
            awaiting_payment += 1

        created_requests.append(req)

    # Enregistrer l'historique
    FamilyImport.objects.create(
        family_account=profile,
        filename=excel_file.name[:200],
        total_rows=success + len(errors),
        success_count=success,
        error_count=len(errors),
        errors_json=json.dumps(errors),
    )

    return JsonResponse({
        "ok": True,
        "success": success,
        "errors": errors,
        "auto_approved": auto_approved,
        "pending": pending,
        "awaiting_payment": awaiting_payment,
        "usage": get_billing_usage(),
    })


@family_required
def api_family_download_template(request):
    """Telecharge le modele Excel."""
    try:
        content = generate_template()
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="modele_invites.xlsx"'
        return response
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ============================================================
#  ADMIN - VALIDATION DES DEMANDES FAMILLES
# ============================================================

@admin_required
def family_guests_admin_page(request):
    return render(request, "dashboard/family_guests.html", {"event_title": EVENT_TITLE})


@admin_required
def api_admin_family_requests(request):
    """Liste toutes les demandes familles pour l'admin."""
    status_filter = request.GET.get("status", "all")

    qs = GuestRequest.objects.select_related("family_account", "guest").all()
    if status_filter != "all":
        qs = qs.filter(request_status=status_filter)
    qs = qs.order_by("-created_at")

    data = []
    for r in qs:
        data.append({
            "id": r.id,
            "family_name": r.family_account.display_name,
            "family_side": r.family_account.side,
            "family_side_display": r.family_account.get_side_display(),
            "full_name": r.full_name,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "phone": r.phone,
            "guest_status": r.guest_status,
            "guest_status_display": r.get_guest_status_display(),
            "table_name": r.table_name,
            "request_status": r.request_status,
            "request_status_display": r.get_request_status_display(),
            "family_note": r.family_note,
            "admin_note": r.admin_note,
            "created_at": r.created_at.isoformat(),
        })

    counts = {
        "pending": GuestRequest.objects.filter(request_status="pending").count(),
        "awaiting_payment": GuestRequest.objects.filter(request_status="awaiting_payment").count(),
        "approved": GuestRequest.objects.filter(request_status="approved").count(),
        "rejected": GuestRequest.objects.filter(request_status="rejected").count(),
    }

    return JsonResponse({
        "requests": data,
        "counts": counts,
        "usage": get_billing_usage(),
    })


@admin_required
@require_http_methods(["POST"])
def api_admin_approve_request(request, request_id):
    req = get_object_or_404(GuestRequest, id=request_id)
    if req.request_status not in ("pending", "awaiting_payment"):
        return JsonResponse({"error": "Cette demande est deja traitee"}, status=400)

    if req.request_status == "awaiting_payment":
        return JsonResponse({"error": "Paiement requis avant approbation"}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    try:
        create_guest_from_request(req)
    except Exception as e:
        return JsonResponse({"error": f"Erreur creation invite : {e}"}, status=500)

    if data.get("admin_note"):
        req.admin_note = data["admin_note"][:300]
        req.save()

    return JsonResponse({"ok": True, "guest_name": req.full_name})


@admin_required
@require_http_methods(["POST"])
def api_admin_reject_request(request, request_id):
    req = get_object_or_404(GuestRequest, id=request_id)
    if req.request_status not in ("pending", "awaiting_payment"):
        return JsonResponse({"error": "Deja traitee"}, status=400)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    req.request_status = "rejected"
    req.admin_note = (data.get("admin_note") or "").strip()[:300]
    req.reviewed_at = timezone.now()
    req.save()
    return JsonResponse({"ok": True})


@admin_required
@require_http_methods(["POST"])
def api_admin_bulk_approve(request):
    """Approuve toutes les demandes en attente (pending seulement)."""
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    req_ids = data.get("ids", [])
    if req_ids:
        qs = GuestRequest.objects.filter(id__in=req_ids, request_status="pending")
    else:
        qs = GuestRequest.objects.filter(request_status="pending")

    approved = 0
    errors = []
    for req in qs:
        try:
            create_guest_from_request(req)
            approved += 1
        except Exception as e:
            errors.append({"id": req.id, "name": req.full_name, "error": str(e)})

    return JsonResponse({
        "ok": True,
        "approved_count": approved,
        "errors": errors,
    })

# ============================================================
#  ADMIN - AJOUTER DIRECTEMENT UN INVITE
# ============================================================

@admin_required
@require_http_methods(["POST"])
def admin_add_guest_to_family(request):
    """Permet a l'admin d'ajouter un invite directement (sans passer par une demande)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    phone = (data.get("phone") or "").strip()[:20]
    guest_status = data.get("guest_status") or "single"
    table_name = (data.get("table_name") or "").strip()[:50]
    family_side = data.get("family") or ""

    if not first_name or not last_name:
        return JsonResponse({"error": "Nom et prenom requis"}, status=400)
    if guest_status not in ("single", "couple"):
        return JsonResponse({"error": "Statut invalide"}, status=400)
    if family_side not in ("", "groom", "bride"):
        return JsonResponse({"error": "Cote famille invalide"}, status=400)

    # Verifier la limite
    cfg = BillingConfig.get_solo()
    if cfg.is_enabled and cfg.is_at_limit:
        return JsonResponse({
            "error": "limit_reached",
            "current": cfg.current_guests,
            "limit": cfg.total_limit,
            "price_usd": str(cfg.price_per_place_usd),
            "price_cdf": cfg.price_per_place_cdf,
        }, status=402)

    # Creer directement
    guest = Guest.objects.create(
        name=f"{last_name} {first_name}".strip(),
        phone=phone,
        status=guest_status,
        table_name=table_name,
        family=family_side,
    )

    return JsonResponse({
        "ok": True,
        "guest": {
            "id": str(guest.id),
            "name": guest.name,
            "status": guest.status,
            "table_name": guest.table_name,
            "family": guest.family,
        },
    }, status=201)


@admin_required
@require_http_methods(["POST"])
def admin_import_excel_any_family(request):
    """Permet a l'admin d'importer un Excel pour une famille specifique."""
    if "file" not in request.FILES:
        return JsonResponse({"error": "Aucun fichier"}, status=400)

    excel_file = request.FILES["file"]
    family_side = request.POST.get("family", "")

    if family_side not in ("", "groom", "bride"):
        return JsonResponse({"error": "Cote famille invalide"}, status=400)

    if not excel_file.name.lower().endswith((".xlsx", ".xls")):
        return JsonResponse({"error": "Format .xlsx ou .xls uniquement"}, status=400)

    # Chercher la FamilyAccount correspondante
    family_account = None
    if family_side:
        family_account = FamilyAccount.objects.filter(side=family_side, is_active=True).first()
        if not family_account:
            return JsonResponse({"error": f"Aucune famille active pour le cote {family_side}"}, status=400)

    try:
        file_bytes = excel_file.read()
    except Exception as e:
        return JsonResponse({"error": f"Lecture impossible : {e}"}, status=400)

    from guests.excel_utils import import_excel
    success, errors, requests_list = import_excel(file_bytes, family_account) if family_account else (0, [{"row": 0, "error": "Pas de famille"}], [])

    if not family_account:
        # Import direct sans famille
        from openpyxl import load_workbook
        from io import BytesIO
        try:
            wb = load_workbook(BytesIO(file_bytes), data_only=True)
            ws = wb.active
        except Exception as e:
            return JsonResponse({"error": f"Excel invalide : {e}"}, status=400)

        created = 0
        errors = []
        cfg = BillingConfig.get_solo()

        for row_idx in range(2, ws.max_row + 1):
            last_name = ws.cell(row=row_idx, column=1).value
            first_name = ws.cell(row=row_idx, column=2).value
            phone = ws.cell(row=row_idx, column=3).value or ""
            status_val = ws.cell(row=row_idx, column=4).value
            table = ws.cell(row=row_idx, column=5).value or ""

            if not last_name and not first_name:
                continue

            if cfg.is_at_limit:
                errors.append({"row": row_idx, "error": "Limite atteinte"})
                continue

            if not last_name or not first_name:
                errors.append({"row": row_idx, "error": "Nom ou prenom manquant"})
                continue

            # Parser statut
            v_low = str(status_val).lower() if status_val else "single"
            gs = "couple" if v_low in ("couple", "2", "duo") else "single"

            try:
                Guest.objects.create(
                    name=f"{str(last_name).strip()} {str(first_name).strip()}",
                    phone=str(phone).strip()[:20],
                    status=gs,
                    table_name=str(table).strip()[:50],
                    family="",
                )
                created += 1
            except Exception as e:
                errors.append({"row": row_idx, "error": str(e)})

        return JsonResponse({
            "ok": True,
            "success": created,
            "errors": errors,
            "family_side": "",
        })

    # Avec famille : creer les GuestRequest puis auto-approuver
    created = 0
    auto_approved = 0
    awaiting = 0

    for req in requests_list:
        from guests.excel_utils import get_billing_usage
        current = get_billing_usage()
        if current["remaining"] > 0:
            req.save()
            from guests.excel_utils import create_guest_from_request
            try:
                create_guest_from_request(req)
                auto_approved += 1
            except Exception as e:
                errors.append({"row": 0, "error": str(e)})
            created += 1
        else:
            req.request_status = "awaiting_payment"
            req.save()
            awaiting += 1

    return JsonResponse({
        "ok": True,
        "success": created + awaiting,
        "auto_approved": auto_approved,
        "awaiting_payment": awaiting,
        "errors": errors,
        "family_side": family_side,
    })

@admin_required
def admin_download_template(request):
    """Telechargement du modele Excel cote admin."""
    from guests.excel_utils import generate_template
    try:
        content = generate_template()
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="modele_invites.xlsx"'
        return response
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ============================================================
#  ADMIN - CONFIGURATION DES QUOTAS PAR COTE
# ============================================================

@admin_required
@require_http_methods(["POST"])
def api_billing_side_config(request):
    """Configure les quotas pour chaque cote (groom + bride)."""
    cfg = BillingConfig.get_solo()
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    if "groom_quota" in data:
        cfg.groom_quota = max(1, int(data["groom_quota"]))
    if "bride_quota" in data:
        cfg.bride_quota = max(1, int(data["bride_quota"]))

    # Mettre a jour base_limit en consequence
    cfg.base_limit = cfg.groom_quota + cfg.bride_quota
    cfg.save()

    return JsonResponse({
        "ok": True,
        "config": {
            "groom_quota": cfg.groom_quota,
            "bride_quota": cfg.bride_quota,
            "total_limit": cfg.total_limit,
        },
    })


@admin_required
@require_http_methods(["POST"])
def api_billing_purchase_for_side(request):
    """Achete des places supplementaires pour un cote specifique."""
    cfg = BillingConfig.get_solo()
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    side = data.get("side")
    places = int(data.get("places", 1))

    if side not in ("groom", "bride"):
        return JsonResponse({"error": "Cote invalide"}, status=400)
    if places < 1 or places > 500:
        return JsonResponse({"error": "Nombre de places invalide (1-500)"}, status=400)

    amount_usd = float(cfg.price_per_place_usd) * places
    amount_cdf = cfg.price_per_place_cdf * places
    reference = f"PAY-{side.upper()}-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    PaymentTransaction.objects.create(
        reference=reference,
        places_purchased=places,
        amount_usd=amount_usd,
        amount_cdf=amount_cdf,
        payment_method=data.get("payment_method", "simulated"),
        status="completed",
        note=f"Achat {places} place(s) pour cote {side}",
    )

    if side == "groom":
        cfg.groom_extra_purchased += places
    else:
        cfg.bride_extra_purchased += places
    cfg.extra_places_purchased += places
    cfg.save()

    return JsonResponse({
        "ok": True,
        "reference": reference,
        "places": places,
        "amount_usd": str(amount_usd),
        "amount_cdf": amount_cdf,
        "config": {
            "groom_total": cfg.groom_total_limit,
            "bride_total": cfg.bride_total_limit,
            "total": cfg.total_limit,
        },
    })

# ============================================================
#  PAGES ADMIN - GUESTS + INVITATIONS (avec theme dashboard)
# ============================================================

@admin_required
def admin_guests_page(request):
    """Page dediee de gestion des invites (theme dashboard)."""
    return render(request, "dashboard/admin_guests.html", {"event_title": EVENT_TITLE})


@admin_required
def admin_invitations_page(request):
    """Page des invitations avec theme dashboard."""
    guests = Guest.objects.all().order_by("name")
    data = []
    for g in guests:
        rel = reverse("public-invitation", args=[g.qr_token])
        abs_url = request.build_absolute_uri(rel)
        phone_clean = "".join(c for c in (g.phone or "") if c.isdigit())
        message = (
            f"*Mariage de Juguel & Viviane*\n\n"
            f"Bonjour {g.name},\n\n"
            f"Voici votre invitation personnelle :\n"
            f"{abs_url}\n\n"
            f"Table : {g.table_name}\n"
            f"Personnes : {g.get_status_display()}"
        )
        from urllib.parse import quote
        whatsapp_url = (
            f"https://wa.me/{phone_clean}?text={quote(message)}"
            if phone_clean else f"https://wa.me/?text={quote(message)}"
        )
        data.append({
            "guest": g,
            "url": abs_url,
            "whatsapp_url": whatsapp_url,
            "has_phone": bool(phone_clean),
        })

    return render(request, "dashboard/admin_invitations.html", {
        "event_title": EVENT_TITLE,
        "invitations": data,
    })

# ============================================================
#  CHANGEMENT DE ROLE (deconnexion + redirection login)
# ============================================================

def switch_role(request, role):
    """
    Deconnecte l'utilisateur actuel et redirige vers le login
    du role demande.
    """
    from django.contrib.auth import logout

    # Deconnecter l'utilisateur actuel
    logout(request)

    # Rediriger vers le login approprie
    valid_roles = {
        "admin": "/dashboard/",
        "controleur": "/controleur/",
        "famille": "/famille/",
    }

    target = valid_roles.get(role, "/dashboard/")

    from urllib.parse import quote
    return redirect(f"/auth/login/?next={quote(target)}")

# ============================================================
#  HOME - Redirection intelligente selon le role
# ============================================================

def home_redirect(request):
    """
    Redirige l'utilisateur vers son dashboard selon son role :
    - Admin       -> /dashboard/
    - Controleur  -> /controleur/
    - Famille     -> /famille/
    - Anonyme     -> /auth/login/
    """
    if not request.user.is_authenticated:
        return redirect("unified-login")

    if request.user.is_staff:
        return redirect("admin-dashboard")

    # Verifier si controleur
    try:
        profile = request.user.controller_profile
        if profile.is_active and request.session.get("controller_token") == profile.current_session_token:
            return redirect("control-dashboard")
    except ControllerProfile.DoesNotExist:
        pass

    # Verifier si famille
    try:
        profile = request.user.family_profile
        if profile.is_active and request.session.get("family_token") == profile.current_session_token:
            return redirect("family-dashboard")
    except FamilyAccount.DoesNotExist:
        pass

    # Connecte mais aucun profil valide
    return redirect("unified-login")