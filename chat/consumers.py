import json
from channels.db import database_sync_to_async
from djangochannelsrestframework.generics import GenericAsyncAPIConsumer
from djangochannelsrestframework.observer import model_observer
from djangochannelsrestframework.observer.generics import ObserverModelInstanceMixin, action

from .models import Room, Message, User
from .serializers import RoomSerializer, MessageSerializer, UserSerializer

class RoomConsumer(GenericAsyncAPIConsumer):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    lookup_field = "pk"

    async def disconnect(self, code):
        if hasattr(self, "room_subscribe"):
            await self.remove_user_from_room(self.room_subsscribe)
            await self.notify_users()
        await super().disconnect(code)

    @action
    async def join_room(self, pk, **kwargs):
        self.room_subscribe = pk
        await self.add_user_to_room(pk)
        await self.notify_users()

    @action
    async def leave_room(self, pk, **kwargs):
        await self.remover_user_from_room(pk)

    @action
    async def create_message(self, message, **kwargs):
        room = await self.get_room(pk=self.room_subscribe)
        await database_sync_to_async(Message.objects.create)(room=room, text=message, user=self.scope["user"])

    @action
    async def subscribe_messages_to_room(self, pk, request_id, **kwargs):
        await self.message_activity.subscribe(room=pk, request_id=request_id)

    @model_observer(Message)
    async def message_activity(self, message, observer=None, subscribing_request_ids = [], **kwargs):
        for request_id in subscribing_request_ids:
            message_body = dict(request_id=request_id)
            message_body.update(message)
            await self.send_json(message_body)

    @message_activity.groups_for_signal
    def message_activity(self, instance, **kwargs):
        yield "room__{instance.room_id}"
        yield f"pk__{instance.pk}"

    @message_activity.groups_for_consumer
    def message_activity(self, room=None, **kwargs):
        if room is not None:
            yield f"room__{room}"

    @message_activity.serializer
    def message_activity(self, instance, action, **kwargs):
        return dict(data=MessageSerializer(instance).data, action=action.value, pk=instance.pk)
    
    async def notify_users(self):
        room = await self.get_room(self.room_subscribe)
        for group in self.groups:
            await self.channel_layer.group_send(
                group,
                {
                    'type': 'update_users',
                    'usarios': await self.current_users(room)
                }
            )

    async def update_users(self, event):
        await self.send(text_data=json.dumps({'usarios': event['usarios']}))

    @database_sync_to_async
    def get_room(self, pk):
        return Room.objects.get(pk=pk)
    
    @database_sync_to_async
    def current_users(self, room):
        return [UserSerializer(user).data for user in room.current_users.all()]
    
    @database_sync_to_async
    def remove_user_from_room(self, room):
        user = self.scope["user"]
        user.current_rooms.remove(room)

    @database_sync_to_async
    def add_user_to_room(self, pk):
        user = self.scope["user"]
        if user.current_rooms.filter(pk=self.room_subscribe).exists():
            user.current_rooms.add(Room.objects.get(pk=pk))