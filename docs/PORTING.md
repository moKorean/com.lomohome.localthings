# LocalThings → Homey 포팅 노트

레퍼런스:

- `../localthings-reference/` — [mbillow/localthings](https://github.com/mbillow/localthings), `main` @ `119a4f4` (v0.16.0). 포팅 원본
- `../smartthings-local-reference/` — [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local), `main` @ `8c2108a`. 전송 계층 소스 + `setup_cert.py`
- `../homey-pythonscript-reference/` — [jaccoh/homey-pythonscript](https://github.com/jaccoh/homey-pythonscript), `main` @ `55f491f` (v0.4.0). Homey 파이썬 런타임 실증 사례

이 문서는 세 레퍼런스를 실제로 읽고 실기기로 검증하며 정리한 설계 메모입니다. 구현이 진행되면 함께 갱신합니다.

---

## 1. 레퍼런스가 실제로 하는 일

HA 통합은 `smartthings-local` 파이썬 라이브러리에 저수준 통신을 위임하고, 자신은 **기기 모델링**만 담당합니다. 이 분업이 포팅 전략을 그대로 결정합니다.

```
HA 통합 (포팅 대상)
  config_flow.py      기기 추가 플로우: IP + CA PEM 입력, UUID 조회, 리프 인증서 발급, 포트 스윕
  coordinator.py      DTLS 세션 수명주기, /device/0 폴링, 상태 캐시, 쓰기 경로
  observe.py          CoAP OBSERVE 구독 (실패 시 폴링으로 강등, 600초마다 복구 재시도)
  registry/           href → capability → 엔티티 매핑 (코드량의 대부분)
  {sensor,switch,...}.py   HA 플랫폼별 엔티티 생성

smartthings-local 0.1.1 (PyPI, 순수 파이썬 py3-none-any)
  protocol/dtls_session.py   DtlsCoapSession: DTLS 핸드셰이크 + CoAP 요청/응답
  protocol/coap.py           CoAP 인코딩/디코딩, Block2, OBSERVE 옵션
  protocol/ocf_root_ca.pem   OCF 루트 CA
  ocf/state_cache.py         OCF 상태 캐시
  ocf/{keepalive,observe_refresh,poll_scheduler}.py
  의존성: cbor2>=5.6, pyopenssl>=23.0  ← 이게 전부입니다
```

핵심 흐름:

1. `_fetch_samsung_uuid()` — 삼성 클라우드 게이트웨이에서 기기 UUID 조회
2. `_mint_leaf_cert(ca_cert, ca_key, uuid)` — pyOpenSSL로 UUID를 CN에 담은 리프 인증서 발급, CA로 서명
3. `_find_live_ports()` — `49152-49160` UDP 라이브니스 스윕 (포트당 1.5초). 닫힌 포트는 ICMP로 즉시 탈락하므로 값싼 선별
4. `DtlsCoapSession(host, port, cert_pem, key_pem)` → `.connect()` → `.get(['device','0'])`
5. `parse_device0_batch()` — CBOR 배치 응답을 `{href: representation}`으로 평탄화
6. `registry/by_type/resolve(resources)` — 리소스 집합을 보고 가전 종류 판정, 해당 레지스트리 선택
7. `registry/discovery.discover()` — 레지스트리에 등록된 href마다 `BoundEntity` 생성. 미등록 href는 커버리지 갭으로 로깅

### 전송 계층 실측값 (`smartthings_local/protocol/dtls_session.py` 주석 기준)

라이브러리를 그대로 쓰든 재구현하든, 이 값들은 협상 대상이 아닙니다.

- **암호 스위트**: `ECDHE-ECDSA-AES128-GCM-SHA256`, `@SECLEVEL=0`과 함께 설정. SECLEVEL을 낮추지 않으면 최신 OpenSSL이 삼성 인증서 체인의 약한 파라미터를 거부합니다
- **ciphertext MTU 1200 고정**. 안 하면 OpenSSL이 클라이언트 인증서를 두 datagram으로 쪼개고 TizenRT가 두 번째를 버립니다
- **응답 상관은 `(token, mid)`로**. RT-OCF는 큰 응답에 ACK + separate-CON을 쓰므로 도착 순서로 짝지으면 one-shot과 OBSERVE 트래픽이 섞여 오배정됩니다
- **Block2는 token-stable**. 블록마다 새 토큰을 쓰면 서버가 조용히 버립니다
- **rate limit**: 세션당 기본 5 req/s (건조기 ~14, 오븐 ~8이 펌웨어 한계)
- **close_notify 없이 끊으면** 기기에 유령 DTLS 연결이 남습니다

### 이식할 때 놓치기 쉬운 디테일

- **DTLS 소스 포트를 기기별로 고정** (`coordinator._local_source_port`, base `49700` + IP 마지막 옥텟). 재접속 시 5-tuple을 유지해 비정상 종료로 남은 유령 세션을 핸드셰이크 시점에 축출합니다(RFC 6347 §4.2.8). 안 하면 5~15분간 읽기가 멈춥니다
- **`serialNum` 플레이스홀더 방어**. `ARTIK051_DONGLE_REF` 계열은 모든 유닛이 `Nothing(SVC)`를 반환하므로, 이를 실제 시리얼로 쓰면 같은 집의 두 기기가 unique id를 공유해 충돌합니다 (`_is_placeholder_serial()`)
- **모델별 기술자가 없습니다.** 기기가 광고하는 리소스 집합으로 종류를 판정하므로, 이미 지원되는 종류의 새 모델은 코드 추가 없이 붙습니다. 이 성질을 유지해야 합니다
- **CA는 1회 입력, 리프는 기기별 자동 발급.** 두 번째 기기부터는 IP만 받습니다

---

## 2. 런타임 선택: 파이썬 (권장) vs Node.js

### Homey는 파이썬 앱을 지원합니다

`homey-pythonscript`가 실증합니다:

```json
{
  "runtime": "python",
  "pythonVersion": "3.14",
  "compatibility": ">=13.0.0",
  "pythonPackages": ["restrictedpython>=7.0.0"]
}
```

`app.py`에 `homey.app.App`을 상속한 클래스를 두고 `homey_export = MyApp`으로 내보냅니다. 공식 `homey` 파이썬 모듈이 있고 플로우 카드 등록·autocomplete·`self.homey.flow` 등 JS SDK와 대응되는 API를 제공합니다. `api.py`로 settings 페이지용 API도 노출됩니다.

`pythonPackages`는 **Homey CLI가 빌드 시점에 `uv`로 아키텍처별 venv로 해석**해 앱과 함께 배포합니다:

```
python_packages/.python-version          # 3.14
python_packages/amd64/.venv/             # cpython-3.14.2-linux-x86_64-gnu
python_packages/arm64/.venv/             # cpython-3.14.6-linux-aarch64-gnu
```

두 venv 모두 저장소에 커밋되어 있습니다. 즉 네이티브 휠도 타겟 아키텍처용으로 개발 머신에서 미리 받아 넣는 구조이므로, 기기에서 컴파일이 일어나지 않습니다.

### 이게 결정적인 이유

원래 계획은 DTLS·CoAP 스택을 순수 JS로 재구현하는 것이었고, 그게 이 프로젝트의 유일한 실패 가능 지점이었습니다.

| | Node.js 경로 | 파이썬 경로 |
|---|---|---|
| DTLS | `node:tls`는 TCP 전용. `@nodertc/dtls`(experimental, 2019년 최종 배포)가 유일 후보 | pyOpenSSL `SSL.Context(SSL.DTLS_METHOD)` — 실제 OpenSSL |
| CoAP + Block2 + OBSERVE | 전부 자체 구현 (`coap` npm은 자기 소켓을 전제해서 DTLS 위에 못 얹음) | `smartthings-local`에 포함 |
| 인증서 발급 | `node-forge` 필요 (Node `crypto`는 X.509 서명 불가) | pyOpenSSL로 레퍼런스 코드 그대로 |
| `@SECLEVEL=0` | 순수 JS 구현에 해당 개념이 없음. 삼성 체인을 받아줄지 불명 | `set_cipher_list` 한 줄 |
| 레지스트리 포팅 | 파이썬 → JS 재작성 | 거의 그대로 복사 |
| 테스트 | 픽스처 재작성 | 레퍼런스의 골든 파일 덤프 그대로 재사용 |

파이썬 경로는 원래 마일스톤 1~3(스파이크·인증서·전송 계층)을 통째로 삭제합니다. 남는 건 HA 고유 글루를 Homey API로 바꾸는 작업뿐입니다.

### 의존성 체인 확인 결과

Homey Pro는 linux-aarch64입니다. 세 패키지 모두 휠이 있습니다:

| 패키지 | 최신 | aarch64 휠 |
|---|---|---|
| `smartthings-local` 0.1.1 | `py3-none-any` (순수 파이썬) | 불필요 |
| `pyopenssl` 26.3.0 | `py3-none-any` | 불필요 |
| `cryptography` 49.0.0 | `cp311-abi3-manylinux_2_28_aarch64.whl` | ✓ abi3이므로 3.14에서도 동작 |
| `cbor2` 6.1.3 | `manylinux_2_28_aarch64.whl` | ✓ (순수 파이썬 폴백도 있음) |

`cryptography`는 자체 OpenSSL을 번들하므로 DTLS 지원과 `@SECLEVEL=0` 동작이 시스템 OpenSSL에 의존하지 않습니다.

### 검증 완료: `pythonPackages`로 전체 의존성 체인이 들어옵니다

`runtime: python` + `pythonPackages: ["smartthings-local>=0.1.1"]`만 선언한 최소 앱으로 `homey app build`를 돌려 확인했습니다. Homey CLI는 공식 빌더 도커 이미지(`ghcr.io/athombv/python-homey-app-builder-{arm64,amd64}`)를 받아 두 아키텍처 모두에서 의존성을 해석합니다.

`python_packages/arm64/.venv/lib/python3.14/site-packages/`에 들어온 것:

```
smartthings_local/                                   0.1.1
OpenSSL/  pyopenssl-26.3.0.dist-info/                순수 파이썬
cryptography/hazmat/bindings/_rust.abi3.so           ELF aarch64  ← Rust 확장
cbor2/_cbor2.cpython-314-aarch64-linux-gnu.so        ELF aarch64
_cffi_backend.cpython-314-aarch64-linux-gnu.so       ELF aarch64
```

`file`로 확인한 결과 전부 `ELF 64-bit LSB shared object, ARM aarch64`입니다. 기기에서 컴파일이 일어나지 않고, 개발 머신에서 크로스 해석되어 앱과 함께 배포됩니다.

pyOpenSSL 26.3.0이 `dtls_session.py`가 실제로 호출하는 API를 노출하는지도 확인했습니다: `DTLS_METHOD = 10`, `Context` 메서드 매핑에 `DTLS_METHOD: (_lib.DTLS_method, None)`, 그리고 `Connection.set_ciphertext_mtu()` 모두 존재합니다.

venv 크기는 아키텍처당 약 18 MB (두 아키텍처 합 ~36 MB)로, 앱 배포 크기에 그만큼 더해집니다.

### 검증 완료: 실기기 런타임 자체 점검 통과

`homey app run --remote`로 Homey Pro(펌웨어 13.4.0, platform version 2)에 설치해 `lib/selfcheck.py`를 돌린 결과입니다. 앱 아카이브는 35.78 MB / 690 파일.

```
interpreter: 3.14.6 on aarch64 (linux)
smartthings-local: version unknown          ← import 성공 (__version__ 속성만 없음)
cbor2: native, roundtrip=True               ← 네이티브 확장 로드됨
pyopenssl-dtls: DTLS_METHOD ok, cipher list accepted, set_ciphertext_mtu=True
udp-bind-from-thread: bound ('0.0.0.0', 49700)
outbound-address: 192.168.1.133
```

의미:

- **네이티브 확장이 기기에서 실제로 로드됩니다.** `cbor2`가 순수 파이썬 폴백이 아니라 native로 잡혔습니다
- **`ECDHE-ECDSA-AES128-GCM-SHA256:@SECLEVEL=0`이 그대로 받아들여집니다.** 번들된 OpenSSL이 SECLEVEL 하향을 허용하므로 삼성 인증서 체인 문제가 없습니다
- **`socket` + `threading` 제약이 없습니다.** `DtlsCoapSession`이 쓰는 소스 포트 49700을 백그라운드 스레드에서 바인딩했습니다
- **앱이 LAN에 직접 붙습니다.** outbound 주소가 `192.168.1.133`(Homey 자신의 LAN IP)입니다. 도커 브리지 주소(`172.17.x.x`)가 아니므로 LAN 가전에 UDP가 도달합니다. HA 레퍼런스가 `network_mode: host`를 요구하는 이유가 여기서 자동으로 해결됩니다

### 검증 완료: 실기기 프로토콜 접근 성공

대상 기기: **삼성 천장형/상업용 에어컨**, `192.168.1.90`. CA 자격증명 준비는 [`CA-SETUP.md`](CA-SETUP.md) 참고.

| 단계 | 결과 |
|---|---|
| UDP 스윕 `49152-49160` | `49154` 응답(살아있는 리스너), `49153` 무응답(후보). 나머지 ICMP 거부 |
| 리프 인증서 발급 | UUID `ab0b0ac4-…`로 `AC14K_M` SHA-1 서명 |
| DTLS 핸드셰이크 | **2.91초에 성공** |
| `GET /oic/sec/acl` | **`2.05` — 기기 ACL이 인증서 수락** |
| `GET /device/0` | **`2.05`, 11,315 바이트, 51개 리소스 파싱** |

라이브 상태값 26개가 정상적으로 읽혔습니다: 현재온도 29.0°C, 습도 49%, 소비전력 99W, 누적 146.5kWh, 필터 사용 56/100시간(`FilterAlarm`), 모드 `AIComfort` 등.

### 이 기기는 레퍼런스 라우팅 표에 없습니다 (한 토큰 추가로 해결)

`modelNum`이 `TP1X_DA-AC-CAC-01001_0000|…`이라 `_board_tokens()`가 `[TP1X, DA, AC, CAC, 01001, 0000]`을 뽑는데, `_BOARD_TOKEN_TO_KEY`의 에어컨 항목은 `RAC/PRAC/KRAC/WAC/FAC/CAWW/ARA`뿐이고 **`CAC`가 없습니다**. `AC`는 제습기·공기청정기를 삼켜서 의도적으로 제외된 토큰이라 폴백도 없고, `for_device_by_resources()`의 시그니처(쿡탑·후드·오븐)에도 안 걸려 `resolve()`가 `None`을 반환합니다.

`_BOARD_TOKEN_TO_KEY`에 `'CAC': 'airconditioner'` 한 줄을 추가해 검증한 결과:

```
registry: airconditioner
bound entities: 41
unbound hrefs:  10 (of 51)
state keys:     26
```

**새 레지스트리가 필요한 게 아니라 라우팅 토큰만 없던 것**이 확인됐습니다. 기존 에어컨 레지스트리가 이 기기의 리소스 표면을 그대로 다룹니다. 업스트림([mbillow/localthings](https://github.com/mbillow/localthings))에도 기여할 가치가 있는 한 줄입니다.

미바인딩 10개는 이 모델 고유 기능들로, 커버리지 확장 대상입니다:

```
/edgelighting/vs/0                 엣지 라이팅 (status, colorOption, modeSupportedList…)
/light/stateful/vs/0               조명 on/off + 모드
/uvled/vs/0                        UV LED 살균
/filter/airdustPM1filter/vs/0      PM1 필터 (별도 필터, airdustfilter는 바인딩됨)
/smartsensingcooling/vs/0          스마트 센싱 냉방
/mds/absenceclean/vs/0             부재 중 청정
/settings/sound/{mode,optimization,output,volume}/vs/0   사운드 설정 4종
```

테스트 픽스처: `tests/fixtures/airconditioner_TP1X_DA-AC-CAC-01001.json` (시리얼·MAC·SSID·otnDUID 리댁션 완료).

### 검증 완료: 쓰기(제어)도 동작합니다

같은 에어컨에 전원 토글을 실행했습니다. 페이로드는 레퍼런스 `airconditioner._climate_write`의 `power` 분기 그대로입니다.

```
POST /power/vs/0   body: {'x.com.samsung.da.power': 'Off'}
  -> 2.04 Changed, 55 bytes
  -> body: {'x.com.samsung.da.power': 'Off', 'controlResponse': {'result': True}}
  +2s 재조회: 'Off'   (On -> Off 확인)
```

알아둘 점:

- **기기가 명시적 ack를 돌려줍니다.** 응답 body의 `controlResponse.result`가 `True`입니다. CoAP 코드(`2.04`)만 보고 성공으로 처리하지 말고 이 필드를 확인하는 것이 확실합니다. 쓰기 실패를 사용자에게 알리는 경로에 쓸 수 있습니다
- **반영이 빠릅니다.** 2초 안에 기기가 새 상태를 보고했습니다. 레퍼런스의 optimistic apply + settle guard가 세탁기 같은 느린 기기를 위한 것이므로, 에어컨은 짧은 settle 창으로 충분할 수 있습니다
- **변경 필드만 보냅니다.** `operationNumber` 같은 나머지 필드는 기기가 병합합니다
- **이 보드는 `/remotectrl/0`·`/remotectrl/vs/0`을 아예 보고하지 않습니다.** 따라서 `remote_control_enabled()`가 기본값 `True`(활성 가정)를 반환해 쓰기 게이트가 걸리지 않습니다. `CONF_BYPASS_REMOTE_CONTROL` 옵션은 이 기기에 불필요합니다
- **`close_notify`로 정상 종료됨을 확인**했습니다. 유령 세션이 남지 않습니다

### 검증 완료: Homey에서 엔드투엔드 동작

앱 설정에서 인증서 등록 → 검색으로 가전 발견 → 기기 생성 → 폴링 → 타일에서 제어까지 실기기로 확인했습니다. 전원 토글, 희망온도(0.5도 단위), 풍량 변경이 모두 반영됩니다. 앱 메모리는 약 45 MB.

### 파이썬 SDK 실측 (문서에 없어 런타임 조회로 확인)

`dir()`로 확인한 실제 표면:

```
homey        api app app_dir app_tmpdir apps arp ble clear_interval clear_timeout clock
             cloud dashboards debug discovery drivers emit env error flow geolocation
             has_feature has_permission i18n images insights log manifest mark_ready
             notifications on ... settings ...
homey.i18n       get_language get_strings get_units translate
homey.settings   get get_settings set unset
homey.arp        get_mac
homey.discovery  get_strategy
homey.api        get post put delete get_api get_api_app get_local_url
                 get_owner_api_token realtime unregister_api
```

주의할 점:

- **`settings.get/set/unset`은 동기입니다.** 다만 확증 전에는 코루틴 가능성을 배제할 수 없었고, `await` 없이 코루틴을 호출하면 **저장이 안 되면서 성공처럼 보입니다**. `lib/compat.py`가 awaitable이면 await하도록 감싸고, 저장 후 되읽어 검증합니다
- **`i18n.get_language()`는 앱의 i18n 언어**를 반환합니다. Homey UI가 한국어여도 `locales/ko.json`이 없으면 `'en'`이 나옵니다(`get_strings()`가 `{}`). 접근자 문제가 아니라 로케일 누락이었습니다
- **`homey:manager:api` 권한은 불필요합니다.** `homey.api.*`(앱이 Homey Web API 호출)를 쓸 때만 필요하고, 설정 페이지가 자기 앱 API를 부르는 것은 CrossFrame 경로입니다. 선언하면 Athom 심사가 강화된다는 경고가 나옵니다

### 웹뷰(설정·페어링) 실측

`homey.js`를 기기에서 직접 받아 확인한 계약입니다. 여기서 두 번 막혔으므로 기록합니다.

```js
Homey.prototype._onWindowLoad = function () {
  this._getOrigin()                                  // /js/homey.<origin>.js 로드
    .then(() => this._onWindowLoadExtended())        // css + getAppLocales + i18n
    .then(() => { window.Homey = this;               // ← 여기서야 인스턴스
                  window.onHomeyReady && window.onHomeyReady(this); })
    .catch(error => this.alert(error));
};
```

- **전역 `Homey`는 처음엔 생성자입니다.** `typeof Homey !== 'undefined'`로 판별하면 생성자를 붙잡게 되고, 그러면 `ready()`가 인스턴스에서 호출되지 않아 **설정 화면은 로딩이 안 걷히고 페어링 뷰는 흰 화면**이 됩니다. 필요한 **메서드 유무로 판별**해야 합니다
- **설정 페이지는 `<script src="/homey.js" data-origin="settings">`가 필요**하고, **페어링 뷰는 넣으면 안 됩니다** — `/js/homey.pair.js`가 404이므로 `loadScript`가 실패합니다. 페어링 뷰용 스크립트는 Homey가 주입합니다
- **설정 페이지는 완전한 HTML 문서**여야 합니다(`<!DOCTYPE html>` + `<head>`)
- `Homey.api(method, path, body, callback)`는 **프로미스와 콜백 둘 다** 지원합니다. `Homey.emit`도 프로미스입니다
- `getLanguage()`는 **프로미스**를 반환합니다. `Homey.language`는 i18n 로드 후에 채워집니다
- `onHomeyReady`가 한 번만 불리므로, 초기화는 `onHomeyReady`/`DOMContentLoaded`/`load`/폴링을 함께 걸고 가드로 중복을 접는 편이 안전합니다

### 디스커버리 실측

- **mDNS·SSDP로는 찾을 수 없습니다.** 실제 네트워크를 훑은 결과 Matter/Thread와 타사 서비스만 있었고, 16진 이름 서비스들은 인스턴스가 없었습니다. `homey.discovery` 전략은 쓸 수 없습니다
- **`arp.get_mac(ip)`은 개별 조회만** 됩니다. 호스트 열거는 불가
- **살아있는 가전은 DTLS 포트로 온 쓰레기 datagram에 alert(15바이트)로 응답합니다.** 이것이 스윕을 가능하게 하는 핵심입니다 — 응답만 후보로 세면 없는 호스트와 닫힌 포트가 모두 걸러지고 오탐이 0입니다. `probe.py`의 단일 호스트 검사는 "무응답 = 후보"로 보는데, 서브넷 전체에서는 그 반대가 필요합니다
- 실측: /24에서 2286개 조합 약 15초, 응답 10곳

### 남은 검증 항목

없습니다. 기능 확장만 남았습니다.

---

## 3. HA → Homey 매핑

| HA | Homey |
|---|---|
| `config_flow.py` | 드라이버 `pair/` 커스텀 HTML 뷰 (IP + CA PEM 2개 필드) + 드라이버 페어링 핸들러. `../com.lomohome.video_door_bell_lock/drivers/smartdoor/pair/configure.html` 패턴 참고 |
| options flow (`CONF_BYPASS_REMOTE_CONTROL`) | `driver.compose.json`의 `settings` |
| `DataUpdateCoordinator` | 디바이스 클래스의 폴링 루프 + `ObserveManager` 대응 로직 |
| 기기 1대 = HA device + N entities | 기기 1대 = Homey device 1개 + N capabilities |
| 플랫폼 `sensor`/`binary_sensor`/`switch`/`number`/`select`/`button`/`time`/`climate`/`fan` | Homey capability 타입 `sensor`/`boolean`/`number`/`enum`. 표준 capability로 안 되는 것은 `.homeycompose/capabilities/*.json`에 커스텀 정의 |
| `registry/by_type/*.py` | 구조를 1:1로 유지 (파이썬 런타임이면 거의 그대로) |
| `entity.py`의 `unique_id` | capability id + 기기 시리얼 |
| `diagnostics.py` | settings 페이지의 진단 덤프 (`api.py` 패턴) |

**드라이버 구성 방향:** 가전 종류마다 드라이버를 따로 만들지 말고, **단일 제네릭 드라이버 + 런타임 capability 동기화**를 권합니다. 레퍼런스가 종류를 런타임에 판정하는 구조이므로 페어링 시점에는 어떤 드라이버인지 알 수 없고, 이 저장소의 `video_door_bell_lock`이 이미 `applyConfig()`로 런타임 capability 추가/제거 패턴을 검증해 두었습니다. 다만 Homey 앱스토어 노출 측면에서는 종류별 드라이버가 유리하므로, 프로토콜이 붙은 뒤 재검토합니다.

---

## 4. 그 외 고려사항

- **CA 자격증명 보관.** `homey.settings`에 앱 단위로 저장(기기 간 재사용). 리프 인증서/키는 기기 store에. `.gitignore`에 `*.pem`/`*.key`를 이미 넣어두었습니다
- **앱스토어 심사.** 사용자에게 CA **개인키**를 붙여넣게 하는 앱은 공식 스토어 승인이 어려울 수 있습니다. 커뮤니티 스토어 또는 자체 설치 배포를 전제하는 편이 안전합니다
- **CA 번들은 저장소에 포함하지 않습니다.** 레퍼런스도 마찬가지이며, 획득 방법만 `SmartThings-Local`의 `setup_cert.py`로 안내합니다

---

## 5. 제안 마일스톤 (파이썬 경로)

1. ~~**스파이크 — `pythonPackages`로 의존성 체인 확인.**~~ **완료** (2절 참고). aarch64 네이티브 확장까지 정상 반입
2. ~~**스파이크 — 실기기 핸드셰이크.**~~ **완료** (2절 참고). `/device/0` 덤프까지 성공
3. ~~`app.py` + 제네릭 드라이버 + 페어링 뷰~~ **완료.** `homey app validate --level publish` 통과, 실기기에 설치해 앱·드라이버 정상 init 확인
4. ~~레지스트리 이식 — 배치 파싱 + 종류 판정~~ **완료** (에어컨). 실기기 덤프를 픽스처로 회귀 테스트 9개
5. ~~**가전 1종 엔드투엔드**~~ **완료.** 에어컨 페어링·폴링·제어 확인
6. ~~**OBSERVE 구독 및 폴링 강등/복구**~~ **완료.** 5대 전부 푸시 모드 확인 (8절)
7. ~~**나머지 가전 종류 레지스트리 확장**~~ **라우팅 완료 (16/16 종, 22/22 토큰).** `scripts/check_reference_coverage.py`가 갭 없음을 보고합니다. 13종은 실기기 미검증 — 10절 참고
8. **에어컨 커버리지 확장** — 현재 8개 리소스 바인딩(51개 중). 운전 상태 상세, 알람 코드, 예약, 자동청소, AI수면, 절전, 모션 감지 풍향, 자가진단, 엣지 라이팅, UV LED, PM1 필터, 사운드 설정 미커버

파이썬 SDK 메서드는 모두 실행으로 확인됐습니다: `get_store()`, `get_settings()`, `get_capabilities()`, `get_capability_value()`, `set_capability_value()`, `register_capability_listener()`, `set_available()`/`set_unavailable()`, `on_pair`, `session.set_handler`, `homey.settings.*`, `homey.i18n.*`.


---

## 6. 레퍼런스에 기기가 추가될 때 우리는 얼마나 쉽게 따라가는가

솔직한 답: **기계적이지만 복사·붙여넣기는 아닙니다.** 종류 하나 추가는 몇 시간 규모의 한정된 작업입니다.

그대로 가져올 수 있는 것:

- **보드 토큰 라우팅** — 표 구조를 1:1로 유지했으므로 토큰 한 줄 추가로 끝납니다 (`CAC`가 그 예)
- **리소스 href와 필드명** — 레퍼런스의 `capabilities/*.py`가 필드명의 근거입니다. 인덕션은 `capabilities/range.py`의 정의를 그대로 따랐고 실기기에서 바로 맞았습니다
- **안전·정확성 판단** — "가열 제어는 노출하지 않는다", "차일드락은 안전하다", "센티넬 값은 발행하지 않는다" 같은 결정은 레퍼런스가 이미 근거와 함께 기록해 뒀습니다
- **테스트 픽스처 형식** — `/device/0` 덤프 그대로

그대로 안 되는 것:

- **HA는 동적 옵션·임의 단위를 갖는 엔티티를 만들지만, Homey는 매니페스트에 정적으로 선언된 capability를 씁니다.** 새 종류마다 `.homeycompose/capabilities/*.json`과 아이콘이 필요합니다. 인덕션에서 9개를 새로 만들었습니다
- **HA 엔티티 다중성 → Homey 서브 capability.** 버너 3개는 `localthings_burner_level.{0,1,2}`가 되고, 구별 이름은 기기 생성 시 `capabilitiesOptions`로 넘겨야 합니다(매니페스트에 못 넣음). `Spec.titles`와 `Registry.capability_options()`가 그 처리입니다
- **복합 엔티티가 1:1로 안 맞습니다.** 에어컨의 HA `climate` 엔티티는 전원·모드·온도·풍량을 하나로 묶고 여러 리소스에 걸쳐 씁니다. 우리 `Spec`은 capability ↔ (리소스, 필드) 단순 대응이라 나눠서 표현합니다
- **레퍼런스의 `poll_tier`, `rt_filter`, `match_fn`, 패턴 capability가 우리에겐 없습니다.** 필요해지면 그때 추가해야 합니다. `exists_fn`에 해당하는 `Spec.exists`는 인덕션 작업에서 필요해져서 추가했습니다

즉 구조는 따라가기 쉽게 맞춰져 있고, **남은 비용은 Homey의 정적 capability 모델 때문**이며 이는 포팅으로 없앨 수 있는 종류의 비용이 아닙니다.


---

## 7. 이 네트워크에서 실제로 찾은 것 (2026-07-29)

보유 삼성 가전 10대(+스마트싱스 허브)에 대해 조사한 결과입니다. 스윕 결과를 그대로 믿으면 안 되는 이유가 여기 있습니다.

### 스윕 응답 10곳 중 삼성 가전은 5곳

MAC OUI로 갈렸습니다:

| 호스트 | OUI | 정체 |
|---|---|---|
| `.90` `.10` `.94` `.118` | `34:55:e5` `1c:e8:9e` `34:fc:99` | **에어컨 4대** (`TP1X_DA-AC-CAC-01001`) |
| `.107` | `34:55:e5` | **인덕션** (`TP1X_DA-KS-COOKTOP-01011`, NV9000D-/KO4) |
| `.117` `.184` `.195` `.246` | `1c:53:f9` `54:ef:44` `2c:ba:ba` `c0:95:6d` | **삼성 아님.** `54:ef:44`는 Lumi United(Aqara) |

**응답 = 삼성 가전이 아닙니다.** DTLS를 쓰는 다른 기기(이 네트워크의 Matter/Thread/Aqara 계열)도 쓰레기 datagram에 alert로 응답합니다. 응답 레코드의 버전 바이트가 갈리는 것도 확인했습니다 — 삼성 RT-OCF는 `0x0200`/`0x0100`, 표준 스택은 `0xFEFD`(DTLS 1.2). 다만 이걸 판별에 쓰기엔 근거가 약해서 앱은 핸드셰이크 성공 여부로만 판정합니다.

### 응답하지 않은 삼성 호스트 3대 = 로컬 API 없음

ARP 스윕으로 삼성 OUI 호스트를 전부 찾아 `.179`, `.192`, `.203`을 추가로 확인했습니다. 이 3대는:

```
udp 49152-49170  응답 없음
tcp 8888/443/80/8080/9080/55000  전부 닫힘
```

**세 번째 범주입니다.** 레퍼런스 README는 신형(DTLS/CoAP)과 구형(`8888/tcp` 토큰 방식)을 구분하는데, 이들은 **둘 다 아니고 로컬 포트를 아예 열지 않습니다** — 클라우드 전용 펌웨어로 보입니다. 냉장고·변온고·후드가 여기 해당할 가능성이 큽니다. 이 프로토콜로는 지원 불가입니다.

선풍기는 삼성 OUI 호스트로도 안 나타났으니 WiFi가 아니라 BLE/Zigbee로 허브에 붙어 있을 것입니다.

### 시사점

- 지원 가능 여부는 **모델 세대**가 갈라놓습니다. 같은 집 안에서도 에어컨·인덕션은 열려 있고 냉장고는 닫혀 있습니다
- 사용자에게 "찾지 못함"을 보고할 때 **왜**를 구분해줄 수 있으면 좋습니다: 응답했지만 삼성 아님 / 삼성이지만 로컬 API 없음 / 구형 펌웨어. 현재 앱은 "응답했지만 식별 실패"까지만 구분합니다
- 미식별 호스트에 대한 핸드셰이크 시도가 기기당 12초까지 걸립니다. 비삼성 기기가 많은 네트워크에서는 검색이 그만큼 길어집니다

---

## 8. Homey 웹뷰·런타임 제약 (실측, 2026-07-29)

여기서 여러 번 막혔으므로 확정된 것만 기록합니다.

### `Homey.emit`은 30초에 타임아웃됩니다

페어링 핸들러가 그보다 오래 걸리면 `Timeout after 30000ms`로 실패합니다. 서브넷 검색은 1~2분(스윕 15초 + 응답 기기당 핸드셰이크, 비삼성 기기는 타임아웃 12초)이라 동기 핸들러로는 불가능합니다.

해결: **백그라운드 작업 + 폴링**. `discover_start`가 태스크만 띄우고 즉시 반환, `discover_status`를 1초 주기로 폴링. 레퍼런스 파이썬 앱이 설정 API의 ~10초 제한에 대해 쓴 것과 같은 패턴입니다. 부수 효과로 결과가 하나씩 나타납니다.

### `homey app run`은 앱을 제거합니다

dev 실행은 영구 설치본을 **대체**하고, 실행이 끝나면 **앱 자체가 제거**됩니다. 개발 후에는 `homey app install`을 다시 해야 남습니다. 로그 한 줄을 보려고 dev 모드를 켜는 비용이 이것이라, 진단은 아래 방식으로 합니다.

### 진단은 앱 API로 (dev 모드 없이)

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

해석된 언어, 로드된 로케일 키, 자격증명 크기, 그리고 **기기별 푸시 상태**(구독 수, 알림 받은 리소스 수, observing 여부)를 반환합니다. OBSERVE 판정 버그를 이걸로 찾았습니다.

### `i18n.get_language()`는 UI 언어가 아닙니다

`locales/ko.json`이 로드된 상태(`get_strings()`가 키를 반환)에서도 한국어 Homey에서 `'en'`을 반환합니다. **앱의 언어**를 주는 것으로 보입니다. 웹뷰의 `Homey.getLanguage()`가 UI 언어를 정확히 줍니다 — 페어링 뷰가 보고한 환경:

```json
{"language_property": "undefined", "has_getLanguage": "function",
 "driver_language": "en", "resolved": "ko"}
```

즉 `Homey.language` 속성은 페어링 뷰에 **없고**, `getLanguage()`는 있습니다. 그래서 뷰는 `getLanguage()` → `Homey.language` → 드라이버 순으로 해석하고, 기기 기본 이름의 언어도 뷰가 드라이버에 넘겨줍니다.

### OBSERVE 검증 완료

에어컨 4대 + 인덕션 1대 전부 푸시 모드 진입 확인:

```
에어컨: subscriptions 22, notified 21~22 -> observing true
인덕션: subscriptions  4, notified  4    -> observing true
```

**판정 시점이 중요합니다.** 처음에는 구독 직후 15초 sleep 안에서 판정했는데, 22개 구독은 전송만 4.4초(라이브러리가 CON을 5/s로 페이싱)이고 초기 알림이 그 뒤로도 계속 도착합니다. 그래서 21/22가 도착하는 기기가 "푸시 불가"로 기록되고 재시도는 10분 뒤였습니다. 이제 구독만 하고 **판정은 이후 폴링 주기에서** 하며, grace는 45초로 늘렸습니다 — 더 이상 아무것도 블로킹하지 않으므로 길게 잡는 비용이 없습니다.


---

## 9. IP가 바뀌면 어떻게 되는가

DHCP로 주소가 바뀌는 것은 흔한 일이고, 세 가지 서로 다른 문제를 만듭니다.

### 문제 1: 연결이 끊긴다

기기 store에 `host`/`port`가 페어링 시점 값으로 박혀 있으면, 주소가 바뀐 뒤 세션이 실패하고 폴링이 계속 실패해 기기가 unavailable로 남습니다. 재페어링 외에 복구 수단이 없습니다.

**해결:** 정체성은 주소가 아니라 **시리얼**입니다(기기의 data id). 폴링이 연속 3회 실패하면 서브넷을 스윕해 **시리얼이 일치하는 호스트**를 찾아 store와 설정을 갱신하고 세션을 새로 맺습니다. 3회로 잡은 이유는 1회 타임아웃은 보통 가전이 잠깐 바쁜 것이고, 전체 스윕이 한 주기 기다리는 것보다 훨씬 비싸기 때문입니다.

시리얼을 보고하지 않는 펌웨어(`read_serial`이 `host:port`로 폴백하는 경우)는 이 방법으로 식별할 수 없어 재배치하지 않습니다. 로그로 이유를 남깁니다.

### 문제 2: 두 기기가 주소를 교환하면 서로를 조작한다

이게 더 위험합니다. 같은 모델 두 대(이 집에는 에어컨 4대가 같은 보드)의 IP가 서로 바뀌면, 각 Homey 기기가 **다른 가전을 조용히 제어**합니다. 안방 에어컨을 끄면 예린방이 꺼지는 식입니다. unavailable보다 나쁩니다.

**해결:** 폴링마다 `/device/0`에서 읽은 시리얼을 저장된 시리얼과 **대조**합니다. 다르면 상태를 적용하지 않고 실패로 처리해, 재배치가 올바른 호스트를 찾도록 합니다.

### 문제 3: 설정 화면이 옛 주소를 보여준다

`host`/`port`가 페어링 시점에만 기록되면, 주소가 바뀐 뒤 사용자가 확인하러 가는 바로 그 값이 낡아 있습니다.

**해결:** 폴링마다 `set_settings`로 동기화합니다. 고급 설정에 이제 이것들이 표시됩니다:

| 항목 | 내용 |
|---|---|
| IP 주소 | 자동 갱신됨 |
| DTLS 포트 | 자동 갱신됨 |
| 모델 | 보드 식별자 |
| 시리얼 번호 | IP가 바뀌어도 불변인 정체성 |
| 연결 상태 | `push, 22 subscriptions` 또는 `polling` |

실측 확인:

```
삼성 에어컨   <serial>   push, 22 subscriptions
삼성 에어컨   <serial>   push, 22 subscriptions
삼성 인덕션   <serial>   push, 4 subscriptions
```

(시리얼은 기기를 식별하는 값이라 문서에는 남기지 않습니다. 실제 값은 각 기기의 고급 설정에서 확인할 수 있습니다.)

### 남는 권장사항

재배치는 서브맷 스윕 + 후보별 핸드셰이크라 **1~2분** 걸리고, 그 사이 기기는 unavailable입니다. 공유기에서 **고정 IP 예약**을 걸어두면 이 경로를 아예 타지 않습니다. 앱이 스스로 복구할 수 있다는 것과 복구가 빠르다는 것은 다른 얘기입니다.


---

## 10. 15종 일괄 이식에서 실제로 한 것과 하지 않은 것

레퍼런스의 16종 전부가 라우팅되고, `scripts/check_reference_coverage.py`가 갭 없음을 보고합니다. 다만 **검증 수준이 다르다는 점이 중요합니다.**

### 한 것

- **보드 토큰 라우팅 22개 전부** + 소비자 모델 접두어(세탁기·건조기·식기세척기). 레퍼런스가 인식하는 기기가 우리 앱에서 "미지원"으로 뜨는 경우는 없습니다
- **공유 코어** (`lib/registry/shared.py`) — 전원(OCF/vendor 양쪽), 차일드락, 원격제어 게이트, 알람, 전력·누적전력, 물 사용량, 정수필터, 펌웨어, 자가진단, 동작상태(진행률·남은시간), 사운드, 문열림. 레퍼런스가 `common.UNIVERSAL`/`common.POWER`를 거의 모든 타입에 앞세우는 구조를 그대로 반영했습니다. **이 코드는 검증된 두 종에서 이미 동작하는 것과 동일합니다**
- **타입별 고유 리소스**를 필드명 단위로 이식
- **테스트 44개** — 특히 이 볼륨에서 의미 있는 구조적 검사들:
  - 레퍼런스가 라우팅하는 모든 토큰이 여기서도 라우팅되는지
  - 레지스트리가 지칭하는 모든 capability에 매니페스트 정의가 있는지 (없으면 그 가전 소유자만 기기 생성 실패)
  - 정의됐지만 안 쓰이는 capability가 없는지 (이름 변경 잔재)
  - `setable` 선언과 `Spec.writable`이 일치하는지 (안 맞으면 조작은 되는데 아무 일도 안 일어남)
  - 아이콘 파일이 실제로 존재하는지
  - **가열 제어가 쓰기 가능하지 않은지** — 오븐·레인지·전자레인지·쿡탑 전체
  - 소비자 접두어가 보드 토큰을 앞지르지 않는지 (`WAC` 창문형 에어컨이 `WA` 세탁기가 되면 안 됨)

### 하지 않은 것

- **13종은 실기기로 확인한 적이 없습니다.** 이 집에는 에어컨과 인덕션만 로컬 API가 열려 있습니다(7절). 레퍼런스 주석이 리소스 모양을 모호하게 남긴 부분에서 값이 잘못 읽힐 수 있습니다
- **냉장고의 구획별 값**은 레퍼런스가 패턴 href(`/temperatures/{n}/vs/0` 계열)로 다루는데, 패턴을 맞추려면 덤프가 필요합니다. 전체 단위 리소스만 바인딩했습니다 — 추측해서 타일에 **잘못된 온도**를 띄우는 것보다 빈 칸이 낫습니다
- **레퍼런스의 복합 엔티티**(에어컨 `climate`, 공기청정기 `fan`)는 Homey에 대응이 없어 개별 capability로 분해했습니다
- `poll_tier`, `rt_filter`, 패턴 capability는 여전히 없습니다

### 검증하는 방법

해당 가전이 있는 사용자가 **기기 추가 → 검색**을 하면 종류가 판정되고, 미커버 리소스가 로그에 남습니다:

```
registry refrigerator, N unbound resources: [...]
```

그 목록과 `/device/0` 덤프가 커버리지를 채우는 데 필요한 전부입니다.
