# LocalThings (로컬띵스)

**SmartThings 클라우드 없이, 최신 삼성 가전을 집 안 네트워크에서 직접 제어하는 Homey 앱입니다.**

Home Assistant 통합 [mbillow/localthings](https://github.com/mbillow/localthings)를 Homey SDK v3로 포팅하는 프로젝트입니다. 가전과 DTLS-over-CoAP 세션을 직접 맺어 상태를 읽고 명령을 보내므로, 클라우드 왕복이 없습니다.

> **상태: 초기 골격 (v0.1.0).** 앱 구조와 저장소만 준비된 단계이며 프로토콜 계층은 아직 구현되지 않았습니다. 설계와 남은 작업은 [`docs/PORTING.md`](docs/PORTING.md)를 참고하세요.

## 동작 방식

| 계층 | 내용 |
|---|---|
| 전송 | UDP `49152-49160` 중 하나에서 DTLS 1.2, 클라이언트 인증서 인증 |
| 인증 | 삼성 펌웨어 신뢰 저장소에 있는 `AC14K_M` 중간 CA가 서명한 리프 인증서 |
| 프로토콜 | CoAP (blockwise 전송, OBSERVE 구독) |
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

- Homey Pro (SDK v3, `>=12.4.0`) — LAN UDP가 필요하므로 `local` 플랫폼 전용입니다. Homey Cloud에서는 동작할 수 없습니다.
- `AC14K_M` CA 인증서와 개인키 (저장소에 포함되어 있지 않습니다). 앱이 이 CA로 기기별 리프 인증서를 직접 발급하므로, 최초 1회만 입력하면 이후 추가하는 기기는 IP만 입력합니다.

## 개발

```sh
npm install
npm run lint
homey app validate
homey app run
```

레퍼런스 구현은 같은 상위 폴더의 `../localthings-reference/`에 클론되어 있습니다.

```sh
cd ../localthings-reference && git pull   # 레퍼런스 최신화
```

## 라이선스

GPL-3.0-or-later. 원본 통합의 프로토콜 분석과 기기 레지스트리 설계는 [mbillow/localthings](https://github.com/mbillow/localthings)와 [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)의 작업에 기반합니다.
