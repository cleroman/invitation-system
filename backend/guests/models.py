import uuid
from django.conf import settings
from django.db import models


class Guest(models.Model):
    STATUS_CHOICES = [
        ("couple", "Couple (2 personnes)"),
        ("single", "Celibataire (1 personne)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nom complet")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Telephone")
    email = models.EmailField(blank=True, verbose_name="Email")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="single",
        verbose_name="Statut"
    )
    table_name = models.CharField(max_length=50, blank=True, verbose_name="Nom de la table")
    family = models.CharField(max_length=20, choices=[('', 'Non assigne'), ('groom', 'Famille du marie'), ('bride', 'Famille de la mariee')], default='', blank=True, verbose_name='Cote famille')
    qr_token = models.CharField(max_length=64, unique=True, editable=False)
    is_checked_in = models.BooleanField(default=False, verbose_name="Est enregistre")
    checked_in_at = models.DateTimeField(null=True, blank=True, verbose_name="Enregistre a")
    # --- Nouveaux champs ---
    is_blocked = models.BooleanField(default=False, verbose_name="QR bloque")
    block_reason = models.CharField(max_length=200, blank=True, verbose_name="Raison du blocage")

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()}) - {self.table_name}"

    @property
    def num_persons(self):
        return 2 if self.status == "couple" else 1


class ControllerProfile(models.Model):
    """
    Profil lie a un User Django. Chaque controleur a son propre login/password.
    Un controleur ne peut etre connecte que sur un seul appareil a la fois
    (session_token garantit l'unicite).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="controller_profile",
        verbose_name="Compte utilisateur",
    )
    display_name = models.CharField(max_length=100, verbose_name="Nom affiche")
    is_active = models.BooleanField(default=True, verbose_name="Acces autorise")
    # Session unique : a chaque connexion, on genere un token
    # Si un autre appareil se connecte, l'ancien token devient invalide
    current_session_token = models.CharField(max_length=64, blank=True, verbose_name="Session active")
    current_session_started = models.DateTimeField(null=True, blank=True, verbose_name="Session demarree le")
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="Derniere IP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Cree le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifie le")

    def __str__(self):
        return self.display_name or self.user.username

    def revoke(self):
        """Deconnecte le controleur de tous ses appareils."""
        self.current_session_token = ""
        self.current_session_started = None
        self.save(update_fields=["current_session_token", "current_session_started"])

    class Meta:
        verbose_name = "Profil controleur"
        verbose_name_plural = "Profils controleurs"

# ============================================================
#  MODELES INVITATION ENRICHIE
# ============================================================

class Drink(models.Model):
    """Boisson geree par l'administrateur."""
    CATEGORY_CHOICES = [
        ("soft", "Soft / Sucree"),
        ("beer", "Biere"),
        ("wine", "Vin / Champagne"),
        ("cocktail", "Cocktail"),
        ("water", "Eau"),
        ("hot", "Chaud (cafe, the)"),
    ]

    name = models.CharField(max_length=100, verbose_name="Nom")
    description = models.CharField(max_length=200, blank=True, verbose_name="Description")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="soft",
        verbose_name="Categorie"
    )
    is_available = models.BooleanField(default=True, verbose_name="Disponible")
    stock = models.IntegerField(default=-1, verbose_name="Stock (-1 = illimite)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    @property
    def is_in_stock(self):
        return self.stock < 0 or self.stock > 0

    class Meta:
        verbose_name = "Boisson"
        verbose_name_plural = "Boissons"
        ordering = ["category", "name"]


class GuestConfirmation(models.Model):
    """Confirmation de presence d'un invite."""
    guest = models.OneToOneField(
        Guest, on_delete=models.CASCADE, related_name="confirmation",
        verbose_name="Invite"
    )
    confirmed = models.BooleanField(default=False, verbose_name="Confirme")
    num_persons_confirmed = models.IntegerField(default=0, verbose_name="Nombre de personnes confirmes")
    message = models.TextField(blank=True, verbose_name="Message")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="Confirme le")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        state = "Confirme" if self.confirmed else "En attente"
        return f"{self.guest.name} - {state} ({self.num_persons_confirmed} pers.)"

    class Meta:
        verbose_name = "Confirmation"
        verbose_name_plural = "Confirmations"


class Wish(models.Model):
    """Message / voeu laisse par un invite."""
    guest = models.ForeignKey(
        Guest, on_delete=models.CASCADE, related_name="wishes",
        verbose_name="Invite"
    )
    message = models.TextField(verbose_name="Message")
    is_approved = models.BooleanField(default=True, verbose_name="Approuve")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Voeu de {self.guest.name}"

    class Meta:
        verbose_name = "Voeu"
        verbose_name_plural = "Voeux"
        ordering = ["-created_at"]


class DrinkOrder(models.Model):
    """Commande de boisson d'un invite."""
    STATUS_CHOICES = [
        ("pending", "En attente"),
        ("preparing", "En preparation"),
        ("served", "Servi"),
        ("cancelled", "Annule"),
    ]

    guest = models.ForeignKey(
        Guest, on_delete=models.CASCADE, related_name="drink_orders",
        verbose_name="Invite"
    )
    drink = models.ForeignKey(
        Drink, on_delete=models.PROTECT, related_name="orders",
        verbose_name="Boisson"
    )
    quantity = models.IntegerField(default=1, verbose_name="Quantite")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending",
        verbose_name="Statut"
    )
    note = models.CharField(max_length=200, blank=True, verbose_name="Note")
    created_at = models.DateTimeField(auto_now_add=True)
    served_at = models.DateTimeField(null=True, blank=True, verbose_name="Servi le")

    def __str__(self):
        return f"{self.guest.name} - {self.quantity}x {self.drink.name}"

    class Meta:
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        ordering = ["-created_at"]

# ============================================================
#  GESTION DE LA SALLE ET DES TABLES
# ============================================================

class VenueConfig(models.Model):
    """Configuration globale de la salle (singleton)."""
    name = models.CharField(max_length=200, default="Salle de reception", verbose_name="Nom de la salle")
    address = models.CharField(max_length=300, blank=True, verbose_name="Adresse")
    total_capacity = models.PositiveIntegerField(default=200, verbose_name="Capacite totale (personnes)")
    max_guests = models.PositiveIntegerField(default=200, verbose_name="Nombre max d'invites")
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Configuration de la salle"
        verbose_name_plural = "Configuration de la salle"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Table(models.Model):
    """Table dans la salle."""
    FAMILY_CHOICES = [
        ("neutral", "Neutre / partagee"),
        ("groom", "Famille du marie"),
        ("bride", "Famille de la mariee"),
    ]

    name = models.CharField(max_length=50, verbose_name="Nom / Numero")
    capacity = models.PositiveIntegerField(default=8, verbose_name="Capacite")
    family = models.CharField(
        max_length=20, choices=FAMILY_CHOICES, default="neutral",
        verbose_name="Famille assignee"
    )
    position_x = models.IntegerField(default=0, verbose_name="Position X")
    position_y = models.IntegerField(default=0, verbose_name="Position Y")
    notes = models.CharField(max_length=200, blank=True, verbose_name="Notes")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_family_display()}, {self.capacity} places)"

    @property
    def guests_count(self):
        """Nombre de personnes assignees a cette table."""
        guests = Guest.objects.filter(table_name=self.name)
        return sum(g.num_persons for g in guests)

    @property
    def guests_list(self):
        return Guest.objects.filter(table_name=self.name)

    @property
    def is_full(self):
        return self.guests_count >= self.capacity

    @property
    def available_seats(self):
        return max(0, self.capacity - self.guests_count)

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ["family", "name"]


class TableProposal(models.Model):
    """
    Proposition faite par une famille (cote marie ou mariee).
    L'admin valide ou refuse.
    """
    ACTION_CHOICES = [
        ("create", "Creer une table"),
        ("update", "Modifier une table"),
        ("delete", "Supprimer une table"),
        ("assign_guest", "Assigner un invite"),
        ("unassign_guest", "Desassigner un invite"),
    ]
    STATUS_CHOICES = [
        ("pending", "En attente"),
        ("approved", "Approuvee"),
        ("rejected", "Refusee"),
    ]

    family = models.CharField(
        max_length=20,
        choices=[("groom", "Famille du marie"), ("bride", "Famille de la mariee")],
        verbose_name="Famille"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Action")
    target_table = models.ForeignKey(
        Table, on_delete=models.CASCADE, null=True, blank=True,
        related_name="proposals", verbose_name="Table concernee"
    )
    target_guest = models.ForeignKey(
        Guest, on_delete=models.CASCADE, null=True, blank=True,
        related_name="table_proposals", verbose_name="Invite concerne"
    )
    payload = models.TextField(blank=True, verbose_name="Donnees (JSON)")
    reason = models.CharField(max_length=300, blank=True, verbose_name="Raison")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending",
        verbose_name="Statut"
    )
    admin_note = models.CharField(max_length=300, blank=True, verbose_name="Note admin")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Creee le")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Examinee le")

    def __str__(self):
        return f"{self.get_family_display()} - {self.get_action_display()} ({self.get_status_display()})"

    class Meta:
        verbose_name = "Proposition"
        verbose_name_plural = "Propositions"
        ordering = ["-created_at"]

# ============================================================
#  COMPTES FAMILLE (cote marie / cote mariee)
# ============================================================

class FamilyAccount(models.Model):
    """
    Compte d'une famille. Peut proposer des modifications
    (tables, invites) que l'admin validera ou refusera.
    """
    SIDE_CHOICES = [
        ("groom", "Famille du marie"),
        ("bride", "Famille de la mariee"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_profile",
        verbose_name="Compte utilisateur",
    )
    side = models.CharField(
        max_length=20, choices=SIDE_CHOICES, verbose_name="Cote"
    )
    display_name = models.CharField(max_length=100, verbose_name="Nom de la famille")
    is_active = models.BooleanField(default=True, verbose_name="Acces autorise")
    current_session_token = models.CharField(max_length=64, blank=True, verbose_name="Session active")
    current_session_started = models.DateTimeField(null=True, blank=True, verbose_name="Session demarree le")
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="Derniere IP")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.display_name} ({self.get_side_display()})"

    def revoke(self):
        self.current_session_token = ""
        self.current_session_started = None
        self.save(update_fields=["current_session_token", "current_session_started"])

    class Meta:
        verbose_name = "Compte famille"
        verbose_name_plural = "Comptes familles"

# ============================================================
#  FACTURATION - Limite gratuite + achats de places
# ============================================================

class BillingConfig(models.Model):
    """Configuration de facturation (singleton)."""
    base_limit = models.PositiveIntegerField(
        default=330,
        verbose_name="Places gratuites de base (total)"
    )
    groom_quota = models.PositiveIntegerField(
        default=180,
        verbose_name="Quota famille du marie (cote homme)"
    )
    bride_quota = models.PositiveIntegerField(
        default=150,
        verbose_name="Quota famille de la mariee (cote femme)"
    )
    extra_places_purchased = models.PositiveIntegerField(
        default=0,
        verbose_name="Places supplementaires achetees (global)"
    )
    groom_extra_purchased = models.PositiveIntegerField(
        default=0,
        verbose_name="Places supplementaires cote marie"
    )
    bride_extra_purchased = models.PositiveIntegerField(
        default=0,
        verbose_name="Places supplementaires cote mariee"
    )
    price_per_place_usd = models.DecimalField(
        max_digits=6, decimal_places=2, default=0.35,
        verbose_name="Prix par place (USD)"
    )
    price_per_place_cdf = models.PositiveIntegerField(
        default=1200,
        verbose_name="Prix par place (CDF)"
    )
    auto_approve_under_limit = models.BooleanField(
        default=True,
        verbose_name="Auto-approuver sous la limite"
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="Facturation active"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Facturation ({self.total_limit} places)"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def total_limit(self):
        """Limite totale = base + extras achetes."""
        return self.base_limit + self.extra_places_purchased

    @property
    def groom_total_limit(self):
        """Limite totale cote marie."""
        return self.groom_quota + self.groom_extra_purchased

    @property
    def bride_total_limit(self):
        """Limite totale cote mariee."""
        return self.bride_quota + self.bride_extra_purchased

    def get_side_limit(self, side):
        """Retourne la limite pour un cote donne ('groom' ou 'bride')."""
        if side == "groom":
            return self.groom_total_limit
        elif side == "bride":
            return self.bride_total_limit
        return self.total_limit

    def get_side_used(self, side):
        """Retourne le nombre d'invites utilises pour un cote."""
        return Guest.objects.filter(family=side).count()

    def get_side_remaining(self, side):
        """Retourne le nombre de places restantes pour un cote."""
        return max(0, self.get_side_limit(side) - self.get_side_used(side))

    def is_side_at_limit(self, side):
        """Verifie si le cote est a la limite."""
        return self.get_side_used(side) >= self.get_side_limit(side)

    @property
    def current_guests(self):
        return Guest.objects.count()

    @property
    def remaining_slots(self):
        return max(0, self.total_limit - self.current_guests)

    @property
    def is_at_limit(self):
        return self.current_guests >= self.total_limit

    class Meta:
        verbose_name = "Configuration de facturation"
        verbose_name_plural = "Configuration de facturation"

class PaymentTransaction(models.Model):
    """Historique des achats de places supplementaires."""
    STATUS_CHOICES = [
        ("pending", "En attente"),
        ("completed", "Complete"),
        ("failed", "Echoue"),
        ("refunded", "Rembourse"),
    ]

    METHOD_CHOICES = [
        ("simulated", "Simule (test)"),
        ("mobile_money", "Mobile Money"),
        ("card", "Carte bancaire"),
        ("cash", "Especes"),
        ("bank_transfer", "Virement"),
    ]

    reference = models.CharField(max_length=64, unique=True, verbose_name="Reference")
    places_purchased = models.PositiveIntegerField(verbose_name="Places achetees")
    amount_usd = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Montant USD")
    amount_cdf = models.PositiveIntegerField(verbose_name="Montant CDF")
    payment_method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default="simulated",
        verbose_name="Methode de paiement"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="completed",
        verbose_name="Statut"
    )
    note = models.CharField(max_length=300, blank=True, verbose_name="Note")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date")

    def __str__(self):
        return f"{self.reference} - {self.places_purchased} places - {self.amount_usd} USD"

    class Meta:
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering = ["-created_at"]

# ============================================================
#  DEMANDES D'AJOUT D'INVITES PAR LES FAMILLES
# ============================================================

class GuestRequest(models.Model):
    """Demande d'ajout d'invite faite par une famille."""
    STATUS_CHOICES = [
        ("pending", "En attente d'approbation"),
        ("awaiting_payment", "En attente de paiement"),
        ("approved", "Approuvee"),
        ("rejected", "Refusee"),
    ]
    GUEST_STATUS_CHOICES = [
        ("single", "Singleton (1 pers.)"),
        ("couple", "Couple (2 pers.)"),
    ]

    family_account = models.ForeignKey(
        FamilyAccount, on_delete=models.CASCADE,
        related_name="guest_requests", verbose_name="Famille"
    )
    first_name = models.CharField(max_length=100, verbose_name="Prenom")
    last_name = models.CharField(max_length=100, verbose_name="Nom")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Telephone")
    guest_status = models.CharField(
        max_length=10, choices=GUEST_STATUS_CHOICES, default="single",
        verbose_name="Statut"
    )
    table_name = models.CharField(max_length=50, blank=True, verbose_name="Table")

    request_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending",
        verbose_name="Statut de la demande"
    )
    admin_note = models.CharField(max_length=300, blank=True, verbose_name="Note admin")
    family_note = models.CharField(max_length=300, blank=True, verbose_name="Note famille")
    guest = models.ForeignKey(
        Guest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requests", verbose_name="Invite cree"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.last_name} {self.first_name} ({self.get_request_status_display()})"

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}".strip()

    class Meta:
        verbose_name = "Demande d'invite"
        verbose_name_plural = "Demandes d'invites"
        ordering = ["-created_at"]


class FamilyImport(models.Model):
    """Historique d'import Excel."""
    family_account = models.ForeignKey(
        FamilyAccount, on_delete=models.CASCADE,
        related_name="imports", verbose_name="Famille"
    )
    filename = models.CharField(max_length=200)
    total_rows = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    errors_json = models.TextField(blank=True, verbose_name="Erreurs (JSON)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.success_count}/{self.total_rows})"

    class Meta:
        verbose_name = "Import Excel"
        verbose_name_plural = "Imports Excel"
        ordering = ["-created_at"]