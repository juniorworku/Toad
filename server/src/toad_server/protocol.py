"""Camel-case fields match Kotlin; microphone and speaker frames remain binary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Action(Message):
    type: Literal["start", "stop", "mute", "unmute", "forget_all"]


class Camera(Message):
    type: Literal["camera"]
    enabled: StrictBool


class Photo(Message):
    type: Literal["photo"]
    requestId: str
    image: str


class PhotoError(Message):
    type: Literal["photo_error"]
    requestId: str
    reason: str


class Forget(Message):
    type: Literal["forget"]
    id: str


class Say(Message):
    type: Literal["say"]
    text: str


class Presence(Message):
    type: Literal["presence"]
    present: StrictBool


DeviceMessage = Annotated[
    Action | Camera | Photo | PhotoError | Forget | Say | Presence, Field(discriminator="type")
]
device_message: TypeAdapter[Action | Camera | Photo | PhotoError | Forget | Say | Presence] = (
    TypeAdapter(DeviceMessage)
)
