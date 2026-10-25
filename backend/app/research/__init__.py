"""도시 조사 다중 에이전트 — 사용자가 고른 나라·도시를 여행 조건(날짜·체류·도착/이동/출국일)에 맞게 실제 소스에서 조사한다.

설계: docs/product/RESEARCH_AGENT.md(후속 PR). 이번 단계(PR1)는 키 없는 공개 소스만 쓰고 LLM 을 부르지 않는다.
- 도시 정체성: GeoNames(geo.py) → Wikidata(P1566) → 영어 위키보이지 문서
- 장소: 위키보이지 listing 템플릿({{see}}·{{eat}}…)을 코드로 파싱 — 모델이 장소를 지어낼 수 없다
- 나라: Wikidata(통화·긴급번호·플러그·전압·운전 방향·언어) · GOV.UK 여행 권고(OGL) · Frankfurter 환율
- 날씨: Open-Meteo(여행 날짜가 16일 안이면 예보, 아니면 최근 5년 같은 날짜 평년값)

원칙: 어떤 도구를 부를지는 코드가 정한다. 소스 실패는 예외가 아니라 status 가 있는 정상 결과다.
"""
import os

# langchain-core 는 langsmith 를 의존성으로 끌고 온다. 누가 환경변수를 켜 두어도 조사 데이터가
# LangSmith 로 나가지 않게, 이 패키지를 불러오는 순간 추적을 끈다.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
