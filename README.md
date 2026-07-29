# LocalThings Community (로컬띵스 커뮤니티)

**Samsung appliances, no cloud** — SmartThings 클라우드 없이, 최신 삼성 가전을 집 안 네트워크에서 직접 제어하는 Homey 앱입니다.

Home Assistant 통합 [mbillow/localthings](https://github.com/mbillow/localthings)를 Homey로 포팅하는 프로젝트입니다. 가전과 DTLS-over-CoAP 세션을 직접 맺어 상태를 읽고 명령을 보내므로, 클라우드 왕복이 없습니다.

> **상태: 개발 중 (v0.1.0).** 에어컨 4대와 인덕션 1대가 검색·페어링·제어까지 실기기에서 동작하고, 상태는 CoAP OBSERVE로 푸시받습니다(폴링은 5분 주기 안전 스윕). 나머지 가전 종류는 미이식입니다. 설계와 실측 자료는 [`docs/PORTING.md`](docs/PORTING.md)를 참고하세요.

## 동작 방식

| 계층 | 내용 |
|---|---|
| 전송 | UDP `49152-49160` 중 하나에서 DTLS 1.2, 클라이언트 인증서 인증 |
| 암호 스위트 | `ECDHE-ECDSA-AES128-GCM-SHA256` (`@SECLEVEL=0` 필요), ciphertext MTU 1200 고정 |
| 인증 | 삼성 펌웨어 신뢰 저장소에 있는 `AC14K_M` 중간 CA가 서명한 리프 인증서 |
| 프로토콜 | CoAP (token-stable Block2 전송, OBSERVE 구독) |
| 페이로드 | CBOR로 인코딩된 OCF 리소스 표현 |
| 모델링 | `/device/0` 배치 응답을 href별 리소스로 파싱 → 가전 종류별 레지스트리가 href를 Homey capability로 매핑 |

## 대상 기기

Tizen RT 3.x / DAWIT 3.0+ 펌웨어를 쓰는 삼성 가전(대략 2022년 이후). 세탁기, 건조기, 에어컨, 공기청정기, 제습기, 냉장고, 식기세척기, 오븐, 전자레인지, 쿡탑, 레인지, 레인지 후드, 정수기, 청소기 스테이션, 에어드레서.

`8888/tcp`만 열려 있는 구형 펌웨어(2018~2022년경, 토큰 기반 HTTPS)는 대상이 아닙니다.

호환 여부 확인:

```sh
nmap -Pn -sU -p 49152-49160 "$APPLIANCE_IP"
```

앱의 **기기 추가 → 검색**이 같은 일을 네트워크 전체에 대해 해줍니다. 응답한 기기만 종류를 확인하므로 IP를 몰라도 됩니다.

> 앱스토어 소개문은 [`README.txt`](README.txt)(영어)와 [`README.ko.txt`](README.ko.txt)(한국어)에 있습니다. 심사 제출 시 이 두 파일이 앱 설명으로 쓰입니다.

## 앱 설치 방법

인증서를 한 번 만들어 앱 설정에 넣는 것이 전부입니다. 가전마다 반복할 필요는 없습니다.

### 1단계 — 앱 설치

Homey 앱스토어에는 아직 없습니다. 저장소를 클론해 직접 설치합니다. [Homey CLI](https://apps.developer.homey.app/the-basics/getting-started)와 Docker가 필요합니다.

```sh
npm install -g homey
homey login

git clone https://github.com/moKorean/com.lomohome.localthings.git
cd com.lomohome.localthings
homey app install
```

`homey app install`이 `pythonPackages`를 아키텍처별 venv로 해석하느라 첫 실행은 몇 분 걸립니다.

> `homey app run`(개발 모드)은 영구 설치본을 **대체하고, 실행이 끝나면 앱을 제거**합니다. 개발 중이 아니라면 `homey app install`을 쓰세요.

### 2단계 — 클라이언트 인증서 발급 (컴퓨터에서 1회)

가전은 `AC14K_M` 중간 CA가 서명한 인증서를 신뢰합니다.

> **이 저장소는 필요한 CA 번들을 포함하지 않습니다.** 획득 방법의 예시 — `AC14K_M` 인증서와 키를 받아 서로 짝이 맞는지 확인하는 과정까지 — 는 `smartthings-local` 프로토콜 프로젝트의 [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py)를 참고하세요.
>
> 원문: *"This repo doesn't include the needed CA bundle. For an example of how to obtain it, including fetching the AC14K_M cert and key and verifying they pair, see the `smartthings-local` protocol project's [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py)."* — [mbillow/localthings](https://github.com/mbillow/localthings)

[`QuiteYellow/SmartThings-Local`](https://github.com/QuiteYellow/SmartThings-Local)의 `setup_cert.py`가 발급 전 과정을 자동화합니다. Python 3과 `openssl`이 필요합니다.

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
python3 -m venv .venv && .venv/bin/pip install pyOpenSSL

# TARGET_IP는 선택입니다. 넣으면 붙여넣기 전에 실제 가전으로 검증합니다.
OUT_DIR=./certs TARGET_IP=192.168.1.90 \
  .venv/bin/python setup_cert.py --test
```

`--test`가 `GET /oic/sec/acl -> 2.05`를 출력하면 가전이 인증서를 수락한 것입니다. 자세한 동작은 [`docs/CA-SETUP.md`](docs/CA-SETUP.md)에 있습니다.

**인증서 하나가 집 안 모든 삼성 가전에 통용됩니다.** 인증서에 들어가는 식별자가 가전이 아니라 삼성 게이트웨이에서 오는 값이기 때문에, 기기별이 아니라 설치별로 하나만 있으면 됩니다.

### 3단계 — 앱 설정에 붙여넣기

Homey에서 **설정 → 앱 → 로컬띵스 커뮤니티**를 엽니다. `certs/`에 생성된 파일 중 **두 개**를 붙여넣습니다:

| 파일 | 입력란 |
|---|---|
| `client_fullchain.pem` | 인증서 체인 |
| `client.key` | 개인키 |

`client.pem`은 안 됩니다 — 리프 하나뿐이라 가전이 검증할 체인이 없습니다. 앱이 이 경우를 감지해 알려줍니다.

저장하면 상태가 **준비 완료**로 바뀌고 식별자·만료일·체인 길이가 표시됩니다. 앱은 **CA 개인키를 받지 않습니다** — 이미 발급된 인증서만 저장하므로, 서명에 쓰인 CA 키는 컴퓨터에 남습니다.

### 4단계 — 가전 추가

**기기 → 기기 추가 → 로컬띵스 커뮤니티 → 검색**

로컬 네트워크를 훑어 응답하는 가전을 찾고 종류까지 확인합니다. 1~2분 걸리며, 발견되는 대로 목록에 나타납니다. IP를 알고 있다면 직접 입력할 수도 있습니다.

### 문제가 생기면

기기의 **⋯ 메뉴 → 유지보수 → 복구**에서 연결을 확인하고, 주소가 바뀐 가전을 시리얼로 다시 찾거나 주소를 직접 지정할 수 있습니다.

설치된 앱의 상태는 개발 모드 없이 확인할 수 있습니다:

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

## IP가 바뀌어도 동작합니다

정체성은 IP가 아니라 **시리얼**(기기의 data id)입니다. 주소가 바뀌면:

- 폴링이 연속 3회 실패하면 앱이 서브넷을 스윕해 **시리얼이 일치하는 기기**를 찾아 스스로 갱신합니다. 재페어링이 필요 없습니다
- 폴링마다 시리얼을 대조하므로, **같은 모델 두 대가 IP를 교환해도 서로를 조작하지 않습니다** — 잘못된 가전에 붙는 대신 실패로 처리합니다
- 고급 설정의 IP·포트·연결 상태가 항상 실제 값으로 갱신됩니다

재배치에는 1~2분이 걸리고 그동안 기기는 사용 불가 상태입니다. 공유기에서 **고정 IP를 예약**해두면 이 경로를 타지 않습니다.

## 요구 사항

- **Homey Pro, 펌웨어 v13.0.0 이상.** 이 앱은 Homey의 파이썬 런타임(`"runtime": "python"`, Python 3.14)으로 동작하므로 v13 미만에서는 설치되지 않습니다.
- LAN UDP가 필요하므로 `local` 플랫폼 전용입니다. Homey Cloud에서는 동작할 수 없습니다.
- **클라이언트 인증서** (저장소에 포함되어 있지 않습니다). `AC14K_M`이 서명한 인증서를 컴퓨터에서 1회 발급해 **설정 → 앱 → 로컬띵스 커뮤니티**에 붙여넣습니다. UUID가 가전이 아니라 삼성 게이트웨이에서 오는 값이라 **인증서 하나로 집 안 모든 삼성 가전에 통용**되며, 이후 가전 추가는 IP만 입력합니다. 절차는 [`docs/CA-SETUP.md`](docs/CA-SETUP.md).

  앱은 **CA 개인키를 받지 않습니다** — 이미 발급된 인증서만 저장합니다.

## 구조

```
app.py                        진입점 (homey.app.App 상속, homey_export로 내보냄)
api.py                        설정 페이지 API (인증서 검증·저장·상태)
settings/index.html           앱 설정 화면 — 인증서 등록과 발급 안내 (en/ko)
lib/
  const.py                    실측 프로토콜 상수 (포트 범위, 타임아웃, 소스 포트 base)
  cert.py                     인증서 검증·설명, 게이트웨이 UUID 대조 (순수 cryptography)
  probe.py                    UDP 라이브니스 스윕 + 페어링 프로브
  discovery.py                서브넷 스윕 (응답 기반, 오탐 없음)
  compat.py                   SDK 계약 어댑터 (settings·i18n 동기/비동기 양쪽)
  session.py                  DtlsCoapSession의 asyncio 래퍼
  resources.py                /device/0 배치 파싱, 시리얼 처리
  registry/                   보드 토큰 라우팅 + 가전별 capability 맵
  selfcheck.py                런타임 자체 점검 (기동 시 1회)
drivers/appliance/
  driver.py                   검색·페어링 (인증서는 앱 설정에서)
  device.py                   세션 유지, 폴링 루프, 쓰기
  pair/configure.html         페어링 화면 (en/ko). 인증서 미설정 시 설정 위치를 안내
  repair/reconnect.html       복구 화면 — 연결 확인, 시리얼로 재탐색, 주소 직접 지정
locales/{en,ko}.json          앱 i18n (없으면 i18n.get_language가 en으로 떨어짐)
tests/
  fixtures/                   실기기 /device/0 덤프 (민감정보 리댁션)
  test_registry.py            레지스트리 회귀 테스트 (11개)
python_packages/              Homey CLI가 생성하는 아키텍처별 venv (커밋하지 않음)
```

전송 계층은 직접 구현하지 않고 [`smartthings-local`](https://pypi.org/project/smartthings-local/)에 위임합니다. `app.json`의 `pythonPackages`에 선언되어 있고, Homey CLI가 빌드 시 `uv`로 아키텍처별 venv에 설치합니다.

**드라이버는 가전 종류별로 나누지 않고 하나입니다.** 레퍼런스가 리소스 표면을 보고 종류를 런타임에 판정하므로 페어링 시점에는 드라이버를 고를 근거가 없습니다. 대신 기기 생성 시 `Registry.capabilities()`가 계산한 capability만 부여하므로, 각 유닛은 실제로 보고한 기능만 갖습니다.

### 지원 현황

레퍼런스가 지원하는 **16종 전부**를 라우팅합니다. 다만 검증 수준이 다릅니다.

| 가전 | 상태 |
|---|---|
| **에어컨** (`RAC/PRAC/KRAC/CAC/WAC/FAC/CAWW/ARA`) | **실기기 검증.** 전원·희망온도·현재온도·모드·풍량·쾌적모드·풍향·공기청정·자동건조·표시등·엣지라이팅·UV살균·부재절전·습도·전력·먼지·필터 (31개) |
| **인덕션** (`COOKTOP`) | **실기기 검증.** 구별 화력·상태·잔열, 차일드락(쓰기), 스마트제어, 안전차단, 전력, BT 온도 프로브 (19개) |
| 냉장고 (`REF`) | 미검증. 급속냉장·급속냉동·제빙·자동급수·내부조명·안식일·웰컴라이팅, 냉장/냉동 온도, 문열림, 정수필터 |
| 세탁기 (`WW/WD/WF/WV/WA*`) | 미검증. 동작상태·진행률·남은시간, 세탁온도·탈수·헹굼, 누적수량 |
| 건조기 (`DV*`) | 미검증. 동작상태·진행률·남은시간, 건조강도, 주름방지 |
| 식기세척기 (`ADW`, `DW*`) | 미검증. 동작상태·진행률, 살균, 가열건조, 누적수량, 사운드 |
| 공기청정기 (`AIR/TVTL/VTWW`) | 미검증. 풍량·표시등·펫필터·HEPA필터·공기질·PM10/2.5/1.0 |
| 제습기 (`DHM`) | 미검증. 습도·목표습도(쓰기)·필터 |
| 오븐·레인지·전자레인지 (`OVEN/RANGE/MICROWAVE`) | 미검증. 동작상태·모드·내부온도·설정온도·문열림 — **가열 제어 없음** |
| 가스쿡탑 (`CT`) | 미검증. 전원 상태·버너 사용 여부 — **읽기 전용** |
| 주방후드 (`AHD`) | 미검증. 풍량·조명(쓰기)·필터·공기질·전력 |
| 정수기 (`WATERPURIFIER`) | 미검증. 동작상태·차일드락·정수필터·누적수량 |
| 청정스테이션 (`VSKR`) | 미검증. 동작상태·먼지봉투 사용량/경고 |
| 에어드레서 (`DF`) | 미검증. 동작상태·진행률·살균 |

**"미검증"의 의미**: 필드명·리소스 경로·쓰기 가능 여부는 레퍼런스 정의에서 그대로 옮겼고, 라우팅과 매니페스트 정합성은 테스트로 확인했지만 **해당 가전 실물로 확인한 적이 없습니다.** 레퍼런스 주석이 모호했던 부분에서 값이 잘못 읽힐 수 있습니다. 공유 코어(전원·차일드락·알람·전력·동작상태)는 검증된 두 종에서 이미 동작하는 같은 코드입니다.

**가열 제어는 어느 타입에도 노출하지 않습니다.** 레퍼런스가 쿡탑에 대해 명시한 원칙(자동화가 원격으로 가열을 시작해선 안 됨)을 오븐·레인지·전자레인지·쿡탑 전체에 적용했고, 테스트로 강제합니다.

`CAC`(국내 천장형/상업용)는 레퍼런스 라우팅 표에 없어서 이 포트에서 추가했습니다.

**인덕션은 가열 제어를 노출하지 않습니다.** 레퍼런스가 명시한 원칙을 따릅니다 — 자동화가 원격으로 가열을 시작해선 안 됩니다. 화력은 읽기만 하고, 차일드락만 쓰기 가능합니다(잠금 토글은 가열 제어가 아니라는 레퍼런스 판단).

### 레퍼런스와 동기화

레퍼런스에 지원 기기가 추가됐는지 확인하는 스크립트가 있습니다. 릴리스 노트가 아니라 **라우팅 표를 직접 비교**하므로 조용히 추가된 토큰도 잡힙니다.

```sh
cd ../localthings-reference && git pull && cd -
python3 scripts/check_reference_coverage.py
```

미이식 종류, 우리가 라우팅하지 않는 보드 토큰, 서로 다르게 라우팅하는 토큰, 그리고 **우리에만 있어 업스트림에 기여할 만한 토큰**을 보고합니다.

## 참조 프로젝트

세 프로젝트를 같은 상위 폴더에 클론해 두고 상시 레퍼런스로 사용합니다. 이 저장소에 포함되지는 않습니다.

### 1. `../localthings-reference/` — [mbillow/localthings](https://github.com/mbillow/localthings)

**포팅 원본.** 최신 삼성 가전을 로컬 제어하는 Home Assistant 커스텀 통합(GPL-3.0). 기기 종류 판정, href → 엔티티 레지스트리, 상태 폴링/OBSERVE 관리, 인증서 발급 플로우 등 **기기 모델링 로직 전체**가 여기 있습니다. 우리가 옮겨야 할 대상이 바로 이 부분입니다.

저수준 통신은 자체 구현하지 않고 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 [`smartthings-local`](https://pypi.org/project/smartthings-local/) 라이브러리(순수 파이썬, 의존성은 `cbor2`·`pyopenssl`뿐)에 위임합니다. DTLS는 pyOpenSSL의 `SSL.DTLS_METHOD`로 처리합니다.

특히 참고할 파일:

| 파일 | 내용 |
|---|---|
| `config_flow.py` | 기기 추가: UUID 조회 → 인증서 발급 → 포트 스윕 → `/device/0` 확인 |
| `coordinator.py` | DTLS 세션 수명주기, 폴링, 쓰기 경로, 기기별 고정 소스 포트 |
| `observe.py` | OBSERVE 구독, 실패 시 폴링 강등 및 복구 재시도 |
| `registry/` | href → capability → 엔티티 매핑 (코드량의 대부분) |

```sh
cd ../localthings-reference && git pull   # 레퍼런스 최신화
```

### 2. `../smartthings-local-reference/` — [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)

**전송 계층의 소스.** `app.json`의 `pythonPackages`로 설치하는 [`smartthings-local`](https://pypi.org/project/smartthings-local/) 패키지의 원본 저장소입니다. 패키지만 써도 동작하지만, 프로토콜 디버깅 때 소스를 보려면 필요합니다.

- `smartthings_local/protocol/dtls_session.py` — DTLS 핸드셰이크 + CoAP 세션. 협상 불가능한 wire 상수들의 근거 주석이 여기 있습니다
- `smartthings_local/protocol/coap.py` — CoAP 인코딩/디코딩, Block2, OBSERVE
- **`setup_cert.py`** — 클라이언트 인증서 발급 스크립트. 사용자가 1회 실행합니다. 절차는 [`docs/CA-SETUP.md`](docs/CA-SETUP.md) 참고
- `mqtt_demo/` — 라이브러리 사용 예시(브리지 구현). 세션 수명주기 참고용

### 3. `../homey-pythonscript-reference/` — [jaccoh/homey-pythonscript](https://github.com/jaccoh/homey-pythonscript)

**Homey에서 파이썬을 쓰는 방법의 실증 사례.** Advanced Flow에서 파이썬 코드를 실행하게 해주는 Homey 앱입니다. 이 프로젝트가 알려주는 핵심 사실:

- Homey Apps SDK v3는 **네이티브 파이썬 런타임을 지원**합니다. `app.json`에 `"runtime": "python"`, `"pythonVersion": "3.14"`, `"pythonPackages": [...]`를 선언하고 `app.py`에 `homey.app.App`을 상속한 클래스를 두면 됩니다 (`compatibility: ">=13.0.0"` 필요).
- `pythonPackages`는 Homey CLI가 빌드 시점에 `uv`로 **아키텍처별 venv**(`python_packages/{amd64,arm64}/.venv/`)로 해석해 앱과 함께 배포합니다. 즉 네이티브 휠도 타겟 아키텍처(Homey Pro는 linux-aarch64)용으로 미리 받아 넣습니다.
- 런타임에 `/userdata/venvs/`에 venv를 만들고 `pip install`까지 할 수 있습니다 (`pythonscript/venv_manager.py`).

**우리 프로젝트에 중요한 이유:** Node.js에는 DTLS가 없어서 원래는 DTLS·CoAP 스택을 순수 JS로 재구현해야 했습니다. 파이썬 런타임을 쓰면 `smartthings-local`을 `pythonPackages`에 선언하는 것만으로 전송 계층이 끝나고, 레퍼런스 통합의 파이썬 코드도 거의 그대로 옮길 수 있습니다. 자세한 비교는 [`docs/PORTING.md`](docs/PORTING.md) 2절에 있습니다.

특히 참고할 파일: `app.json`(런타임 선언 방식), `app.py`(진입점과 플로우 카드 등록), `pythonscript/venv_manager.py`(런타임 venv 관리), `api.py`(settings 페이지용 API).

```sh
cd ../homey-pythonscript-reference && git pull
```

## 개발

```sh
homey app build                    # pythonPackages를 아키텍처별 venv로 해석 (Docker 필요)
homey app validate --level publish
homey app install                  # 영구 설치
```

> `homey app run`(dev 모드)은 영구 설치본을 대체하고 **실행이 끝나면 앱을 제거**합니다. 개발 후에는 `homey app install`을 다시 하세요.

설치된 앱 상태는 dev 모드 없이 확인할 수 있습니다:

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

해석된 언어, 로케일, 자격증명 크기, 기기별 푸시 상태(구독 수·알림 수·observing)를 반환합니다.

`homey app build`는 공식 빌더 이미지(`ghcr.io/athombv/python-homey-app-builder-{arm64,amd64}`)를 받아 `python_packages/{amd64,arm64}/.venv/`를 만듭니다. 이 venv들은 `app.json`에서 재생성 가능하므로 커밋하지 않습니다(약 36 MB의 바이너리). 클론 직후에는 `homey app build`를 한 번 돌리면 됩니다.

로컬 테스트·린트용 가상환경:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## 다국어

한국어와 영어를 지원하고, **선언되지 않은 언어는 영어로 표시됩니다** — 앱 이름·설명·capability 63개·플로우 카드·설정 라벨·웹뷰 3개·기기 이름 전부. `tests/test_i18n.py`가 이를 강제합니다(한국어 문자열만 추가하고 영어를 빠뜨리는 실수는 작성자에게 보이지 않기 때문에).

파이썬에서 발생하는 오류 메시지도 번역됩니다. Homey의 서버측 i18n은 앱 언어를 반환해 쓸 수 없으므로, 웹뷰가 알려준 UI 언어를 저장해 씁니다 — 자세한 내용은 [`docs/PORTING.md`](docs/PORTING.md) 11절.

## 라이선스

GPL-3.0-or-later. 프로토콜 분석과 기기 레지스트리 설계는 [mbillow/localthings](https://github.com/mbillow/localthings)와 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 작업에 기반합니다.

`assets/capabilities/mdi-*.svg`는 [Material Design Icons](https://pictogrammers.com/library/mdi/)에서 수정 없이 가져왔습니다 (Pictogrammers Free License / Apache-2.0). 새 capability 아이콘도 이 아이콘셋에서 가져옵니다:

```sh
curl -O https://raw.githubusercontent.com/Templarian/MaterialDesign/master/svg/<name>.svg
```
