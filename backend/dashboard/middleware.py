"""
Middleware pour forcer l'encodage UTF-8 dans les headers HTTP.
Resout les problemes de caracteres speciaux (accents, puces).
"""


class UTF8CharsetMiddleware:
    """Force Content-Type: text/html; charset=utf-8 sur toutes les reponses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Ajouter charset=utf-8 si Content-Type commence par text/ ou application/json
        content_type = response.get('Content-Type', '')
        if content_type and 'charset' not in content_type.lower():
            if content_type.startswith('text/') or content_type.startswith('application/json'):
                response['Content-Type'] = f"{content_type}; charset=utf-8"

        return response