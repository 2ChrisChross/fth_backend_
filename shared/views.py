from rest_framework.response import Response


def index(request):
    return Response({"message": "FTH API is running."})
