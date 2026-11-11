from . import services


def roles(request):
    u = request.user
    return {"es_supervisor": bool(u.is_authenticated and services.es_supervisor(u))}
