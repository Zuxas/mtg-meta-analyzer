"""Minimal reader for .NET BinaryFormatter streams (MS-NRBF spec).

Returns plain Python values: objects become dicts with a "__class__" key,
arrays become lists, references are resolved. Only the record types a
serialized object graph uses are supported; method-call records raise.
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta

_EPOCH = datetime(1, 1, 1)


class _Ref:
    __slots__ = ("id",)

    def __init__(self, id_: int):
        self.id = id_


class _Nulls:
    __slots__ = ("n",)

    def __init__(self, n: int):
        self.n = n


class NrbfReader:
    def __init__(self, data: bytes):
        self.b = data
        self.i = 0
        self.objects: dict[int, object] = {}
        self.classes: dict[int, tuple[str, list[str], list, list]] = {}
        self.root_id: int | None = None

    # -------------------------------------------------------------- primitives
    def _u8(self) -> int:
        v = self.b[self.i]
        self.i += 1
        return v

    def _unpack(self, fmt: str):
        v = struct.unpack_from(fmt, self.b, self.i)[0]
        self.i += struct.calcsize(fmt)
        return v

    def _i32(self) -> int:
        return self._unpack("<i")

    def _lps(self) -> str:
        n = shift = 0
        while True:
            x = self._u8()
            n |= (x & 0x7F) << shift
            shift += 7
            if x < 0x80:
                break
        s = self.b[self.i:self.i + n].decode("utf-8", errors="replace")
        self.i += n
        return s

    def _primitive(self, t: int):
        if t == 1:
            return self._u8() != 0
        if t in (2, 10):
            return self._unpack("<B" if t == 2 else "<b")
        if t == 3:  # UTF-8 char
            first = self.b[self.i]
            n = 1 if first < 0x80 else 2 if first < 0xE0 else 3 if first < 0xF0 else 4
            s = self.b[self.i:self.i + n].decode("utf-8", errors="replace")
            self.i += n
            return s
        if t in (5, 18):
            return self._lps()
        if t == 6:
            return self._unpack("<d")
        if t == 11:
            return self._unpack("<f")
        if t in (7, 14):
            return self._unpack("<h" if t == 7 else "<H")
        if t in (8, 15):
            return self._unpack("<i" if t == 8 else "<I")
        if t in (9, 16):
            return self._unpack("<q" if t == 9 else "<Q")
        if t == 12:
            return timedelta(microseconds=self._unpack("<q") // 10)
        if t == 13:
            ticks = self._unpack("<Q") & 0x3FFFFFFFFFFFFFFF
            return _EPOCH + timedelta(microseconds=ticks // 10)
        if t == 17:
            return None
        raise ValueError(f"unsupported primitive type {t}")

    # -------------------------------------------------------------- class metadata
    def _class_info(self):
        oid = self._i32()
        name = self._lps()
        names = [self._lps() for _ in range(self._i32())]
        return oid, name, names

    def _member_types(self, count: int):
        btypes = [self._u8() for _ in range(count)]
        extra = []
        for bt in btypes:
            if bt in (0, 7):
                extra.append(self._u8())
            elif bt == 3:
                extra.append(self._lps())
            elif bt == 4:
                extra.append((self._lps(), self._i32()))
            else:
                extra.append(None)
        return btypes, extra

    def _members(self, oid: int, cls_id: int):
        name, names, btypes, extra = self.classes[cls_id]
        obj: dict = {"__class__": name}
        self.objects[oid] = obj
        for nm, bt, ex in zip(names, btypes, extra):
            if bt == 0:
                obj[nm] = self._primitive(ex)
            else:
                v = self._record()
                if isinstance(v, _Nulls):
                    v = None
                obj[nm] = v
        return obj

    def _elements(self, n: int) -> list:
        out: list = []
        while len(out) < n:
            v = self._record()
            if isinstance(v, _Nulls):
                out.extend([None] * v.n)
            else:
                out.append(v)
        return out

    # -------------------------------------------------------------- records
    def _record(self):
        rt = self._u8()
        if rt == 0:
            self.root_id = self._i32()
            self.i += 12
            return None
        if rt == 1:  # ClassWithId
            oid, meta = self._i32(), self._i32()
            self.classes[oid] = self.classes[meta]
            return self._members(oid, oid)
        if rt in (2, 3):  # members without type info: every member is a record
            oid, name, names = self._class_info()
            if rt == 3:
                self._i32()
            self.classes[oid] = (name, names, [2] * len(names), [None] * len(names))
            return self._members(oid, oid)
        if rt in (4, 5):
            oid, name, names = self._class_info()
            btypes, extra = self._member_types(len(names))
            if rt == 5:
                self._i32()
            self.classes[oid] = (name, names, btypes, extra)
            return self._members(oid, oid)
        if rt == 6:
            oid = self._i32()
            s = self._lps()
            self.objects[oid] = s
            return s
        if rt == 7:  # BinaryArray
            oid = self._i32()
            atype = self._u8()
            rank = self._i32()
            lengths = [self._i32() for _ in range(rank)]
            if atype in (3, 4, 5):
                self.i += 4 * rank
            (bt,), (ex,) = self._member_types(1)
            total = 1
            for n in lengths:
                total *= n
            arr = ([self._primitive(ex) for _ in range(total)] if bt == 0
                   else self._elements(total))
            self.objects[oid] = arr
            return arr
        if rt == 8:
            return self._primitive(self._u8())
        if rt == 9:
            return _Ref(self._i32())
        if rt == 10:
            return None
        if rt == 11:
            raise StopIteration
        if rt == 12:
            self._i32()
            self._lps()
            return self._record()
        if rt == 13:
            return _Nulls(self._u8())
        if rt == 14:
            return _Nulls(self._i32())
        if rt in (15, 16, 17):
            oid, n = self._i32(), self._i32()
            if rt == 15:
                t = self._u8()
                arr = [self._primitive(t) for _ in range(n)]
            else:
                arr = self._elements(n)
            self.objects[oid] = arr
            return arr
        raise ValueError(f"unsupported NRBF record type {rt} at offset {self.i - 1}")

    def read(self):
        try:
            while self.i < len(self.b):
                self._record()
        except StopIteration:
            pass
        if self.root_id is None or self.root_id not in self.objects:
            raise ValueError("no root object")
        return _resolve(self.objects[self.root_id], self.objects, set())


def _resolve(v, objects, stack):
    if isinstance(v, _Ref):
        target = objects.get(v.id)
        if id(target) in stack:
            return None  # cycle: not needed by callers
        return _resolve(target, objects, stack)
    if isinstance(v, dict):
        stack.add(id(v))
        out = {k: _resolve(x, objects, stack) for k, x in v.items()}
        stack.discard(id(v))
        return out
    if isinstance(v, list):
        stack.add(id(v))
        out = [_resolve(x, objects, stack) for x in v]
        stack.discard(id(v))
        return out
    return v


def loads(data: bytes):
    return NrbfReader(data).read()
