"""内容寻址 ObjectStore 测试。"""

from __future__ import annotations

import os

import pytest

from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectRef,
    object_id_from_bytes,
    sha256_digest,
)

_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"


def _object_path(
    store: ContentAddressedObjectStore,
    ref: ObjectRef,
):
    return store.root / "sha256" / ref.digest[:2] / ref.digest[2:]


def test_sha256_digest_is_deterministic() -> None:
    assert sha256_digest(b"") == _EMPTY_SHA256

    assert sha256_digest(b"") == sha256_digest(b"")


def test_object_id_uses_sha256_prefix() -> None:
    assert object_id_from_bytes(b"") == f"sha256:{_EMPTY_SHA256}"


def test_hash_functions_require_bytes() -> None:
    with pytest.raises(
        TypeError,
        match="object_data_must_be_bytes",
    ):
        sha256_digest("not-bytes")

    with pytest.raises(
        TypeError,
        match="object_data_must_be_bytes",
    ):
        object_id_from_bytes("not-bytes")


def test_object_ref_exposes_digest() -> None:
    ref = ObjectRef(
        object_id=(f"sha256:{'a' * 64}"),
        size_bytes=123,
    )

    assert ref.digest == "a" * 64


@pytest.mark.parametrize(
    "object_id",
    [
        "not-a-content-id",
        "sha256:abc",
        f"sha1:{'a' * 64}",
        f"sha256:{'A' * 64}",
        f"sha256:{'g' * 64}",
        f"sha256:{'a' * 63}",
        f"sha256:{'a' * 65}",
    ],
)
def test_object_ref_rejects_invalid_object_id(
    object_id,
) -> None:
    with pytest.raises(
        ValueError,
        match="object_id_invalid",
    ):
        ObjectRef(
            object_id=object_id,
            size_bytes=1,
        )


def test_object_ref_rejects_non_text_object_id() -> None:
    with pytest.raises(
        TypeError,
        match="object_id_must_be_text",
    ):
        ObjectRef(
            object_id=123,
            size_bytes=1,
        )


@pytest.mark.parametrize(
    "size_bytes",
    [
        1.5,
        "1",
        True,
        None,
    ],
)
def test_object_ref_requires_integer_size(
    size_bytes,
) -> None:
    with pytest.raises(
        TypeError,
        match=("object_ref_size_bytes_must_be_int"),
    ):
        ObjectRef(
            object_id=(f"sha256:{'a' * 64}"),
            size_bytes=size_bytes,
        )


def test_object_ref_rejects_negative_size() -> None:
    with pytest.raises(
        ValueError,
        match=("object_ref_size_bytes_invalid"),
    ):
        ObjectRef(
            object_id=(f"sha256:{'a' * 64}"),
            size_bytes=-1,
        )


def test_put_and_read_round_trip(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    payload = b"hello karkinos"

    ref = store.put_bytes(payload)

    assert ref.object_id == (object_id_from_bytes(payload))
    assert ref.size_bytes == len(payload)

    assert store.read_bytes(ref) == payload


def test_put_uses_content_addressed_layout(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = store.put_bytes(b"layout-test")

    path = _object_path(
        store,
        ref,
    )

    assert path.is_file()
    assert path.read_bytes() == (b"layout-test")


def test_same_bytes_are_idempotent(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    payload = b"same immutable object"

    first = store.put_bytes(payload)

    second = store.put_bytes(payload)

    assert first == second

    object_files = [
        path for path in (store.root / "sha256").rglob("*") if path.is_file()
    ]

    assert len(object_files) == 1


def test_different_bytes_have_different_object_ids(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = store.put_bytes(b"first")
    second = store.put_bytes(b"second")

    assert first.object_id != second.object_id


def test_empty_bytes_are_valid_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = store.put_bytes(b"")

    assert ref.object_id == (f"sha256:{_EMPTY_SHA256}")
    assert ref.size_bytes == 0
    assert store.read_bytes(ref) == b""
    assert store.verify(ref) is True


def test_put_requires_bytes(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="object_data_must_be_bytes",
    ):
        store.put_bytes("not-bytes")


def test_read_missing_object_fails(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = ObjectRef(
        object_id=(f"sha256:{'a' * 64}"),
        size_bytes=123,
    )

    with pytest.raises(
        ObjectNotFoundError,
        match="object_not_found",
    ):
        store.read_bytes(ref)

    assert store.verify(ref) is False


def test_read_detects_content_corruption(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = store.put_bytes(b"original")

    path = _object_path(
        store,
        ref,
    )

    # 主动绕过只读权限，模拟磁盘损坏。
    os.chmod(
        path,
        0o644,
    )
    path.write_bytes(b"corrupted")

    with pytest.raises(
        ObjectIntegrityError,
        match="object_integrity_mismatch",
    ):
        store.read_bytes(ref)

    assert store.verify(ref) is False


def test_read_detects_size_mismatch(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    actual = store.put_bytes(b"payload")

    forged = ObjectRef(
        object_id=actual.object_id,
        size_bytes=actual.size_bytes + 1,
    )

    with pytest.raises(
        ObjectIntegrityError,
        match="object_integrity_mismatch",
    ):
        store.read_bytes(forged)


def test_existing_corrupted_object_cannot_be_overwritten(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    payload = b"immutable"

    ref = store.put_bytes(payload)

    path = _object_path(
        store,
        ref,
    )

    os.chmod(
        path,
        0o644,
    )
    path.write_bytes(b"corrupted")

    with pytest.raises(
        ObjectIntegrityError,
        match="object_integrity_mismatch",
    ):
        store.put_bytes(payload)

    # put_bytes 不能把损坏对象偷偷覆盖回正确内容。
    assert path.read_bytes() == (b"corrupted")


def test_symlink_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    payload = b"symlink target"

    ref = ObjectRef(
        object_id=(object_id_from_bytes(payload)),
        size_bytes=len(payload),
    )

    path = _object_path(
        store,
        ref,
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    unrelated = tmp_path / "unrelated"
    unrelated.write_bytes(payload)

    path.symlink_to(unrelated)

    with pytest.raises(
        ObjectIntegrityError,
        match=("object_path_must_not_be_symlink"),
    ):
        store.read_bytes(ref)

    with pytest.raises(
        ObjectIntegrityError,
        match=("object_path_must_not_be_symlink"),
    ):
        store.put_bytes(payload)


def test_resolve_ref_from_content_id(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    original = store.put_bytes(b"hello karkinos")

    resolved = store.resolve_ref(original.object_id)

    assert resolved == original


def test_resolve_ref_supports_empty_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    original = store.put_bytes(b"")

    resolved = store.resolve_ref(original.object_id)

    assert resolved == original
    assert resolved.size_bytes == 0


def test_resolve_ref_rejects_missing_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    missing_id = "sha256:" + "a" * 64

    with pytest.raises(
        ObjectNotFoundError,
        match="object_not_found",
    ):
        store.resolve_ref(missing_id)


def test_resolve_ref_detects_corruption(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = store.put_bytes(b"original")

    path = _object_path(
        store,
        ref,
    )

    os.chmod(
        path,
        0o644,
    )
    path.write_bytes(b"corrupted")

    with pytest.raises(
        ObjectIntegrityError,
        match="object_integrity_mismatch",
    ):
        store.resolve_ref(ref.object_id)


@pytest.mark.parametrize(
    "object_id",
    [
        "missing-prefix",
        "sha256:abc",
        f"sha256:{'A' * 64}",
    ],
)
def test_resolve_ref_rejects_invalid_content_id(
    tmp_path,
    object_id,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        ValueError,
        match="object_id_invalid",
    ):
        store.resolve_ref(object_id)


def test_read_requires_object_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="object_ref_invalid",
    ):
        store.read_bytes("not-an-object-ref")


def test_verify_requires_object_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="object_ref_invalid",
    ):
        store.verify("not-an-object-ref")
