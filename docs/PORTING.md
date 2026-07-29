# LocalThings → Homey 포팅 노트

레퍼런스: `../localthings-reference/` (mbillow/localthings, 포팅 시작 시점 `main` @ `119a4f4`, v0.16.0)

이 문서는 레퍼런스 구조를 실제로 읽고 정리한 설계 메모입니다. 구현이 진행되면 함께 갱신합니다.

---

## 1. 레퍼런스가 실제로 하는 일

HA 통합은 `smartthings-local` 파이썬 라이브러리에 저수준 통신을 위임하고, 자신은 **기기 모델링**만 담당합니다. 이 분업이 포팅 난이도를 그대로 결정합니다.

```
HA 통합 (포팅 대상, 파이썬 → JS 재작성)
  config_flow.py      기기 추가 플로우: IP + CA PEM 입력, UUID 조회, 리프 인증서 발급, 포트 스윕
  coordinator.py      DTLS 세션 수명주기, /device/0 폴링, 상태 캐시, 쓰기 경로
  observe.py          CoAP OBSERVE 구독 (실패 시 폴링으로 강등, 600초마다 복구 재시도)
  registry/           href → capability → 엔티티 매핑 (여기가 코드량의 대부분)
  {sensor,switch,...}.py   HA 플랫폼별 엔티티 생성

smartthings-local (파이썬 라이브러리, Homey에서 대체 필요 ← 진짜 문제)
  protocol/dtls_session.py   DtlsCoapSession: DTLS 핸드셰이크 + CoAP 요청/응답
  ocf/state_cache.py         OCF 상태 캐시
```

핵심 흐름:

1. `_fetch_samsung_uuid()` — 삼성 클라우드 게이트웨이에서 기기 UUID 조회
2. `_mint_leaf_cert(ca_cert, ca_key, uuid)` — pyOpenSSL로 UUID를 CN에 담은 리프 인증서 발급, CA로 서명
3. `_find_live_ports()` — `49152-49160` UDP 라이브니스 스윕 (포트당 1.5초). 닫힌 포트는 ICMP로 즉시 탈락하므로 값싼 선별
4. `DtlsCoapSession(host, port, cert_pem, key_pem)` → `.connect()` → `.get(['device','0'])`
5. `parse_device0_batch()` — CBOR 배치 응답을 `{href: representation}`으로 평탄화
6. `registry/by_type/resolve(resources)` — 리소스 집합을 보고 가전 종류 판정, 해당 레지스트리 선택
7. `registry/discovery.discover()` — 레지스트리에 등록된 href마다 `BoundEntity` 생성. 미등록 href는 커버리지 갭으로 로깅

주목할 설계 결정 (Homey에서도 그대로 유효):

- **모델별 기술자가 없습니다.** 기기가 광고하는 리소스 집합으로 종류를 판정하므로, 이미 지원되는 종류의 새 모델은 코드 추가 없이 붙습니다.
- **CA는 1회 입력, 리프는 기기별 자동 발급.** 두 번째 기기부터는 IP만 받습니다.
- **DTLS 소스 포트를 기기별로 고정** (`coordinator._local_source_port`, base `49700` + IP 마지막 옥텟). 재접속 시 5-tuple을 유지해 비정상 종료로 남은 유령 세션을 핸드셰이크 시점에 축출합니다(RFC 6347 §4.2.8). 안 하면 5~15분간 읽기가 멈춥니다. **포팅 시 반드시 이식할 항목입니다.**
- **`serialNum` 플레이스홀더 방어.** `ARTIK051_DONGLE_REF` 계열은 모든 유닛이 `Nothing(SVC)`를 반환하므로, 이를 실제 시리얼로 쓰면 같은 집의 두 기기가 unique id를 공유해 충돌합니다. `_is_placeholder_serial()` 대응 필요.

---

## 2. 가장 큰 위험: Node.js에는 DTLS가 없습니다

`node:tls`는 TCP 전용입니다. Homey 앱은 Node.js이고 Homey Pro에서는 네이티브 모듈 컴파일이 불가능하므로 **순수 JS DTLS 1.2 클라이언트**가 필요합니다.

조사 결과:

| 후보 | 판정 |
|---|---|
| `@nodertc/dtls` 0.6.0 | **유일한 현실적 후보.** 순수 JS, 네이티브 의존성 없음, MIT. `options.certificate` / `options.certificatePrivateKey`로 **클라이언트 인증서 인증 지원**(RSASSA-PKCS1-v1_5, ECDSA). 단 `stability-experimental`, 최종 배포 2019년, `engines: node>=8.3` |
| `node-dtls-client` 2.0.3 | PSK 전용. 클라이언트 인증서 불가 → **사용 불가** |
| `dtls` 0.0.1 | 사실상 빈 패키지 |
| 네이티브 mbedTLS/OpenSSL 바인딩 | Homey Pro에서 컴파일 불가 → **사용 불가** |

### 먼저 해야 할 스파이크 (여기서 프로젝트 성패가 갈립니다)

**암호 스위트 교집합 확인.** `@nodertc/dtls`가 지원하는 스위트는 ECDHE-ECDSA/ECDHE-RSA/RSA의 **GCM과 ChaCha20-Poly1305**뿐입니다. 반면 CoAP를 쓰는 제약 기기들은 관례적으로 **CCM / CCM_8**(RFC 7251, 예: `TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8`)을 제공합니다. 삼성 가전이 CCM만 제공한다면 `@nodertc/dtls`로는 핸드셰이크가 성립하지 않고, CCM 모드를 직접 구현해 포크하는 작업이 추가됩니다.

확인 방법 — 실기기에 `openssl s_client`로 DTLS 핸드셰이크를 걸어 ServerHello가 고르는 스위트를 봅니다:

```sh
openssl s_client -dtls1_2 -connect "$APPLIANCE_IP:49154" \
  -cert leaf.pem -key leaf.key -state -debug 2>&1 | grep -i cipher
```

또는 `smartthings-local`의 `dtls_session.py`가 어떤 스위트를 설정하는지 확인합니다(현재 저장소에 벤더링되어 있지 않아 PyPI에서 별도로 받아야 합니다).

**이 결과가 나오기 전에는 레지스트리 포팅에 시간을 쓰지 않는 것이 좋습니다.** 레지스트리는 코드량이 크지만 기계적인 작업이고, 전송 계층이 막히면 전부 무의미해집니다.

### 나머지 자체 구현 항목

- **CoAP.** `coap` npm 패키지는 자기가 소유한 UDP 소켓을 전제하므로, DTLS 스트림 위에 얹을 수 없습니다. 메시지 인코딩/디코딩, **Block2 blockwise 재조립**(`/device/0` 응답이 커서 필수), **OBSERVE** 구독을 DTLS 소켓 위에 직접 구현해야 합니다.
- **인증서 발급.** Node `crypto`는 키 생성은 되지만 X.509 서명은 불가합니다. `node-forge`(순수 JS)로 대체합니다.
- **CBOR.** `cbor-x` 또는 `cbor`. 순수 JS 경로가 있는지 확인 필요(`cbor-x`는 선택적 네이티브 가속을 씁니다 — 반드시 JS 폴백으로 동작시켜야 합니다).

---

## 3. HA → Homey 매핑

| HA | Homey |
|---|---|
| `config_flow.py` | 드라이버 `pair/` 커스텀 HTML 뷰 (IP + CA PEM 2개 필드). `../com.lomohome.video_door_bell_lock/drivers/smartdoor/pair/configure.html` 패턴 참고 |
| options flow (`CONF_BYPASS_REMOTE_CONTROL`) | `driver.compose.json`의 `settings` |
| `DataUpdateCoordinator` | `device.js`의 폴링 루프 + `ObserveManager` 대응 로직 |
| 기기 1대 = HA device + N entities | 기기 1대 = Homey device 1개 + N capabilities |
| 플랫폼 `sensor`/`binary_sensor`/`switch`/`number`/`select`/`button`/`time`/`climate`/`fan` | Homey capability 타입 `sensor`/`boolean`/`number`/`enum`. 표준 capability로 안 되는 것은 `.homeycompose/capabilities/*.json`에 커스텀 정의 |
| `registry/by_type/*.py` | `lib/registry/by-type/*.js` — 구조를 1:1로 옮깁니다 |
| `entity.py`의 `unique_id` | capability id + 기기 시리얼 |

**드라이버 구성 방향:** 가전 종류마다 드라이버를 따로 만들지 말고, **단일 제네릭 드라이버 + 런타임 capability 동기화**를 권합니다. 레퍼런스가 종류를 런타임에 판정하는 구조이므로 페어링 시점에는 어떤 드라이버인지 알 수 없고, 이 저장소의 `video_door_bell_lock`이 이미 `applyConfig()`로 런타임 capability 추가/제거 패턴을 검증해 두었습니다. 다만 Homey 앱스토어 노출 측면에서는 종류별 드라이버가 유리하므로, 프로토콜이 붙은 뒤 재검토합니다.

---

## 4. 그 외 고려사항

- **CA 자격증명 보관.** `homey.settings`에 앱 단위로 저장(기기 간 재사용). 리프 인증서/키는 기기 store에. `.gitignore`에 `*.pem`/`*.key`를 이미 넣어두었습니다.
- **앱스토어 심사.** 사용자에게 CA **개인키**를 붙여넣게 하는 앱은 공식 스토어 승인이 어려울 수 있습니다. 커뮤니티 스토어 또는 자체 설치 배포를 전제하는 편이 안전합니다.
- **메모리.** Homey 앱은 메모리 제약이 있습니다. 기기당 DTLS 세션 1개 + 상태 캐시이므로, 가전 여러 대를 붙였을 때의 사용량을 실측해야 합니다.
- **CA 번들은 저장소에 포함하지 않습니다.** 레퍼런스도 마찬가지이며, 획득 방법만 `SmartThings-Local`의 `setup_cert.py`로 안내합니다.

---

## 5. 제안 마일스톤

1. **스파이크 — 암호 스위트 교집합 확인.** 실기기 대상. 실패 시 CCM 구현 범위 산정. (여기서 계속/중단 결정)
2. `lib/cert.js` — `node-forge`로 UUID 기반 리프 인증서 발급, CA 서명. 오프라인 검증 가능
3. `lib/dtls-coap.js` — DTLS 세션 + CoAP GET/POST, Block2 재조립, 기기별 고정 소스 포트. `/device/0` 덤프까지 성공하면 최대 난관 통과
4. `lib/registry/` — 배치 파싱 + 종류 판정. 레퍼런스의 골든 파일 덤프를 그대로 테스트 픽스처로 재사용
5. 드라이버 + 페어링 뷰 — 가전 1종(예: 세탁기)으로 엔드투엔드 완성
6. OBSERVE 구독 및 폴링 강등/복구
7. 나머지 가전 종류 레지스트리 확장 (기계적 작업)
