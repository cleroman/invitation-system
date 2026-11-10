"""
Context processor pour detecter le role de l'utilisateur
et adapter la navigation (navbar) selon son profil.
"""


def user_role(request):
    """
    Ajoute 'user_role' a tous les templates :
    - 'anonymous' : non connecte
    - 'admin'     : is_staff = True
    - 'controller': a un ControllerProfile
    - 'family'    : a un FamilyAccount
    - 'unknown'   : connecte sans profil
    """
    if not request.user.is_authenticated:
        return {'user_role': 'anonymous'}

    if request.user.is_staff:
        return {'user_role': 'admin'}

    # Verifier controleur
    try:
        request.user.controller_profile
        return {'user_role': 'controller'}
    except Exception:
        pass

    # Verifier famille
    try:
        request.user.family_profile
        return {'user_role': 'family'}
    except Exception:
        pass

    return {'user_role': 'unknown'}