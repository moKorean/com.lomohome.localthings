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

### 남은 검증 항목

**메모리만 남았습니다.** 기기당 DTLS 세션 1개 + 상태 캐시. 파이썬 런타임 오버헤드 포함해 실측 필요.

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
5. **가전 1종 엔드투엔드** — 페어링(CA 입력 → IP → 기기 생성)과 타일 동작을 실제로 확인하는 단계. Homey 앱 UI 조작이 필요
6. OBSERVE 구독 및 폴링 강등/복구 — 현재는 폴링만
7. 나머지 가전 종류 레지스트리 확장 (기계적 작업)

### 마일스톤 5에서 확인할 것

- 페어링 화면이 CA 저장 → IP 프로브 → 기기 생성까지 도는지
- 타일에 capability가 뜨고 폴링으로 값이 갱신되는지
- 타일에서 전원·온도·모드·풍량을 바꿀 때 `_write`의 optimistic apply가 자연스럽게 보이는지
- 파이썬 SDK 메서드 이름 확인 필요: `get_store()`, `get_settings()`, `get_capabilities()`, `get_capability_value()`, `set_available()`/`set_unavailable()`, `homey.settings.get/set`, `homey.i18n.get_language()`. JS SDK를 snake_case로 옮긴 형태로 작성했고 `set_capability_value`·`register_capability_listener`·`on_pair`·`session.set_handler`는 공식 문서로 확인했지만, 나머지는 문서에 파이썬 예시가 없어 실행으로 검증해야 합니다
