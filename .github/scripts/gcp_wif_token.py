"""GitHub Actions → Google Cloud 단기 접근 토큰(Workload Identity Federation). 키 파일 없이.

흐름: ① Actions OIDC 토큰(id-token: write) → ② STS 토큰 교환(연합 토큰) → ③ 서비스 계정 가장
(generateAccessToken, 15분). 서드파티 액션을 쓰지 않는다(표준 라이브러리만 — verify-key-pin 과 같은 원칙).

입력(환경변수): GCP_WIF_PROVIDER = projects/<번호>/locations/global/workloadIdentityPools/<풀>/providers/<공급자>
               GCP_ANCHOR_SA    = <이름>@<프로젝트>.iam.gserviceaccount.com
출력: 토큰을 로그에서 가리고(::add-mask::), $GITHUB_ENV 에 GCP_ACCESS_TOKEN 으로 넘긴다. 화면에는 찍지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_PROVIDER = re.compile(r"^projects/[0-9]{1,20}/locations/global/workloadIdentityPools/[a-z0-9-]{4,32}/providers/[a-z0-9-]{4,32}$")
_SA = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,61}[a-z0-9]\.iam\.gserviceaccount\.com$")


class WifError(Exception):
    pass


def _post(url: str, body: bytes, headers: dict, opener) -> dict:
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with opener(req, timeout=20) as res:
            return json.loads(res.read() or b"{}")
    except Exception as exc:            # noqa: BLE001 — 응답·토큰을 메시지에 넣지 않는다
        raise WifError("%s 실패(%s)" % (url.split("/")[2], type(exc).__name__)) from exc


def access_token(provider: str, service_account: str, env: dict, opener=urllib.request.urlopen) -> str:
    if not _PROVIDER.fullmatch(provider or ""):
        raise WifError("GCP_WIF_PROVIDER 형식이 아닙니다(projects/<번호>/locations/global/workloadIdentityPools/…/providers/…)")
    if not _SA.fullmatch(service_account or ""):
        raise WifError("GCP_ANCHOR_SA 형식이 아닙니다")
    url, req_token = env.get("ACTIONS_ID_TOKEN_REQUEST_URL"), env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not req_token:
        raise WifError("OIDC 토큰을 받을 수 없습니다 — 워크플로에 permissions: id-token: write 가 필요합니다")
    audience = "https://iam.googleapis.com/" + provider
    req = urllib.request.Request(url + "&audience=" + urllib.parse.quote(audience, safe=""))
    req.add_header("Authorization", "bearer " + req_token)
    try:
        with opener(req, timeout=20) as res:
            oidc = json.loads(res.read() or b"{}").get("value", "")
    except Exception as exc:            # noqa: BLE001
        raise WifError("OIDC 토큰 요청 실패(%s)" % type(exc).__name__) from exc
    if not oidc:
        raise WifError("OIDC 토큰이 비었습니다")
    sts = _post("https://sts.googleapis.com/v1/token", json.dumps({
        "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
        "audience": "//iam.googleapis.com/" + provider,
        "scope": SCOPE,
        "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
        "subjectToken": oidc,
        "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
    }).encode(), {"Content-Type": "application/json"}, opener)
    federated = sts.get("access_token", "")
    if not federated:
        raise WifError("STS 교환 결과에 토큰이 없습니다(공급자 조건·저장소 제한을 확인하세요)")
    sa = _post("https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/%s:generateAccessToken"
               % urllib.parse.quote(service_account, safe="@."),
               json.dumps({"scope": [SCOPE], "lifetime": "900s"}).encode(),
               {"Content-Type": "application/json", "Authorization": "Bearer " + federated}, opener)
    token = sa.get("accessToken", "")
    if not token:
        raise WifError("서비스 계정 가장 실패 — 풀 주체에 roles/iam.workloadIdentityUser 가 있어야 합니다")
    return token


def main() -> int:
    try:
        token = access_token(os.environ.get("GCP_WIF_PROVIDER", ""), os.environ.get("GCP_ANCHOR_SA", ""), dict(os.environ))
    except WifError as exc:
        print("::error::" + str(exc))
        return 1
    print("::add-mask::" + token)
    target = os.environ.get("GITHUB_ENV")
    if not target:
        print("::error::GITHUB_ENV 가 없습니다(Actions 밖에서 실행)")
        return 1
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("GCP_ACCESS_TOKEN=" + token + "\n")
    print("GCP 단기 토큰 준비됨(15분, 값은 출력하지 않음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
