import io
import qrcode
from urllib.parse import quote
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Guest

# --- Evenement ---
EVENT_TITLE     = 'Mariage de Juguel & Viviane'
EVENT_DATE      = '19 Decembre 2026'
EVENT_VENUE     = 'Kinshasa, RDC'
EVENT_MESSAGE   = 'C\'est avec une joie immense que nous vous convions a celebrer notre union.'
EVENT_HOST      = 'Juguel & Viviane'

# --- Donnees specifiques a l'invitation ---
EVENT_FAMILIES   = 'Familles MBUMBA & TUNIENO'
EVENT_GROOM      = 'Juguel'
EVENT_BRIDE      = 'Viviane'
EVENT_MAIN_DATE  = '19 Decembre 2026'
EVENT_THEME      = 'Amour'
EVENT_DRESS_CODE = 'Bleu pale & Rose entremêle'

EVENT_PROGRAMS = [
    {
        'icon': 'fa-ring',
        'title': 'Mariage Civil',
        'date': 'Jeudi 17 Decembre 2026',
        'place': 'Commune de Mont-Ngafula',
    },
    {
        'icon': 'fa-crown',
        'title': 'Ceremonie Coutumiere',
        'date': 'Jeudi 17 Decembre 2026',
        'place': 'Salle (a preciser)',
    },
    {
        'icon': 'fa-church',
        'title': 'Benediction Nuptiale',
        'date': 'Samedi 19 Decembre 2026 a 11h00',
        'place': 'Eglise Christ Emmanuel',
    },
    {
        'icon': 'fa-champagne-glasses',
        'title': 'Soiree Dansante',
        'date': 'Samedi 19 Decembre 2026 a 19h00',
        'place': 'Salle Panafricaine, Cite Verte, Selembao',
    },
]


def _render_qr_png(token: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


@api_view(['GET'])
def download_guest_list(request):
    guests = Guest.objects.all().values(
        'id', 'name', 'status', 'table_name', 'qr_token', 'is_checked_in'
    )
    return Response(list(guests))


@api_view(['POST'])
def sync_checkin(request):
    results = request.data.get('checkins', [])
    updated = []
    for item in results:
        try:
            guest = Guest.objects.get(qr_token=item['qr_token'])
            if not guest.is_checked_in:
                guest.is_checked_in = True
                guest.checked_in_at = item.get('timestamp')
                guest.save()
                updated.append(guest.qr_token)
        except Guest.DoesNotExist:
            pass
    return Response({'synced': updated})


def qr_png(request, token):
    guest = get_object_or_404(Guest, qr_token=token)
    png = _render_qr_png(guest.qr_token)
    return HttpResponse(png, content_type='image/png')


def qr_download(request, token):
    guest = get_object_or_404(Guest, qr_token=token)
    png = _render_qr_png(guest.qr_token)
    response = HttpResponse(png, content_type='image/png')
    safe_name = (guest.name or 'invite').replace(' ', '_').replace('/', '_')
    response['Content-Disposition'] = f'attachment; filename="qr_{safe_name}.png"'
    return response


def public_invitation(request, token):
    from guests.models import GuestConfirmation, Wish, DrinkOrder, Drink
    guest = get_object_or_404(Guest, qr_token=token)

    confirmation = GuestConfirmation.objects.filter(guest=guest).first()
    wishes = list(guest.wishes.filter(is_approved=True).order_by('-created_at')[:20])
    orders = list(guest.drink_orders.exclude(status='cancelled').order_by('-created_at'))
    drinks = list(Drink.objects.filter(is_available=True).order_by('category', 'name'))
    # Filtrer les boissons en stock
    drinks = [d for d in drinks if d.is_in_stock]

    return render(request, 'guests/public_invitation.html', {
        'guest': guest,
        'families': EVENT_FAMILIES,
        'couple_groom': EVENT_GROOM,
        'couple_bride': EVENT_BRIDE,
        'main_date': EVENT_MAIN_DATE,
        'programs': EVENT_PROGRAMS,
        'theme': EVENT_THEME,
        'dress_code': EVENT_DRESS_CODE,
        'confirmation': confirmation,
        'wishes': wishes,
        'orders': orders,
        'drinks': drinks,
        'event_title': EVENT_TITLE,
        'event_date': EVENT_DATE,
        'event_venue': EVENT_VENUE,
        'event_message': EVENT_MESSAGE,
        'event_host': EVENT_HOST,
    })

def invitation_list(request):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    guests = Guest.objects.all().order_by('name')
    data = []
    for g in guests:
        rel = reverse('public-invitation', args=[g.qr_token])
        abs_url = request.build_absolute_uri(rel)

        whatsapp_message = (
            f'*{EVENT_TITLE}*\n\n'
            f'Bonjour {g.name},\n\n'
            f'{EVENT_MESSAGE}\n\n'
            f'*Date :* {EVENT_MAIN_DATE}\n'
            f'*Table :* {g.table_name}\n'
            f'*Personnes :* {g.get_status_display()}\n\n'
            f'Voici votre invitation personnelle :\n'
            f'{abs_url}\n\n'
            f'A bientot !\n'
            f'{EVENT_HOST}'
        )

        phone_clean = ''.join(c for c in (g.phone or '') if c.isdigit())

        if phone_clean:
            whatsapp_url = f'https://wa.me/{phone_clean}?text={quote(whatsapp_message)}'
        else:
            whatsapp_url = f'https://wa.me/?text={quote(whatsapp_message)}'

        data.append({
            'guest': g,
            'url': abs_url,
            'whatsapp_url': whatsapp_url,
            'whatsapp_message': whatsapp_message,
            'has_phone': bool(phone_clean),
        })

    return render(request, 'guests/invitation_list.html', {'data': data})

# ============================================================
#  ENDPOINTS PUBLICS (identifies par token, sans login)
# ============================================================
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.http import JsonResponse
from guests.models import GuestConfirmation, Wish, DrinkOrder, Drink
import json


@csrf_exempt
def api_invitation_info(request, token):
    if request.method != "GET":
        return JsonResponse({"error": "GET uniquement"}, status=405)
    guest = get_object_or_404(Guest, qr_token=token)
    conf = GuestConfirmation.objects.filter(guest=guest).first()
    drinks = Drink.objects.filter(is_available=True).order_by("category", "name")
    drinks = [d for d in drinks if d.is_in_stock]
    orders = list(guest.drink_orders.exclude(status="cancelled").order_by("-created_at"))
    wishes = list(guest.wishes.filter(is_approved=True).order_by("-created_at")[:20])
    return JsonResponse({
        "guest": {
            "name": guest.name,
            "status": guest.status,
            "table_name": guest.table_name,
        },
        "confirmation": {
            "confirmed": conf.confirmed if conf else False,
            "num_persons": conf.num_persons_confirmed if conf else 0,
            "message": conf.message if conf else "",
            "confirmed_at": conf.confirmed_at.isoformat() if conf and conf.confirmed_at else None,
        } if conf else None,
        "drinks": [
            {"id": d.id, "name": d.name, "description": d.description,
             "category": d.category, "category_label": d.get_category_display()}
            for d in drinks
        ],
        "orders": [
            {"id": o.id, "drink_name": o.drink.name, "quantity": o.quantity,
             "status": o.status, "status_label": o.get_status_display(),
             "created_at": o.created_at.isoformat()}
            for o in orders
        ],
        "wishes": [
            {"id": w.id, "message": w.message, "created_at": w.created_at.isoformat()}
            for w in wishes
        ],
    })


@csrf_exempt
def api_confirm_attendance(request, token):
    if request.method != "POST":
        return JsonResponse({"error": "POST uniquement"}, status=405)
    guest = get_object_or_404(Guest, qr_token=token)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    confirmed = bool(data.get("confirmed", False))
    num_persons = int(data.get("num_persons", 1))
    message = (data.get("message") or "").strip()[:500]

    # Valider le nombre de personnes selon le statut de l'invite
    max_persons = 2 if guest.status == "couple" else 1
    if num_persons < 1 or num_persons > max_persons:
        num_persons = max_persons

    conf, _ = GuestConfirmation.objects.get_or_create(guest=guest)
    conf.confirmed = confirmed
    conf.num_persons_confirmed = num_persons if confirmed else 0
    conf.message = message
    conf.confirmed_at = timezone.now() if confirmed else None
    conf.save()

    return JsonResponse({
        "ok": True,
        "confirmed": conf.confirmed,
        "num_persons": conf.num_persons_confirmed,
        "message": conf.message,
    })


@csrf_exempt
def api_add_wish(request, token):
    if request.method != "POST":
        return JsonResponse({"error": "POST uniquement"}, status=405)
    guest = get_object_or_404(Guest, qr_token=token)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    message = (data.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Message vide"}, status=400)
    if len(message) > 1000:
        return JsonResponse({"error": "Message trop long (max 1000)"}, status=400)

    wish = Wish.objects.create(guest=guest, message=message)
    return JsonResponse({"ok": True, "wish": {
        "id": wish.id, "message": wish.message, "created_at": wish.created_at.isoformat()
    }})


@csrf_exempt
def api_order_drink(request, token):
    """Enregistre les boissons choisies (1 pour singleton, 2 pour couple)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST uniquement"}, status=405)
    
    guest = get_object_or_404(Guest, qr_token=token)
    
    # Doit avoir confirme sa presence
    if guest.rsvp_status != 'confirmed':
        return JsonResponse({"error": "Veuillez confirmer votre presence d'abord"}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)

    drink_id_1 = data.get("drink_id_1")
    drink_id_2 = data.get("drink_id_2")

    if not drink_id_1:
        return JsonResponse({"error": "Boisson 1 requise"}, status=400)

    # Verifier que les boissons existent
    try:
        drink1 = Drink.objects.get(id=drink_id_1, is_available=True)
    except Drink.DoesNotExist:
        return JsonResponse({"error": "Boisson 1 indisponible"}, status=404)

    drink2 = None
    if guest.status == 'couple' and drink_id_2:
        try:
            drink2 = Drink.objects.get(id=drink_id_2, is_available=True)
        except Drink.DoesNotExist:
            return JsonResponse({"error": "Boisson 2 indisponible"}, status=404)

    # Supprimer les anciennes commandes
    guest.drink_orders.all().delete()

    # Creer les nouvelles
    DrinkOrder.objects.create(guest=guest, drink=drink1, quantity=1)
    if drink2:
        DrinkOrder.objects.create(guest=guest, drink=drink2, quantity=1)

    return JsonResponse({"ok": True, "message": "Boissons enregistrees"})


