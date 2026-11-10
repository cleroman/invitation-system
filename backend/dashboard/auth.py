"""
Decorateurs de securite personnalises.
Chaque decorateur redirige vers /auth/login/ si l'utilisateur n'est pas authentifie.
- admin_required : admin uniquement (is_staff)
- controller_required : controleur OU admin (pour scanner)
- family_required : compte famille actif uniquement
"""
from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


# ============================================================
#  ADMIN
# ============================================================
def admin_required(view_func):
    """
    Verifie que l'utilisateur est authentifie ET staff (admin).
    Redirige vers /auth/login/ si anonyme, 403 si connecte mais pas staff.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url='/auth/login/')

        if not request.user.is_staff:
            # Redirection intelligente vers l'espace de l'utilisateur
            try:
                request.user.controller_profile
                return redirect('control-dashboard')
            except Exception:
                pass
            try:
                request.user.family_profile
                return redirect('family-dashboard')
            except Exception:
                pass
            # Ni admin, ni controleur, ni famille -> login
            return redirect('unified-login')

        return view_func(request, *args, **kwargs)
    return _wrapped


# ============================================================
#  CONTROLEUR (ou admin en mode scanner)
# ============================================================
def controller_required(view_func):
    """
    Verifie que l'utilisateur est un controleur actif
    OU un admin (qui peut aussi scanner).
    """
    from guests.models import ControllerProfile

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url='/auth/login/')

        # Les admins peuvent utiliser le scanner directement
        if request.user.is_staff:
            request.controller_profile = None
            request.is_admin_scanner = True
            return view_func(request, *args, **kwargs)

        # Sinon, doit etre un controleur valide
        try:
            profile = request.user.controller_profile
        except ControllerProfile.DoesNotExist:
            return HttpResponseForbidden(
                "Vous n'etes pas autorise a scanner. "
                "Utilisez un compte controleur."
            )

        if not profile.is_active:
            return _logout_and_redirect(
                request, 'controleur/login/',
                "Votre acces controleur a ete revoque. Contactez l'administrateur.",
                'unified-login',
            )

        session_token = request.session.get("controller_token", "")
        if not session_token or session_token != profile.current_session_token:
            return _logout_and_redirect(
                request, 'controleur/login/',
                "Vous avez ete deconnecte car ce compte est utilise sur un autre appareil.",
                'unified-login',
            )

        request.controller_profile = profile
        request.is_admin_scanner = False
        return view_func(request, *args, **kwargs)
    return _wrapped


# ============================================================
#  FAMILLE
# ============================================================
def family_required(view_func):
    """
    Verifie que l'utilisateur est un compte famille actif
    avec une session unique valide.
    """
    from guests.models import FamilyAccount

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url='/auth/login/')

        try:
            profile = request.user.family_profile
        except FamilyAccount.DoesNotExist:
            return HttpResponseForbidden(
                "Ce compte n'est pas un compte famille."
            )

        if not profile.is_active:
            return _logout_and_redirect(
                request, 'famille/login/',
                "Votre acces famille a ete revoque. Contactez l'administrateur.",
                'unified-login',
            )

        session_token = request.session.get("family_token", "")
        if not session_token or session_token != profile.current_session_token:
            return _logout_and_redirect(
                request, 'famille/login/',
                "Vous avez ete deconnecte car ce compte est utilise ailleurs.",
                'unified-login',
            )

        request.family_profile = profile
        return view_func(request, *args, **kwargs)
    return _wrapped


# ============================================================
#  UTILITAIRES
# ============================================================
def _logout_and_redirect(request, login_url, message, redirect_name):
    """Deconnecte l'utilisateur et redirige vers le login approprie."""
    from django.contrib.auth import logout

    logout(request)
    if 'controleur' in login_url:
        request.session["login_error"] = message
    elif 'famille' in login_url:
        request.session["family_login_error"] = message

    return redirect(redirect_name)