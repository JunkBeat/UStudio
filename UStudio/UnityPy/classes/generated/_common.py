# type: ignore
from __future__ import annotations

from abc import ABC
from typing import List, Optional, Tuple, TypeVar, Union

from attrs import define as attrs_define

from ..math import (
    ColorRGBA,
    Matrix3x4f,
    Matrix4x4f,
    Quaternionf,
    Vector2f,
    Vector3f,
    Vector4f,
    float3,
    float4,
)
from ..Object import Object
from ..PPtr import PPtr

T = TypeVar("T")


def unitypy_define(cls: T) -> T:
    """
    A hacky solution to bypass multiple problems related to attrs and inheritance.

    The class inheritance is very lax and based on the typetrees.
    Some of the child classes might not have the same attributes as the parent class,
    which would make type-hinting more tricky, and breaks attrs.define.

    Therefore this function bypasses the issue
    by redefining the bases for problematic classes for the attrs.define call.
    """
    bases = cls.__bases__
    if bases[0] in (object, Object, ABC):
        cls = attrs_define(cls, slots=True, unsafe_hash=True)
    else:
        cls.__bases__ = (Object,)
        cls = attrs_define(cls, slots=False, unsafe_hash=True)
        cls.__bases__ = bases
    return cls
