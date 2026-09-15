"""内容寻址的不可变对象存储。

ObjectStore 只负责 bytes 的不可变持久化：

    bytes
      ↓
    SHA256
      ↓
    ObjectRef
      ↓
    immutable object

它不理解 MarketRevision、Dataset、Parquet 或其他 domain 概念。

物理布局：

    <root>/
    └── sha256/
        └── ab/
            └── cdef...

其中完整 object id 为：

    sha256:abcdef...

写入采用临时文件 + fsync + hard link 的方式发布，避免覆盖已经存在的
内容寻址对象。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SHA256_PREFIX = "sha256:"
_SHA256_HEX_LENGTH = 64


class ObjectStoreError(RuntimeError):
    """ObjectStore 基础异常。"""


class ObjectNotFoundError(ObjectStoreError):
    """请求的内容寻址对象不存在。"""


class ObjectIntegrityError(ObjectStoreError):
    """对象内容与声明的内容地址不一致。"""


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """一个不可变对象的精确引用。"""

    object_id: str
    size_bytes: int

    def __post_init__(self) -> None:
        object_id = _validate_object_id(self.object_id)

        if isinstance(self.size_bytes, bool) or not isinstance(
            self.size_bytes,
            int,
        ):
            raise TypeError("object_ref_size_bytes_must_be_int")

        if self.size_bytes < 0:
            raise ValueError("object_ref_size_bytes_invalid")

        object.__setattr__(
            self,
            "object_id",
            object_id,
        )

    @property
    def digest(self) -> str:
        """返回不带 ``sha256:`` 前缀的十六进制 digest。"""
        return self.object_id[len(_SHA256_PREFIX) :]


def sha256_digest(
    data: bytes,
) -> str:
    """计算 bytes 的 SHA256 十六进制摘要。"""
    if not isinstance(
        data,
        bytes,
    ):
        raise TypeError("object_data_must_be_bytes")

    return hashlib.sha256(data).hexdigest()


def object_id_from_bytes(
    data: bytes,
) -> str:
    """根据 bytes 生成标准 content-addressed object id。"""
    return _SHA256_PREFIX + sha256_digest(data)


class ContentAddressedObjectStore:
    """本地不可变内容寻址对象存储。"""

    def __init__(
        self,
        root: str | Path,
    ) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def put_bytes(
        self,
        data: bytes,
    ) -> ObjectRef:
        """不可变地写入 bytes，并返回内容地址引用。

        相同 bytes 重复写入是幂等操作。

        已存在对象不会被覆盖；如果同一 object id 对应的磁盘内容已经损坏，
        会 fail closed。
        """
        if not isinstance(
            data,
            bytes,
        ):
            raise TypeError("object_data_must_be_bytes")

        ref = ObjectRef(
            object_id=(object_id_from_bytes(data)),
            size_bytes=len(data),
        )

        path = self._path_for(ref.object_id)

        parent = path.parent
        parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if path.is_symlink():
            raise ObjectIntegrityError(
                f"object_path_must_not_be_symlink:{ref.object_id}"
            )

        if path.exists():
            self._verify_path(
                path,
                ref,
            )
            return ref

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".karkinos-object-",
            dir=parent,
        )

        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(
                file_descriptor,
                "wb",
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            # 发布后的 immutable object 默认只读。
            os.chmod(
                temporary_path,
                0o444,
            )

            try:
                # hard link 具有 no-overwrite 语义：
                # 如果目标已经存在，不会替换它。
                os.link(
                    temporary_path,
                    path,
                )

            except FileExistsError:
                # 可能有另一个 writer 同时发布了同一 object。
                # 必须验证已有对象确实与我们的 ObjectRef 一致。
                if path.is_symlink():
                    raise ObjectIntegrityError(
                        f"object_path_must_not_be_symlink:{ref.object_id}"
                    )

                self._verify_path(
                    path,
                    ref,
                )

            else:
                _fsync_directory(parent)

        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

        return ref

    def read_bytes(
        self,
        ref: ObjectRef,
    ) -> bytes:
        """读取对象，并验证 size 与 content identity。"""
        if not isinstance(
            ref,
            ObjectRef,
        ):
            raise TypeError("object_ref_invalid")

        path = self._path_for(ref.object_id)

        return self._read_verified_path(
            path,
            ref,
        )

    def resolve_ref(
        self,
        object_id: str,
    ) -> ObjectRef:
        """根据 content id 找回一个已存在对象的完整 ObjectRef。

        Dataset Manifest 等持久化 contract 通常只需要保存稳定的
        ``sha256:...`` identity，而不必复制 size_bytes。

        replay 时可以通过这个方法从 immutable ObjectStore 恢复：

            object_id
                ↓
            verify bytes
                ↓
            ObjectRef(object_id, size_bytes)

        本方法会重新计算 SHA256，因此损坏对象不能被解析成合法 ObjectRef。
        """
        object_id = _validate_object_id(object_id)

        path = self._path_for(object_id)

        if path.is_symlink():
            raise ObjectIntegrityError(f"object_path_must_not_be_symlink:{object_id}")

        if not path.exists():
            raise ObjectNotFoundError(f"object_not_found:{object_id}")

        if not path.is_file():
            raise ObjectIntegrityError(f"object_path_must_be_file:{object_id}")

        data = path.read_bytes()

        actual_id = object_id_from_bytes(data)

        if actual_id != object_id:
            raise ObjectIntegrityError(f"object_integrity_mismatch:{object_id}")

        return ObjectRef(
            object_id=object_id,
            size_bytes=len(data),
        )

    def verify(
        self,
        ref: ObjectRef,
    ) -> bool:
        """验证对象当前是否存在且内容完整。"""
        if not isinstance(
            ref,
            ObjectRef,
        ):
            raise TypeError("object_ref_invalid")

        try:
            self.read_bytes(ref)
        except ObjectStoreError:
            return False

        return True

    def _path_for(
        self,
        object_id: str,
    ) -> Path:
        """把 content id 映射为磁盘路径。"""
        object_id = _validate_object_id(object_id)

        digest = object_id[len(_SHA256_PREFIX) :]

        return self._root / "sha256" / digest[:2] / digest[2:]

    def _verify_path(
        self,
        path: Path,
        ref: ObjectRef,
    ) -> None:
        """验证已有路径与 ObjectRef 完全一致。"""
        self._read_verified_path(
            path,
            ref,
        )

    def _read_verified_path(
        self,
        path: Path,
        ref: ObjectRef,
    ) -> bytes:
        if path.is_symlink():
            raise ObjectIntegrityError(
                f"object_path_must_not_be_symlink:{ref.object_id}"
            )

        if not path.exists():
            raise ObjectNotFoundError(f"object_not_found:{ref.object_id}")

        if not path.is_file():
            raise ObjectIntegrityError(f"object_path_must_be_file:{ref.object_id}")

        data = path.read_bytes()

        actual_id = object_id_from_bytes(data)

        if len(data) != ref.size_bytes or actual_id != ref.object_id:
            raise ObjectIntegrityError(f"object_integrity_mismatch:{ref.object_id}")

        return data


def _validate_object_id(
    object_id: str,
) -> str:
    """验证标准 ``sha256:<64 lowercase hex>`` object id。"""
    if not isinstance(
        object_id,
        str,
    ):
        raise TypeError("object_id_must_be_text")

    if not object_id.startswith(_SHA256_PREFIX):
        raise ValueError("object_id_invalid")

    digest = object_id[len(_SHA256_PREFIX) :]

    if len(digest) != _SHA256_HEX_LENGTH:
        raise ValueError("object_id_invalid")

    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("object_id_invalid")

    return object_id


def _fsync_directory(
    path: Path,
) -> None:
    """同步目录元数据，保证新发布的 hard link 尽量可靠落盘。"""
    flags = os.O_RDONLY | getattr(
        os,
        "O_DIRECTORY",
        0,
    )

    descriptor = os.open(
        path,
        flags,
    )

    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
