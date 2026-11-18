from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from farmers.authentication import FarmerJWTAuthentication
from shared.account_api import active_user
from shared.models import FarmerMessage


class MessageInput(serializers.Serializer):
    farmer_id = serializers.IntegerField(min_value=1)
    body = serializers.CharField(max_length=4000)


def message_data(message):
    return {
        "message_id": message.pk,
        "farmer_id": message.recipient_id,
        "sender_id": message.sender_id,
        "sender_username": message.sender.username if message.sender else None,
        "sender_kind": message.sender_kind,
        "body": message.body,
        "created_at": message.created_at,
    }


class SendFarmerMessageView(APIView):
    permission_classes = [IsAuthenticated]
    sender_kind = None

    def post(self, request):
        serializer = MessageInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recipient = active_user(data["farmer_id"], "Farmer")
        if recipient is None:
            return Response({"detail": "Farmer not found."}, status=404)
        message = FarmerMessage.objects.create(
            recipient=recipient,
            sender=request.user,
            sender_kind=self.sender_kind,
            body=data["body"],
        )
        return Response(message_data(message), status=201)


class FarmerInboxView(APIView):
    authentication_classes = [FarmerJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        messages = FarmerMessage.objects.filter(recipient=request.user).select_related(
            "sender"
        )
        return Response([message_data(message) for message in messages])
