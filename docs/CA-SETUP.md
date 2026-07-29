# CA 자격증명 준비

앱이 가전과 DTLS 세션을 맺으려면 `AC14K_M` 중간 CA의 **인증서와 개인키**가 필요합니다. 이 저장소에는 포함되어 있지 않고, 앞으로도 포함하지 않습니다.

## 왜 필요한가

삼성 Tizen/RT-OCF 가전은 공장 ACL에서 특정 UUID에 `href=*`에 대한 `perm=31`(전체 권한)을 부여합니다. 그 UUID는 삼성 클라우드 게이트웨이의 TLS 서버 인증서 subject DN에 `uuid:<UUID>` 형태로 공개되어 있습니다. `AC14K_M` 중간 CA가 서명한 인증서에 이 UUID를 넣으면 가전이 정품 허브로 인식합니다.

즉 **기기의 원본 인증서나 키는 필요 없습니다.** `AC14K_M`이 서명한 무언가만 있으면 되고, 서명은 우리가 직접 합니다.

## 절차

[`QuiteYellow/SmartThings-Local`](https://github.com/QuiteYellow/SmartThings-Local)의 `setup_cert.py`가 전 과정을 자동화합니다. 이 저장소는 `../smartthings-local-reference/`에 클론되어 있습니다.

### 사전 준비

- `openssl` CLI (스크립트가 서브프로세스로 호출합니다)
- Python 3
- `pyOpenSSL` — `--test`(4단계 실기기 검증)에만 필요

```sh
cd ../smartthings-local-reference
python3 -m venv .venv
.venv/bin/pip install pyOpenSSL
```

### 실행

가전 IP를 알고 있다면 `--test`까지 한 번에 돌리는 것을 권합니다. 인증서 발급과 실기기 수락 여부를 동시에 확인합니다.

```sh
cd ../smartthings-local-reference
OUT_DIR=./certs \
TARGET_IP=192.168.1.<가전IP> \
TARGET_PORT=49154 \
.venv/bin/python setup_cert.py --test
```

`TARGET_PORT`는 `nmap -Pn -sU -p 49152-49160`으로 확인한 포트를 넣습니다(기본값 49154).

### 스크립트가 하는 일

| 단계 | 내용 |
|---|---|
| 1 | 공개 미러에서 `AC14K_M` 번들(개인키 1 + 인증서 4)을 받아 분리하고, cert와 key의 modulus가 짝인지 검증 |
| 2 | `connect-v2.samsungiotcloud.com:443`에 TLS 접속해 서버 인증서 subject DN에서 `uuid:<UUID>` 추출 |
| 3 | RSA-2048 키 생성 → CN/OU/SAN에 UUID를 담은 CSR → `AC14K_M`으로 **SHA-1** 서명 (기기 트러스트 체인이 SHA-1 기준) |
| 4 | `--test`일 때 가전에 DTLS 핸드셰이크 후 `GET /oic/sec/acl`. **`2.05`가 오면 인증서가 수락된 것** (`4.01`이면 거부) |

### 결과물

```
certs/
  .bundle/ac14k_m.pem        ← 앱에 넣을 CA 인증서
  .bundle/ac14k_m.key        ← 앱에 넣을 CA 개인키
  .bundle/cert_1..4.pem      상위 체인
  client.key                 스크립트가 발급한 클라이언트 키
  client_fullchain.pem       스크립트가 발급한 클라이언트 인증서 + 체인
  samsung_cloud_leaf.pem     참고용 삼성 서버 인증서
```

**우리 앱에 필요한 것은 `.bundle/ac14k_m.pem`과 `.bundle/ac14k_m.key` 두 개입니다.** 앱은 레퍼런스 통합처럼 이 CA로 기기별 리프 인증서를 직접 발급하므로, CA만 1회 입력하면 이후 기기는 IP만 입력합니다. `client.*`는 스크립트가 브리지 직접 사용을 위해 만든 것이라 앱에는 쓰지 않지만, 4단계 검증을 통과했다면 체인 전체가 정상이라는 증거입니다.

### 실패 시 우회

라이브 조회가 막히면 스크립트가 환경변수 우회를 지원합니다.

```sh
# UUID를 직접 지정
openssl s_client -connect connect-v2.samsungiotcloud.com:443 \
                 -servername connect-v2.samsungiotcloud.com \
                 -showcerts < /dev/null 2>/dev/null \
  | openssl x509 -noout -subject          # subject에서 OU=uuid:<UUID> 확인
UUID=<uuid> .venv/bin/python setup_cert.py

# 번들을 로컬 파일이나 다른 미러에서
AC14K_M_CERT_BUNDLE=/path/to/cert.pem .venv/bin/python setup_cert.py
BRAYSTORM_URL=https://<mirror>/cert.pem .venv/bin/python setup_cert.py
```

## 보안상 알아둘 것

- **이 CA 개인키는 공개된 값입니다.** 삼성이 전 기기 트러스트 스토어에 넣어 배포한 중간 CA이고 수년간 공개되어 있었습니다. 따라서 같은 LAN에 있는 누구든 같은 키로 가전을 제어할 수 있습니다. 이건 이 앱이 만드는 위험이 아니라 기기 펌웨어의 설계이며, 가전을 신뢰할 수 없는 네트워크에 두지 않는 것이 유일한 완화책입니다.
- 이 자격증명으로 제어되는 범위는 **본인 소유 가전, 본인 LAN 안**입니다. 외부로 노출되는 경로는 없습니다.
- `certs/`, `*.pem`, `*.key`는 이 저장소 `.gitignore`에 있습니다. 그래도 커밋 전 `git status`로 한 번 확인하세요.
- 앱에 넣은 CA는 `homey.settings`에 앱 단위로 저장됩니다. 채팅·이슈·로그에 개인키를 붙여넣지 마세요.
