# 백로그 — 아직 매핑하지 못한 리소스

실기기가 보고하는데 capability로 연결하지 못한 리소스들입니다. 대부분 **필드명은 보이지만
의미나 쓰기 계약을 모르는** 경우입니다.

이 목록의 항목은 추측으로 채우지 않습니다. 주방 후드가 그렇게 이식됐다가 필드명이 전부
틀려서 페어링은 되고 아무것도 제어되지 않았고, 테스트는 전부 통과했습니다. 냉장고의 `253`도
단일 덤프만 봤을 때는 켈빈 인코딩으로 보였지만, 같은 모델을 다른 모드로 쓰는 두 번째 유닛이
반증했습니다.

**확정 방법은 대조 실험입니다.** 기기에서 설정을 하나 바꾸고 다시 덤프해 무엇이 변했는지
보면 됩니다.

```sh
homey api raw --path "/api/app/com.lomohome.localthings/resources?host=<IP>&raw=1"
```

`raw=1` 없이 호출하면 시리얼·MAC·Wi-Fi 이름이 가려집니다. 공유할 때는 `raw=1`을 빼세요.

쓰기가 실제로 커밋되는지는 되읽기까지 해주는 진단 엔드포인트로 확인합니다. 냉장고 설정값이
두 번 잘못 구현된 뒤에야 이걸 만들었는데, 그 즉시 답이 나왔습니다 — 추측하지 말고 이걸 쓰세요.

```sh
homey api raw -X POST \
  --path /api/app/com.lomohome.localthings/write-resource \
  --body '{"host":"192.168.1.203","path":"/temperature/desired/cooler/0",
           "body":{"temperature":4}}'
```

응답에 가전이 돌려준 값(`response`), 수락 여부(`accepted`), 그리고 **쓰기 직후 다시 읽은
리소스**(`after`)가 담깁니다. `accepted`가 true인데 `after`가 안 바뀌면 "받아들이지만
반영하지 않는" 경로입니다 — 냉장고 벤더 경로가 정확히 그랬습니다.

---

## 냉장고 (`TP2X_REF_21K`, 키친핏)

### 김치 냉각 강도 — `/mode/vs/0`

```
x.com.samsung.da.supportedOptions = ["CV_TMF_KIMCHI_WEAKCOOL",
                                     "CV_TMF_KIMCHI_NORMAL",
                                     "CV_TMF_KIMCHI_STRONGCOOL"]
```

변온고 두 대 모두 이 세 값을 광고하지만, **현재 어느 것이 선택돼 있는지 알려주는 필드가
없습니다.** `modes`에는 `MULTIROOM_COOLER`/`MULTIROOM_FREEZER`만 있고 `CV_TMF_*`는 없습니다.

레퍼런스는 이 상태를 `/status/kimchi/<slot>/vs/0`의 `currentMode`/`supportMode`에서 읽는데,
**이 기기에는 그 리소스가 없습니다.**

- **실험**: 변온실을 **김치 모드로 전환**한 뒤 덤프. `modes`의 세 번째 토큰이
  `MULTIROOM_KIMCHI` 같은 값으로 바뀌는지, 그리고 `CV_TMF_*` 중 하나가 어딘가에 나타나는지
  확인. 그다음 강도를 약냉→강냉으로 바꿔 어느 필드가 따라 움직이는지 봅니다.
- 알아내면: 변온실 모드에 김치 값을 추가하고, 강도를 별도 enum(읽기 전용부터)으로 노출.

### 자동문 타이머 — `/autodoor/timer/vs/0`

```
x.com.samsung.da.time.desired          = "2"
x.com.samsung.da.time.supportedOptions = ["2", "3", "4"]
```

세 대 모두 있습니다. **단위를 모릅니다** — 2/3/4초일 수도, 분일 수도, 단계 이름일 수도
있습니다. 레퍼런스에 이 리소스는 아예 없습니다.

- **실험**: SmartThings 앱에서 이 설정의 UI 라벨을 확인(초/분 표기), 또는 값을 4로 바꾸고
  덤프해 필드가 따라오는지 확인.
- 알아내면: 단위가 확인될 때만 노출. 단위 없는 숫자는 사용자에게 의미가 없습니다.

### `ado.soundcontrol` — `/status/lock/vs/0`

```
x.com.samsung.da.ado.soundcontrol = "On"
```

레퍼런스는 같은 href에서 `ado.devicecontrol`(자동문 개폐)과 `device.sound`(기기 알림음)를
읽습니다. **이건 그 둘과 다른 세 번째 필드명**이라 어느 쪽인지, 아니면 "자동문 작동음"이라는
제3의 설정인지 불명확합니다. 이름만으로 스위치를 만들면 사용자가 끄려던 것과 다른 것이 꺼질
수 있습니다.

- **실험**: SmartThings 앱에서 알림음 관련 설정을 끄고 덤프해 이 필드가 `Off`가 되는지 확인.
- 알아내면: 쓰기 가능 스위치(레퍼런스의 `_status_lock_write` 계약과 동일한 형태).

### `/energy/ailevel/vs/0`

일반 냉장고(변온 없는 변형)에만 있습니다. 내용 확인 필요.

### `/drlc/0`, `/drlc/vs/0`

수요반응(Demand Response) 제어. 냉장고·후드·에어컨에 모두 있습니다.
`drlcLevel`, `durationminutes`, `start`, `override`, `realSaving`. 한국 전력 환경에서 실제로
쓰이는지 불명. 진단용 읽기 전용으로는 넣을 수 있습니다.

---

## 에어컨 (`TP1X_DA-AC-CAC-01001`)

### 모션 센서 — 라이브 재실 값은 없습니다 (조사 완료)

`MDS`는 삼성이 쓰는 Motion Detection Sensor의 약자이고, 관련 리소스가 네 개 있습니다.
이 중 셋은 **설정**으로 확정해 바인딩했습니다(부재 감지 on/off, 부재 판정 분,
모션 모니터링 on/off — 모두 읽기 전용).

**재실 여부를 알려주는 값은 이 펌웨어에 없습니다.** 결론이지 추측이 아니며, 근거는 두
가지입니다.

첫째, `/mds/absencestate/vs/0`의 `status`/`absenceTime`은 재실과 상관이 없습니다. 실제
상황을 알려받아 대조한 결과:

| 방 | 실제 | `status` | `absenceTime` |
|---|---|---|---|
| 안방 | 사람 있음 | Off | 0 |
| 예린방 | 사람 있음(취침) | On | 30 |
| 손님방 | **비어 있음** | Off | 0 |

빈 방과 사람 있는 방이 같은 값입니다. `supportedTimes`가 `["0","30","60","120"]`으로
`absenceTime`의 선택지 모양이고 두 값이 짝지어 움직이므로, "N분간 움직임이 없으면 부재로
판정" 임계값 설정으로 봅니다.

둘째, 레퍼런스가 언급하는 `motionState`(+`supportedMotionState`) 필드를 네 대 전부에서
검색했지만 **어디에도 없습니다.**

### `maxDetectCount` — 로그가 아니라 학습된 패턴으로 보입니다

`/mds/absencestate/vs/0`의 48칸 배열(값 0~3). 30분 × 48 = 24시간이고, 방별 생활 패턴과 잘
맞습니다(예린방은 07:00~21:30이 3, 심야는 0).

**35분 간격으로 두 번 떠서 비교했더니 네 대 모두 한 칸도 바뀌지 않았습니다.** 그 사이 안방에는
사람이 있었습니다. 즉 라이브 카운터가 아닙니다. 이름이 `maxDetectCount`("최대" 감지 수)인
점과 합치면, 가전이 부재를 예측하는 데 쓰는 **누적·학습된 시간대별 프로필**로 보입니다.

- **한계**: 관측 창 동안 에어컨 네 대가 모두 꺼져 있었습니다. "운전 중에만 갱신된다"는
  가능성은 배제하지 못했습니다. 확인하려면 에어컨을 켜 둔 채 같은 비교를 반복해야 합니다.
- 갱신 주기가 확인되지 않는 한 타일에 올릴 값이 아닙니다. 라이브가 아닌 값을 모션 센서처럼
  보여주면 빈 방을 "감지됨"으로 표시하게 됩니다.

### AI 절전 — `/aisleep/vs/0`

```
displayNightMode, elapsedTime, requestFeedback, resultFeedback,
statusFeedback, sleepTime = "14002200"
```

`sleepTime`이 `HHMM`+`HHMM`(14:00–22:00) 형태로 보이지만 확인 안 됨. `test_registry.py`가
이 href를 미매핑 목록에 남겨 두어 잊히지 않게 하고 있습니다.

---

## 후드 (`AHD-WW-TP1-22`)

### `/airlevelcheck/vs/0`

```
periodicSensingActivationState, periodicSensingInterval = "3600",
sensingState, lastSensingTime, lastSensingLevel = "Kr1",
autoExeState = "Sensing", supportedAutoExeState = ["Airpurify", "Alarm"]
```

주기적 공기질 감지. `lastSensingLevel`의 `Kr1`은 한국 기준 등급으로 보이나 척도 불명.
`autoExeState`는 쓰기 가능해 보이지만(`supportedAutoExeState`가 있음) 미확인.

### `/autoventilation/vs/0`

```
action = "Start"
```

레퍼런스도 이 필드를 그냥 센서로만 노출합니다. 명령용인지 상태용인지 불명.

---

## 위젯 — 한 번 만들었다가 뺐다

후드의 전원·풍량·조명·밝기를 한 카드에 놓는 위젯을 만들어 설치까지 했고, **보기에 좋지
않아서 제거했습니다.** 다시 시도할 때 계약을 처음부터 조사하지 않도록 알아낸 것을 남깁니다.

`widgets/<id>/` 아래에 네 가지가 필요합니다:

- `widget.compose.json` — `name`, `height`(숫자는 절대값, `%`는 종횡비), `api`,
  그리고 `devices`
- `public/index.html` — 진입점. `public/` 아래 파일은 Homey에서 호스팅됩니다
- `api.py` — `async def f(*, homey, query, params, body)` 시그니처, `__all__`로 내보냅니다
- `preview-light.png` / `preview-dark.png` — 필수

**기기 선택은 `devices` 설정이 합니다.** `{"type": "app", "singular": true, "filter":
{"capabilities": "..."}}` 형태이고, 뷰에서 `Homey.getDeviceIds()`로 받습니다. 클래스 필터는
쓰지 않는 게 맞습니다 — 후드의 `class`는 `fan`인데 공기청정기도 `fan`입니다.

**`Homey.ready()`가 로딩 상태를 없앱니다.** 첫 요청 전에 불러야 하고, 그러지 않으면 앱이
응답하는 동안 카드가 스피너로 남습니다.

**스타일은 Homey가 제공하는 것을 씁니다** — `--homey-su-*`(4px 배수 간격),
`.homey-button-primary-*`/`.homey-button-small`, `--homey-color-*`, `.homey-text-*`.
자체 색을 박으면 다크 모드에서 다른 카드와 어긋납니다.

**미리보기는 스크린샷이 아닙니다.** 심사 가이드라인 1.10: 텍스트 없음, 단순 도형, 투명 배경,
위젯 선택 화면 배경색과 같은 색 금지, 색 수 최소.

**요구 버전은 `>=12.3.0`** 이고 이 앱은 `>=13.0.0`이라 충족합니다. **Homey Cloud에서는 위젯이
동작하지 않습니다** — 이 앱은 `local` 전용이라 무관합니다.

다시 만들 때 유의할 점: 위젯 디자인은 대시보드의 다른 카드들과 나란히 놓였을 때 판단해야
하므로, 만들고 설치해서 실제로 보는 것 외에 검증 방법이 없습니다.

---

## 구조 — 드라이버는 하나로 유지한다 (결정됨)

한때 검증된 종류마다 드라이버를 따로 두는 안을 검토했습니다. **하지 않기로 했습니다.**
같은 조사를 반복하지 않도록 근거를 남깁니다.

### 확인된 제약 두 가지

**다른 드라이버의 기기를 만들 수 없습니다.** `PairSession`에도 `Driver`에도 `create_device`가
없고, 페어링 뷰의 `Homey.createDevice()`는 그 뷰가 속한 드라이버에만 기기를 만듭니다. 따라서
드라이버를 쪼개면 사용자가 "기기 추가" 목록에서 종류를 먼저 골라야 합니다. 이것만 보면 큰
문제는 아닙니다 — 사람은 자기 냉장고가 냉장고인 걸 알고, 종류가 안 맞으면 프로브 후 거부하면
됩니다.

**기존 기기는 옮길 수 없습니다.** `Device.driver`가 `Final`입니다. 쪼개도 이미 페어링된 기기는
전부 범용 드라이버에 남고, 전용 드라이버의 이점을 받으려면 재페어링해야 하며 그러면 플로우와
인사이트 이력을 잃습니다. **비용을 내는 사람과 이득을 받는 사람이 어긋납니다.**

### 얻는 것이 적습니다

쪼개려던 이유 네 가지 중 셋은 다른 방법으로 이미 해결됩니다.

| 이유 | 해결 상태 |
|---|---|
| 기기별 커스텀 뷰 | **위젯**이 해결합니다. 위젯은 캐패빌리티 필터로 기기를 고르므로 드라이버와 무관합니다 |
| `device_class` | `set_class`로 시작할 때마다 맞춥니다 (에어컨 thermostat, 후드 fan) |
| 기기 화면의 캐패빌리티 제목 | `Spec.titles`로 기기별 재정의됩니다 (후드 "조명" / 에어컨 "표시등") |
| 드라이버 아이콘이 하나 | 쪼개야 해결. 순수 미관 |
| 플로우 카드 문구 | 쪼개야 해결. 공용 캐패빌리티 **한 개**(`localthings_display_light`)에만 영향 |

남는 실익은 아이콘과 카드 문구 하나이고, 대가는 아이콘 4개 + 스토어 이미지 12장입니다.
가이드라인 1.6이 드라이버마다 **고유** 아이콘을 요구하므로 재사용도 불가합니다.

### 그래도 해 둔 것

구현을 `lib/appliance/{driver,device}.py`로 옮기고 `drivers/appliance/*.py`는 15줄 shim으로
만들었습니다. **상속이 Homey 파이썬 런타임에서 동작하는 것도 확인했습니다**(기기 9대 정상).

그래서 나중에 쪼갤 이유가 생기면 드라이버 하나가 15줄 + 에셋 + `$extends` 템플릿입니다. 결정을
미룰 수 있게 만들어 둔 것이 이 리팩터링의 성과입니다.

**다시 검토할 조건**: 검증된 종류가 훨씬 늘어 범용 아이콘 하나가 실제로 혼란을 주기 시작할 때,
또는 Homey가 기기 이전이나 드라이버 간 생성을 지원하게 될 때.

---

## 레퍼런스에서 아직 이식하지 않은 것

### 다중 실내기 / subdevice (`#177`, `#205`, `#214`, 611줄)

2-in-1 / 시스템 에어컨이 하나의 IP·하나의 DTLS 세션 뒤에 논리적 실내기를 여러 개 두는 경우.
두 가지 방식(인덱스형 `/device/<n>`, UUID 접두사형 `/subdevices/vs/0`)이 있습니다.

**보유 기기 9대 전부에 해당 신호가 없습니다** — `/subdevices/vs/0`, `/device/1`, `/mode/vs/1`
모두 부재. discovery·coordinator·adapter·platform 4개 경계를 건드리는 변경이라 검증 없이
이식하지 않습니다. 해당 기기 사용자의 덤프가 필요합니다.

**v0.17.2 재확인 (2026-07-31).** 레퍼런스가 이 영역을 `subunits.py` → `subdevices.py`로
개편하며 492줄에서 611줄로 늘었습니다. 이번에 추가된 것:

- **flat-href 폴백** — 접두사형 subdevice에 `/device/0` Collection이 없으면 href를 개별로
  폴링 (`#205`가 그 하드웨어에서 간헐 무응답을 보고한 건과 맞물립니다)
- **liveness 게이트** — 살아 있는 상태가 전력 계량기뿐인 슬롯은 실체화하지 않음.
  `#214`의 "유령 두 번째 에어컨"이 바로 이 게이트가 없어서 생긴 기기입니다
- **`async_remove_config_entry_device`** (`#214`) — HA 고유. HA는 로드된 config entry에
  속한 기기를 UI에서 지울 방법이 없어서 이 핸들러를 정의해야 삭제 버튼이 생깁니다.
  **Homey에는 해당 사항이 없습니다** — 기기 삭제가 항상 가능하고, 애초에 유령 기기를 만들
  subdevice 코드가 없습니다

설치된 앱의 `/resources`로 9대를 다시 훑어 `subdevice`·`numofsubdevice`를 포함하는 href나
필드가 하나도 없음을 재확인했습니다(추정이 아니라 실측). Homey에서는 subdevice 1개당 Device
1개가 되어야 자연스러운데 SDK가 드라이버 간 `create_device`를 제공하지 않으므로, 이식은
기기 모델 자체를 다시 설계하는 일입니다. 검증할 하드웨어가 없는 상태에서 할 작업이 아닙니다.

### 정수기 진단 리소스 (`#196`)

레퍼런스가 AILITE 보드(RWP70F15ANW)에서 새로 매핑한 것 중 셋을 보류했습니다.

| 리소스 | 보류 이유 |
|---|---|
| `/cup/state/vs/0` | 관측된 값이 `UnReady` 하나뿐. 레퍼런스도 상태 도메인 미확인이라 enum이 아닌 평문 센서로 둠 |
| `/settings/sound/output/vs/0` | `deviceType`, `alarmInMute`. 쓰기 계약을 광고하는 형제 필드가 없어 읽기 전용 |
| `/statistic/pour/vs/0` | `last.capacity`의 단위 미확인 (레퍼런스도 단위 없이 노출) |

같은 릴리스의 `/settings/sound/{mode,volume}`는 **이식했습니다** — 이미 정의된 capability를
재사용하므로 새 정의·아이콘·플로우 카드가 필요 없습니다. 위 셋은 커스텀 capability를 새로
만들어야 하는데, 정수기는 실기기 검증이 없는 종류이고 세 값 모두 레퍼런스 스스로 의미를
확정하지 못한 진단값입니다. 정수기 실기기 덤프가 생기면 함께 확정합니다.

`supportedHotTemperatures`가 없는 보드에서 온수 온도 선택을 끄는 `#196`의 게이트는
**해당 사항이 없습니다** — 우리 정수기 레지스트리에 온수 온도 capability 자체가 없습니다.

### 냉장고 이산 냉장 설정값 (`#186`)

`/temperature/definite/cooler/vs/0` — `supportedList`가 연속 범위가 아닌 단문형 냉장고용.
보유 냉장고 3대에 이 리소스가 없습니다.

### 오븐 스위치 2종 (`#183`)

`EnergySaving`, `BurnerOnAlert` 옵션 토큰. 오븐 실기기가 없습니다.
