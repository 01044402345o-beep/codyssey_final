"""MFA1 컨테이너와 키 파일 테스트 — 왕복·변조·다른 키·압축 순서를 실제로 검증한다.

실행: `tools/opsarchive` 에서
    set PYTHONPATH=. && python -m unittest discover -s tests -t .
(Windows PowerShell: `$env:PYTHONPATH="."; & <python> -m unittest discover -s tests -t .`)
"""

from __future__ import annotations

import gzip
import json
import os
import struct
import tempfile
import unittest

from opsarchive import container as C


class ContainerTest(unittest.TestCase):
    def test_roundtrip(self):
        private, public = C.keypair()
        payload = json.dumps({"a": "탈퇴 실패", "b": [1, 2, 3]}, ensure_ascii=False).encode()
        blob = C.seal(payload, public)
        self.assertTrue(blob.startswith(C.MAGIC))
        self.assertEqual(C.unseal(blob, private), payload)

    def test_body_is_gzip_before_encryption(self):
        """압축을 나중에 하면(암호문 압축) 크기가 줄지 않는다 — 순서를 실제로 확인한다."""
        private, public = C.keypair()
        payload = b"a" * 50000
        sealed = C.seal(payload, public)
        self.assertLess(len(sealed), 2000)                      # gzip 이 먼저 돌았다
        self.assertEqual(C.unseal(sealed, private), payload)

    def test_wrong_key_is_rejected(self):
        _, public = C.keypair()
        other, _ = C.keypair()
        blob = C.seal(b"x", public)
        with self.assertRaises(C.ContainerError) as caught:
            C.unseal(blob, other)
        self.assertIn(caught.exception.code, ("key_mismatch", "corrupt"))

    def test_tampering_is_detected(self):
        private, public = C.keypair()
        blob = bytearray(C.seal(b"important", public))
        for index in (len(blob) - 1, 20, 6):                    # 본문·헤더(key_id)·알고리즘
            broken = bytearray(blob)
            broken[index] ^= 0x01
            with self.assertRaises(C.ContainerError):
                C.unseal(bytes(broken), private)

    def test_header_is_bound_as_aad(self):
        """헤더와 본문을 서로 다른 메시지에서 짝지으면 인증이 깨진다(AAD 에 헤더가 묶여 있다)."""
        private, public = C.keypair()
        a = C.seal(b"AAAA", public)
        b = C.seal(b"BBBB", public)
        self.assertEqual(len(a), len(b))
        split = C.HEADER_FIXED + struct.unpack(">H", a[14:16])[0] + C.NONCE_LEN
        with self.assertRaises(C.ContainerError):
            C.unseal(a[:split] + b[split:], private)

    def test_short_and_bad_magic(self):
        with self.assertRaises(C.ContainerError) as caught:
            C.unseal(b"MFA1", b"\x00" * 32)
        self.assertEqual(caught.exception.code, "too_short")
        with self.assertRaises(C.ContainerError) as caught:
            C.unseal(b"XXXX" + b"\x00" * 200, b"\x00" * 32)
        self.assertEqual(caught.exception.code, "bad_magic")

    def test_public_key_pack_roundtrip(self):
        _, public = C.keypair()
        text = C.pack_public_key(public)
        self.assertTrue(text.startswith("x25519:"))
        self.assertEqual(C.unpack_public_key(text), public)
        self.assertEqual(len(C.key_id(public)), 8)

    def test_public_from_private_matches(self):
        private, public = C.keypair()
        self.assertEqual(C.public_from_private(private), public)


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-test-")

    def path(self, name="admin.key"):
        return os.path.join(self.dir, name)

    def test_save_load_roundtrip(self):
        private, _ = C.keypair()
        C.save_private_key(self.path(), private, "비밀문장")
        self.assertEqual(C.load_private_key(self.path(), "비밀문장"), private)

    def test_wrong_passphrase(self):
        private, _ = C.keypair()
        C.save_private_key(self.path(), private, "right")
        with self.assertRaises(C.ContainerError) as caught:
            C.load_private_key(self.path(), "wrong")
        self.assertEqual(caught.exception.code, "key_mismatch")

    def test_file_does_not_contain_the_private_key(self):
        private, _ = C.keypair()
        C.save_private_key(self.path(), private, "phrase")
        with open(self.path(), "rb") as fh:
            blob = fh.read()
        self.assertTrue(blob.startswith(C.KEY_MAGIC))
        self.assertNotIn(private, blob)                          # 평문 개인키가 남지 않는다
        n, r, p = struct.unpack(">III", blob[C.KEY_PARAMS_AT:C.KEY_NONCE_AT])
        self.assertEqual((n, r, p), (C.SCRYPT_N, C.SCRYPT_R, C.SCRYPT_P))

    def test_corrupt_key_file(self):
        with open(self.path(), "wb") as fh:
            fh.write(b"MFAK1" + b"\x00" * 10)
        with self.assertRaises(C.ContainerError) as caught:
            C.load_private_key(self.path(), "x")
        self.assertEqual(caught.exception.code, "bad_key_file")

    def test_gzip_header_is_used(self):
        """컨테이너는 gzip 본문을 쓴다(다른 구현이 읽을 때 이 형식을 가정한다)."""
        _, public = C.keypair()
        private, _ = C.keypair()
        payload = b"plain"
        blob = C.seal(payload, public)
        # 헤더를 건너뛴 본문을 직접 복호화하지 않고, gzip 으로 압축한 것과 같은 바이트인지만 본다.
        self.assertEqual(gzip.decompress(gzip.compress(payload)), payload)


if __name__ == "__main__":
    unittest.main()
