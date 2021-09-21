#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
import warnings
from decimal import Decimal
from deepdiff import DeepDiff
from datetime import datetime, timezone
from enum import Enum, EnumMeta
from inflection import camelize, underscore
from inspect import signature
from typing import Any, Callable, Dict, Optional, Union, Type, TypeVar

try:
    import ujson as json
except ImportError:
    import json

reserved = ('type', 'id', 'list', 'except', 'from', 'to', 'open', 'sum', 'uuid')
SerializableType = TypeVar('SerializableType', bound='Serializable')

Numeric = Union[int, float, str, Decimal]


def camel(s: str, uppercase_first_letter=False):
    if s.endswith('_'):
        return camelize(s[:-1], uppercase_first_letter)
    else:
        return camelize(s, uppercase_first_letter)


def extract_to_model(data: Any, obj: Any, eraise: bool = True) -> Any:
    """
    Serialize JSON-like data to Serializable object
    :param data: incoming data, list or dicts
    :param obj: child of Serializable class
    :param eraise: raise RuntimeError if incorrect data supplied or model out-of-data
    :return: Serializable class instance
    """
    if isinstance(data, list):
        if hasattr(obj, '__model__'):
            return [obj.from_json(item, eraise) for item in data]
        else:
            return [obj(item) for item in data]
    elif isinstance(data, dict):
        return obj.from_json(data, eraise)
    elif isinstance(data, obj):
        return data
    else:
        return None


def to_string(d: datetime, fmt: str = '%Y-%m-%dT%H:%M:%S.%fZ') -> str:
    return d.strftime(fmt)


def dt_to_timestamp(d: datetime, millis: bool = False) -> int:
    if millis:
        return int(d.timestamp() * 1000)
    else:
        return int(d.timestamp())


def timestamp_to_dt(ts: Optional[Numeric], tz: timezone = timezone.utc) -> Optional[datetime]:
    if ts is None:
        return None
    else:
        try:
            if isinstance(ts, (str, Decimal)):
                return datetime.fromtimestamp(float(ts), tz=tz)
            else:
                return datetime.fromtimestamp(ts, tz=tz)
        except ValueError:
            return timestamp_to_dt(float(ts) / 1000, tz)


def str_to_dt(s: Optional[str], fmt: str = '%Y-%m-%dT%H:%M:%S.%f%z') -> Optional[datetime]:
    try:
        return datetime.strptime(s, fmt)
    except ValueError:
        return None


def dt_to_str(d: Optional[datetime], fmt: str = '%Y-%m-%dT%H:%M:%S.%f%z') -> Optional[str]:
    if d:
        return d.strftime(fmt)
    else:
        return None


def dc(value: Optional[Numeric]) -> Optional[Decimal]:
    if value is None:
        return None
    elif isinstance(value, float):
        return Decimal(str(value))
    else:
        return Decimal(value)


def opt_int(i: Optional[Numeric]) -> Optional[int]:
    if i is None:
        return None
    else:
        return int(dc(i))


class BaseSerializable:
    __model__ = True

    def __dict(self, obj: Any, dt_parser: Callable, keep_null: bool) -> Any:
        if isinstance(obj, dict):
            return {
                self.__dict(key, dt_parser, keep_null): self.__dict(value, dt_parser, keep_null)
                for key, value in obj.items()
                if (not keep_null and value is not None) or keep_null
            }
        elif isinstance(obj, Decimal):
            return str(obj)
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, datetime):
            return dt_parser(obj)
        elif hasattr(obj, '__iter__') and not isinstance(obj, str):
            return [self.__dict(value, dt_parser, keep_null)
                    for value in obj
                    if (not keep_null and value is not None) or keep_null]
        elif hasattr(obj, '__dict__'):
            data = {
                camel(key): self.__dict(value, dt_parser, keep_null)
                for key, value in obj.__dict__.items()
                if (not callable(value)) and ((not keep_null and value is not None) or keep_null)}
            return data
        else:
            return obj

    @staticmethod
    def to_enum(source: Union[int, str, Enum, None], obj: EnumMeta) -> Optional[Enum]:
        if source is None:
            return None
        else:
            try:
                return obj(source)
            except ValueError:
                try:
                    return obj[source]
                except KeyError:
                    raise ValueError(f"Unable to extract Enum from {obj}")

    def to_json(self, keep_null: bool = False, dt_parser: Callable = to_string) -> Dict[str, Union[str, int, float]]:
        """
        Method to convert model to JSON
        :param keep_null: True to keep "field": null in generated JSON, default is False (no key)
        :param dt_parser: function to convert datetime object to printable
        :return: JSON-like dictionary
        """
        return self.__dict(self, dt_parser, keep_null)

    def __repr__(self) -> str:
        return json.dumps(self.to_json(False))

    def __eq__(self, other) -> bool:
        if hasattr(other, '__model__'):
            return bool(not DeepDiff(self.to_json(keep_null=True), other.to_json(keep_null=True), ignore_order=True))
        else:
            raise ValueError("Impossible to directly compare non-models objects")


class Serializable(BaseSerializable):
    __model__ = True

    @classmethod
    def _empty_init(cls) -> Dict[str, None]:
        return {
            k: None
            for k in signature(cls.__init__).parameters.keys()
            if k not in ('args', 'kwargs', 'self')
        }

    @classmethod
    def from_json(cls: Type[SerializableType], obj: Union[Dict, SerializableType, None],
                  eraise: bool = True) -> Optional[SerializableType]:
        def make_key(key: str) -> str:
            key = underscore(key)
            if key in reserved:
                return '%s_' % key
            else:
                return key
        try:
            if obj in (None, [], {}, [{}]):
                return cls(**cls._empty_init())  # type: ignore
            elif isinstance(obj, dict):
                data = dict()  # type: Dict[str, Any]
                for k, v in obj.items():
                    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                        data[make_key(k)] = dc(v)
                    else:
                        data[make_key(k)] = v
                return cls(**data)  # type: ignore
            elif isinstance(obj, cls):
                return obj
        except TypeError:
            if eraise:
                raise RuntimeError('could not get {} from {} as {}'.format(cls, type(obj), obj))
            else:
                warnings.warn("'could not get {} from {} as {}".format(cls, type(obj), obj))
                return None
