# SmartThings Local (스마트싱스 로컬)

**[English README](README.md)** · **한국어**

SmartThings 클라우드 없이, 최신 삼성 가전을 집 안 네트워크에서 직접 제어하는 Homey 앱입니다.

Home Assistant 통합 [mbillow/localthings](https://github.com/mbillow/localthings)를 Homey로 포팅하는 프로젝트입니다. 가전과 DTLS-over-CoAP 세션을 직접 맺어 상태를 읽고 명령을 보내므로, 클라우드 왕복이 없습니다.

> **상태: [Homey 앱스토어 등록 완료](https://homey.app/a/com.lomohome.localthings/)** — 실제로 배포 중인 버전은 링크에서 확인하세요. 제출한 버전은 인증을 통과할 때까지 스토어에 반영되지 않습니다. 에어컨 4대, 인덕션 1대, 주방 후드 1대, 냉장고 3대가 검색·페어링·제어까지 실기기에서 동작하고, 상태는 CoAP OBSERVE로 푸시받습니다(폴링은 5분 주기 안전 스윕). 커스텀 capability 77개 전부가 플로우에서 쓰입니다. 나머지 14종은 라우팅과 capability 매핑까지 이식했지만 실기기 검증은 못 했습니다. 설계와 실측 자료는 [`docs/PORTING.md`](docs/PORTING.md), 남은 미매핑 리소스와 결정 기록은 [`docs/BACKLOG.md`](docs/BACKLOG.md)를 참고하세요.

## 동작 방식

| 계층 | 내용 |
|---|---|
| 전송 | UDP `49152-49160` 중 하나에서 DTLS 1.2, 클라이언트 인증서 인증 |
| 암호 스위트 | `ECDHE-ECDSA-AES128-GCM-SHA256` (`@SECLEVEL=0` 필요), ciphertext MTU 1200 고정 |
| 인증 | 삼성 클라우드 게이트웨이가 공개하는 식별자를 담은 클라이언트 인증서. 가전은 그 식별자를 확인하고 서명은 확인하지 않으므로, 앱이 직접 발급합니다 |
| 프로토콜 | CoAP (token-stable Block2 전송, OBSERVE 구독) |
| 페이로드 | CBOR로 인코딩된 OCF 리소스 표현 |
| 모델링 | `/device/0` 배치 응답을 href별 리소스로 파싱 → 가전 종류별 레지스트리가 href를 Homey capability로 매핑 |
| 종류 판정 | 기기가 스스로 밝히는 OCF 종류(`/oic/d`)를 먼저 보고, 그다음 모델 문자열의 보드 토큰. 같은 답에 이르는 독립적인 두 경로 |

## 대상 기기

Tizen RT 3.x / DAWIT 3.0+ 펌웨어를 쓰는 삼성 가전(대략 2022년 이후).

**앱이 지원한다고 밝히는 기기는 에어컨, 인덕션, 주방 후드, 냉장고입니다** — 실기기로 검증한 네 종입니다. 코드는 레퍼런스가 다루는 18종 전부를 라우팅하지만(아래 [지원 현황](#지원-현황)), 나머지 14종은 검증하지 못했으므로 앱 설명·태그에서 의도적으로 빼 두었습니다. 실제로는 동작할 수 있으니 시도해 보시고 결과를 알려주시면 반영하겠습니다.

미지원 기기를 IP로 추가하려 하면 앱이 그 기기의 `/device/0` 덤프로 **지원요청 리포트**를 만들어 줍니다. 시리얼·MAC·Wi-Fi 이름 같은 개별 식별자는 가려지고, 종류를 매핑하는 데 필요한 리소스 경로와 필드명은 남습니다.

`8888/tcp`만 열려 있는 구형 펌웨어(2018~2022년경, 토큰 기반 HTTPS)는 대상이 아닙니다.

호환 여부 확인:

```sh
nmap -Pn -sU -p 49152-49160 "$APPLIANCE_IP"
```

앱의 **기기 추가 → 검색**이 같은 일을 네트워크 전체에 대해 해줍니다. 응답한 기기만 종류를 확인하므로 IP를 몰라도 됩니다.

> 앱스토어 소개문은 [`README.txt`](README.txt)(영어)와 [`README.ko.txt`](README.ko.txt)(한국어)에 있습니다. 심사 제출 시 이 두 파일이 앱 설명으로 쓰입니다.

## 앱 설치 방법

앱을 설치하고 가전을 추가하면 됩니다. 앱이 첫 실행 때 클라이언트 인증서를 직접 발급하므로 별도의 인증서 단계가 없고, 컴퓨터에서 할 일도 없습니다.

### 1단계 — 앱 설치

**➡️ [Homey 앱스토어에서 설치](https://homey.app/a/com.lomohome.localthings/)**

대부분은 이것으로 끝입니다. 개발하거나 아직 배포되지 않은 변경을 써 보려면 소스에서 직접 설치합니다. [Homey CLI](https://apps.developer.homey.app/the-basics/getting-started)와 Docker가 필요합니다.

```sh
npm install -g homey
homey login

git clone https://github.com/moKorean/com.lomohome.localthings.git
cd com.lomohome.localthings
homey app install
```

`homey app install`이 `pythonPackages`를 아키텍처별 venv로 해석하느라 첫 실행은 몇 분 걸립니다.

> `homey app run`(개발 모드)은 영구 설치본을 **대체하고, 실행이 끝나면 앱을 제거**합니다. 개발 중이 아니라면 `homey app install`을 쓰세요.

### 2단계 — 없습니다. 앱이 직접 발급합니다

앱은 첫 실행 때 가전이 기대하는 식별자를 삼성 게이트웨이에서 읽고, 키를 만들어 클라이언트 인증서를 스스로 발급합니다. **설정 → 앱 → 스마트싱스 로컬**에 식별자·만료일과 앱이 발급했다는 표시가 나오고, 새로 발급하는 버튼도 있습니다. Homey를 교체했거나 식별자가 바뀐 경우에 쓰세요.

**인증서 하나가 집 안 모든 삼성 가전에 통용됩니다.** 식별자가 가전이 아니라 삼성 게이트웨이에서 오는 값이기 때문에, 기기별이 아니라 설치별로 하나만 있으면 됩니다.

이것이 가능한 이유는 **가전이 인증서에 담긴 식별자를 확인하고, 서명한 주체는 확인하지 않기** 때문입니다 — 에어컨과 냉장고에서 실측했고, 즉석에서 만든 키로 서명한 인증서를 둘 다 수락했습니다. 그래서 CA 개인키를 받아오거나 앱에 넣거나 저장하는 일이 전혀 없고, 다른 기기가 필요하지 않습니다. (거꾸로 말하면 같은 네트워크의 아무 기기나 같은 일을 할 수 있다는 뜻입니다. 식별자는 공개된 값이고 `AC14K_M` CA 키도 수년째 공개돼 있어, 로컬 발급이 이 범위를 넓히지는 않습니다.)

앱이 시작될 때 Homey에 인터넷 경로가 없으면 발급하지 않습니다. 연결된 뒤 앱 설정에서 버튼을 한 번 누르세요.

#### 직접 받은 인증서를 쓰려면 (선택)

삼성 `AC14K_M` CA가 서명한 인증서를 붙여넣을 수도 있고, 그쪽이 우선합니다 — 사용자가 넣은 인증서는 앱이 덮어쓰지 않습니다. 삼성이 서명한 인증서를 쓰고 싶을 때, 또는 나중에 가전 업데이트로 앱이 발급한 인증서를 받지 않게 될 때 사용하세요.

> **➡️ 전체 안내는 [`docs/CA-SETUP.md`](docs/CA-SETUP.md)에 있습니다.**

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
python3 -m venv .venv && .venv/bin/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/bin/python setup_cert.py --test
```

`client_fullchain.pem`을 **인증서 체인**에, `client.key`를 **개인키**에 붙여넣습니다. `client.pem`은 안 됩니다 — 리프 하나뿐입니다. 어느 방식이든 앱은 **CA 개인키를 받지 않습니다**.

### 3단계 — 가전 추가

**기기 → 기기 추가 → 스마트싱스 로컬 → 검색**

로컬 네트워크를 훑어 응답하는 가전을 찾고 종류까지 확인합니다. 1~2분 걸리며, 발견되는 대로 목록에 나타납니다. IP를 알고 있다면 직접 입력할 수도 있습니다.

### 문제가 생기면

기기의 **⋯ 메뉴 → 유지보수 → 복구**에서 연결을 확인하고, 주소가 바뀐 가전을 시리얼로 다시 찾거나 주소를 직접 지정할 수 있습니다.

설치된 앱의 상태는 개발 모드 없이 확인할 수 있습니다:

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

## 플로우 자동화

Homey는 **시스템 capability에만** 플로우 카드를 만들어 줍니다. 이 앱이 직접 정의한 77개는
카드가 없었고, 그래서 후드 조명을 플로우로 켜거나 필터 사용률로 알림을 보낼 수 없었습니다.

이제 **131장**입니다 — 동작 29, 조건 78, 트리거 24.

| 종류 | 범위 |
|---|---|
| 동작 | 쓰기 가능한 capability **전부**. 자동화를 막고 있던 실제 공백입니다 |
| 조건 | capability **전부**. 플로우에서 값을 읽을 수 있어야 센서가 의미를 갖습니다 |
| 트리거 | **사건인 것만** — 잔열 경고, 안전 차단, 프로브 연결, 진행률 등. "차일드락 변경됨"은 플로우가 기다리는 사건이 아닙니다 |

이 수가 한 번에 쏟아지지는 않습니다. 모든 기기 인자에 `capabilities=` 필터가 걸려 있어서
**그 capability를 가진 가전에만 카드가 보입니다** — 후드 사용자는 21장을 봅니다.

### 에어컨은 카드 한 장으로

설정 카드를 여러 장 이어 붙이면 각 카드가 이 앱이 캐시한 `/device/0`을 보고 보낼 내용을
정합니다. 이 캐시는 폴링으로 갱신되고 푸시 모드에서는 최대 5분 간격이라, 바로 뒤에 실행되는
카드가 앞 카드 이전의 상태를 보고 동작할 수 있습니다.

게다가 **수락 응답은 증거가 아닙니다.** 실기기 측정: 전원을 켜고 약 3초 뒤 운전 모드를 쓰면,
쓰기는 수락된 뒤 **기기가 시작하며 복원하는 자기 모드로 덮어써집니다.** 보고해 주신 플로우에서
사라진 설정이 바로 이것 — 켜기 다음에 오는 첫 카드입니다.

**에어컨 설정 한 번에 적용** 카드는 전원·운전 모드·희망 온도·공기청정·쾌적 모드를 한 장에서
받습니다. 각 단계 후 기기를 다시 읽어 값이 실제로 남았는지 확인하고, 기기가 되돌렸으면 다시
보냅니다 — 위 상황이 복구되는 것을 하드웨어에서 확인했습니다. 바꾸지 않을 항목은
"변경 안 함"(온도는 0)으로 두면 건너뜁니다.

**운전 모드가 우선입니다.** 모드마다 받아들이는 설정이 다르고, 받지 않는 설정도 프로토콜
상으로는 수락되며 거부 플래그가 없기 때문입니다. 처음 보고된 증상의 정체가 이것이었습니다:
플로우 마지막의 쾌적 모드 카드가 앞서 건 운전 모드를 되돌려서, 먼저 실행된 설정이 실패한
것처럼 보였습니다.

| 운전 모드 | 희망 온도 | 바람 세기 | 바람 방향 | 청정 | 무풍 | 롱바람 | 스피드 |
|---|---|---|---|---|---|---|---|
| AI 쾌적 | ✓ | | ✓ | ✓ | | | |
| 자동 | ✓ | | ✓ | ✓ | | | |
| 냉방 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 제습 | ✓ | | ✓ | ✓ | ✓ | ✓ | |
| 송풍 | | ✓ | ✓ | ✓ | ✓ | ✓ | |

기기 화면에서 모드별로 직접 확인한 표입니다. 선택한 모드가 받지 않는 항목은 쓰지 않고 그대로
둡니다 — 써도 무시되기 때문입니다. `난방`·`바람`은 이 유닛들이 냉방 전용이라 표에 없고,
모르는 모드는 아무것도 막지 않습니다. **확인된 것만 막는다**가 원칙입니다. 표는
[`lib/registry/ac_mode_matrix.py`](lib/registry/ac_mode_matrix.py)에 있습니다.

### 트리거는 Homey가 직접 실행합니다

Homey에는 커스텀 capability용 규약이 있습니다. `set_capability_value`로 값이 바뀔 때
`<capability>_true`/`<capability>_false`(boolean) 또는 `<capability>_changed`(그 외) 이름의
카드를 **Homey가 스스로 실행**합니다. 카드 이름을 그 규약에 맞췄으므로 앱에는 발화 코드가
거의 없습니다.

매 폴링마다 실행되지 않는 이유는 [`Device._apply`](lib/appliance/device.py)가 **값이 실제로
달라질 때만** setter를 호출하기 때문입니다. Homey가 내부적으로 변경을 판단하든 안 하든 결과는
같습니다.

**예외는 서브 capability입니다.** Homey는 `localthings_alarm_hot_surface.2_true`라는 카드를
찾으므로 존재할 수 없고, 그러면 인덕션의 구별 잔열 경고나 공기청정기의 HEPA·정수 필터 경보가
아무 트리거도 실행하지 못합니다. **그것만** 앱이 기본 capability의 카드로 발화합니다 — 일반
capability까지 발화하면 모든 플로우가 두 번 실행됩니다.

### 생성과 검증

카드는 [`scripts/make_flow_cards.py`](scripts/make_flow_cards.py)가 capability 정의에서
생성하고, `--check` 모드를 테스트가 실행합니다. capability를 추가하고 카드를 만들지 않으면
테스트가 실패합니다. **조건·동작 리스너도 같은 매니페스트에서 생성됩니다** — 카드마다 손으로
쓰면 거의 같은 함수가 백 개 생기고, 카드와 어긋난 첫 번째 것이 그 가전을 가진 사람에게만
실패합니다.

동작 카드는 `set_capability_value`가 아니라 `trigger_capability_listener`를 씁니다. 전자는
Homey의 값만 바꾸고 가전에는 아무것도 보내지 않으며, 거부됐을 때 예외도 나지 않습니다 — 그러면
플로우가 이루지 못한 성공을 보고합니다.

## 활동(타임라인)에 남는 것

Homey는 **insight 제목이 붙은 boolean** capability가 바뀔 때 타임라인에 스스로 한 줄 씁니다.
전원과 부재 감지만 보이던 이유가 이것입니다. 자동 건조와 자가진단에도 제목을 붙였으므로 사이클
시작·종료가 사건으로 남고, 부재 감지도 어느 쪽으로 바뀌었는지 표시됩니다.

두 가지는 그 경로로 갈 수 없어서 빠져 있었습니다. **숫자**는 insights를 켜도 그래프만 되고 줄이
안 생기며, **문자열**은 아예 불가입니다 — Homey 기본 라이브러리 전체에 `string` 타입으로
insights를 쓰는 capability가 하나도 없습니다. 그래서 운전 모드와 희망 온도 변경만 직접 씁니다.
모드는 고르실 때 쓰신 말로 표시됩니다. 기본값은 꺼짐이고 기기마다 **설정 → 타임라인**에서 켭니다
— 가전 아홉 대가 희망 온도가 바뀔 때마다 줄을 쓰면 타임라인이 묻히고, 원치 않는 타임라인은
없느니만 못합니다.

## IP가 바뀌어도 동작합니다

정체성은 IP가 아니라 **시리얼**(기기의 data id)입니다. 주소가 바뀌면:

- 폴링이 연속 3회 실패하면 앱이 서브넷을 스윕해 **시리얼이 일치하는 기기**를 찾아 스스로 갱신합니다. 재페어링이 필요 없습니다
- 폴링마다 시리얼을 대조하므로, **같은 모델 두 대가 IP를 교환해도 서로를 조작하지 않습니다** — 잘못된 가전에 붙는 대신 실패로 처리합니다
- 고급 설정의 IP·포트·연결 상태가 항상 실제 값으로 갱신됩니다

재배치에는 1~2분이 걸리고 그동안 기기는 사용 불가 상태입니다. 공유기에서 **고정 IP를 예약**해두면 이 경로를 타지 않습니다.

## 요구 사항

- **Homey Pro, 펌웨어 v13.0.0 이상.** 이 앱은 Homey의 파이썬 런타임(`"runtime": "python"`, Python 3.14)으로 동작하므로 v13 미만에서는 설치되지 않습니다.
- LAN UDP가 필요하므로 `local` 플랫폼 전용입니다. Homey Cloud에서는 동작할 수 없습니다.
- **클라이언트 인증서** — 앱이 첫 실행 때 직접 발급하므로 준비할 것이 없습니다. 원한다면 `AC14K_M`이 서명한 인증서를 컴퓨터에서 발급해 **설정 → 앱 → 스마트싱스 로컬**에 붙여넣습니다. UUID가 가전이 아니라 삼성 게이트웨이에서 오는 값이라 **인증서 하나로 집 안 모든 삼성 가전에 통용**되며, 이후 가전 추가는 IP만 입력합니다. 절차는 [`docs/CA-SETUP.md`](docs/CA-SETUP.md).

  앱은 **CA 개인키를 받지 않습니다** — 이미 발급된 인증서만 저장합니다.

## 구조

```
app.py                        진입점 (homey.app.App 상속, homey_export로 내보냄)
api.py                        설정 페이지 API (인증서 검증·저장·상태)
settings/index.html           앱 설정 화면 — 인증서 등록과 발급 안내 (en/ko)
lib/
  const.py                    실측 프로토콜 상수 (포트 범위, 타임아웃, 소스 포트 base)
  cert.py                     인증서 검증·설명, 게이트웨이 UUID 대조 (순수 cryptography)
  probe.py                    포트 스윕 + DTLS 라이브니스 게이트 + 페어링 프로브
  discovery.py                서브넷 스윕 (응답 기반, 오탐 없음)
  compat.py                   SDK 계약 어댑터 (settings·i18n 동기/비동기 양쪽)
  session.py                  DtlsCoapSession의 asyncio 래퍼
  resources.py                /device/0 배치 파싱, 시리얼 처리
  registry/                   종류 라우팅(/oic/d → 보드 토큰) + 가전별 capability 맵
    ac_mode_matrix.py         에어컨 운전 모드별로 실제 적용되는 설정 표
  support.py                  미지원 기기 리포트 (개별 식별자 리댁션)
  selfcheck.py                런타임 자체 점검 (기동 시 1회)
  appliance/                  드라이버·기기 구현. 종류별 드라이버가 상속할 수 있게 분리
    driver.py                 검색·페어링, 플로우 카드 리스너
    device.py                 세션 유지, 폴링 루프, 쓰기, capability 재조정
drivers/appliance/
  driver.py                   lib/appliance/driver.py를 상속하는 15줄 shim
  device.py                   lib/appliance/device.py를 상속하는 15줄 shim
  pair/configure.html         페어링 화면 (en/ko). IP 직접 입력은 서브넷을 미리 채웁니다
  repair/reconnect.html       복구 화면 — 연결 확인, 시리얼로 재탐색, 주소 직접 지정
locales/{en,ko}.json          앱 i18n (없으면 i18n.get_language가 en으로 떨어짐)
scripts/
  make_flow_cards.py          커스텀 capability에서 플로우 카드 생성 (--check로 검증)
  make_store_images.py        스토어 이미지, make_driver_images.py 드라이버 이미지
  check_reference_coverage.py 레퍼런스 대비 미이식 리소스 점검
tests/
  fixtures/                   실기기 /device/0 덤프 (식별자 난독화)
  test_registry.py            레지스트리 회귀 테스트
  test_range_hood.py          실기기 덤프로 후드 매핑 고정
  test_refrigerator.py        냉장고 3대(변온 냉장/냉동, 일반) 대조 검증
  test_flow_cards.py          생성된 카드와 capability 정의의 일치 검증
  test_support_report.py      미지원 기기 리포트의 리댁션 검증
python_packages/              Homey CLI가 생성하는 아키텍처별 venv (커밋하지 않음)
```

전송 계층은 직접 구현하지 않고 [`smartthings-local`](https://pypi.org/project/smartthings-local/)에 위임합니다. `app.json`의 `pythonPackages`에 선언되어 있고, Homey CLI가 빌드 시 `uv`로 아키텍처별 venv에 설치합니다.

**드라이버는 가전 종류별로 나누지 않고 하나입니다.** 레퍼런스가 리소스 표면을 보고 종류를 런타임에 판정하므로 페어링 시점에는 드라이버를 고를 근거가 없습니다. 대신 기기 생성 시 `Registry.capabilities()`가 계산한 capability만 부여하므로, 각 유닛은 실제로 보고한 기능만 갖습니다.

### 지원 현황

레퍼런스가 지원하는 **18종 전부**를 라우팅합니다. 다만 검증 수준이 다릅니다. 미검증 항목은 레퍼런스에서 이식했을 뿐 실제 기기로 확인하지 못한 것이고, 후드가 보여준 것처럼 **필드명을 추측하면 대체로 틀립니다** — 페어링은 되지만 아무 값도 읽히지 않습니다.

| 가전 | 상태 |
|---|---|
| **에어컨** (`RAC/PRAC/KRAC/CAC/WAC/FAC/CAWW/ARA`) | **실기기 검증.** 전원·희망온도·현재온도·모드·풍량·쾌적모드·풍향·공기청정·자동건조·표시등·엣지라이팅·UV살균·부재절전·습도·전력·먼지·필터·사운드·스마트 쿨 클린 상태/진행률 (38개) |
| **인덕션** (`COOKTOP`) | **실기기 검증.** 구별 화력·상태·잔열, 차일드락(쓰기), 스마트제어, 안전차단, 전력, BT 온도 프로브 (19개) |
| **주방후드** (`AHD`) | **실기기 검증** (AHD-WW-TP1-22). 전원, 풍량 5단(쓰기), 조명 켜기/끄기와 밝기 2단(쓰기), 자동환기 상태, 필터 사용률·교체경보, 공기질·먼지 PM10/2.5/1.0, 누적전력 (14개) |
| **냉장고** (`REF`) | **실기기 검증** (TP2X_REF_21K 키친핏 3대 — 변온고 냉장/냉동, 일반). 칸별 현재온도와 목표온도(쓰기), 변온실 모드(쓰기), 급속냉장(쓰기), 문열림, 누적전력 2종, 순간전력, 자체점검, 펌웨어 (9개) |
| 세탁기 (`WW/WD/WF/WV/WA*`) | 미검증. 동작상태·진행률·남은시간, 세탁온도·탈수·헹굼, 누적수량 |
| 건조기 (`DV*`) | 미검증. 동작상태·진행률·남은시간, 건조강도, 주름방지 |
| 식기세척기 (`ADW`, `DW*`) | 미검증. 동작상태·진행률, 살균, 가열건조, 누적수량, 사운드 |
| 공기청정기 (`AIR/TVTL/VTWW/AVT`) | 미검증. 풍량·표시등·펫필터·HEPA필터·공기질·PM10/2.5/1.0 |
| 제습기 (`DHM`) | 미검증. 습도·목표습도(쓰기)·필터 |
| 오븐·레인지·전자레인지 (`OVEN/RANGE/MICROWAVE`) | 미검증. 동작상태·모드·내부온도·설정온도·문열림 — **가열 제어 없음** |
| 가스쿡탑 (`CT`) | 미검증. 전원 상태·버너 사용 여부 — **읽기 전용** |
| 정수기 (`WATERPURIFIER`) | 미검증. 동작상태·차일드락·정수필터·누적수량 |
| 청정스테이션 (`VSKR`, `VSWW`) | 미검증. 동작상태·먼지봉투 사용량/경고 |
| 에어드레서 (`DF`) | 미검증. 동작상태·진행률·살균 |
| 에어모니터 (`ASM`) | 미검증. 공기질·PM10/2.5/1.0·CO2·습도·배터리 — 센서 전용, 전원 리소스가 없는 보드 |
| 열펌프 (`EHS`) | 미검증. 전원·출수 온도·설정 온도. zone 운전 모드·온수 루프·외출 모드는 별도 capability가 필요 — BACKLOG 참고 |

**"미검증"의 의미**: 필드명·리소스 경로·쓰기 가능 여부는 레퍼런스 정의에서 그대로 옮겼고, 라우팅과 매니페스트 정합성은 테스트로 확인했지만 **해당 가전 실물로 확인한 적이 없습니다.** 레퍼런스 주석이 모호했던 부분에서 값이 잘못 읽힐 수 있습니다. 공유 코어(전원·차일드락·알람·전력·동작상태)는 검증된 두 종에서 이미 동작하는 같은 코드입니다.

**가열 제어는 어느 타입에도 노출하지 않습니다.** 레퍼런스가 쿡탑에 대해 명시한 원칙(자동화가 원격으로 가열을 시작해선 안 됨)을 오븐·레인지·전자레인지·쿡탑 전체에 적용했고, 테스트로 강제합니다.

`CAC`(국내 천장형/상업용)는 레퍼런스 라우팅 표에 없어서 이 포트에서 추가했습니다.


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

**포팅 원본.** 최신 삼성 가전을 로컬 제어하는 Home Assistant 커스텀 통합(MIT). 기기 종류 판정, href → 엔티티 레지스트리, 상태 폴링/OBSERVE 관리, 인증서 발급 플로우 등 **기기 모델링 로직 전체**가 여기 있습니다. 우리가 옮겨야 할 대상이 바로 이 부분입니다.

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

가전을 제대로 매핑하려면 추측이 아니라 기기가 실제로 보고하는 값을 읽어야 하므로 — 주방 후드가
모든 필드명을 틀린 채 배포된 이유가 그것입니다 — 엔드포인트가 둘 더 있습니다.

```sh
# 각 가전이 보고하는 모든 리소스 (개별 식별자는 기본 리댁션, raw=1로 해제)
homey api raw --path /api/app/com.lomohome.localthings/resources

# 경로 하나를 전체 가전에서 한 번에 읽기 — /device/0에 없는 경로용
homey api raw -X POST --path /api/app/com.lomohome.localthings/read-resource \
  --body '{"path":"/oic/d"}'

# 쓰고 바로 다시 읽기 — "수락됐지만 반영 안 됨"이 구분됩니다
homey api raw -X POST --path /api/app/com.lomohome.localthings/write-resource \
  --body '{"host":"192.168.1.203","path":"/temperature/desired/cooler/0",
           "body":{"temperature":4}}'
```

`read-resource`를 만든 계기가 `/oic/d`입니다. 이 경로는 **모든 `/device/0` 배치 응답에 없어서**
직접 GET하지 않으면 실기기가 값을 채우는지 알 수 없었습니다. 우리 9대는 전부 채웁니다.

`homey app build`는 공식 빌더 이미지(`ghcr.io/athombv/python-homey-app-builder-{arm64,amd64}`)를 받아 `python_packages/{amd64,arm64}/.venv/`를 만듭니다. 이 venv들은 `app.json`에서 재생성 가능하므로 커밋하지 않습니다(약 36 MB의 바이너리). 클론 직후에는 `homey app build`를 한 번 돌리면 됩니다.

로컬 테스트·린트용 가상환경:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## 다국어

한국어와 영어를 지원하고, **선언되지 않은 언어는 영어로 표시됩니다** — 앱 이름·설명·capability 77개·플로우 카드 131장·설정 라벨·웹뷰 3개·기기 이름 전부. `tests/test_i18n.py`가 이를 강제합니다(한국어 문자열만 추가하고 영어를 빠뜨리는 실수는 작성자에게 보이지 않기 때문에).

파이썬에서 발생하는 오류 메시지도 번역됩니다. Homey의 서버측 i18n은 앱 언어를 반환해 쓸 수 없으므로, 웹뷰가 알려준 UI 언어를 저장해 씁니다 — 자세한 내용은 [`docs/PORTING.md`](docs/PORTING.md) 11절.

## 라이선스

GPL-3.0-or-later.

프로토콜 분석과 기기 레지스트리 설계는 [mbillow/localthings](https://github.com/mbillow/localthings)(MIT, © Marc Billow)와 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 작업에 기반하고, DTLS-CoAP 전송은 `smartthings-local`(MIT, © Jack Nagy)을 수정 없이 씁니다. MIT는 재사용을 허용하되 저작권·허가 표기를 함께 배포할 것을 요구하므로, 두 라이선스 전문을 [`NOTICE`](NOTICE)에 그대로 담고 어느 부분이 무엇에서 파생되었는지 적어 두었습니다. 앱 매니페스트의 `copyright`와 `contributors`에도 같은 내용을 표기했습니다(App Store 가이드라인 2.1).

`assets/capabilities/mdi-*.svg`는 [Material Design Icons](https://pictogrammers.com/library/mdi/)에서 수정 없이 가져왔습니다 (Pictogrammers Free License / Apache-2.0). 새 capability 아이콘도 이 아이콘셋에서 가져옵니다:

```sh
curl -O https://raw.githubusercontent.com/Templarian/MaterialDesign/master/svg/<name>.svg
```
