# LocalThings community (로컬띵스 커뮤니티)

**SmartThings 클라우드 없이, 최신 삼성 가전을 집 안 네트워크에서 직접 제어하는 Homey 앱입니다.**

Home Assistant 통합 [mbillow/localthings](https://github.com/mbillow/localthings)를 Homey로 포팅하는 프로젝트입니다. 가전과 DTLS-over-CoAP 세션을 직접 맺어 상태를 읽고 명령을 보내므로, 클라우드 왕복이 없습니다.

> **상태: 개발 중 (v0.1.0).** 에어컨이 검색·페어링·폴링·제어까지 실기기에서 동작합니다. 상태 갱신은 폴링(기본 30초)이며 OBSERVE(푸시)는 미구현, 나머지 가전 종류는 미이식입니다. 설계와 실측 자료는 [`docs/PORTING.md`](docs/PORTING.md)를 참고하세요.

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
locales/{en,ko}.json          앱 i18n (없으면 i18n.get_language가 en으로 떨어짐)
tests/
  fixtures/                   실기기 /device/0 덤프 (민감정보 리댁션)
  test_registry.py            레지스트리 회귀 테스트 (11개)
python_packages/              Homey CLI가 생성하는 아키텍처별 venv (커밋하지 않음)
```

전송 계층은 직접 구현하지 않고 [`smartthings-local`](https://pypi.org/project/smartthings-local/)에 위임합니다. `app.json`의 `pythonPackages`에 선언되어 있고, Homey CLI가 빌드 시 `uv`로 아키텍처별 venv에 설치합니다.

**드라이버는 가전 종류별로 나누지 않고 하나입니다.** 레퍼런스가 리소스 표면을 보고 종류를 런타임에 판정하므로 페어링 시점에는 드라이버를 고를 근거가 없습니다. 대신 기기 생성 시 `Registry.capabilities()`가 계산한 capability만 부여하므로, 각 유닛은 실제로 보고한 기능만 갖습니다.

### 지원 현황

| 가전 | 상태 |
|---|---|
| 에어컨 (`RAC/PRAC/KRAC/CAC/WAC/FAC/CAWW/ARA`) | 전원·희망온도·현재온도·모드·풍량·공기청정·습도·전력·누적전력·필터 |
| 인덕션 (`COOKTOP`) | 구별 화력·상태·잔열, 차일드락(쓰기), 스마트제어, 안전차단, 전력, BT 온도 프로브 |
| 그 외 14종 | 미이식 ([`docs/PORTING.md`](docs/PORTING.md) 마일스톤 7) |

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
homey app run
```

`homey app build`는 공식 빌더 이미지(`ghcr.io/athombv/python-homey-app-builder-{arm64,amd64}`)를 받아 `python_packages/{amd64,arm64}/.venv/`를 만듭니다. 이 venv들은 `app.json`에서 재생성 가능하므로 커밋하지 않습니다(약 36 MB의 바이너리). 클론 직후에는 `homey app build`를 한 번 돌리면 됩니다.

로컬 테스트·린트용 가상환경:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## 라이선스

GPL-3.0-or-later. 프로토콜 분석과 기기 레지스트리 설계는 [mbillow/localthings](https://github.com/mbillow/localthings)와 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 작업에 기반합니다.
