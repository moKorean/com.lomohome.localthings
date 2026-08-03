# 클라이언트 인증서 준비

**[English](CA-SETUP.en.md)** · **한국어**

앱을 쓰기 전에 **한 번만** 하는 준비입니다. 컴퓨터에서 스크립트를 하나 돌려 파일 두 개를 만들고,
그 내용을 Homey 앱 설정에 붙여넣으면 끝입니다. 가전마다 반복하지 않습니다.

10분 정도 걸리고, 명령줄을 처음 쓰더라도 따라올 수 있게 적었습니다.

---

## 이걸 왜 하나

삼성 가전은 아무나 로컬에서 제어하게 두지 않습니다. **정품 허브임을 증명하는 인증서**를 제시해야
연결을 받아 줍니다. 그 인증서를 만드는 것이 이 작업입니다.

인증서에 들어가는 식별자는 **가전이 아니라 삼성 서버**에서 오는 값이라 모든 사용자·모든 기기가
같습니다. 그래서 **집 전체에 인증서 하나**면 됩니다.

앱은 **CA 개인키를 받지 않습니다.** 이미 만들어진 인증서만 저장하므로, 서명에 쓰인 키는 컴퓨터에
남고 Homey로 전송되지 않습니다.

---

## 1단계 — 준비물 확인

두 가지가 필요합니다: **Python 3**과 **OpenSSL**. 본인 운영체제를 찾아 그대로 따라오세요.

<details open>
<summary><b>macOS</b></summary>

터미널을 엽니다 (`Command + Space` → `터미널` 입력 → Enter). 아래를 붙여넣고 Enter:

```sh
python3 --version && openssl version
```

두 줄이 출력되면 준비 완료입니다. macOS에는 둘 다 기본으로 들어 있습니다.

`python3`에서 개발자 도구 설치 창이 뜨면 **설치**를 누르고, 끝난 뒤 다시 실행하세요.

</details>

<details>
<summary><b>Windows</b></summary>

Windows에는 OpenSSL이 기본으로 없습니다. **Git for Windows**를 설치하면 OpenSSL과 함께
macOS·Linux와 같은 명령을 쓸 수 있는 터미널(Git Bash)이 딸려 오므로 이 방법을 권합니다.

1. **Python** — [python.org/downloads](https://www.python.org/downloads/)에서 설치합니다.
   설치 첫 화면의 **Add python.exe to PATH**를 반드시 체크하세요.
2. **Git for Windows** — [git-scm.com/download/win](https://git-scm.com/download/win)에서
   설치합니다. 기본 옵션 그대로 진행하면 됩니다.

설치가 끝나면 시작 메뉴에서 **Git Bash**를 실행하고 아래를 붙여넣습니다 (붙여넣기는 마우스 오른쪽
클릭):

```sh
python --version && openssl version
```

`python`에서 오류가 나면 `python3`으로 바꿔 보세요. 둘 다 안 되면 Python 설치 때 PATH 항목을
놓친 것이니 다시 설치하면서 체크하세요.

> 이 문서의 나머지 명령은 **Git Bash**에서 실행한다고 가정합니다. PowerShell이나 명령 프롬프트는
> 경로 구분자와 환경변수 문법이 달라 그대로 붙여넣을 수 없습니다.

</details>

<details>
<summary><b>Linux</b></summary>

터미널에서:

```sh
python3 --version && openssl version
```

없다고 나오면 배포판에 맞게 설치합니다.

```sh
# Debian, Ubuntu, Raspberry Pi OS
sudo apt update && sudo apt install -y python3 python3-venv openssl git

# Fedora, RHEL
sudo dnf install -y python3 openssl git

# Arch
sudo pacman -S --needed python openssl git
```

</details>

---

## 2단계 — 인증서 만들기

발급 스크립트는 별도 프로젝트에 있습니다. 받아서 실행합니다.

> **이 저장소는 필요한 CA 번들을 포함하지 않습니다.** 획득 방법의 예시 — `AC14K_M` 인증서와 키를
> 받아 서로 짝이 맞는지 확인하는 과정까지 — 는 `smartthings-local` 프로토콜 프로젝트의
> [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py)를
> 참고하세요.
>
> 원문: *"This repo doesn't include the needed CA bundle. For an example of how to obtain
> it, including fetching the AC14K_M cert and key and verifying they pair, see the
> `smartthings-local` protocol project's
> [`setup_cert.py`](https://github.com/QuiteYellow/SmartThings-Local/blob/main/setup_cert.py)."*
> — [mbillow/localthings](https://github.com/mbillow/localthings)

먼저 스크립트를 받습니다. 한 줄씩 붙여넣고 Enter를 누르세요. (macOS·Linux·Windows 모두 같습니다)

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
```

이어서 실행합니다. `TARGET_IP`에 **가전 하나의 IP 주소**를 넣으면 만든 인증서를 그 가전으로 바로
시험해 봅니다. 주소를 모르면 `TARGET_IP=192.168.1.90 ` 부분을 지우고 실행하세요.

<details open>
<summary><b>macOS · Linux</b></summary>

```sh
python3 -m venv .venv
.venv/bin/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/bin/python setup_cert.py --test
```

</details>

<details>
<summary><b>Windows (Git Bash)</b></summary>

venv 안의 경로만 다릅니다 — `bin`이 아니라 `Scripts`입니다.

```sh
python -m venv .venv
.venv/Scripts/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/Scripts/python setup_cert.py --test
```

</details>

> `pyOpenSSL`은 **시험 접속(`--test`)에만** 필요합니다. 설치가 안 되더라도 인증서는 만들어지고,
> 스크립트가 시험만 건너뜁니다.

**가전 IP 주소를 모른다면**: 공유기 관리 화면의 접속 기기 목록, 또는 SmartThings 앱에서 가전을 열고
설정 → 정보 → 네트워크에서 볼 수 있습니다. 몰라도 됩니다 — 나중에 앱의 **검색**이 알아서 찾습니다.

### 잘 됐는지 확인

`--test`를 붙였다면 마지막에 이런 줄이 나와야 합니다.

```
GET /oic/sec/acl -> 2.05
```

**`2.05`가 나오면 가전이 인증서를 받아들인 것입니다.**

| 출력 | 뜻 | 할 일 |
|---|---|---|
| `2.05` | 성공 | 3단계로 |
| `4.01` | 인증서를 거부함 | 아래 [문제 해결](#문제-해결) |
| 시험을 건너뜀 | `pyOpenSSL`이 없거나 `TARGET_IP`를 안 넣음 | 인증서는 만들어졌습니다. 3단계로 진행해도 됩니다 |

`certs/` 폴더에 파일 네 개가 생깁니다. 그중 **두 개만** 씁니다.

| 파일 | 쓰나요 |
|---|---|
| `client_fullchain.pem` | **씁니다** — 인증서 체인 |
| `client.key` | **씁니다** — 개인키 |
| `client.pem` | 쓰지 않습니다 (체인이 없는 리프 단독) |
| `client.csr` | 쓰지 않습니다 (중간 산물) |

---

## 3단계 — 앱에 붙여넣기

Homey 앱에서 **설정 → 앱 → 스마트싱스 로컬**을 엽니다. 입력란이 두 개 있습니다.

파일을 첨부하는 것이 아니라 **파일 내용 전체를 텍스트로 복사**해 붙여넣습니다.

<details open>
<summary><b>macOS · Linux — 클립보드로 바로 복사</b></summary>

```sh
# macOS
cat certs/client_fullchain.pem | pbcopy      # 붙여넣기 → 인증서 체인
cat certs/client.key | pbcopy                # 붙여넣기 → 개인키

# Linux (xclip 필요: sudo apt install xclip)
xclip -sel clip < certs/client_fullchain.pem
xclip -sel clip < certs/client.key
```

</details>

<details>
<summary><b>Windows (Git Bash) — 클립보드로 바로 복사</b></summary>

```sh
cat certs/client_fullchain.pem | clip        # 붙여넣기 → 인증서 체인
cat certs/client.key | clip                  # 붙여넣기 → 개인키
```

</details>

<details>
<summary><b>어느 OS든 — 편집기로 열어서 복사</b></summary>

`certs/` 폴더를 파일 탐색기에서 열고 파일을 **메모장·TextEdit 같은 텍스트 편집기**로 엽니다.
`Ctrl + A` (macOS는 `Command + A`)로 전체 선택 후 복사합니다.

Word 같은 문서 프로그램으로 열면 안 됩니다 — 보이지 않는 서식이 섞입니다.

</details>

붙여넣을 내용은 이렇게 생겼습니다. `-----BEGIN` 줄과 `-----END` 줄을 **포함해서** 전부 넣습니다.

```
-----BEGIN CERTIFICATE-----
MIIDpTCCAo2gAwIBAgIUJ...
...
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIDkTCCAnmgAwIBAgIUY...
...
-----END CERTIFICATE-----
```

`client.pem`을 넣으면 **안 됩니다** — 인증서가 하나뿐이라 가전이 검증할 체인이 없습니다. 앱이 이
경우를 감지해 알려줍니다.

저장을 누르면 앱이 검사합니다: 인증서와 키가 짝인지, 식별자가 들어 있는지, 체인이 2개 이상인지,
만료되지 않았는지. 하나라도 어긋나면 저장하지 않고 이유를 알려주며 이전 값을 그대로 둡니다.

성공하면 상태가 **준비 완료**로 바뀌고 식별자·만료일·체인 길이가 표시됩니다.

---

## 4단계 — 가전 추가

**기기 → 기기 추가 → 스마트싱스 로컬 → 검색**

네트워크를 훑어 응답하는 가전을 찾고 종류까지 확인합니다. 1~2분 걸립니다.

검색이 모든 가전을 찾아내지는 못합니다. 못 찾으면 **IP 주소로 추가** 버튼으로 직접 넣으세요 —
앞자리는 미리 채워져 있어 마지막 숫자만 입력하면 됩니다.

---

## 문제 해결

**`openssl: command not found`**
1단계를 건너뛰었습니다. Windows라면 PowerShell이 아니라 **Git Bash**에서 실행하고 있는지
확인하세요.

**`python3: command not found`** (Windows)
`python3` 대신 `python`을 쓰세요. 그래도 안 되면 Python 설치 때 **Add python.exe to PATH**를
체크하지 않은 것이니 다시 설치하세요.

**`GET /oic/sec/acl -> 4.01`** — 가전이 인증서를 거부했습니다
가장 흔한 원인은 그 가전이 **구형 펌웨어**여서 이 방식을 지원하지 않는 것입니다. 다른 가전 IP로
시험해 보세요. 대략 2022년 이후 모델이 대상입니다.

**`openssl` 서명 단계에서 실패합니다 (Fedora·RHEL·최신 Ubuntu)**
이 인증서는 `AC14K_M` 체인 때문에 **SHA-1 서명**이어야 하는데, 최근 배포판의 시스템 crypto
policy가 SHA-1 서명을 아예 막습니다. 발급 스크립트가 이 경우를 감지해 SHA-1을 허용하는 임시
설정으로 재시도하도록 고쳐졌으니(`SmartThings-Local` 저장소 이슈 #19), **클론을 최신으로
받으면 해결됩니다.**

```sh
cd SmartThings-Local && git pull
```

**시험이 아무 응답 없이 멈춥니다**
IP 주소가 틀렸거나, 가전이 다른 네트워크(게스트 망 등)에 있습니다. 컴퓨터와 가전이 같은
네트워크에 있어야 합니다.

**앱이 "인증서 체인이 필요합니다"라고 합니다**
`client.pem`을 넣었습니다. `client_fullchain.pem`으로 다시 넣으세요.

**앱이 "인증서와 키가 짝이 아닙니다"라고 합니다**
두 입력란의 내용이 뒤바뀌었거나, 다른 실행에서 만든 파일이 섞였습니다. `certs/` 폴더를 지우고
2단계를 다시 하세요.

**나중에 다시 해야 하나요**
인증서에는 만료일이 있습니다(10년). 만료되거나 삼성이 식별자를 바꾸면 다시 발급해야 합니다.
설정 화면의 **삼성 게이트웨이와 대조** 버튼이 저장된 식별자가 아직 유효한지 확인해 줍니다 —
불일치는 네트워크 장애처럼 보이지만 실제로는 재발급이 필요한 유일한 경우라서 따로 만들었습니다.

---

## 보안상 알아둘 것

- **`AC14K_M` CA 개인키는 공개된 값입니다.** 삼성이 전 기기 트러스트 스토어에 넣어 배포한 중간
  CA이고 수년간 공개되어 있었습니다. 따라서 같은 LAN에 있는 누구든 같은 방법으로 가전을 제어할
  수 있습니다. 이건 이 앱이 만드는 위험이 아니라 기기 펌웨어의 설계이며, 가전을 신뢰할 수 없는
  네트워크에 두지 않는 것이 유일한 완화책입니다.
- **`client.key`는 비밀로 관리하세요.** 이 키를 가진 사람은 같은 네트워크에서 가전을 제어할 수
  있습니다. 붙여넣기가 끝나면 `certs/` 폴더를 지워도 됩니다 — 재발급은 언제든 가능합니다.
- 제어 범위는 **본인 소유 가전, 본인 LAN 안**입니다. 외부로 나가는 경로는 없습니다.
- `certs/`, `*.pem`, `*.key`는 이 저장소와 `SmartThings-Local` 저장소 모두 `.gitignore`에
  있습니다. 그래도 커밋 전 `git status`로 확인하세요.
- 앱은 저장된 PEM을 설정 화면으로 돌려주지 않습니다. 상태 표시에 필요한 메타데이터(식별자·만료일·
  체인 길이)만 노출합니다.

---

## 배경 — 왜 이 방법이 통하나

여기부터는 몰라도 사용에 지장이 없습니다.

삼성 Tizen/RT-OCF 가전은 공장 ACL에서 특정 UUID에 `href=*`에 대한 `perm=31`(전체 권한)을
부여합니다. 그 UUID는 삼성 클라우드 게이트웨이의 TLS 서버 인증서 subject DN에 `uuid:<UUID>`
형태로 공개되어 있습니다. `AC14K_M`이 서명한 인증서에 이 UUID를 넣으면 가전이 정품 허브로
인식합니다. **기기의 원본 인증서나 키는 필요 없습니다.**

UUID가 가전이 아니라 게이트웨이에서 오는 값이므로 모든 기기·모든 사용자가 동일하고 호출마다
바뀌지 않습니다(실측 확인). 그래서 이 앱은 CA를 받아 직접 발급하지 않고 **이미 발급된 인증서만**
받습니다.

> 레퍼런스 HA 통합은 CA를 받아 config entry마다 리프를 발급하지만, UUID가 동일하므로 결과물은
> 사실상 같습니다. 이 포트는 앱이 보관하는 민감 자료를 줄이는 쪽을 택했습니다.

스크립트가 하는 일:

| 단계 | 내용 |
|---|---|
| 1 | 공개 미러에서 `AC14K_M` 번들(개인키 1 + 인증서 4)을 받아 분리하고, cert와 key의 modulus가 짝인지 검증 |
| 2 | `connect-v2.samsungiotcloud.com:443`에서 서버 인증서 subject의 `uuid:<UUID>` 추출 |
| 3 | RSA-2048 키 생성 → CN/OU/SAN에 UUID를 담은 CSR → `AC14K_M`으로 **SHA-1** 서명 |
| 4 | `--test`일 때 가전에 DTLS 핸드셰이크 후 `GET /oic/sec/acl`. **`2.05`면 인증서 수락됨** (`4.01`이면 거부) |

환경변수로 조정할 수 있는 값: `OUT_DIR`(기본 `./certs/`), `TARGET_IP`, `TARGET_PORT`(기본
`49154`), `UUID`(자동 조회 대신 직접 지정).
