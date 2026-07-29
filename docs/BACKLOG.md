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

## 레퍼런스에서 아직 이식하지 않은 것

### 다중 실내기 (`#177`, 492줄)

2-in-1 / 시스템 에어컨이 하나의 IP·하나의 DTLS 세션 뒤에 논리적 실내기를 여러 개 두는 경우.
두 가지 방식(인덱스형 `/device/<n>`, UUID 접두사형 `/subdevices/vs/0`)이 있습니다.

**보유 기기 9대 전부에 해당 신호가 없습니다** — `/subdevices/vs/0`, `/device/1`, `/mode/vs/1`
모두 부재. discovery·coordinator·adapter·platform 4개 경계를 건드리는 변경이라 검증 없이
이식하지 않습니다. 해당 기기 사용자의 덤프가 필요합니다.

### 냉장고 이산 냉장 설정값 (`#186`)

`/temperature/definite/cooler/vs/0` — `supportedList`가 연속 범위가 아닌 단문형 냉장고용.
보유 냉장고 3대에 이 리소스가 없습니다.

### 오븐 스위치 2종 (`#183`)

`EnergySaving`, `BurnerOnAlert` 옵션 토큰. 오븐 실기기가 없습니다.
