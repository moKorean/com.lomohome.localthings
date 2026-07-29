# LocalThings (로컬띵스)

**SmartThings 클라우드 없이, 최신 삼성 가전을 집 안 네트워크에서 직접 제어하는 Homey 앱입니다.**

Home Assistant 통합 [mbillow/localthings](https://github.com/mbillow/localthings)를 Homey로 포팅하는 프로젝트입니다. 가전과 DTLS-over-CoAP 세션을 직접 맺어 상태를 읽고 명령을 보내므로, 클라우드 왕복이 없습니다.

> **상태: 초기 골격 (v0.1.0).** 파이썬 런타임 앱 구조와 의존성만 준비된 단계이며, 드라이버·레지스트리는 아직 구현되지 않았습니다. 설계와 남은 작업은 [`docs/PORTING.md`](docs/PORTING.md)를 참고하세요.

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

## 요구 사항

- **Homey Pro, 펌웨어 v13.0.0 이상.** 이 앱은 Homey의 파이썬 런타임(`"runtime": "python"`, Python 3.14)으로 동작하므로 v13 미만에서는 설치되지 않습니다.
- LAN UDP가 필요하므로 `local` 플랫폼 전용입니다. Homey Cloud에서는 동작할 수 없습니다.
- `AC14K_M` CA 인증서와 개인키 (저장소에 포함되어 있지 않습니다). 앱이 이 CA로 기기별 리프 인증서를 직접 발급하므로, 최초 1회만 입력하면 이후 추가하는 기기는 IP만 입력합니다.

## 구조

```
app.py                  진입점 (homey.app.App 상속, homey_export로 내보냄)
drivers/appliance/       제네릭 드라이버 — driver.py(페어링) + device.py(세션·폴링)
lib/                     전송 글루, 인증서 발급, 기기 레지스트리
python_packages/         Homey CLI가 생성하는 아키텍처별 venv (커밋하지 않음)
```

전송 계층은 직접 구현하지 않고 [`smartthings-local`](https://pypi.org/project/smartthings-local/)에 위임합니다. `app.json`의 `pythonPackages`에 선언되어 있고, Homey CLI가 빌드 시 `uv`로 아키텍처별 venv에 설치합니다.

## 참조 프로젝트

두 프로젝트를 같은 상위 폴더에 클론해 두고 상시 레퍼런스로 사용합니다. 이 저장소에 포함되지는 않습니다.

### 1. `../localthings-reference/` — [mbillow/localthings](https://github.com/mbillow/localthings)

**포팅 원본.** 최신 삼성 가전을 로컬 제어하는 Home Assistant 커스텀 통합(GPL-3.0). 기기 종류 판정, href → 엔티티 레지스트리, 상태 폴링/OBSERVE 관리, 인증서 발급 플로우 등 **기기 모델링 로직 전체**가 여기 있습니다. 우리가 옮겨야 할 대상이 바로 이 부분입니다.

저수준 통신은 자체 구현하지 않고 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 [`smartthings-local`](https://pypi.org/project/smartthings-local/) 라이브러리(순수 파이썬, 의존성은 `cbor2`·`pyopenssl`뿐)에 위임합니다. DTLS는 pyOpenSSL의 `SSL.DTLS_METHOD`로 처리합니다.

특히 참고할 파일:

| 파일 | 내용 |
|---|---|
| `config_flow.py` | 기기 추가: UUID 조회 → 리프 인증서 발급 → 포트 스윕 → `/device/0` 확인 |
| `coordinator.py` | DTLS 세션 수명주기, 폴링, 쓰기 경로, 기기별 고정 소스 포트 |
| `observe.py` | OBSERVE 구독, 실패 시 폴링 강등 및 복구 재시도 |
| `registry/` | href → capability → 엔티티 매핑 (코드량의 대부분) |

```sh
cd ../localthings-reference && git pull   # 레퍼런스 최신화
```

### 2. `../homey-pythonscript-reference/` — [jaccoh/homey-pythonscript](https://github.com/jaccoh/homey-pythonscript)

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
