"""Utilitaires pour import/export Excel des invites."""
import json
from io import BytesIO
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Guest, GuestRequest, BillingConfig, FamilyAccount


def get_billing_usage(side=None):
    """
    Retourne l'utilisation actuelle de la limite.
    Si side='groom' ou 'bride', retourne les infos du cote specifique.
    """
    cfg = BillingConfig.get_solo()

    if side in ("groom", "bride"):
        # Stats specifiques a un cote
        side_guests = Guest.objects.filter(family=side).count()
        side_limit = cfg.get_side_limit(side)
        side_remaining = max(0, side_limit - side_guests)

        # Demandes en attente de ce cote
        pending_count = GuestRequest.objects.filter(
            family_account__side=side,
            request_status="pending"
        ).count()
        awaiting_count = GuestRequest.objects.filter(
            family_account__side=side,
            request_status="awaiting_payment"
        ).count()

        return {
            "side": side,
            "side_limit": side_limit,
            "used": side_guests,
            "guests": side_guests,
            "pending": pending_count,
            "awaiting_payment": awaiting_count,
            "limit": side_limit,
            "remaining": side_remaining,
            "is_full": side_guests >= side_limit,
            "price_usd": str(cfg.price_per_place_usd),
            "price_cdf": cfg.price_per_place_cdf,
            "auto_approve": cfg.auto_approve_under_limit,
            # Global
            "global_limit": cfg.total_limit,
            "global_used": cfg.current_guests,
            "groom_quota": cfg.groom_quota,
            "bride_quota": cfg.bride_quota,
        }

    # Stats globales
    guests = Guest.objects.count()
    pending = GuestRequest.objects.filter(
        request_status__in=["pending", "awaiting_payment"]
    ).count()
    awaiting = GuestRequest.objects.filter(request_status="awaiting_payment").count()
    used = guests + pending - awaiting

    return {
        "used": used,
        "guests": guests,
        "pending": pending - awaiting,
        "awaiting_payment": awaiting,
        "limit": cfg.total_limit,
        "remaining": max(0, cfg.total_limit - used),
        "is_full": used >= cfg.total_limit,
        "price_usd": str(cfg.price_per_place_usd),
        "price_cdf": cfg.price_per_place_cdf,
        "auto_approve": cfg.auto_approve_under_limit,
        # Details par cote
        "groom_quota": cfg.groom_quota,
        "bride_quota": cfg.bride_quota,
        "groom_extra": cfg.groom_extra_purchased,
        "bride_extra": cfg.bride_extra_purchased,
        "groom_total": cfg.groom_total_limit,
        "bride_total": cfg.bride_total_limit,
        "groom_used": Guest.objects.filter(family="groom").count(),
        "bride_used": Guest.objects.filter(family="bride").count(),
        "groom_remaining": cfg.get_side_remaining("groom"),
        "bride_remaining": cfg.get_side_remaining("bride"),
    }

def generate_template():
    """Genere un modele Excel vide avec les bons en-tetes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Invites"

    headers = ["Nom", "Prenom", "Telephone", "Statut", "Table"]
    header_fill = PatternFill("solid", fgColor="C25E25")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border
        ws.column_dimensions[get_column_letter(col)].width = 20

    # Exemple ligne 2
    exemple = ["Dupont", "Jean", "243812345678", "couple", "Table 1"]
    for col, v in enumerate(exemple, 1):
        c = ws.cell(row=2, column=col, value=v)
        c.font = Font(italic=True, color="999999")
        c.border = border

    # Instructions
    ws2 = wb.create_sheet("Instructions")
    ws2["A1"] = "INSTRUCTIONS D'IMPORT"
    ws2["A1"].font = Font(bold=True, size=14, color="C25E25")
    instructions = [
        "",
        "1. Remplissez la feuille 'Invites' avec vos invites",
        "2. Colonnes obligatoires : Nom, Prenom",
        "3. Colonnes optionnelles : Telephone, Statut, Table",
        "",
        "FORMAT DU STATUT :",
        "  - 'single' ou '1' ou 'singleton' -> 1 personne",
        "  - 'couple' ou '2' -> 2 personnes",
        "",
        "FORMAT DU TELEPHONE :",
        "  - Format international sans + (ex: 243812345678)",
        "",
        "SUPPRIMEZ la ligne d'exemple avant d'importer !",
    ]
    for i, line in enumerate(instructions, 2):
        ws2[f"A{i}"] = line
    ws2.column_dimensions["A"].width = 60

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def parse_status(value):
    """Normalise la valeur du statut."""
    if not value:
        return "single"
    v = str(value).strip().lower()
    if v in ("couple", "2", "duo", "double", "deux"):
        return "couple"
    return "single"


def import_excel(file_bytes, family_account):
    """
    Importe un fichier Excel et cree des GuestRequest.
    Retourne (success_count, errors_list, requests_list).
    """
    try:
        wb = load_workbook(BytesIO(file_bytes), data_only=True)
        ws = wb.active
    except Exception as e:
        return 0, [{"row": 0, "error": f"Fichier Excel invalide : {e}"}], []

    success = 0
    errors = []
    requests = []

    # Verifier les en-tetes (ligne 1)
    headers = [ws.cell(row=1, column=c).value for c in range(1, 6)]
    expected = ["nom", "prenom", "telephone", "statut", "table"]
    # Normaliser
    headers_norm = [str(h).strip().lower() if h else "" for h in headers]

    # Verifier que les 2 premieres colonnes sont bien Nom et Prenom
    if headers_norm[0] not in ("nom", "name", "nom de famille"):
        return 0, [{"row": 1, "error": "Colonne A doit etre 'Nom'"}], []
    if headers_norm[1] not in ("prenom", "first_name", "firstname", "prenom(s)"):
        return 0, [{"row": 1, "error": "Colonne B doit etre 'Prenom'"}], []

    # Lire les lignes
    for row_idx in range(2, ws.max_row + 1):
        try:
            last_name = ws.cell(row=row_idx, column=1).value
            first_name = ws.cell(row=row_idx, column=2).value
            phone = ws.cell(row=row_idx, column=3).value or ""
            status = ws.cell(row=row_idx, column=4).value
            table = ws.cell(row=row_idx, column=5).value or ""

            # Ignorer les lignes vides
            if not last_name and not first_name:
                continue

            if not last_name or not str(last_name).strip():
                errors.append({"row": row_idx, "error": "Nom manquant"})
                continue
            if not first_name or not str(first_name).strip():
                errors.append({"row": row_idx, "error": "Prenom manquant"})
                continue

            req = GuestRequest(
                family_account=family_account,
                last_name=str(last_name).strip()[:100],
                first_name=str(first_name).strip()[:100],
                phone=str(phone).strip()[:20] if phone else "",
                guest_status=parse_status(status),
                table_name=str(table).strip()[:50] if table else "",
            )
            requests.append(req)
            success += 1
        except Exception as e:
            errors.append({"row": row_idx, "error": str(e)})

    return success, errors, requests


def create_guest_from_request(req, auto_approve=False):
    """
    Cree un Guest reel depuis une GuestRequest.
    Met a jour req.guest et req.request_status.
    """
    from django.utils import timezone

    guest = Guest.objects.create(
        name=req.full_name,
        phone=req.phone,
        status=req.guest_status,
        table_name=req.table_name,
        family=req.family_account.side,
    )
    req.guest = guest
    req.request_status = "approved"
    req.reviewed_at = timezone.now()
    req.save()
    return guest